from functools import lru_cache
from typing import Annotated, Any, Literal

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from plotly.exceptions import PlotlyError
from pydantic import BaseModel, Field

from geobrain.build_geoJSON import slice_regions
from geobrain.choropleth_render import value_to_color
from geobrain.colormaps import resolve_name
from geobrain.coord_system import pixel_scale, slice_index_to_coordinate_mm

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
	resolution_um: float,
	slice_indices: list[int],
	min_area_px: float = 5.0,
	simplify_px: float = 0.8,
	smooth_sigma: float = 1.0,
	polygon_mode: str = "contour",
	progress=None,
	species: str = "mouse",
	voxel_size_um: tuple[float, float, float] | None = None,
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
	``callable(i, n, slice_index)`` used to drive the progress bar. ``species``
	decides whether slices get a bregma-relative ``coordinate_mm`` (mouse
	only) or ``None``.

	``voxel_size_um`` (AP, DV, LR) handles anisotropic atlases: rows and
	columns are stretched by their voxel size relative to the finest axis, so
	the slice keeps its true proportions on screen. Omitted, voxels are
	treated as cubes.
	"""
	sx, sy = (1.0, 1.0) if voxel_size_um is None else pixel_scale(orientation, voxel_size_um)

	id2row = structure_df.set_index("id").to_dict(orient="index")
	by_slice: dict[str, list[dict[str, Any]]] = {}
	slices_meta: list[dict[str, Any]] = []
	dims: dict[str, int] = {"w": 0, "h": 0}

	n = len(slice_indices)
	slices = slice_regions(
		volume,
		slice_indices,
		orientation,
		voxel_size_um=voxel_size_um,
		min_area_px=min_area_px,
		simplify_px=simplify_px,
		smooth_sigma=smooth_sigma,
		polygon_mode=polygon_mode,
	)
	for i, (si, (n_rows, n_cols), traced) in enumerate(slices, start=1):
		dims = _screen_dims(orientation, round(n_rows * sy), round(n_cols * sx))

		try:
			coord_mm = slice_index_to_coordinate_mm(si, orientation, resolution_um, species=species)
		except ValueError:  # no bregma for this species (see _require_mouse)
			coord_mm = None

		regions: list[dict[str, Any]] = []
		for rid, geom in traced:
			rings: list[list[list[float]]] = []
			for poly in geom.geoms:
				ring = []
				for x, y in poly.exterior.coords:
					px, py = _screen_xy(orientation, x, y)
					ring.append([round(float(px), 2), round(float(py), 2)])
				if len(ring) >= 3:
					rings.append(ring)
			if not rings:
				continue

			row = id2row.get(rid, {})
			regions.append({"rid": rid, "name": row.get("name") or str(rid), "rings": rings})

		by_slice[str(si)] = regions
		slices_meta.append(
			{
				"slice_index": si,
				"coordinate_mm": None if coord_mm is None else round(float(coord_mm), 3),
			}
		)
		if progress is not None:
			progress(i, n, si)

	payload = {"by_slice": by_slice, "dims": dims, "orientation": orientation}
	return payload, slices_meta


# Schema for an uploaded slice GeoJSON (the shape build_geojson and the app's
# Save button write). Extra properties are ignored; anything missing or of the
# wrong type is rejected with the exact field path.
_Ring = list[tuple[float, float]]  # 2D points only
_PolygonCoords = Annotated[list[_Ring], Field(min_length=1)]  # [outer, *holes]


class _Polygon(BaseModel):
	type: Literal["Polygon"]
	coordinates: _PolygonCoords


class _MultiPolygon(BaseModel):
	type: Literal["MultiPolygon"]
	coordinates: list[_PolygonCoords]


class _Properties(BaseModel):
	region_id: int = Field(alias="Region ID")
	region_name: str | None = Field(None, alias="Region name")
	slice_index: int
	coordinate_mm: float | None = None


class _Feature(BaseModel):
	properties: _Properties
	geometry: Annotated[_Polygon | _MultiPolygon, Field(discriminator="type")]


class SliceGeoJSON(BaseModel):
	type: Literal["FeatureCollection"]
	features: list[_Feature]


def geojson_to_payload(
	geojson_obj: SliceGeoJSON,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	"""Build a geometry payload from a previously saved (lon/lat) GeoJSON.

	Used by the "load processed files" path. The coordinates are the package's
	pseudo lon/lat (already y-up), so no reversed range is applied (``dims`` is
	left empty and the figure autoranges). Only outer rings are kept, matching
	``build_slice_geometry``.
	"""
	by_slice: dict[str, list[dict[str, Any]]] = {}
	seen: dict[int, float | None] = {}

	for feat in geojson_obj.features:
		props = feat.properties
		si = props.slice_index
		if si not in seen:
			cm = props.coordinate_mm
			seen[si] = None if cm is None else round(cm, 3)

		geom = feat.geometry
		polygons = [geom.coordinates] if geom.type == "Polygon" else geom.coordinates
		rings = [[[round(x, 3), round(y, 3)] for x, y in poly[0]] for poly in polygons]
		if not rings:
			continue
		by_slice.setdefault(str(si), []).append(
			{
				"rid": props.region_id,
				"name": props.region_name or str(props.region_id),
				"rings": rings,
			}
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
	except PlotlyError:  # unknown colorscale name
		colors = sample_colorscale("Aurora", points, colortype="rgb")
		reverse = False

	if reverse:
		colors = colors[::-1]

	return [[points[i], _parse_rgb(c)] for i, c in enumerate(colors)]


# The same (value, range, colormap) recurs across slices and panels.
_cached_color = lru_cache(maxsize=4096)(value_to_color)


def _region_traces(regions, id2value, zmin, zmax, cmap, selected, flat_color, xaxis, yaxis):
	"""One panel's filled-polygon traces, gated like the live view (render.js).

	Consecutive rings with the same fill share one trace (a ``None``/NaN gap separates the
	polygons), which keeps the trace count, and so build and render time, low.
	Consecutive only, so the draw order is unchanged.

	Returns ``(traces, static_mode)``.
	"""
	region_rids = {int(r["rid"]) for r in regions}
	# The gate is dropped when none of the selected regions are on this slice
	# (same anti-flash guard as the browser).
	sel_active = bool(selected) and not region_rids.isdisjoint(selected)
	static_mode = flat_color is not None and sel_active

	runs: list[list] = []  # [fill, xs, ys]
	for region in regions:
		rid = int(region["rid"])
		if sel_active and rid not in selected:
			fill = "#d9d9d9"
		elif static_mode:
			fill = flat_color
		else:
			fill = _cached_color(id2value.get(rid), zmin, zmax, cmap, "#d9d9d9")
		for ring in region["rings"]:
			if not runs or runs[-1][0] != fill:
				runs.append([fill, [], []])
			_, xs, ys = runs[-1]
			if xs:
				xs.append(None)
				ys.append(None)
			xs.extend(p[0] for p in ring)
			ys.extend(p[1] for p in ring)
	line = dict(color="rgba(255,255,255,0.95)", width=0.7, shape="spline", smoothing=0.6)
	# Plain dicts: add_traces validates them once, instead of twice via go.Scatter.
	traces = [
		dict(
			type="scatter",
			x=np.array(xs, dtype=float),  # arrays skip plotly's slow per-item list validation
			y=np.array(ys, dtype=float),
			xaxis=xaxis,
			yaxis=yaxis,
			mode="lines",
			fill="toself",
			fillcolor=fill,
			line=line,
			hoverinfo="skip",
			showlegend=False,
		)
		for fill, xs, ys in runs
	]
	return traces, static_mode


def _colorbar_trace(zmin, zmax, colorscale, title):
	return go.Scatter(
		x=[None, None],
		y=[None, None],
		mode="markers",
		marker=dict(
			size=0,
			color=[zmin, zmax],
			colorscale=colorscale,
			cmin=zmin,
			cmax=zmax,
			showscale=True,
			colorbar=dict(title=dict(text=title, side="right"), thickness=14, len=0.85),
		),
		hoverinfo="skip",
		showlegend=False,
	)


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
	score_records: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
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

	``score_records`` is one group's records, or ``{group: records}`` to draw the
	groups side by side as titled panels sharing one color range.

	The optional ``selected_rids`` (row selection) and ``flat_color`` (flat-color
	toggle) mirror the live view's gating in ``assets/render.js`` so an export
	reflects what's on screen.
	"""
	value_col = SCORE_VALUE_COLUMN[score]
	# Panel label -> {region id: value}; a single unlabelled panel for one group.
	panels = score_records if isinstance(score_records, dict) else {None: score_records}
	panel_values: dict[str | None, dict[int, float]] = {}
	for label, records in panels.items():
		id2value = panel_values[label] = {}
		for row in records:
			rid = row.get("Region ID")
			val = row.get(value_col)
			if rid is not None and val is not None:
				id2value[int(rid)] = float(val)
	all_values = [v for id2value in panel_values.values() for v in id2value.values()]

	regions = geometry_payload.get("by_slice", {}).get(str(int(slice_index)), [])
	dims = geometry_payload.get("dims")
	cmap = colorscale or "RdBu_r"
	colorbar_scale = resolve_name(cmap)  # Handle custom cmaps

	# Auto-range unset limits from the data, matching the live view (render.js).
	# Without this, density (default range (None, None)) collapses every region
	# to the colorscale midpoint on export.
	zmin, zmax = _auto_range(all_values, zmin, zmax)

	# The row selection narrows coloring to `selected_rids`, and the flat color
	# replaces the colormap once a selection narrows this slice (see render.js).
	selected = selected_rids or set()
	static_mode = False
	fig = go.Figure()
	n = len(panel_values)
	for i, (label, id2value) in enumerate(panel_values.items()):
		axis = str(i + 1) if i else ""  # x/y, x2/y2, ...
		traces, static_mode = _region_traces(
			regions, id2value, zmin, zmax, cmap, selected, flat_color, f"x{axis}", f"y{axis}"
		)
		fig.add_traces(traces)
		# Panels share the width equally; each keeps its own 1:1 aspect.
		fig.update_layout(
			{
				f"xaxis{axis}": dict(domain=[(i + 0.02) / n, (i + 0.98) / n] if n > 1 else [0, 1]),
				f"yaxis{axis}": dict(anchor=f"x{axis}", scaleanchor=f"x{axis}"),
			}
		)
		if label is not None:
			fig.add_annotation(
				text=label,
				showarrow=False,
				xref="paper",
				yref="paper",
				x=(i + 0.5) / n,
				y=1,
				yanchor="bottom",
			)

	if all_values and zmin is not None and zmax is not None and not static_mode:
		fig.add_trace(_colorbar_trace(zmin, zmax, colorbar_scale, value_col))

	if dims:
		fig.update_xaxes(visible=False, range=[0, dims["w"]], constrain="domain")
		fig.update_yaxes(visible=False, range=[dims["h"], 0], constrain="domain")
	else:
		fig.update_xaxes(visible=False)
		fig.update_yaxes(visible=False)

	fig.update_layout(
		title=title,
		paper_bgcolor="white",
		plot_bgcolor="white",
		margin=dict(l=10, r=10, t=40, b=10),
	)
	return fig


# Anatomical direction at the low / high slice-index end of each orientation
# (Allen CCF: AP index grows posteriorly, DV ventrally, LR rightwards).
_INDEX_ENDS = {
	"coronal": ("anterior", "posterior"),
	"sagittal": ("left", "right"),
	"horizontal": ("dorsal", "ventral"),
}

_AXIS_TITLE = {
	"coronal": "Anteroposterior position relative to bregma (mm)",
	"sagittal": "Mediolateral position relative to bregma (mm)",
	"horizontal": "Dorsoventral position relative to bregma (mm)",
}


def build_publication_figure(
	geometry_payload: dict,
	scores: dict[str, list[dict[str, Any]]],
	slices_meta: list[dict[str, Any]],
	score: str,
	colorscale: str,
	zmin: float | None,
	zmax: float | None,
	*,
	selected_rids: set[int] | None = None,
	flat_color: str | None = None,
	cell_px: int = 260,
) -> go.Figure:
	"""Facet grid for publication: rows = groups, columns = consecutive slices.

	One shared color scale, and one annotation axis under the whole grid with a
	tick per column: the bregma-relative coordinate when every slice has one,
	otherwise the slice index. ``scores`` maps group label -> score records
	(empty -> a single unlabelled row of plain atlas maps).
	"""
	from plotly.subplots import make_subplots

	groups = list(scores) or [""]
	n_rows, n_cols = len(groups), len(slices_meta)
	orientation = geometry_payload.get("orientation")
	dims = geometry_payload.get("dims")
	use_coords = all(m.get("coordinate_mm") is not None for m in slices_meta)

	# One range for every panel, or panels would not be comparable.
	value_col = SCORE_VALUE_COLUMN[score]
	all_vals = [
		r[value_col]
		for recs in scores.values()
		for r in recs
		if r.get("Region ID") is not None and r.get(value_col) is not None
	]
	zmin, zmax = _auto_range(all_vals, zmin, zmax)

	fig = make_subplots(rows=n_rows, cols=n_cols, horizontal_spacing=0.004, vertical_spacing=0.015)
	cmap = colorscale or "RdBu_r"
	selected = selected_rids or set()
	traces = []
	any_static = False
	for i, group in enumerate(groups):
		id2value = {
			int(r["Region ID"]): float(r[value_col])
			for r in scores.get(group, [])
			if r.get("Region ID") is not None and r.get(value_col) is not None
		}
		for j, meta in enumerate(slices_meta):
			regions = geometry_payload.get("by_slice", {}).get(str(int(meta["slice_index"])), [])
			k = i * n_cols + j + 1  # make_subplots numbers axes row by row
			sfx = "" if k == 1 else k
			cell, static = _region_traces(
				regions, id2value, zmin, zmax, cmap, selected, flat_color, f"x{sfx}", f"y{sfx}"
			)
			traces += cell
			any_static = any_static or static
	fig.add_traces(traces)  # one batch: row/col lookups per trace are slow
	has_colorbar = bool(all_vals) and not any_static
	colorbar = _colorbar_trace(zmin, zmax, resolve_name(cmap), value_col) if has_colorbar else None

	cell_w, cell_h = (cell_px, cell_px * dims["h"] / dims["w"]) if dims else (cell_px, cell_px)
	margin = dict(l=110, r=110 if colorbar else 20, t=20, b=110)
	height = round(n_rows * cell_h) + margin["t"] + margin["b"]
	width = n_cols * cell_px + margin["l"] + margin["r"]
	plot_h = height - margin["t"] - margin["b"]

	fig.update_xaxes(visible=False, constrain="domain")
	fig.update_yaxes(visible=False, constrain="domain")
	if dims:
		fig.update_xaxes(range=[0, dims["w"]])
		fig.update_yaxes(range=[dims["h"], 0])
	for n in range(1, n_rows * n_cols + 1):  # lock each panel's aspect to its own x
		sfx = "" if n == 1 else str(n)
		fig.layout[f"yaxis{sfx}"].scaleanchor = f"x{sfx}"

	if colorbar is not None:
		colorbar.marker.colorbar.len = 0.6
		colorbar.marker.colorbar.x = 1.01
		fig.add_trace(colorbar)

	fig.update_layout(
		width=width,
		height=height,
		margin=margin,
		paper_bgcolor="white",
		plot_bgcolor="white",
		showlegend=False,
		font=dict(family="Arial", size=14, color="#222"),
	)

	def px(n: float) -> float:  # pixels below the plot -> paper y
		return -n / plot_h

	for i, group in enumerate(groups):
		dom = fig.layout[f"yaxis{i * n_cols + 1 if i else ''}"].domain
		if group:
			n = next((r["n_animals"] for r in scores[group] if r.get("n_animals")), None)
			label = f"<b>{group}</b>" + (
				f"<br><span style='font-size:12px;color:#666'>n = {int(n)}</span>" if n else ""
			)
			fig.add_annotation(
				xref="paper",
				yref="paper",
				x=-12 / (width - margin["l"] - margin["r"]),
				y=sum(dom) / 2,
				text=label,
				showarrow=False,
				xanchor="right",
			)

	y0 = px(8)
	fig.add_shape(
		type="line",
		xref="paper",
		yref="paper",
		x0=0,
		x1=1,
		y0=y0,
		y1=y0,
		line=dict(color="#222", width=1.5),
	)
	for j, meta in enumerate(slices_meta):
		dom = fig.layout[f"xaxis{j + 1 if j else ''}"].domain
		x = sum(dom) / 2
		label = f"{meta['coordinate_mm']:+.2f}" if use_coords else str(meta["slice_index"])
		fig.add_shape(
			type="line",
			xref="paper",
			yref="paper",
			x0=x,
			x1=x,
			y0=y0,
			y1=px(15),
			line=dict(color="#222", width=1.5),
		)
		fig.add_annotation(
			xref="paper", yref="paper", x=x, y=px(19), text=label, showarrow=False, yanchor="top"
		)
	title = _AXIS_TITLE.get(orientation, "Position (mm)") if use_coords else "Slice index"
	fig.add_annotation(
		xref="paper", yref="paper", x=0.5, y=px(60), text=title, showarrow=False, yanchor="top"
	)
	if orientation in _INDEX_ENDS:
		ends = _INDEX_ENDS[orientation]
		if slices_meta[0]["slice_index"] > slices_meta[-1]["slice_index"]:
			ends = ends[::-1]  # columns run high -> low index
		hint = dict(
			xref="paper",
			yref="paper",
			y=px(60),
			yanchor="top",
			showarrow=False,
			font=dict(size=12, color="#666"),
		)
		fig.add_annotation(x=0, xanchor="left", text=f"◀ {ends[0]}", **hint)
		fig.add_annotation(x=1, xanchor="right", text=f"{ends[1]} ▶", **hint)
	return fig
