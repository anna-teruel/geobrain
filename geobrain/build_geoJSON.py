"""
Build selected per-slice GeoJSON polygons from an atlas annotation volume.
"""

import json
import os
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from rasterio.features import shapes
from scipy.ndimage import gaussian_filter
from skimage import measure
from shapely.affinity import scale as scale_geometry
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from tqdm.auto import tqdm

from geobrain.coord_system import (
	coord_mm_to_slice_index,
	pixel_scale,
	range_mm_to_slice_indices,
	slice_axis,
	slice_index_to_coordinate_mm,
)


@dataclass
class BuildConfig:
	"""
	Configuration for building a GeoJSON from selected Allen CCF annotation slices.

	The selected slices can be defined in two ways:

	    1. Explicit coordinate list:
	        example: coords_mm=[2.0, -2.0, -3.9]
	    2. Coordinate interval:
	        example: start_mm=-3.0, end_mm=-2.0

	Args:
	    out_dir : str
	        Output directory where the final GeoJSON file is saved.
	    resolution_um : float, default=25
	        Isotropic atlas voxel size in microns, e.g. ``Atlas.resolution_um``.
	    voxel_size_um : tuple[float, float, float] | None, default=None
	        Per-axis voxel size (AP, DV, LR) for anisotropic atlases, e.g.
	        ``Atlas.voxel_size_um``. Takes precedence over resolution_um.
	    orientation : {"coronal", "sagittal", "horizontal"}, default="coronal"
	        Slice orientation used to extract 2D views from the 3D annotation
	        volume. Orientation determines which stereotaxic coordinate is used:
	            coronal    -> AP coordinate
	            sagittal   -> ML coordinate
	            horizontal -> DV coordinate
	    coords_mm : list[float] | None, default=None
	        Explicit list of stereotaxic coordinates in mm relative to bregma.
	        Use this for one slice or selected slices.
	    start_mm : float | None, default=None
	        Start coordinate in mm for an interval.
	    end_mm : float | None, default=None
	        End coordinate in mm for an interval.
	    step_mm : float | None, default=None
	        Optional spacing in mm between sampled coordinates.
	        If None and start_mm/end_mm are provided, all Allen slices in the
	        interval are included.
	    min_area_px : float, default=5.0
	        Minimum polygon/component area in pixels to keep after converting
	        a region mask into geometry.
	    simplify_px : float, default=0.8
	        Polygon simplification tolerance in pixels. Higher values reduce
	        vertex count and file size, but may reduce boundary detail.
	    polygon_mode : {"raster", "contour"}, default="contour"
	        Method used to convert binary masks into polygons.
	            "raster"  : pixel-boundary polygonization.
	            "contour" : Gaussian smoothing followed by contour extraction.
	    smooth_sigma : float, default=1.0
	        Gaussian smoothing sigma used only when polygon_mode="contour".
	    geojson_filename : str, default="atlas_slices.geojson"
	        Name of the output GeoJSON file written to out_dir.
	"""

	out_dir: str
	resolution_um: float = 25
	voxel_size_um: tuple[float, float, float] | None = None
	orientation: Literal["coronal", "sagittal", "horizontal"] = "coronal"

	coords_mm: list[float] | None = None
	start_mm: float | None = None
	end_mm: float | None = None
	step_mm: float | None = None

	min_area_px: float = 5.0
	simplify_px: float = 0.8
	polygon_mode: Literal["raster", "contour"] = "contour"
	smooth_sigma: float = 1.0
	geojson_filename: str = "atlas_slices.geojson"


def get_slice_view(
	volume: np.ndarray,
	index: int,
	orientation: str,
) -> np.ndarray:
	"""
	Extract a 2D slice from a 3D annotation volume.

	Args:
	    volume : np.ndarray
	        3D annotation volume.
	    index : int
	        Slice index along the chosen orientation.
	    orientation : {"coronal", "sagittal", "horizontal"}
	        Anatomical slicing direction.

	Returns:
	    np.ndarray
	        2D array representing the selected slice.
	"""
	if orientation == "coronal":
		return volume[index, :, :]
	if orientation == "sagittal":
		return volume[:, :, index]
	if orientation == "horizontal":
		return volume[:, index, :]
	raise ValueError(f"Unknown orientation: {orientation}")


def clean_polygons_geometry(
	polys: list[Polygon],
	min_area_px: float,
	simplify_px: float,
) -> MultiPolygon | None:
	"""
	Validate, simplify, filter, and merge a list of raw Shapely polygons.

	Steps applied in order:
	    1. Skip empty geometries.
	    2. Repair invalid geometries with a zero-width buffer.
	    3. Simplify with Douglas-Peucker (if simplify_px > 0).
	    4. Drop components smaller than min_area_px.
	    5. Merge all survivors with unary_union into a single MultiPolygon.

	Args:
	    polys : list[Polygon]
	        Raw candidate polygons from rasterization or contour extraction.
	    min_area_px : float
	        Minimum polygon area in pixels. Smaller components are discarded.
	    simplify_px : float
	        Simplification tolerance in pixels (Douglas-Peucker).
	        Pass 0 to skip simplification.

	Returns:
	    MultiPolygon | None
	        Merged geometry, or None if nothing survives cleaning.
	"""
	survivors: list[Polygon] = []

	for poly in polys:
		if poly.is_empty:
			continue
		if not poly.is_valid:
			poly = poly.buffer(0)
		if poly.is_empty:
			continue

		if simplify_px > 0:
			poly = poly.simplify(simplify_px, preserve_topology=True)
			if poly.is_empty:
				continue

		# Flatten MultiPolygons that simplification may have produced.
		if isinstance(poly, Polygon):
			if poly.area >= min_area_px:
				survivors.append(poly)
		elif isinstance(poly, MultiPolygon):
			survivors.extend(p for p in poly.geoms if p.area >= min_area_px)

	if not survivors:
		return None

	merged = unary_union(survivors)
	if merged.is_empty:
		return None

	# Normalise output type to always be MultiPolygon.
	if isinstance(merged, Polygon):
		return MultiPolygon([merged])
	if isinstance(merged, MultiPolygon):
		return merged

	return None


def _mask_to_polygon_raster(
	mask: np.ndarray,
	min_area_px: float,
	simplify_px: float,
) -> MultiPolygon | None:
	"""
	Polygonize a binary mask using rasterio pixel-boundary tracing.

	Produces axis-aligned polygon edges that closely follow voxel boundaries.
	Fast, but blocky at low resolutions.

	The main goal of this function is to extract polygons directly from pixel
	boundaries.

	Args:
	    mask : np.ndarray
	        2D binary mask (will be cast to uint8 internally).
	    min_area_px : float
	        Minimum polygon area in pixels.
	    simplify_px : float
	        Simplification tolerance in pixels.

	Returns:
	    MultiPolygon | None
	"""
	mask_u8 = mask.astype(np.uint8)
	if mask_u8.max() == 0:
		return None

	polys: list[Polygon] = []
	for geom_dict, value in shapes(mask_u8, mask=mask_u8 > 0):
		if value != 1:
			continue
		geom = shape(geom_dict)
		if geom.is_empty:
			continue
		if isinstance(geom, Polygon):
			polys.append(geom)
		elif isinstance(geom, MultiPolygon):
			polys.extend(geom.geoms)

	return clean_polygons_geometry(polys, min_area_px, simplify_px)


def _mask_to_polygon_contour(
	mask: np.ndarray,
	min_area_px: float,
	simplify_px: float,
	smooth_sigma: float,
) -> MultiPolygon | None:
	"""
	Polygonize a binary mask via Gaussian smoothing + iso-contour extraction.

	Produces smoother boundaries than raster mode, especially at coarse
	resolutions. Slower due to the smoothing step.

	Args:
	    mask : np.ndarray
	        2D binary mask.
	    min_area_px : float
	        Minimum polygon area in pixels.
	    simplify_px : float
	        Simplification tolerance in pixels.
	    smooth_sigma : float
	        Gaussian smoothing sigma applied before contour extraction.

	Returns:
	    MultiPolygon | None
	"""
	mask_f = mask.astype(float)
	if mask_f.max() == 0:
		return None

	smoothed = gaussian_filter(mask_f, sigma=smooth_sigma)
	contours = measure.find_contours(smoothed, level=0.5)

	polys: list[Polygon] = []
	for contour in contours:
		if contour.shape[0] < 3:
			continue
		# skimage returns (row, col); Shapely expects (x, y) = (col, row).
		coords = [(float(c[1]), float(c[0])) for c in contour]
		poly = Polygon(coords)
		if not poly.is_empty:
			polys.append(poly)

	return clean_polygons_geometry(polys, min_area_px, simplify_px)


def mask_to_polygon(
	mask: np.ndarray,
	min_area_px: float,
	simplify_px: float,
	polygon_mode: Literal["raster", "contour"] = "contour",
	smooth_sigma: float = 1.0,
) -> MultiPolygon | None:
	"""
	Convert a binary mask into cleaned polygon geometry.

	Dispatches to raster or contour extraction based on polygon_mode, then
	passes the result through clean_polygons_geometry.

	Args:
	    mask : np.ndarray
	        2D binary mask for a single brain region.
	    min_area_px : float
	        Minimum polygon area in pixels.
	    simplify_px : float
	        Simplification tolerance in pixels.
	    polygon_mode : {"raster", "contour"}, default="contour"
	        "raster" is faster; "contour" produces smoother boundaries.
	    smooth_sigma : float, default=1.0
	        Gaussian sigma, used only when polygon_mode="contour".

	Returns:
	    MultiPolygon | None
	        Cleaned geometry, or None if the mask is empty or too small.
	"""
	if polygon_mode == "raster":
		return _mask_to_polygon_raster(mask, min_area_px, simplify_px)

	if polygon_mode == "contour":
		return _mask_to_polygon_contour(mask, min_area_px, simplify_px, smooth_sigma)

	raise ValueError(f"Unknown polygon_mode: {polygon_mode!r}. Choose 'raster' or 'contour'.")


def scale_cartesian_to_lonlat(
	geojson_obj: dict,
	lon_range: tuple[float, float] = (-15.0, 15.0),
	lat_range: tuple[float, float] = (-10.0, 10.0),
	keep_aspect: bool = True,
) -> dict:
	"""
	Convert GeoJSON polygon coordinates from atlas Cartesian pixel space [x, y]
	to pseudo-geographic lon/lat coordinates [lon, lat].

	This modifies the input GeoJSON in place and returns it.

	GeoJSON MultiPolygon geometry is structured as:
	MultiPolygon
	└── polygons        (disconnected parts of one region)
	    └── rings       (ring[0] = outer boundary, ring[1:] = holes)
	        └── points  ([x, y] coordinate pairs)
	That's why we scale the coordinates in a loop.

	Bounds are computed globally across all features in a single pass, so
	the scaling is consistent across the entire slice. The y axis is inverted
	because atlas pixel coordinates increase downward while latitude increases
	upward.

	With keep_aspect=True (default), x and y share one scale factor, so the
	geometry keeps its proportions: it fills lon_range or lat_range
	(whichever is tighter) and is centred in the other. With
	keep_aspect=False, x and y are stretched independently to fill both
	ranges, which distorts slices whose shape differs from the ranges'.

	Args:
	    geojson_obj : dict
	        GeoJSON FeatureCollection containing coordinates in atlas
	        Cartesian pixel space [x, y].
	    lon_range : tuple[float, float], default=(-10.0, 10.0)
	        Output longitude range used for min-max scaling.
	    lat_range : tuple[float, float], default=(-10.0, 10.0)
	        Output latitude range used for min-max scaling.
	    keep_aspect : bool, default=True
	        Use one scale factor for both axes so shapes are not distorted.

	Returns:
	    dict
	        The modified GeoJSON FeatureCollection with coordinates
	        transformed into pseudo lon/lat space.

	Raises:
	    ValueError
	        If an unsupported geometry type is encountered.

	Examples:
	    Convert atlas coordinates before choropleth rendering:

	    >>> geojson = build_geojson(...)
	    >>> geojson = scale_cartesian_to_lonlat(
	    ...     geojson,
	    ...     lon_range=(-5, 5),
	    ...     lat_range=(-5, 5),
	    ... )

	    Save the result:

	    >>> save_geojson(geojson, "brain_slice_lonlat.geojson")
	"""
	features = geojson_obj["features"]
	for f in features:
		if f["geometry"]["type"] != "MultiPolygon":
			raise ValueError(f"Expected MultiPolygon, got {f['geometry']['type']}")

	all_coords = np.array(
		[
			[x, y]
			for f in features
			for polygon in f["geometry"]["coordinates"]
			for ring in polygon
			for x, y in ring
		]
	)

	xmin, xmax = all_coords[:, 0].min(), all_coords[:, 0].max()
	ymin, ymax = all_coords[:, 1].min(), all_coords[:, 1].max()
	lon_min, lon_max = lon_range
	lat_min, lat_max = lat_range

	x_span = xmax - xmin
	y_span = ymax - ymin

	# Scale factors (degrees per pixel). A zero-extent axis (e.g. a single
	# point or a sliver) gets no factor of its own, so it maps to the middle of
	# its range instead of dividing by zero and producing NaN/inf.
	kx = (lon_max - lon_min) / x_span if x_span else None
	ky = (lat_max - lat_min) / y_span if y_span else None
	if keep_aspect:
		factors = [k for k in (kx, ky) if k is not None]
		kx = ky = min(factors) if factors else 0.0
	kx, ky = kx or 0.0, ky or 0.0

	x_mid, y_mid = (xmin + xmax) / 2, (ymin + ymax) / 2
	lon_mid, lat_mid = (lon_min + lon_max) / 2, (lat_min + lat_max) / 2

	for f in features:
		geom = f["geometry"]
		geom["coordinates"] = [
			[
				[
					[float(lon_mid + (x - x_mid) * kx), float(lat_mid - (y - y_mid) * ky)]
					for x, y in ring
				]
				for ring in polygon
			]
			for polygon in geom["coordinates"]
		]

	return geojson_obj


def build_geojson(
	volume: np.ndarray,
	structure_df: pd.DataFrame,
	orientation: str,
	resolution_um: float = 25,
	species: str = "mouse",
	voxel_size_um: tuple[float, float, float] | None = None,
	min_area_px: float = 5.0,
	simplify_px: float = 0.8,
	smooth_sigma: float = 1.0,
	polygon_mode: Literal["raster", "contour"] = "contour",
	slice_indices: list[int] | None = None,
	coords_mm: list[float] | None = None,
	start_mm: float | None = None,
	end_mm: float | None = None,
	step_mm: float | None = None,
	lon_range: tuple[float, float] = (-15.0, 15.0),
	lat_range: tuple[float, float] = (-10.0, 10.0),
	keep_aspect: bool = True,
) -> dict:
	"""
	Build one GeoJSON FeatureCollection from selected Allen atlas slices.

	The function extracts 2D slices from a 3D Allen CCF annotation volume,
	converts every brain region mask into polygon geometry, and stores all
	regions from all selected slices inside a single GeoJSON FeatureCollection.

	Each geoJSON feature always means one object on the map. In our context, each
	feature corresponds to ONE brain region in ONE slice. For example: Field CA1
	in coronal slice -2.0mm.
	Classical geoJSON features include information about one country, including the
	country name, state, country metadata, country boundary, lat/lon polygon, and the
	geographic map. Compared to the brain geoJSON we are building, each feature of our
	geoJSON will describe one brain region, including the region name, the allen ontology
	metadata, brain region boundary, atlas pixel polygon [x,y], and the atlas slice.

	An important conceptual difference is that classic geoJSON are representing 2D
	geographic space [lon/lat], but in our case, our brain geoJSON represents 2D atlas
	slice space in pixels [x,y]. But, structurally, they are build in the same
	geoJSON standard way.

	Args:
	    volume : np.ndarray
	        3D Allen CCF annotation volume containing integer structure IDs.
	    structure_df : pd.DataFrame
	        Ontology table, e.g. ``Atlas.structure_df`` from ``load_atlas()``.
	    orientation : {"coronal", "sagittal", "horizontal"}
	        Slice orientation used when extracting 2D views from the volume.
	    resolution_um : float, default=25
	        Isotropic atlas voxel size in microns, e.g. ``Atlas.resolution_um``.
	    species : str, default="mouse"
	        Atlas species, e.g. ``Atlas.species``. Bregma-relative
	        coordinates (coords_mm, start_mm/end_mm) are only supported for
	        "mouse"; other species must select slices with slice_indices, and
	        their features get ``coordinate_mm=None``.
	    voxel_size_um : tuple[float, float, float] | None, default=None
	        Per-axis voxel size (AP, DV, LR), e.g. ``Atlas.voxel_size_um``.
	        Required for anisotropic atlases; takes precedence over
	        resolution_um. Polygons are stretched by their in-plane voxel sizes
	        so slices keep their true proportions.
	    min_area_px : float, default=5.0
	        Minimum polygon area in pixels. Smaller polygons are discarded.
	    simplify_px : float, default=0.8
	        Polygon simplification tolerance in pixels. Higher values reduce
	        vertex count and file size but may reduce anatomical detail.
	    smooth_sigma : float, default=1.0
	        Gaussian smoothing sigma used only when
	        polygon_mode="contour".
	    polygon_mode : {"raster", "contour"}, default="contour"
	        Method used to convert binary masks into polygon geometry.
	            "raster"  : pixel-boundary polygonization.
	            "contour" : Gaussian smoothing followed by contour extraction.
	    slice_indices : list[int] | None, default=None
	        Explicit Allen slice indices to include.
	    coords_mm : list[float] | None, default=None
	        Explicit stereotaxic coordinates in millimetres relative to Bregma (mm)
	    start_mm : float | None, default=None
	        Start coordinate in millimetres for interval selection.
	    end_mm : float | None, default=None
	        End coordinate in millimetres for interval selection.
	    step_mm : float | None, default=None
	        Optional spacing between sampled coordinates in millimetres.
	        If None, all Allen slices in the interval are included.
	    lon_range : tuple[float, float], default=(-15.0, 15.0)
	        Output longitude range used during coordinate scaling.
	    lat_range : tuple[float, float], default=(-10.0, 10.0)
	        Output latitude range used during coordinate scaling.
	    keep_aspect : bool, default=True
	        Keep the slice's proportions when scaling to lon/lat (see
	        scale_cartesian_to_lonlat).

	Returns:
	    dict
	        GeoJSON FeatureCollection containing all extracted brain-region
	        polygons across all selected slices.

	Raises:
	    ValueError
	        If both slice_indices and stereotaxic coordinates are provided.

	Examples:
	    Build from explicit stereotaxic coordinates:

	    >>> geojson = build_geojson(
	    ...     volume=volume,
	    ...     structure_df=structure_df,
	    ...     orientation="coronal",
	    ...     resolution_um=25,
	    ...     coords_mm=[2.0, -1.5, -3.0],
	    ...     min_area_px=5,
	    ...     simplify_px=0.8,
	    ... )

	    Build from a coordinate interval sampled every 0.5 mm:

	    >>> geojson = build_geojson(
	    ...     volume=volume,
	    ...     structure_df=structure_df,
	    ...     orientation="coronal",
	    ...     resolution_um=25,
	    ...     start_mm=-3.0,
	    ...     end_mm=-1.0,
	    ...     step_mm=0.5,
	    ...     min_area_px=5,
	    ...     simplify_px=0.8,
	    ... )

	    Build from explicit Allen slice indices:

	    >>> geojson = build_geojson(
	    ...     volume=volume,
	    ...     structure_df=structure_df,
	    ...     orientation="coronal",
	    ...     resolution_um=25,
	    ...     slice_indices=[120, 240, 360],
	    ...     min_area_px=5,
	    ...     simplify_px=0.8,
	    ... )
	"""

	selection_methods = [
		slice_indices is not None,
		coords_mm is not None,
		start_mm is not None or end_mm is not None,
	]

	if sum(selection_methods) != 1:
		raise ValueError(
			"Provide exactly one slice-selection method: "
			"slice_indices, coords_mm, or start_mm/end_mm."
		)

	voxel = tuple(float(v) for v in (voxel_size_um or (resolution_um,) * 3))
	# Voxel size along the slicing axis: the one that turns mm into slice
	# indices (bregma coordinates are mouse-only, whose atlases are isotropic).
	resolution_um = voxel[slice_axis(orientation)]
	sx, sy = pixel_scale(orientation, voxel)

	if slice_indices is not None:
		pass

	elif coords_mm is not None:
		slice_indices = [
			coord_mm_to_slice_index(
				coord_mm=coord,
				orientation=orientation,
				resolution_um=resolution_um,
				species=species,
			)
			for coord in coords_mm
		]

	else:
		slice_indices = range_mm_to_slice_indices(
			start_mm=start_mm,
			end_mm=end_mm,
			step_mm=step_mm,
			orientation=orientation,
			resolution_um=resolution_um,
			species=species,
		)

	id2row = structure_df.set_index("id").to_dict(orient="index")
	all_features: list[dict] = []

	for slice_index in tqdm(slice_indices, desc="Building GeoJSON slices"):
		slice_img = get_slice_view(volume, slice_index, orientation)

		try:
			coordinate_mm = slice_index_to_coordinate_mm(
				slice_index=slice_index,
				orientation=orientation,
				resolution_um=resolution_um,
				species=species,
			)  # we convert to mm for metadata
		except ValueError:  # no bregma for this species (see `_require_mouse`)
			coordinate_mm = None

		unique_ids = np.unique(slice_img)  # find allen region IDs inside the loaded slice
		unique_ids = unique_ids[unique_ids != 0]  # exclude the background

		for rid in unique_ids:  # for each region id in all regions in the slice
			rid = int(rid)

			geom = mask_to_polygon(
				mask=(slice_img == rid),
				min_area_px=min_area_px,
				simplify_px=simplify_px,
				polygon_mode=polygon_mode,
				smooth_sigma=smooth_sigma,
			)  # create a polygon for every region id in each slice

			if geom is None:
				continue
			if (sx, sy) != (1.0, 1.0):
				geom = scale_geometry(geom, xfact=sx, yfact=sy, origin=(0, 0))

			row = id2row.get(rid, {})

			all_features.append(
				{
					"type": "Feature",
					"properties": {
						"feature_id": f"{slice_index}_{rid}",
						"Region ID": rid,
						"Region name": row.get("name"),
						"Acronym": row.get("acronym"),
						"parent_structure_id": row.get("parent_structure_id"),
						"structure_id_path": row.get("structure_id_path"),
						"slice_index": int(slice_index),
						"coordinate_mm": coordinate_mm,
						"orientation": orientation,
						"resolution_um": resolution_um,
						"voxel_size_um": list(voxel),
					},
					"geometry": mapping(geom),
				}
			)

	geojson = {
		"type": "FeatureCollection",
		"features": all_features,
	}

	geojson = scale_cartesian_to_lonlat(
		geojson,
		lon_range=lon_range,
		lat_range=lat_range,
		keep_aspect=keep_aspect,
	)

	return geojson


def save_geojson(
	geojson_obj: dict,
	out_path: str,
) -> str:
	"""
	Save a GeoJSON FeatureCollection to disk.

	Args:
	    geojson_obj : dict
	        GeoJSON FeatureCollection to save.
	    out_path : str
	        Output GeoJSON file path.

	Returns:
	    str
	        Absolute path to the saved GeoJSON file.

	Examples:
	    Save a GeoJSON file produced by build_geojson():

	    >>> geojson = build_geojson(...)
	    >>> save_geojson(geojson, "atlas_slice.geojson")
	"""

	os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

	with open(out_path, "w", encoding="utf-8") as f:
		json.dump(
			geojson_obj,
			f,
			indent=2,
			ensure_ascii=False,
		)

	return os.path.abspath(out_path)
