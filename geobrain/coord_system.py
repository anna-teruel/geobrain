"""
Utilities to convert between Allen CCF slice indices and
approximate AP coordinates relative to bregma.

https://community.brain-map.org/t/how-to-transform-ccf-x-y-z-coordinates-into-stereotactic-coordinates/1858
"""

from dataclasses import dataclass
from typing import Literal
import numpy as np

Orientation = Literal[
	"coronal", "sagittal", "horizontal"
]  # orientation is only allowed to have one of these 3 values


def _require_mouse(species: str) -> None:
	"""
	Guard bregma-relative stereotaxic conversion to mouse only.

	The bregma offsets in this module are curated specifically for the Allen
	mouse CCF and have no general equivalent across species (BrainGlobe atlas
	metadata does not carry bregma information at all). See the GeoBrain
	issue tracker for the generalization discussion; until resolved,
	non-mouse callers must address slices by index instead of
	bregma-relative mm.

	Args:
	    species : str
	        Species identifier, e.g. from an AtlasProvider.

	Raises:
	    ValueError
	        If species is not "mouse" (case-insensitive).
	"""
	if species.lower() != "mouse":
		raise ValueError(
			f"Bregma-relative stereotaxic coordinates are only supported for "
			f"species='mouse' (got {species!r}). See the GeoBrain issue tracker "
			"for the coordinate-system generalization discussion."
		)


@dataclass(frozen=True)
class CCFConfig:
	"""
	Configuration for a specific Allen annotation volume resolution.

	Args:
	    resolution_um : int
	        Isotropic voxel size in microns. This is directly related to which annotation volume we load
	        from the ANNOTATION_URLS in build_polygons.py. Following values are accepted: 10, 25, 50, 100.
	    bregma_ml_index : int
	        Approximate mediolateral voxel index of bregma.
	    bregma_dv_index : int
	        Approximate dorsoventral voxel index of bregma.
	    bregma_ap_index : int
	        Approximate anteroposterior voxel index of bregma.
	"""

	resolution_um: int
	bregma_ml_index: int
	bregma_dv_index: int
	bregma_ap_index: int


def get_ccf_config(resolution_um: int, species: str = "mouse") -> CCFConfig:
	"""
	Compute approximate Allen CCF bregma indices for a given voxel resolution.

	The physical bregma position is assumed to be approximately: ML = 5400 µm
	DV = 450 µm, AP = 5700 µm. These are the coordinates of the approximate bregma
	location inside the Allen CCF reference space, according to the following forum
	discussion:
	https://community.brain-map.org/t/how-to-transform-ccf-x-y-z-coordinates-into-stereotactic-coordinates/1858

	This function converts the physical position in microns into voxel indices for
	a chosen atlas resolution.

	Args:
	    resolution_um : int
	        Atlas voxel size in microns. Loaded from the config class.
	        Example:
	            >>> bregma_ml_index = round(5400 / 25)  # 216
	            >>> bregma_dv_index = round(450 / 25)  # 18
	            >>> bregma_ap_index = round(5700 / 25)  # 228

	            Meaning:
	                In the 25 µm Allen annotation volume,
	                bregma is approximately at voxel/index:

	                ML = 216
	                DV = 18
	                AP = 228
	    species : str, default="mouse"
	        Species the bregma offsets apply to. Only "mouse" is currently
	        supported; see ``_require_mouse()``.

	Returns:
	    CCFConfig: Configuration object with resolution and bregma indices, based on our conversion system.

	Raises:
	    ValueError
	        If species is not "mouse".
	"""
	_require_mouse(species)

	BREGMA_ML_UM = 5400  # microns
	BREGMA_DV_UM = 450  # microns
	BREGMA_AP_UM = 5700  # microns

	return CCFConfig(
		resolution_um=resolution_um,
		bregma_ml_index=round(BREGMA_ML_UM / resolution_um),
		bregma_dv_index=round(BREGMA_DV_UM / resolution_um),
		bregma_ap_index=round(BREGMA_AP_UM / resolution_um),
	)


def coord_mm_to_slice_index(
	coord_mm: float,
	orientation: Orientation = "coronal",
	resolution_um: int = 25,
	species: str = "mouse",
) -> int:
	"""
	Convert a stereotaxic coordinate in mm (from Bregma) to the corresponding Allen slice index,
	depending on slice orientation.

	The orientation determines which anatomical axis is being sliced:
	    coronal-> AP axis
	    sagittal-> ML axis
	    horizontal-> DV axis

	The conversion is performed relative to the approximate bregma
	voxel indices computed by ``get_ccf_config()``.

	The anatomical sign convention depends on the orientation:
	    AP: anterior is more positive, posterior more negative
	    ML: right is positive, left is negative
	    DV: dorsal is superficial and ventral (deeper) is negative.

	Args:
	    coord_mm: float. Stereotaxic coordinate in mm relative to Bregma.
	    orientation: {'coronal', 'sagittal', 'horizontal'}, default = 'coronal'
	    resolution_um: int, default = 25. Atlas vixel resolution in microns
	    species: str, default = 'mouse'. Only 'mouse' is currently supported;
	        see ``_require_mouse()``.

	Returns:
	    int: approximate slice index in the Allen annotation volume

	Raises:
	    ValueError: if species is not 'mouse'.

	Example:
	    For a coronal atlas at 25 µm resolution:
	        >>> coord_mm = -2.0
	        >>> offset_voxels = round((-2.0 * 1000) / 25)
	        >>> offset_voxels
	        -80
	    Meaning: the requested coordinate is located 80 voxels posterior to
	    bregma slice.

	    If:
	        >>> cfg.bregma_ap_index = 228
	        >>> slice_index = 228 - (-80)
	        >>> slice index
	        308

	    So, AP = -2.0 mm approximately corresponds to Allen Coronal slice index 308.
	"""
	cfg = get_ccf_config(resolution_um, species=species)
	offset_voxels = round(
		(coord_mm * 1000.0) / cfg.resolution_um
	)  # how many slices away from bregma your coord is

	if orientation == "coronal":
		# +AP --> anterior to Bregma
		# -AP --> posterior to Bregma
		# the Allen axis 1 increases posteriorly
		return int(cfg.bregma_ap_index - offset_voxels)

	if orientation == "sagittal":
		return int(cfg.bregma_ml_index - offset_voxels)

	if orientation == "horizontal":
		return int(cfg.bregma_dv_index - offset_voxels)

	raise ValueError(f"Unknown orientation: {orientation}")


def slice_index_to_coordinate_mm(
	slice_index: int,
	orientation: Orientation = "coronal",
	resolution_um: int = 25,
	species: str = "mouse",
) -> float:
	"""
	Convert an Allen slice index to an approximate stereotaxic coordinate in mm (from Bregma),
	depending on slice orientation (coronal, sagittal and horizontal)

	Args:
	    slice_index: int, slice index in the allen annotation volume
	    orientation: {'coronal', 'sagittal', 'horizontal}, default = 'coronal',
	                atlas slicing orientation
	    resolution_um: int, default = 25, atlas voxel resolution
	    species: str, default = 'mouse'. Only 'mouse' is currently supported;
	        see ``_require_mouse()``.

	Returns:
	    float: approximatestereotaxic coords in mm relative to Bregma.

	Raises:
	    ValueError: if species is not 'mouse'.
	"""
	cfg = get_ccf_config(resolution_um, species=species)

	if orientation == "coronal":
		offset_voxels = cfg.bregma_ap_index - slice_index

	elif orientation == "sagittal":
		offset_voxels = cfg.bregma_ml_index - slice_index

	elif orientation == "horizontal":
		offset_voxels = cfg.bregma_dv_index - slice_index

	else:
		raise ValueError(f"Unknown orientation: {orientation}")

	return (offset_voxels * cfg.resolution_um) / 1000.0


def range_mm_to_slice_indices(
	start_mm: float | None = None,
	end_mm: float | None = None,
	coords_mm: list[float] | None = None,
	step_mm: float | None = None,
	orientation: Orientation = "coronal",
	resolution_um: int = 25,
	species: str = "mouse",
) -> list[int]:
	"""
	Convert a range stereotaxic coordinates in mm to Allen slice indices
	for subsequent rendering.

	Two modes are supported:
	    1. Manual coordinate list:
	        Provide a list of bregma levels (mm) that you want to render.
	        Example: coords_mm=[2.0, -2.0, -3.9]

	    2. Coordinate interval:
	        Given a start and end slice, it renders all the slices in between the interval.
	        Example: start_mm=-3.0, end_mm=-2.0
	        If `step_mm` is None, all Allen slices available between start_mm
	        and end_mm are returned.
	        If `step_mm` is provided, coordinates are sampled every step_mm and
	        converted to slice indices.

	Args:
	    start_mm : float | None
	        Start coordinate in mm relative to bregma.
	    end_mm : float | None
	        End coordinate in mm relative to bregma.
	    coords_mm : list[float] | None
	        Explicit list of coordinates in mm to convert.
	    step_mm : float | None
	        Optional spacing in mm between sampled coordinates.
	        If None, all slices in the interval are returned.
	    orientation : {"coronal", "sagittal", "horizontal"}, default="coronal"
	        Atlas slicing orientation.
	    resolution_um : int, default=25
	        Atlas voxel resolution in microns.
	    species : str, default="mouse"
	        Only "mouse" is currently supported; see ``_require_mouse()``.

	Returns:
	    list[int]: Sorted unique Allen slice indices.

	Raises:
	    ValueError: if species is not "mouse".
	"""
	if coords_mm is not None:
		indices = [
			coord_mm_to_slice_index(
				coord_mm=c,
				orientation=orientation,
				resolution_um=resolution_um,
				species=species,
			)
			for c in coords_mm
		]
		return sorted(set(indices))

	if start_mm is None or end_mm is None:
		raise ValueError("Provide either coords_mm, or both start_mm and end_mm.")

	if step_mm is None:
		i0 = coord_mm_to_slice_index(
			coord_mm=start_mm,
			orientation=orientation,
			resolution_um=resolution_um,
			species=species,
		)
		i1 = coord_mm_to_slice_index(
			coord_mm=end_mm,
			orientation=orientation,
			resolution_um=resolution_um,
			species=species,
		)

		lo, hi = sorted((i0, i1))
		return list(range(lo, hi + 1))

	if step_mm <= 0:
		raise ValueError("step_mm must be positive.")

	else:
		lo_mm, hi_mm = sorted((start_mm, end_mm))
		# np.arange's upper bound is padded by step_mm so the endpoint is
		# included when it divides evenly; clip so a non-dividing step never
		# samples a coordinate past hi_mm.
		coords = np.arange(lo_mm, hi_mm + step_mm, step_mm)
		coords = coords[coords <= hi_mm + 1e-9]

		indices = [
			coord_mm_to_slice_index(
				coord_mm=c,
				orientation=orientation,
				resolution_um=resolution_um,
				species=species,
			)
			for c in coords
		]

		return sorted(set(indices))
