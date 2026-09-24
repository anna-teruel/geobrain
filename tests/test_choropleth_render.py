"""Tests for choropleth rendering and the value->color helper."""

import copy

import plotly.graph_objects as go
import pytest

from geobrain.choropleth_render import render_brain_slice, value_to_color


def test_render_returns_figure(sample_geojson, score_df):
	fig = render_brain_slice(sample_geojson, score_df, value_col="density")
	assert isinstance(fig, go.Figure)


def test_render_includes_all_regions(sample_geojson, score_df):
	# GeoBrain no longer excludes any region by ID (see issue #40 discussion):
	# root/background aren't universal across atlases, so region 997 (root),
	# present in sample_geojson but absent from score_df, still reaches the
	# plot as a NaN-scored feature via the left join.
	fig = render_brain_slice(sample_geojson, score_df, value_col="density")
	locations = list(fig.data[0].locations)
	assert "1_997" in locations
	assert set(locations) == {"1_315", "1_672", "1_997"}


def test_render_missing_feature_id_raises(sample_geojson, score_df):
	broken = copy.deepcopy(sample_geojson)
	del broken["features"][0]["properties"]["feature_id"]
	with pytest.raises(KeyError):
		render_brain_slice(broken, score_df, value_col="density")


def test_render_handles_region_without_score(sample_geojson):
	import pandas as pd

	# Only region 315 has a score; 672 and 997 should survive as NaN (left join).
	partial = pd.DataFrame({"Region ID": [315], "density": [0.3]})
	fig = render_brain_slice(sample_geojson, partial, value_col="density")
	assert isinstance(fig, go.Figure)
	assert set(fig.data[0].locations) == {"1_315", "1_672", "1_997"}


def test_value_to_color_nan_returns_na_color():
	assert value_to_color(float("nan"), 0.0, 1.0, na_color="#abcabc") == "#abcabc"
	assert value_to_color(None, 0.0, 1.0, na_color="#abcabc") == "#abcabc"


def test_value_to_color_returns_color_string():
	color = value_to_color(0.5, 0.0, 1.0)
	assert isinstance(color, str)
	assert color.startswith("rgb")


def test_value_to_color_clamps_out_of_range():
	# Below vmin and above vmax should map to the scale endpoints,
	# i.e. identical to the clamped boundary values.
	low = value_to_color(-5.0, 0.0, 1.0)
	at_min = value_to_color(0.0, 0.0, 1.0)
	high = value_to_color(5.0, 0.0, 1.0)
	at_max = value_to_color(1.0, 0.0, 1.0)
	assert low == at_min
	assert high == at_max


def test_value_to_color_degenerate_range_uses_midpoint():
	# vmax == vmin -> t defaults to 0.5 (no division by zero).
	assert value_to_color(3.0, 2.0, 2.0) == value_to_color(99.0, 2.0, 2.0)


def test_render_uses_explicit_color_range(sample_geojson, score_df):
	fig = render_brain_slice(
		sample_geojson,
		score_df,
		value_col="density",
		zmin=0,
		zmax=10,
	)

	assert fig.layout.coloraxis.cmin == 0
	assert fig.layout.coloraxis.cmax == 10


def test_render_forwards_plotly_kwargs(sample_geojson, score_df):
	fig = render_brain_slice(
		sample_geojson,
		score_df,
		value_col="density",
		title="My Brain Map",
		zoom=5,
	)

	assert fig.layout.title.text == "My Brain Map"
