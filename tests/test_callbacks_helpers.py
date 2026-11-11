"""Unit tests for the pure helper functions in geobrain.app.callbacks.

These exercise the module-level helpers (delimiter resolution, column parsing,
filename building, score-store normalization, GeoJSON serialization, slider
config) directly, with no Dash app or callback context involved.
"""

import pandas as pd
import pytest

from geobrain.app import callbacks as cb


# --------------------------------------------------------------------------- #
# _resolve_sep
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
	"value, expected",
	[
		("tab", "\t"),
		("\\t", "\t"),
		("semicolon", ";"),
		("comma", ","),
		("TAB", "\t"),  # case-insensitive alias
		("|", "|"),  # unknown value passed through verbatim
	],
)
def test_resolve_sep_explicit_value(value, expected):
	# data_dir is irrelevant when a concrete value is given.
	assert cb._resolve_sep(value, "/does/not/matter") == expected


def test_resolve_sep_auto_detects_semicolon(quint_dir):
	# quint_dir writes ';'-separated *_RefAtlasRegions.csv files.
	assert cb._resolve_sep("auto", quint_dir) == ";"
	assert cb._resolve_sep(None, quint_dir) == ";"
	assert cb._resolve_sep("  ", quint_dir) == ";"  # blank-after-strip -> auto


def test_resolve_sep_auto_detects_comma(tmp_path):
	(tmp_path / "X_RefAtlasRegions.csv").write_text(
		"Region ID,Region name,Object count\n315,Isocortex,4\n", encoding="utf-8"
	)
	assert cb._resolve_sep("auto", str(tmp_path)) == ","


def test_resolve_sep_no_files_defaults_semicolon(tmp_path):
	assert cb._resolve_sep("auto", str(tmp_path)) == ";"


def test_resolve_sep_unreadable_file_defaults_semicolon(tmp_path, monkeypatch):
	# A matching file exists, but opening it raises -> fall back to ';'.
	(tmp_path / "X_RefAtlasRegions.csv").write_text("Region ID,x\n1,2\n", encoding="utf-8")

	def boom(*args, **kwargs):
		raise OSError("permission denied")

	monkeypatch.setattr("builtins.open", boom)
	assert cb._resolve_sep("auto", str(tmp_path)) == ";"


def test_resolve_sep_header_with_no_delimiter_defaults_semicolon(tmp_path):
	# A single-column header has no ; , or tab -> falls back to ';'.
	(tmp_path / "X_RefAtlasRegions.csv").write_text("RegionID\n315\n", encoding="utf-8")
	assert cb._resolve_sep("auto", str(tmp_path)) == ";"


# --------------------------------------------------------------------------- #
# _parse_cols
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
	"text, expected",
	[
		(None, None),
		("", None),
		("   ", None),
		("  ,  ", None),  # only separators/whitespace
		("group", "group"),  # single -> bare string
		(" group ", "group"),  # stripped
		("group,sex", ["group", "sex"]),  # multiple -> list
		("group, sex ,age", ["group", "sex", "age"]),
	],
)
def test_parse_cols(text, expected):
	assert cb._parse_cols(text) == expected


# --------------------------------------------------------------------------- #
# _slice_filename
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
	"orientation, coord, expected",
	[
		("coronal", 1.5, "brain_AP_+1.50mm"),
		("sagittal", -2.0, "brain_ML_-2.00mm"),
		("horizontal", 0.0, "brain_DV_+0.00mm"),
	],
)
def test_slice_filename_with_coordinate(orientation, coord, expected):
	assert cb._slice_filename("brain", orientation, coord, 7) == expected


def test_slice_filename_falls_back_to_index_without_orientation():
	assert cb._slice_filename("brain", None, 1.5, 7) == "brain_slice7"


def test_slice_filename_falls_back_to_index_without_coordinate():
	assert cb._slice_filename("brain", "coronal", None, 7) == "brain_slice7"


# --------------------------------------------------------------------------- #
# _scores_to_store
# --------------------------------------------------------------------------- #
def test_scores_to_store_dict_input_adds_combined_mean():
	groups = {
		"control": pd.DataFrame(
			{"Region ID": [315], "Region name": ["Isocortex"], "density": [0.2]}
		),
		"treated": pd.DataFrame(
			{"Region ID": [315], "Region name": ["Isocortex"], "density": [0.4]}
		),
	}
	store = cb._scores_to_store(groups)
	assert set(store) == {"control", "treated", cb.COMBINED_GROUP_LABEL}
	# combined entry is the per-region mean across groups
	combined = store[cb.COMBINED_GROUP_LABEL]
	assert combined[0]["Region ID"] == 315
	assert combined[0]["density"] == pytest.approx(0.3)


def test_scores_to_store_single_dataframe_no_groups():
	df = pd.DataFrame({"Region ID": [315], "Region name": ["Isocortex"], "density": [0.2]})
	store = cb._scores_to_store(df)
	assert list(store) == ["All"]
	assert cb.COMBINED_GROUP_LABEL not in store


def test_scores_to_store_dataframe_with_group_label_splits_and_combines():
	df = pd.DataFrame(
		{
			"group_label": ["control", "treated"],
			"Region ID": [315, 315],
			"Region name": ["Isocortex", "Isocortex"],
			"density": [0.2, 0.4],
		}
	)
	store = cb._scores_to_store(df)
	assert set(store) == {"control", "treated", cb.COMBINED_GROUP_LABEL}
	# group_label column is dropped from the per-group records
	assert "group_label" not in store["control"][0]


def test_scores_to_store_single_group_label_no_combined():
	df = pd.DataFrame(
		{
			"group_label": ["control"],
			"Region ID": [315],
			"Region name": ["Isocortex"],
			"density": [0.2],
		}
	)
	store = cb._scores_to_store(df)
	assert list(store) == ["control"]
	assert cb.COMBINED_GROUP_LABEL not in store


# --------------------------------------------------------------------------- #
# _payload_to_geojson
# --------------------------------------------------------------------------- #
def _ring_square():
	return [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]


def test_payload_to_geojson_single_ring_polygon_with_y_flip():
	geometry = {
		"orientation": "coronal",
		"dims": {"h": 10.0},
		"by_slice": {"1": [{"rid": 315, "name": "Isocortex", "rings": [_ring_square()]}]},
	}
	slices = [{"slice_index": 1, "coordinate_mm": -2.0}]
	gj = cb._payload_to_geojson(geometry, slices)

	assert gj["type"] == "FeatureCollection"
	feat = gj["features"][0]
	assert feat["geometry"]["type"] == "Polygon"
	# y is flipped about h=10: y=0 -> 10, y=2 -> 8
	ys = [pt[1] for pt in feat["geometry"]["coordinates"][0]]
	assert max(ys) == 10.0 and min(ys) == 8.0
	props = feat["properties"]
	assert props["Region ID"] == 315
	assert props["slice_index"] == 1
	assert props["coordinate_mm"] == -2.0
	assert props["orientation"] == "coronal"


def test_payload_to_geojson_multiple_rings_multipolygon():
	geometry = {
		"orientation": "coronal",
		"by_slice": {
			"1": [{"rid": 315, "name": "Isocortex", "rings": [_ring_square(), _ring_square()]}]
		},
	}
	gj = cb._payload_to_geojson(geometry, None)
	assert gj["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_payload_to_geojson_skips_ringless_region():
	geometry = {
		"orientation": "coronal",
		"by_slice": {"1": [{"rid": 315, "name": "Isocortex", "rings": []}]},
	}
	gj = cb._payload_to_geojson(geometry, None)
	assert gj["features"] == []


def test_payload_to_geojson_no_dims_leaves_y_unflipped():
	# Geometry loaded from a y-up GeoJSON has no dims -> no flip applied.
	geometry = {
		"orientation": "coronal",
		"by_slice": {"1": [{"rid": 315, "name": "Isocortex", "rings": [_ring_square()]}]},
	}
	gj = cb._payload_to_geojson(geometry, None)
	ys = [pt[1] for pt in gj["features"][0]["geometry"]["coordinates"][0]]
	assert max(ys) == 2.0 and min(ys) == 0.0


# --------------------------------------------------------------------------- #
# _slider_config
# --------------------------------------------------------------------------- #
def test_slider_config_empty():
	assert cb._slider_config([]) == (0, 0, 0, {})


def test_slider_config_marks_use_coordinate_when_present():
	slices = [
		{"slice_index": 0, "coordinate_mm": -2.0},
		{"slice_index": 1, "coordinate_mm": 0.0},
		{"slice_index": 2, "coordinate_mm": 2.0},
	]
	smin, smax, sval, marks = cb._slider_config(slices)
	assert (smin, smax, sval) == (0, 2, 0)
	assert marks == {0: "-2.0", 1: "+0.0", 2: "+2.0"}


def test_slider_config_marks_fall_back_to_index_without_coordinate():
	slices = [{"slice_index": 10, "coordinate_mm": None}]
	_, _, _, marks = cb._slider_config(slices)
	assert marks == {0: "10"}


# --------------------------------------------------------------------------- #
# side by side: _records_for / _data_range
# --------------------------------------------------------------------------- #
_SBS_SCORES = {
	"All (mean)": [{"Region ID": 1, "density": 5.0}],
	"A": [{"Region ID": 1, "density": 1.0}],
	"B": [{"Region ID": 1, "density": 3.0}],
}


def test_records_for_side_by_side_skips_combined_group():
	got = cb._records_for(_SBS_SCORES, cb.SIDE_BY_SIDE_LABEL)
	assert list(got) == ["A", "B"]


def test_records_for_single_group_falls_back_to_first():
	assert cb._records_for(_SBS_SCORES, "B")[0]["density"] == 3.0
	assert cb._records_for(_SBS_SCORES, "nope")[0]["density"] == 5.0  # first group
	assert cb._records_for({}, "A") == []


def test_data_range_side_by_side_spans_every_group():
	# The combined mean (5.0) is not a panel, so the range is the real groups': 1..3.
	assert cb._data_range(_SBS_SCORES, cb.SIDE_BY_SIDE_LABEL, "density") == (1.0, 3.0)
