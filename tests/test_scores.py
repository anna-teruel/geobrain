"""Tests for scoring: loading, aggregation, and the individual score metrics."""

import os

import pandas as pd
import pytest

from geobrain.scores import (
	find_animal_id,
	load_refatlas_regions,
	compute_animal_region_counts,
	compute_region_counts,
	compute_reference_stats,
	relative_abundance,
	consistency_score,
	density_score,
	score_table,
	save_scores,
)


# --- filename parsing -------------------------------------------------------


@pytest.mark.parametrize(
	"filename, expected",
	[
		("A1_RefAtlasRegions.csv", "A1"),
		("/some/path/A2_RefAtlasRegions.csv", "A2"),
		("grp1-2_RefAtlasRegions.csv", "grp1"),  # collapses on first dash
	],
)
def test_find_animal_id(filename, expected):
	assert find_animal_id(filename) == expected


# --- loading ----------------------------------------------------------------


def test_load_refatlas_regions_keeps_background_and_root(quint_dir):
	# GeoBrain no longer excludes any region by ID (see issue #40 discussion):
	# root/background aren't universal across atlases, so filtering is left
	# to the caller instead of being hardcoded here.
	df = load_refatlas_regions(quint_dir)
	assert {0, 997}.issubset(set(df["Region ID"].dropna().tolist()))
	assert "animal" in df.columns
	assert set(df["animal"]) == {"A1", "A2", "A3", "A4"}


def test_load_refatlas_regions_no_files_raises(tmp_path):
	empty = tmp_path / "empty"
	empty.mkdir()
	with pytest.raises(FileNotFoundError):
		load_refatlas_regions(str(empty))


# --- aggregation ------------------------------------------------------------


def test_compute_animal_region_counts_sums_duplicates(quint_dir):
	df = load_refatlas_regions(quint_dir)
	rbs = compute_animal_region_counts(df)
	a1_315 = rbs[(rbs["animal"] == "A1") & (rbs["Region ID"] == 315)]
	assert len(a1_315) == 1
	# A1 had region 315 split into rows of 4 and 6 -> summed to 10.
	assert a1_315["objects"].iloc[0] == 10


def test_compute_region_counts(region_by_subject):
	out = compute_region_counts(region_by_subject)
	row_315 = out[out["Region ID"] == 315].iloc[0]
	assert row_315["objects_total"] == 30
	assert row_315["n_animals"] == 3


# --- relative abundance -----------------------------------------------------


def test_relative_abundance_within(region_by_subject):
	out = relative_abundance(region_by_subject, method="within")
	z = dict(zip(out["Region ID"], out["relative_abundance_z"]))
	# totals [30, 10] -> mean 20, std(ddof=0) 10 -> z = [+1, -1].
	assert z[315] == pytest.approx(1.0)
	assert z[672] == pytest.approx(-1.0)
	assert set(out["rel_abundance_method"]) == {"within"}


def test_relative_abundance_reference_uses_supplied_stats(region_by_subject):
	stats = {"reference_mean": 0.0, "reference_std": 10.0}
	out = relative_abundance(region_by_subject, method="reference", reference_stats=stats)
	z = dict(zip(out["Region ID"], out["relative_abundance_z"]))
	assert z[315] == pytest.approx(3.0)  # (30 - 0) / 10
	assert z[672] == pytest.approx(1.0)  # (10 - 0) / 10
	assert set(out["rel_abundance_method"]) == {"reference"}
	assert "reference_mean" in out.columns


def test_relative_abundance_reference_requires_stats(region_by_subject):
	with pytest.raises(ValueError):
		relative_abundance(region_by_subject, method="reference")


def test_relative_abundance_invalid_method(region_by_subject):
	with pytest.raises(ValueError):
		relative_abundance(region_by_subject, method="bogus")


# --- reference stats --------------------------------------------------------


def test_compute_reference_stats(region_by_subject):
	stats = compute_reference_stats(region_by_subject)
	assert stats["reference_mean"] == pytest.approx(20.0)
	assert stats["reference_std"] == pytest.approx(10.0)
	assert stats["n_regions_reference"] == 2


def test_compute_reference_stats_zero_std_raises():
	# Single region -> population std is 0 -> cannot z-score.
	df = pd.DataFrame(
		[
			{
				"animal": "A1",
				"Region ID": 315,
				"Region name": "R",
				"objects": 5,
				"region_area": 1.0,
			},
			{
				"animal": "A2",
				"Region ID": 315,
				"Region name": "R",
				"objects": 5,
				"region_area": 1.0,
			},
		]
	)
	with pytest.raises(ValueError):
		compute_reference_stats(df)


# --- frequency / consistency ------------------------------------------------


def test_consistency_score_frequency(region_by_subject):
	out = consistency_score(region_by_subject)
	freq = dict(zip(out["Region ID"], out["frequency"]))
	# 3 animals; region 315 positive in A1,A2 (A3=0); region 672 positive in A2,A3.
	assert freq[315] == pytest.approx(2 / 3)
	assert freq[672] == pytest.approx(2 / 3)
	assert set(out["total_animals"]) == {3}


# --- density ----------------------------------------------------------------


def test_density_score(region_by_subject):
	out = density_score(region_by_subject)
	dens = dict(zip(out["Region ID"], out["density"]))
	assert dens[315] == pytest.approx(30 / 100)
	assert dens[672] == pytest.approx(10 / 50)


def test_density_score_zero_area_is_na():
	df = pd.DataFrame(
		[
			{"animal": "A1", "Region ID": 1, "Region name": "Z", "objects": 5, "region_area": 0.0},
			{"animal": "A2", "Region ID": 1, "Region name": "Z", "objects": 7, "region_area": 0.0},
		]
	)
	out = density_score(df)
	assert pd.isna(out.loc[out["Region ID"] == 1, "density"].iloc[0])


# --- score_table integration ------------------------------------------------


def test_score_table_ungrouped_has_all_score_columns(quint_dir):
	out = score_table(quint_dir)
	for col in ("relative_abundance_z", "frequency", "density"):
		assert col in out.columns
	assert "group_label" not in out.columns
	assert set(out["Region ID"].dropna()) == {0, 315, 672, 997}


def test_score_table_subset_of_scores(quint_dir):
	out = score_table(quint_dir, scores=["density"])
	assert "density" in out.columns
	assert "frequency" not in out.columns


def test_score_table_invalid_score_raises(quint_dir):
	with pytest.raises(ValueError):
		score_table(quint_dir, scores=["not_a_score"])


def test_score_table_grouped(quint_dir, metadata_csv):
	out = score_table(
		quint_dir,
		metadata_path=metadata_csv,
		metadata_sep=",",
		group_col="group",
	)
	assert "group_label" in out.columns
	assert set(out["group_label"]) == {"control", "treated"}


def test_score_table_reference_group_mode(quint_dir, metadata_csv):
	out = score_table(
		quint_dir,
		scores=["rel_abundance"],
		metadata_path=metadata_csv,
		metadata_sep=",",
		group_col="group",
		rel_abundance_method="reference",
		reference_mode="group",
		reference_group="control",
	)
	assert "relative_abundance_z" in out.columns
	assert set(out["rel_abundance_method"]) == {"reference"}


def test_score_table_reference_group_missing_raises(quint_dir, metadata_csv):
	with pytest.raises(ValueError):
		score_table(
			quint_dir,
			scores=["rel_abundance"],
			metadata_path=metadata_csv,
			metadata_sep=",",
			group_col="group",
			rel_abundance_method="reference",
			reference_mode="group",
			reference_group="nonexistent",
		)


# --- save_scores ------------------------------------------------------------


def test_save_scores_writes_table_matching_score_table(quint_dir, tmp_path):
	out_path = tmp_path / "nested" / "scores.csv"  # nested dir must be created
	returned = save_scores(quint_dir, str(out_path), scores=["density"])

	assert os.path.exists(out_path)
	reloaded = pd.read_csv(out_path)
	# The returned table equals score_table(), and the file is its serialization.
	expected = score_table(quint_dir, scores=["density"])
	pd.testing.assert_frame_equal(returned.reset_index(drop=True), expected.reset_index(drop=True))
	assert set(reloaded["Region ID"].dropna()) == {0, 315, 672, 997}
