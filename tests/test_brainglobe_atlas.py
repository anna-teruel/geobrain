"""Tests for geobrain.brainglobe_atlas, geobrain.io.load_atlas and species handling downstream of it.

brainglobe_atlasapi's BrainGlobeAtlas is replaced by an in-memory fake so nothing is downloaded.
"""

import json
from types import SimpleNamespace

import numpy as np
import pytest

import geobrain.brainglobe_atlas as atlas_module
from geobrain.app import figure
from geobrain.brainglobe_atlas import BrainGlobeAtlas
from geobrain.build_geoJSON import build_geojson
from geobrain.io import load_atlas


def _fake_atlas(
	name="fake_mouse_25um",
	species="Mus musculus",
	origin=("a", "s", "r"),
	resolution=(25.0, 25.0, 25.0),
	annotation=None,
):
	structures = {
		997: {
			"id": 997,
			"acronym": "root",
			"name": "root",
			"parent_structure_id": np.nan,  # what BrainGlobe gives the root
			"structure_id_path": [997],
			"rgb_triplet": [255, 255, 255],
		},
		315: {
			"id": 315,
			"acronym": "Isocortex",
			"name": "Isocortex",
			"parent_structure_id": 997.0,
			"structure_id_path": [997, 315],
			"rgb_triplet": [112, 255, 113],
		},
		182305693: {
			"id": 182305693,
			"acronym": "SSp-un1",
			"name": "Primary somatosensory area, unassigned, layer 1",
			# brainglobe_atlasapi reads parents as uint16: 182305689 wraps to 50073
			"parent_structure_id": 50073,
			"structure_id_path": [997, 182305689, 182305693],
			"rgb_triplet": [24, 128, 100],
		},
	}
	return SimpleNamespace(
		atlas_name=name,
		metadata={"species": species},
		space=SimpleNamespace(origin=origin),
		resolution=resolution,
		annotation=annotation,
		structures=structures,
	)


@pytest.fixture
def use_fake_atlas(monkeypatch):
	"""Patch brainglobe_atlasapi's BrainGlobeAtlas; call the returned function with _fake_atlas kwargs."""

	def install(**kwargs):
		fake = _fake_atlas(**kwargs)
		monkeypatch.setattr(atlas_module, "_BGAtlas", lambda name: fake)
		return fake

	return install


# --- BrainGlobeAtlas -----------------------------------------------------


def test_structure_df_schema_and_values(use_fake_atlas):
	use_fake_atlas()
	df = BrainGlobeAtlas("fake_mouse_25um").structure_df

	assert list(df.columns) == [
		"id",
		"acronym",
		"name",
		"parent_structure_id",
		"structure_id_path",
		"color_hex_triplet",
	]
	rows = df.set_index("id").to_dict(orient="index")
	assert rows[315]["color_hex_triplet"] == "70FF71"
	assert rows[315]["parent_structure_id"] == 997
	assert type(rows[315]["parent_structure_id"]) is int
	assert rows[997]["parent_structure_id"] is None
	# Parent comes from structure_id_path, not the uint16-truncated field.
	assert rows[182305693]["parent_structure_id"] == 182305689


def test_structure_df_serializes_to_valid_json(use_fake_atlas):
	# NaN would be written as a bare `NaN` token, which is not valid JSON.
	use_fake_atlas()
	records = BrainGlobeAtlas("fake_mouse_25um").structure_df.to_dict(orient="records")
	json.loads(json.dumps(records, allow_nan=False))


@pytest.mark.parametrize(
	"species, expected",
	[("Mus musculus", "mouse"), ("mus musculus ", "mouse"), ("Homo sapiens", "Homo sapiens")],
)
def test_species_maps_to_common_name(use_fake_atlas, species, expected):
	use_fake_atlas(species=species)
	assert BrainGlobeAtlas("fake").species == expected


def test_name_and_resolution(use_fake_atlas):
	use_fake_atlas(name="allen_mouse_25um")
	atlas = load_atlas("allen_mouse_25um")
	assert atlas.name == "allen_mouse_25um"
	assert atlas.resolution_um == 25.0


def test_non_isotropic_resolution_raises(use_fake_atlas):
	use_fake_atlas(resolution=(25.0, 25.0, 50.0))
	with pytest.raises(ValueError, match="Non-isotropic"):
		BrainGlobeAtlas("fake").resolution_um


def test_non_asr_origin_raises(use_fake_atlas):
	use_fake_atlas(origin=("l", "s", "a"))
	with pytest.raises(ValueError, match="standard 'asr'"):
		BrainGlobeAtlas("fake")


# --- species downstream: build_geojson / build_slice_geometry ---------------


def test_build_geojson_from_non_mouse_atlas_by_index(use_fake_atlas, synthetic_volume):
	use_fake_atlas(species="Homo sapiens", annotation=synthetic_volume)
	atlas = BrainGlobeAtlas("fake_human")
	geojson = build_geojson(
		volume=atlas.annotation,
		structure_df=atlas.structure_df,
		orientation="coronal",
		resolution_um=atlas.resolution_um,
		species=atlas.species,
		slice_indices=[1],
	)
	props = geojson["features"][0]["properties"]
	assert props["Region ID"] == 315
	assert props["coordinate_mm"] is None
	assert props["parent_structure_id"] == 997
	json.loads(json.dumps(geojson, allow_nan=False))


def test_build_geojson_non_mouse_rejects_bregma_coords(synthetic_volume, structure_df):
	with pytest.raises(ValueError, match="only supported for species='mouse'"):
		build_geojson(
			volume=synthetic_volume,
			structure_df=structure_df,
			orientation="coronal",
			species="Homo sapiens",
			coords_mm=[-2.0],
		)


def test_build_geojson_mouse_keeps_coordinates(synthetic_volume, structure_df):
	geojson = build_geojson(
		volume=synthetic_volume,
		structure_df=structure_df,
		orientation="coronal",
		species="mouse",
		slice_indices=[1],
	)
	assert geojson["features"][0]["properties"]["coordinate_mm"] is not None


@pytest.mark.parametrize("species, has_coord", [("mouse", True), ("Homo sapiens", False)])
def test_build_slice_geometry_coordinate_by_species(
	synthetic_volume, structure_df, species, has_coord
):
	_, slices = figure.build_slice_geometry(
		volume=synthetic_volume,
		structure_df=structure_df,
		orientation="coronal",
		resolution_um=25,
		slice_indices=[1],
		species=species,
	)
	assert (slices[0]["coordinate_mm"] is not None) == has_coord


@pytest.mark.parametrize(
	("name", "species"),
	[
		("allen_mouse_25um", "mouse"),
		("whs_sd_rat_39um", "rat"),
		("nadkarni_mri_mouselemur_91um", "mouse lemur"),
		("african_molerat_20um", "african mole-rat"),
		("azba_zfish_4um", "zebrafish"),
		("mystery_brain_10um", atlas_module.OTHER_SPECIES),
	],
)
def test_atlas_species_from_name(name, species):
	assert atlas_module.atlas_species_from_name(name) == species


def test_list_available_atlases_merges_remote_and_downloaded(monkeypatch):
	monkeypatch.setattr(
		atlas_module.list_atlases,
		"get_all_atlases_lastversions",
		lambda: {"allen_mouse_25um": "3.0", "admba_3d_p14_mouse_16.752um": "3.0"},
	)
	monkeypatch.setattr(
		atlas_module.list_atlases, "get_downloaded_atlases", lambda: ["whs_sd_rat_39um"]
	)
	atlas_module.list_available_atlases.cache_clear()
	try:
		catalog = atlas_module.list_available_atlases()
	finally:
		atlas_module.list_available_atlases.cache_clear()

	rows = catalog.set_index("name")
	assert set(rows.index) == {"allen_mouse_25um", "admba_3d_p14_mouse_16.752um", "whs_sd_rat_39um"}
	assert rows.loc["admba_3d_p14_mouse_16.752um", "resolution_um"] == 16.752
	assert rows.loc["whs_sd_rat_39um", "species"] == "rat"
	assert rows.loc["whs_sd_rat_39um", "downloaded"]
	assert not rows.loc["allen_mouse_25um", "downloaded"]


def test_list_available_atlases_offline_falls_back_to_allen_mouse(monkeypatch):
	def _offline():
		raise ConnectionError("no network")

	monkeypatch.setattr(atlas_module.list_atlases, "get_all_atlases_lastversions", _offline)
	monkeypatch.setattr(atlas_module.list_atlases, "get_downloaded_atlases", lambda: [])
	atlas_module.list_available_atlases.cache_clear()
	try:
		catalog = atlas_module.list_available_atlases()
	finally:
		atlas_module.list_available_atlases.cache_clear()

	assert list(catalog["name"]) == [f"allen_mouse_{r}um" for r in (10, 25, 50, 100)]


def test_ui_atlas_options_chain():
	from geobrain.app import layout

	catalog = atlas_module.pd.DataFrame(
		[
			("allen_mouse_25um", "allen_mouse", "mouse", 25.0, True),
			("allen_mouse_10um", "allen_mouse", "mouse", 10.0, False),
			("whs_sd_rat_39um", "whs_sd_rat", "rat", 39.0, False),
		],
		columns=["name", "atlas", "species", "resolution_um", "downloaded"],
	)
	assert [o["value"] for o in layout.species_options(catalog)] == ["mouse", "rat"]
	assert layout.atlas_options(catalog, "rat") == [{"label": "whs_sd_rat", "value": "whs_sd_rat"}]
	res = layout.resolution_options(catalog, "allen_mouse")
	assert [o["value"] for o in res] == ["allen_mouse_25um", "allen_mouse_10um"]
	assert res[0]["label"] == "25 µm (downloaded)"
	assert layout.pick_option(res, "missing") == "allen_mouse_25um"
