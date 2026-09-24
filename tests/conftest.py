"""Shared fixtures for the PlotlyBrain backend test suite.

Fixtures are synthetic and self-contained so the suite is deterministic and
never touches the network (Allen Institute downloads are mocked or avoided).
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def structure_df() -> pd.DataFrame:
	"""Minimal Allen ontology table, shaped like load_structure_graph()."""
	return pd.DataFrame(
		[
			{
				"id": 315,
				"acronym": "Isocortex",
				"name": "Isocortex",
				"parent_structure_id": 8,
				"structure_id_path": "/997/8/315/",
				"color_hex_triplet": "70FF71",
			},
			{
				"id": 672,
				"acronym": "CP",
				"name": "Caudoputamen",
				"parent_structure_id": 8,
				"structure_id_path": "/997/8/672/",
				"color_hex_triplet": "98D6F9",
			},
		]
	)


@pytest.fixture
def synthetic_volume() -> np.ndarray:
	"""Tiny 3D annotation volume with one large region block on slice 1.

	Shape is (3, 30, 30) so coronal slicing (axis 0) yields indices 0-2.
	Slice 1 holds a solid 20x20 block of region id 315; everything else is
	background (0). The block is far larger than the default min_area_px, so
	build_geojson is guaranteed to emit one feature.
	"""
	vol = np.zeros((3, 30, 30), dtype=np.uint32)
	vol[1, 5:25, 5:25] = 315
	return vol


@pytest.fixture
def region_by_subject() -> pd.DataFrame:
	"""Hand-built per-animal/per-region counts (output of
	compute_animal_region_counts) with known aggregate scores.

	Region 315: objects_total=30, area mean=100, 2/3 animals positive.
	Region 672: objects_total=10, area mean=50,  2/3 animals positive.
	"""
	return pd.DataFrame(
		[
			{
				"animal": "A1",
				"Region ID": 315,
				"Region name": "Isocortex",
				"objects": 10,
				"region_area": 100.0,
			},
			{
				"animal": "A1",
				"Region ID": 672,
				"Region name": "Caudoputamen",
				"objects": 0,
				"region_area": 50.0,
			},
			{
				"animal": "A2",
				"Region ID": 315,
				"Region name": "Isocortex",
				"objects": 20,
				"region_area": 100.0,
			},
			{
				"animal": "A2",
				"Region ID": 672,
				"Region name": "Caudoputamen",
				"objects": 4,
				"region_area": 50.0,
			},
			{
				"animal": "A3",
				"Region ID": 315,
				"Region name": "Isocortex",
				"objects": 0,
				"region_area": 100.0,
			},
			{
				"animal": "A3",
				"Region ID": 672,
				"Region name": "Caudoputamen",
				"objects": 6,
				"region_area": 50.0,
			},
		]
	)


def _write_quint_csv(path, region_rows):
	"""Write a QUINT-style ';'-separated *_RefAtlasRegions.csv file.

	region_rows: list of (region_id, region_name, object_count, region_area).
	Always includes background (0) and root (997) rows to verify
	load_refatlas_regions retains them (GeoBrain no longer excludes any
	region by ID; see issue #40).
	"""
	header = "Region ID;Region name;Object count;Region area"
	lines = [header, "0;Clear Label;1;0", "997;root;0;72746.0"]
	for rid, name, count, area in region_rows:
		lines.append(f"{rid};{name};{count};{area}")
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def quint_dir(tmp_path):
	"""Directory of synthetic QUINT exports for 4 animals across 2 groups.

	Animal A1 has region 315 split into two rows (4 + 6) to exercise the
	per-animal summation in compute_animal_region_counts.
	"""
	data = tmp_path / "quint"
	data.mkdir()

	# A1: 315 appears twice (4 + 6 = 10); 672 absent (count 0)
	_write_quint_csv(
		data / "A1_RefAtlasRegions.csv",
		[
			(315, "Isocortex", 4, 100.0),
			(315, "Isocortex", 6, 100.0),
			(672, "Caudoputamen", 0, 50.0),
		],
	)
	_write_quint_csv(
		data / "A2_RefAtlasRegions.csv",
		[(315, "Isocortex", 20, 100.0), (672, "Caudoputamen", 4, 50.0)],
	)
	_write_quint_csv(
		data / "A3_RefAtlasRegions.csv",
		[(315, "Isocortex", 6, 100.0), (672, "Caudoputamen", 2, 50.0)],
	)
	_write_quint_csv(
		data / "A4_RefAtlasRegions.csv",
		[(315, "Isocortex", 8, 100.0), (672, "Caudoputamen", 0, 50.0)],
	)
	return str(data)


@pytest.fixture
def metadata_csv(tmp_path):
	"""Metadata CSV mapping animals to groups. Column names include leading
	whitespace to exercise the column-stripping in MetadataConfig.load().
	"""
	path = tmp_path / "metadata.csv"
	path.write_text(
		"animal, group , sex\nA1,control,M\nA2,control,F\nA3,treated,M\nA4,treated,F\n",
		encoding="utf-8",
	)
	return str(path)


@pytest.fixture
def sample_geojson() -> dict:
	"""Small lon/lat FeatureCollection with two regions plus an excluded one."""

	def feature(rid, name, square):
		return {
			"type": "Feature",
			"properties": {
				"feature_id": f"1_{rid}",
				"Region ID": rid,
				"Region name": name,
				"slice_index": 1,
				"coordinate_mm": -2.0,
				"orientation": "coronal",
				"resolution_um": 25,
			},
			"geometry": {"type": "MultiPolygon", "coordinates": [[square]]},
		}

	sq_a = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
	sq_b = [[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 3.0], [2.0, 2.0]]
	sq_root = [[4.0, 4.0], [5.0, 4.0], [5.0, 5.0], [4.0, 5.0], [4.0, 4.0]]
	return {
		"type": "FeatureCollection",
		"features": [
			feature(315, "Isocortex", sq_a),
			feature(672, "Caudoputamen", sq_b),
			feature(997, "root", sq_root),
		],
	}


@pytest.fixture
def score_df() -> pd.DataFrame:
	"""Region-level score table aligned with sample_geojson."""
	return pd.DataFrame(
		{
			"Region ID": [315, 672],
			"Region name": ["Isocortex", "Caudoputamen"],
			"density": [0.3, 0.2],
		}
	)
