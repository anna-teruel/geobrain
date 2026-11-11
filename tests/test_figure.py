"""Tests for geobrain.app.figure.build_export_figure."""

import numpy as np

from geobrain.app import figure

_GEOMETRY = {
	"by_slice": {
		"1": [
			{
				"rid": 315,
				"name": "Isocortex",
				"rings": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
			}
		]
	},
	"dims": {"w": 20, "h": 20},
	"orientation": "coronal",
}


def _has_colorbar(fig) -> bool:
	return any(getattr(trace, "marker", None) and trace.marker.showscale for trace in fig.data)


def test_build_export_figure_no_scores_omits_colorbar():
	fig = figure.build_export_figure(
		geometry_payload=_GEOMETRY,
		score_records=[],
		slice_index=1,
		score="density",
		colorscale="Viridis",
		zmin=None,
		zmax=None,
	)
	assert not _has_colorbar(fig)


def test_build_export_figure_with_scores_shows_colorbar():
	fig = figure.build_export_figure(
		geometry_payload=_GEOMETRY,
		score_records=[{"Region ID": 315, "density": 0.5}],
		slice_index=1,
		score="density",
		colorscale="Viridis",
		zmin=None,
		zmax=None,
	)
	assert _has_colorbar(fig)


def test_build_export_figure_side_by_side_panels():
	"""A {group: records} mapping draws one titled panel per group on its own axes,
	with one shared color range (so the groups are comparable) and one colorbar."""
	geometry = {"by_slice": {"1": [{"rid": 315, "rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}]}}
	fig = figure.build_export_figure(
		geometry_payload=geometry,
		score_records={
			"control": [{"Region ID": 315, "density": 0.2}],
			"treated": [{"Region ID": 315, "density": 0.8}],
		},
		slice_index=1,
		score="density",
		colorscale="Viridis",
		zmin=None,
		zmax=None,
	)
	regions = [t for t in fig.data if t.fill == "toself"]
	assert [(t.xaxis, t.yaxis) for t in regions] == [("x", "y"), ("x2", "y2")]
	assert regions[0].fillcolor != regions[1].fillcolor
	assert [a.text for a in fig.layout.annotations] == ["control", "treated"]
	colorbars = [t for t in fig.data if t.marker.showscale]
	assert len(colorbars) == 1
	assert (colorbars[0].marker.cmin, colorbars[0].marker.cmax) == (0.2, 0.8)


def _grid_inputs(coords):
	ring = [[1, 1], [9, 1], [9, 7], [1, 7]]
	payload = {
		"by_slice": {
			str(i): [{"rid": 1, "name": "a", "rings": [ring]}] for i in range(len(coords))
		},
		"dims": {"w": 10, "h": 8},
		"orientation": "coronal",
	}
	meta = [{"slice_index": i, "coordinate_mm": c} for i, c in enumerate(coords)]
	scores = {
		g: [{"Region ID": 1, "relative_abundance_z": v, "n_animals": 5}]
		for g, v in (("A", -1.0), ("B", 2.0))
	}
	return payload, scores, meta


def test_publication_figure_axis_labels():
	payload, scores, meta = _grid_inputs([1.5, 1.0, 0.5])
	fig = figure.build_publication_figure(payload, scores, meta, "rel_abundance", "RdBu_r", -3, 3)
	texts = [a.text for a in fig.layout.annotations]
	assert {"+1.50", "+1.00", "+0.50", "◀ anterior", "posterior ▶"} <= set(texts)
	assert any(t.startswith("<b>A</b>") and "n = 5" in t for t in texts)
	assert any("bregma" in t for t in texts)


def test_publication_figure_falls_back_to_slice_index_without_bregma():
	payload, scores, meta = _grid_inputs([None, None])
	fig = figure.build_publication_figure(payload, scores, meta, "rel_abundance", "RdBu_r", -3, 3)
	texts = [a.text for a in fig.layout.annotations]
	assert {"0", "1", "Slice index"} <= set(texts)


def test_same_fill_neighbours_share_one_trace():
	"""Consecutive rings with one fill (here the grey "no data" ones) are a single
	NaN-separated trace; a differently coloured region keeps its own."""
	ring = [[0, 0], [1, 0], [1, 1]]
	geometry = {
		"by_slice": {
			"1": [{"rid": r, "rings": [ring]} for r in (1, 2, 3)],
		}
	}
	fig = figure.build_export_figure(
		geometry, [{"Region ID": 3, "density": 1.0}], 1, "density", "Viridis", 0, 1
	)
	fills = [t for t in fig.data if t.fill == "toself"]
	assert [t.fillcolor for t in fills][0] == "#d9d9d9"
	assert len(fills) == 2
	assert len(fills[0].x) == 7 and np.isnan(fills[0].x[3])  # two rings, NaN gap between
