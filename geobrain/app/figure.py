from typing import Any

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from geobrain.build_geoJSON import get_slice_view, mask_to_polygon
from geobrain.choropleth_render import value_to_color
from geobrain.colormaps import resolve_name
from geobrain.coord_system import slice_index_to_coordinate_mm

SCORE_VALUE_COLUMN = {
	"rel_abundance": "relative_abundance_z",
	"frequency": "frequency",
	"density": "density",
}

SCORE_DEFAULT_RANGE = {
	"rel_abundance": (-3.0, 3.0),
	"frequency": (0.0, 1.0),
	"density": (None, None),
}


def _screen_xy(orientation: str, x: float, y: float) -> tuple[float, float]:
	"""Map mask coordinates (x=col, y=row) to screen axes for one orientation.

	Goal: vertical axis = dorsoventral (dorsal up, achieved with a reversed
	y-range in the figure), horizontal axis = the remaining in-plane axis.

	- coronal   : slice is (DV=row, ML=col) -> X=ML=col, Y=DV=row  (identity)
	- horizontal: slice is (AP=row, ML=col) -> X=ML=col, Y=AP=row  (identity)
	- sagittal  : slice is (AP=row, DV=col) -> X=AP=row, Y=DV=col  (swap), so
	              the anterior-posterior axis is horizontal (no 90° rotation).
	"""
	if orientation == "sagittal":
		return y, x
	return x, y


def _screen_dims(orientation: str, n_rows: int, n_cols: int) -> dict[str, int]:
	if orientation == "sagittal":
		return {"w": int(n_rows), "h": int(n_cols)}
	return {"w": int(n_cols), "h": int(n_rows)}


def build_slice_geometry(
	volume: np.ndarray,
	structure_df,
	orientation: str,
	resolution_um: int,
	slice_indices: list[int],
	min_area_px: float = 5.0,
	simplify_px: float = 0.8,
	smooth_sigma: float = 1.0,
	polygon_mode: str = "contour",
	progress=None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	"""Build undistorted, correctly-oriented pixel geometry for the given slices.

	Returns ``(payload, slices_meta)`` where ``payload`` is::

	    {
	        "by_slice": {slice_index: [{"rid", "name", "rings"}]},
	        "dims": {"w", "h"},
	        "orientation": orientation,
	    }

	``rings`` are exterior rings ``[[x, y], ...]`` in pixel/screen coordinates
	(holes are dropped, matching ``plotly_render``). ``progress`` is an optional
	``callable(i, n, slice_index)`` used to drive the progress bar.
	"""
	id2row = structure_df.set_index("id").to_dict(orient="index")
	by_slice: dict[str, list[dict[str, Any]]] = {}
	slices_meta: list[dict[str, Any]] = []
	dims: dict[str, int] = {"w": 0, "h": 0}

	n = len(slice_indices)
	for i, si in enumerate(slice_indices, start=1):
		si = int(si)
		slice_img = get_slice_view(volume, si, orientation)
		n_rows, n_cols = slice_img.shape
		dims = _screen_dims(orientation, n_rows, n_cols)

		coord_mm = slice_index_to_coordinate_mm(si, orientation, resolution_um)

		regions: list[dict[str, Any]] = []
		unique_ids = np.unique(slice_img)
		unique_ids = unique_ids[unique_ids != 0]

		for rid in unique_ids:
			rid = int(rid)
			geom = mask_to_polygon(
				mask=(slice_img == rid),
				min_area_px=min_area_px,
				simplify_px=simplify_px,
				polygon_mode=polygon_mode,
				smooth_sigma=smooth_sigma,
			)
			if geom is None:
				continue

			rings: list[list[list[float]]] = []
			for poly in geom.geoms:
				ring = []
				for x, y in poly.exterior.coords:
					sx, sy = _screen_xy(orientation, x, y)
					ring.append([round(float(sx), 2), round(float(sy), 2)])
				if len(ring) >= 3:
					rings.append(ring)
			if not rings:
				continue

			row = id2row.get(rid, {})
			regions.append({"rid": rid, "name": row.get("name") or str(rid), "rings": rings})

		by_slice[str(si)] = regions
		slices_meta.append({"slice_index": si, "coordinate_mm": round(float(coord_mm), 3)})
		if progress is not None:
			progress(i, n, si)

	payload = {"by_slice": by_slice, "dims": dims, "orientation": orientation}
	return payload, slices_meta


def geojson_to_payload(geojson_obj: dict) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	"""Build a geometry payload from a previously saved (lon/lat) GeoJSON.

	Used by the "load processed files" path. The coordinates are the package's
	pseudo lon/lat (already y-up), so no reversed range is applied (``dims`` is
	left empty and the figure autoranges).
	"""
	by_slice: dict[str, list[dict[str, Any]]] = {}
	seen: dict[int, float | None] = {}

	for feat in geojson_obj.get("features", []):
		props = feat.get("properties", {})
		rid = props.get("Region ID")
		if rid is None:
			continue
		si = props.get("slice_index")
		key = str(int(si)) if si is not None else "0"
		if si is not None and int(si) not in seen:
			cm = props.get("coordinate_mm")
			seen[int(si)] = round(float(cm), 3) if cm is not None else None

		geom = feat.get("geometry", {})
		gtype = geom.get("type")
		coords = geom.get("coordinates", [])
		rings: list[list[list[float]]] = []
		if gtype == "Polygon" and coords:
			rings.append([[round(float(x), 3), round(float(y), 3)] for x, y in coords[0]])
		elif gtype == "MultiPolygon":
			for poly in coords:
				if poly:
					rings.append([[round(float(x), 3), round(float(y), 3)] for x, y in poly[0]])
		if not rings:
			continue
		by_slice.setdefault(key, []).append(
			{"rid": int(rid), "name": props.get("Region name") or str(int(rid)), "rings": rings}
		)

	slices_meta = [{"slice_index": si, "coordinate_mm": seen[si]} for si in sorted(seen)]
	payload = {"by_slice": by_slice, "dims": None, "orientation": None}
	return payload, slices_meta


def _parse_rgb(rgb: str) -> list[int]:
	inside = rgb[rgb.index("(") + 1 : rgb.index(")")]
	parts = [float(p) for p in inside.split(",")]
	return [int(round(parts[0])), int(round(parts[1])), int(round(parts[2]))]


def resolve_colorscale(name: str | None, n: int = 21) -> list[list[Any]]:
	"""Resolve a named Plotly colorscale to ``[[t, [r, g, b]], ...]`` stops.

	Sampling to evenly-spaced RGB stops lets the browser interpolate fill colors
	without shipping Plotly's colorscale machinery. Handles the ``_r`` reversed
	suffix and falls back to Aurora for unknown names.
	"""
	name = name or "RdBu_r"
	reverse = name.endswith("_r")
	base = resolve_name(name[:-2] if reverse else name)
	points = [i / (n - 1) for i in range(n)]

	try:
		colors = sample_colorscale(base, points, colortype="rgb")
	except Exception:
		colors = sample_colorscale("Aurora", points, colortype="rgb")
		reverse = False

	if reverse:
		colors = colors[::-1]

	return [[points[i], _parse_rgb(c)] for i, c in enumerate(colors)]


def _auto_range(
	values, zmin: float | None, zmax: float | None
) -> tuple[float | None, float | None]:
	"""Fill missing color limits from the data, mirroring ``autoRange`` in render.js.

	The live view auto-ranges any limit left unset (e.g. density, whose default
	range is ``(None, None)``); the export must do the same or every region maps
	to the colorscale midpoint.
	"""
	if zmin is not None and zmax is not None:
		return zmin, zmax
	nums = [
		float(v) for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))
	]
	if not nums:
		lo, hi = 0.0, 1.0
	else:
		lo, hi = min(nums), max(nums)
		if lo == hi:
			hi = lo + 1.0
	return (lo if zmin is None else zmin, hi if zmax is None else zmax)


def build_export_figure(
	geometry_payload: dict,
	score_records: list[dict[str, Any]],
	slice_index: int,
	score: str,
	colorscale: str,
	zmin: float | None,
	zmax: float | None,
	title: str | None = None,
	*,
	selected_rids: set[int] | None = None,
	flat_color: str | None = None,
) -> go.Figure:
	"""Server-side render of one slice for static export, matching the app view.

	Built from the same pixel geometry the browser uses, so exported figures are
	oriented and proportioned identically to what the user sees.

	The optional ``selected_rids`` (row selection) and ``flat_color`` (flat-color
	toggle) mirror the live view's gating in ``assets/render.js`` so an export
	reflects what's on screen.
	"""
	value_col = SCORE_VALUE_COLUMN[score]
	id2value: dict[int, float] = {}
	for row in score_records:
		rid = row.get("Region ID")
		val = row.get(value_col)
		if rid is not None and val is not None:
			id2value[int(rid)] = float(val)

	regions = geometry_payload.get("by_slice", {}).get(str(int(slice_index)), [])
	dims = geometry_payload.get("dims")
	cmap = colorscale or "RdBu_r"
	colorbar_scale = resolve_name(cmap)  # Handle custom cmaps

	# Auto-range unset limits from the data, matching the live view (render.js).
	# Without this, density (default range (None, None)) collapses every region
	# to the colorscale midpoint on export.
	zmin, zmax = _auto_range(id2value.values(), zmin, zmax)

	# Auto-range unset limits from the data, matching the live view (render.js).
	# Without this, density (default range (None, None)) collapses every region
	# to the colorscale midpoint on export.
	zmin, zmax = _auto_range(id2value.values(), zmin, zmax)

	# Mirror the live view's gating (see assets/render.js): the row selection
	# narrows coloring to `selected_rids`, and the flat color replaces the
	# colormap once a selection is narrowing this slice. The gate is dropped when
	# none of the selected regions are on this slice (same anti-flash guard as the
	# browser), so the export matches what's on screen.
	region_rids = {int(r["rid"]) for r in regions}
	selected = selected_rids or set()
	sel_active = bool(selected) and not region_rids.isdisjoint(selected)
	static_mode = flat_color is not None and sel_active

	fig = go.Figure()
	for region in regions:
		rid = int(region["rid"])
		gated = sel_active and rid not in selected
		if gated:
			fill = "#d9d9d9"
		elif static_mode:
			fill = flat_color
		else:
			fill = value_to_color(
				id2value.get(rid), zmin, zmax, colorscale=cmap, na_color="#d9d9d9"
			)
		for ring in region["rings"]:
			fig.add_trace(
				go.Scatter(
					x=[p[0] for p in ring],
					y=[p[1] for p in ring],
					mode="lines",
					fill="toself",
					fillcolor=fill,
					line=dict(
						color="rgba(255,255,255,0.95)", width=0.7, shape="spline", smoothing=0.6
					),
					hoverinfo="skip",
					showlegend=False,
				)
			)

	if id2value and zmin is not None and zmax is not None and not static_mode:
		fig.add_trace(
			go.Scatter(
				x=[None, None],
				y=[None, None],
				mode="markers",
				marker=dict(
					size=0,
					color=[zmin, zmax],
					colorscale=colorbar_scale,
					cmin=zmin,
					cmax=zmax,
					showscale=True,
					colorbar=dict(title=dict(text=value_col, side="right"), thickness=14, len=0.85),
				),
				hoverinfo="skip",
				showlegend=False,
			)
		)

	if dims:
		fig.update_xaxes(visible=False, range=[0, dims["w"]], constrain="domain")
		fig.update_yaxes(visible=False, range=[dims["h"], 0], scaleanchor="x", constrain="domain")
	else:
		fig.update_xaxes(visible=False)
		fig.update_yaxes(visible=False, scaleanchor="x")

	fig.update_layout(
		title=title,
		paper_bgcolor="white",
		plot_bgcolor="white",
		margin=dict(l=10, r=10, t=40, b=10),
	)
	return fig
