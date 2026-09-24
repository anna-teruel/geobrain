"""Tests for geobrain.app.figure.build_export_figure."""

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
