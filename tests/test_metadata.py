"""Tests for MetadataConfig: loading, group-column normalization, merging."""

import pandas as pd
import pytest

from geobrain.metadata import MetadataConfig


def test_load_none_path_returns_none():
	assert MetadataConfig(metadata_path=None).load() is None


def test_load_strips_column_whitespace(metadata_csv):
	cfg = MetadataConfig(metadata_path=metadata_csv, sep=",", animal_col="animal")
	meta = cfg.load()
	assert "group" in meta.columns  # " group " -> "group"
	assert "sex" in meta.columns


def test_load_missing_animal_col_raises(metadata_csv):
	cfg = MetadataConfig(metadata_path=metadata_csv, sep=",", animal_col="subject")
	with pytest.raises(KeyError):
		cfg.load()


@pytest.mark.parametrize(
	"group_col, expected",
	[
		(None, None),
		("group", ["group"]),
		(["group", "sex"], ["group", "sex"]),
	],
)
def test_group_cols_normalization(group_col, expected):
	assert MetadataConfig(group_col=group_col).group_cols() == expected


def test_merge_and_add_groups_single_column(metadata_csv):
	cfg = MetadataConfig(
		metadata_path=metadata_csv, sep=",", animal_col="animal", group_col="group"
	)
	df = pd.DataFrame({"animal": ["A1", "A3"], "objects": [10, 5]})
	merged, group_cols = cfg.merge_and_add_groups(df)
	assert group_cols == ["group"]
	assert merged.loc[merged["animal"] == "A1", "group_label"].iloc[0] == "control"
	assert merged.loc[merged["animal"] == "A3", "group_label"].iloc[0] == "treated"


def test_merge_and_add_groups_multi_column_label(metadata_csv):
	cfg = MetadataConfig(
		metadata_path=metadata_csv,
		sep=",",
		animal_col="animal",
		group_col=["group", "sex"],
		group_name_sep="_",
	)
	df = pd.DataFrame({"animal": ["A1"], "objects": [10]})
	merged, group_cols = cfg.merge_and_add_groups(df)
	assert group_cols == ["group", "sex"]
	assert merged["group_label"].iloc[0] == "control_M"


def test_merge_and_add_groups_no_metadata_no_groups():
	cfg = MetadataConfig(metadata_path=None, group_col=None)
	df = pd.DataFrame({"animal": ["A1"], "objects": [10]})
	merged, group_cols = cfg.merge_and_add_groups(df)
	assert group_cols is None
	assert "group_label" not in merged.columns


def test_merge_and_add_groups_missing_group_column_raises():
	# No metadata file, but a grouping column is requested that does not exist.
	cfg = MetadataConfig(metadata_path=None, group_col="nope")
	df = pd.DataFrame({"animal": ["A1"], "objects": [10]})
	with pytest.raises(KeyError):
		cfg.merge_and_add_groups(df)


def test_merge_and_add_groups_unmatched_animal_yields_nan_group(metadata_csv):
	# A9 is absent from the metadata; a left merge leaves its group column NaN,
	# which .astype(str) turns into the literal string "nan". This documents
	# the current (silent) behavior so a future change to it is intentional.
	cfg = MetadataConfig(
		metadata_path=metadata_csv, sep=",", animal_col="animal", group_col="group"
	)
	df = pd.DataFrame({"animal": ["A1", "A9"], "objects": [10, 5]})
	merged, _ = cfg.merge_and_add_groups(df)
	assert merged.loc[merged["animal"] == "A1", "group_label"].iloc[0] == "control"
	assert merged.loc[merged["animal"] == "A9", "group_label"].iloc[0] == "nan"


def test_merge_numeric_animal_ids(tmp_path):
	# IDs parsed from filenames are text; numeric metadata IDs must still match.
	path = tmp_path / "meta.csv"
	path.write_text("animal,group\n12,a\n13,b\n", encoding="utf-8")
	df = pd.DataFrame({"animal": ["12", "13"], "objects": [1, 2]})
	cfg = MetadataConfig(metadata_path=str(path), sep=",", animal_col="animal", group_col="group")
	merged, _ = cfg.merge_and_add_groups(df)
	assert list(merged["group_label"]) == ["a", "b"]


def test_merge_custom_animal_column(tmp_path):
	path = tmp_path / "meta.csv"
	path.write_text("mouse_id,group\nA1,a\nA2,b\n", encoding="utf-8")
	df = pd.DataFrame({"animal": ["A1", "A2"], "objects": [1, 2]})
	cfg = MetadataConfig(metadata_path=str(path), sep=",", animal_col="mouse_id", group_col="group")
	merged, _ = cfg.merge_and_add_groups(df)
	assert list(merged["group_label"]) == ["a", "b"]
	assert "mouse_id" not in merged.columns
