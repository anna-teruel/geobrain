"""
Choropleth rendering of Allen atlas slice GeoJSONs with Plotly.
"""

import pandas as pd
import math
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from geobrain.colormaps import resolve_name


def render_brain_slice(
	geojson_obj: dict,
	score_df: pd.DataFrame,
	value_col: str,
	zmin: float | None = None,
	zmax: float | None = None,
	col_id: str = "Region ID",
	name_col: str = "Region name",
	line_color: str = "rgba(255,255,255,0.9)",
	line_width: float = 0.5,
	**kwargs,
) -> go.Figure:
	"""
	Render Allen atlas slices using px.choropleth_map.

	Args:
	    geojson_obj : dict
	        GeoJSON FeatureCollection containing atlas polygons in pseudo
	        lon/lat coordinates. Each feature must contain
	        ``properties["feature_id"]``.
	    score_df : pd.DataFrame
	        Region-level score table. Must contain ``col_id`` and
	        ``value_col``.
	    value_col : str
	        Name of the score column to visualize.
	    zmin : float | None, default=None
	        Minimum value used for color normalization. If None, Plotly
	        infers the minimum from the data.
	    zmax : float | None, default=None
	        Maximum value used for color normalization. If None, Plotly
	        infers the maximum from the data.
	    col_id : str, default="Region ID"
	        Column/property containing Allen structure IDs.
	    name_col : str, default="Region name"
	        Column/property containing region names.
	    line_color : str, default="rgba(255,255,255,0.9)"
	        Boundary color used to outline regions.
	    line_width : float, default=0.5
	        Boundary line width in pixels.
	    **kwargs
	        Additional keyword arguments passed directly to
	        ``plotly.express.choropleth_map``. These can be used to customize
	        Plotly options such as ``title``, ``color_continuous_scale``,
	        ``map_style``, ``center``, ``zoom``, ``width``, ``height``,
	        ``opacity``, ``template`` and ``labels``.

	Returns:
	    go.Figure
	        Plotly choropleth figure.
	"""
	score_df = score_df.copy()
	score_df[col_id] = pd.to_numeric(score_df[col_id], errors="coerce").astype("Int64")
	score_df[value_col] = pd.to_numeric(score_df[value_col], errors="coerce")
	score_df = score_df.dropna(subset=[col_id])

	feature_rows = []

	for feat in geojson_obj.get("features", []):
		props = feat.get("properties", {})
		rid = props.get(col_id)

		if rid is None:
			continue

		rid = int(rid)

		if "feature_id" not in props:
			raise KeyError(
				"GeoJSON feature is missing properties['feature_id']. "
				"Add it in build_geojson(), for example: "
				"feature_id = f'{slice_index}_{rid}'."
			)

		feature_rows.append(
			{
				"feature_id": props["feature_id"],
				col_id: rid,
				name_col: props.get(name_col, str(rid)),
				"slice_index": props.get("slice_index"),
				"coordinate_mm": props.get("coordinate_mm"),
				"orientation": props.get("orientation"),
				"resolution_um": props.get("resolution_um"),
			}
		)

	feature_df = pd.DataFrame(feature_rows)

	plot_df = feature_df.merge(
		score_df[[col_id, value_col]],
		on=col_id,
		how="left",
	)

	range_color = None
	if zmin is not None and zmax is not None:
		range_color = (zmin, zmax)

	kwargs.setdefault("color_continuous_scale", resolve_name("Aurora"))
	kwargs.setdefault("map_style", "white-bg")
	kwargs.setdefault("center", {"lat": 0, "lon": 0})
	kwargs.setdefault("zoom", 3)

	fig = px.choropleth_map(
		plot_df,
		geojson=geojson_obj,
		locations="feature_id",
		color=value_col,
		featureidkey="properties.feature_id",
		hover_name=name_col,
		hover_data={
			col_id: True,
			"slice_index": True,
			"coordinate_mm": True,
			"orientation": True,
			"resolution_um": True,
			value_col: True,
			"feature_id": False,
		},
		range_color=range_color,
		**kwargs,
	)

	fig.update_traces(
		marker_opacity=1.0,
		marker_line_color=line_color,
		marker_line_width=line_width,
	)

	fig.update_layout(
		margin=dict(l=0, r=0, t=40, b=0),
		paper_bgcolor="white",
		plot_bgcolor="white",
	)

	return fig


def value_to_color(
	value: float | None,
	vmin: float | None,
	vmax: float | None,
	colorscale: str = "RdBu_r",
	na_color: str = "#d9d9d9",
) -> str:
	"""
	Map a numeric value (score) to a Plotly colorscale color.

	Args:
	    value : float | None
	        Score value for one region.
	    vmin, vmax : float | None
	        Color normalization limits.
	    colorscale : str
	        Plotly colorscale name.
	    na_color : str
	        Fallback color for missing values.

	Returns:
	    str
	        CSS color string.
	"""
	if value is None or (isinstance(value, float) and math.isnan(value)):
		return na_color

	if vmin is None or vmax is None or vmax == vmin:
		t = 0.5
	else:
		t = (float(value) - float(vmin)) / (float(vmax) - float(vmin))
		t = max(0.0, min(1.0, t))

	return sample_colorscale(resolve_name(colorscale), [t])[0]
