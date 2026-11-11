"""Tests for the guard / error branches of the synchronous Dash callbacks.

The callbacks are closures registered inside ``register_callbacks``; each
registered entry keeps the raw inner function on ``.callback.__wrapped__``,
which we invoke directly with positional args. Branches that raise a toast call
``set_props``, which needs a Dash callback context - the ``toast_ctx`` fixture
installs a minimal one and captures the emitted notifications.

The happy paths of these callbacks run in headless Chrome (test_app_callbacks);
here we cover only the early-return / exception branches the browser flow skips.
"""

import base64
import json

import numpy as np
import pytest
from dash import no_update

import geobrain
from geobrain.app import cache, figure


@pytest.fixture(scope="module")
def callbacks_by_name():
	"""Map each registered callback's function name to its raw inner function."""
	from geobrain.app.server import create_app

	app = create_app()
	out = {}
	for spec in app.callback_map.values():
		fn = spec.get("callback")
		inner = getattr(fn, "__wrapped__", None)  # clientside callbacks have neither
		if inner is not None:
			out[inner.__name__] = inner
	return out


@pytest.fixture
def toast_ctx():
	"""Install a minimal Dash callback context so ``set_props`` (toasts) works.

	Yields the context's ``updated_props`` dict; after a toast it holds the
	``notifications-container`` entry with the emitted ``dmc.Notification``.
	"""
	from dash._callback_context import context_value
	from dash._utils import AttributeDict

	ctx = AttributeDict(updated_props={})
	token = context_value.set(ctx)
	yield ctx.updated_props
	context_value.reset(token)


@pytest.fixture
def session():
	"""A cache session id that is wiped after the test."""
	sid = cache.new_session()
	yield sid
	cache.clear(sid)


def _data_url(raw: bytes, mime: str = "application/json") -> str:
	return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _toast_color(updated_props) -> str:
	"""Color of the most recently emitted notification."""
	return updated_props["notifications-container"]["children"].color


# --------------------------------------------------------------------------- #
# download_geojson / download_scores - empty-data guards (no toast)
# --------------------------------------------------------------------------- #
def test_download_geojson_no_geometry(callbacks_by_name):
	fn = callbacks_by_name["download_geojson"]
	assert fn(1, None, None) is no_update


def test_download_geojson_empty_by_slice(callbacks_by_name):
	fn = callbacks_by_name["download_geojson"]
	assert fn(1, {"by_slice": {}}, None) is no_update


def test_download_scores_no_scores(callbacks_by_name):
	assert callbacks_by_name["download_scores"](1, None) is no_update


# --------------------------------------------------------------------------- #
# load_cached_geojson - empty / unreadable / no-slices
# --------------------------------------------------------------------------- #
def test_load_cached_geojson_no_contents(callbacks_by_name):
	result = callbacks_by_name["load_cached_geojson"](None, None, None)
	assert len(result) == 8
	assert result[6] == "Choose a GeoJSON file to load."
	assert result[:6] == (no_update,) * 6


def test_load_cached_geojson_bad_json_toasts_error(callbacks_by_name, toast_ctx):
	bad = _data_url(b"{ not valid json")
	result = callbacks_by_name["load_cached_geojson"](bad, "x.geojson", None)
	assert len(result) == 8
	assert _toast_color(toast_ctx) == "red"


def test_load_cached_geojson_no_slices_toasts_warning(callbacks_by_name, toast_ctx):
	empty = _data_url(json.dumps({"type": "FeatureCollection", "features": []}).encode())
	# Pass a session id so the no-slices branch is reached without allocating one.
	result = callbacks_by_name["load_cached_geojson"](empty, "x.geojson", "test-session")
	assert result[6] == "No slices found in that GeoJSON."
	assert _toast_color(toast_ctx) == "yellow"


# --------------------------------------------------------------------------- #
# load_cached_scores - empty / unreadable
# --------------------------------------------------------------------------- #
def test_load_cached_scores_no_contents(callbacks_by_name):
	data, msg = callbacks_by_name["load_cached_scores"](None, None)
	assert data is no_update
	assert msg == "Choose a scores CSV to load."


def test_load_cached_scores_bad_csv_toasts_error(callbacks_by_name, toast_ctx):
	# Empty bytes make pandas raise EmptyDataError.
	bad = _data_url(b"", mime="text/csv")
	data, _ = callbacks_by_name["load_cached_scores"](bad, "x.csv")
	assert data is no_update
	assert _toast_color(toast_ctx) == "red"


def test_load_cached_scores_wrong_columns_toasts_error(callbacks_by_name, toast_ctx):
	wrong = _data_url(b"name,value\na,1\n", mime="text/csv")
	data, _ = callbacks_by_name["load_cached_scores"](wrong, "x.csv")
	assert data is no_update
	assert _toast_color(toast_ctx) == "red"


# --------------------------------------------------------------------------- #
# export_slice - missing geometry / nothing to export / export failure
# --------------------------------------------------------------------------- #
def _export_args(session_id, scores, slices):
	"""Positional args for export_slice with placeholder render controls."""
	return (
		1,  # n_clicks
		session_id,
		scores,
		slices,
		0,  # slider_val
		"density",  # score
		"All",  # group
		"Viridis",  # colorscale
		None,  # zmin
		None,  # zmax
		".",  # out_dir
		"brain",  # name
		"svg",  # fmt
		None,  # selected_ids
		None,  # static_color
		False,  # use_flat
	)


def test_export_slice_no_geometry(callbacks_by_name, toast_ctx):
	fn = callbacks_by_name["export_slice"]
	out = fn(*_export_args(None, None, None))
	assert out == "No geometry in memory - build or load slices first."
	assert _toast_color(toast_ctx) == "yellow"


def test_export_slice_nothing_to_export(callbacks_by_name, toast_ctx, session):
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})
	fn = callbacks_by_name["export_slice"]
	out = fn(*_export_args(session, None, None))  # geometry present, no scores
	assert out == "Nothing to export yet."
	assert _toast_color(toast_ctx) == "yellow"


def test_export_slice_no_scores_exports_empty_atlas(
	callbacks_by_name, toast_ctx, session, monkeypatch
):
	"""Slices without loaded scores still export - a plain atlas map (issue #45)."""
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})

	captured = {}

	def fake_build_export_figure(*, score_records, title, **kwargs):
		captured["score_records"] = score_records
		captured["title"] = title
		return "fig"

	monkeypatch.setattr(figure, "build_export_figure", fake_build_export_figure)
	monkeypatch.setattr(geobrain, "save_figure", lambda fig, **kwargs: "/tmp/brain.svg")

	fn = callbacks_by_name["export_slice"]
	slices = [{"slice_index": 1}]
	out = fn(*_export_args(session, None, slices))  # geometry + slices, no scores

	assert captured["score_records"] == []
	assert captured["title"] is None
	assert "Saved" in out.children
	assert _toast_color(toast_ctx) == "green"


# --------------------------------------------------------------------------- #
# export_all_slices - missing geometry / nothing to export / no scores
# --------------------------------------------------------------------------- #
def _export_all_args(session_id, scores, slices):
	"""Positional args for export_all_slices (background callback: no set_progress)."""
	return (
		1,  # n_clicks
		session_id,
		scores,
		slices,
		"density",  # score
		"All",  # group
		"Viridis",  # colorscale
		None,  # zmin
		None,  # zmax
		".",  # out_dir
		"brain",  # name
		"svg",  # fmt
		None,  # selected_ids
		None,  # static_color
		False,  # use_flat
	)


def test_export_all_slices_no_geometry(callbacks_by_name, toast_ctx):
	fn = callbacks_by_name["export_all_slices"]
	out = fn(lambda *a: None, *_export_all_args(None, None, None))
	assert out == "No geometry in memory - build or load slices first."
	assert _toast_color(toast_ctx) == "yellow"


def test_export_all_slices_nothing_to_export(callbacks_by_name, toast_ctx, session):
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})
	fn = callbacks_by_name["export_all_slices"]
	out = fn(lambda *a: None, *_export_all_args(session, None, None))  # no slices
	assert out == "Nothing to export yet."
	assert _toast_color(toast_ctx) == "yellow"


def test_export_all_slices_no_scores_exports_empty_atlas(
	callbacks_by_name, toast_ctx, session, monkeypatch
):
	"""Slices without loaded scores still export - a plain atlas map (issue #45)."""
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})

	captured = []
	titles = []

	def fake_build_export_figure(*, score_records, title, **kwargs):
		captured.append(score_records)
		titles.append(title)
		return "fig"

	monkeypatch.setattr(figure, "build_export_figure", fake_build_export_figure)
	monkeypatch.setattr(geobrain, "save_figure", lambda fig, **kwargs: "/tmp/brain.svg")

	fn = callbacks_by_name["export_all_slices"]
	slices = [{"slice_index": 1}, {"slice_index": 2}]
	progress_calls = []
	out = fn(
		progress_calls.append, *_export_all_args(session, None, slices)
	)  # geometry + slices, no scores

	assert captured == [[], []]
	assert titles == [None, None]
	assert "Saved" in out.children
	assert _toast_color(toast_ctx) == "green"


def test_export_all_slices_with_scores_exports(callbacks_by_name, toast_ctx, session, monkeypatch):
	"""With scores loaded, each slice is exported using the matched group's records."""
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})

	captured = []
	titles = []

	def fake_build_export_figure(*, score_records, title, **kwargs):
		captured.append(score_records)
		titles.append(title)
		return "fig"

	monkeypatch.setattr(figure, "build_export_figure", fake_build_export_figure)
	monkeypatch.setattr(geobrain, "save_figure", lambda fig, **kwargs: "/tmp/brain.svg")

	fn = callbacks_by_name["export_all_slices"]
	scores = {"All": [{"Region ID": 315, "density": 0.2}]}
	slices = [{"slice_index": 1}, {"slice_index": 2}]
	progress_calls = []
	out = fn(progress_calls.append, *_export_all_args(session, scores, slices))

	assert captured == [scores["All"], scores["All"]]
	assert titles == ["density - slice 1", "density - slice 2"]
	assert "Saved" in out.children
	assert _toast_color(toast_ctx) == "green"


def test_export_slice_export_failure_toasts_error(
	callbacks_by_name, toast_ctx, session, monkeypatch
):
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})

	def boom(**kwargs):
		raise RuntimeError("kaleido missing")

	monkeypatch.setattr(figure, "build_export_figure", boom)

	fn = callbacks_by_name["export_slice"]
	scores = {"All": [{"Region ID": 315, "density": 0.2}]}
	slices = [{"slice_index": 1}]
	out = fn(*_export_args(session, scores, slices))
	# _status returns a dmc.Text whose first child carries the message.
	assert "Export failed" in out.children
	assert _toast_color(toast_ctx) == "red"


# --------------------------------------------------------------------------- #
# load_raw / build_geo - bregma only for Allen mouse, slices clipped to atlas
# --------------------------------------------------------------------------- #


class _FakeAtlas:
	def __init__(self, name, structure_df):
		self.name = name
		self.species = "mouse"
		self.annotation = np.zeros((3, 30, 30), dtype=np.uint32)
		self.annotation[1, 5:25, 5:25] = 315
		self.structure_df = structure_df
		self.voxel_size_um = (25.0, 25.0, 25.0)


@pytest.mark.parametrize(
	"atlas_name, expected", [("allen_mouse_25um", "mouse"), ("allen_cord_20um", "none")]
)
def test_load_raw_bregma_only_for_allen_mouse(
	callbacks_by_name, monkeypatch, structure_df, atlas_name, expected
):
	monkeypatch.setattr(geobrain, "load_atlas", lambda name: _FakeAtlas(name, structure_df))
	sid, _, _ = callbacks_by_name["load_raw"](lambda _: None, 1, atlas_name, None)
	try:
		assert cache.get(sid, "coord_species") == expected
	finally:
		cache.clear(sid)


def test_build_geo_drops_slices_outside_atlas(callbacks_by_name, toast_ctx, session, structure_df):
	atlas = _FakeAtlas("allen_mouse_25um", structure_df)
	cache.put(session, "volume", atlas.annotation)
	cache.put(session, "structure_df", structure_df)
	cache.put(session, "voxel_size_um", atlas.voxel_size_um)
	cache.put(session, "coord_species", "mouse")
	# At 25 um bregma is slice 228, so 5.6..6.0 mm spans indices -12..4; only 0-2 exist.
	result = callbacks_by_name["build_geo"](
		lambda _: None, 1, session, "coronal", 5.6, 6.0, None, "raster", 5.0, 0.0, 1.0
	)
	slices = result[1]
	assert [s["slice_index"] for s in slices] == [0, 1, 2]


# --------------------------------------------------------------------------- #
# load_cached_geojson - schema validation (pydantic)
# --------------------------------------------------------------------------- #


def _feature(props, geometry):
	return {"type": "Feature", "properties": props, "geometry": geometry}


_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]


def test_load_cached_geojson_valid_upload(callbacks_by_name, toast_ctx, session):
	gj = {
		"type": "FeatureCollection",
		"features": [
			_feature(
				{
					"Region ID": 315,
					"Region name": "Isocortex",
					"slice_index": 4,
					"coordinate_mm": -2,
				},
				{"type": "Polygon", "coordinates": [_SQUARE]},
			)
		],
	}
	result = callbacks_by_name["load_cached_geojson"](
		_data_url(json.dumps(gj).encode()), "x.geojson", session
	)
	geometry, slices = result[0], result[1]
	assert slices == [{"slice_index": 4, "coordinate_mm": -2.0}]
	assert geometry["by_slice"]["4"][0]["rid"] == 315


@pytest.mark.parametrize(
	"props, geometry, field",
	[
		({"slice_index": 1}, {"type": "Polygon", "coordinates": [_SQUARE]}, "Region ID"),
		(
			{"Region ID": 1, "slice_index": 1},
			{"type": "Polygon", "coordinates": [[[0, 0, 5], [1, 0, 5], [1, 1, 5]]]},
			"coordinates",
		),
		({"Region ID": 1}, {"type": "Polygon", "coordinates": [_SQUARE]}, "slice_index"),
	],
)
def test_load_cached_geojson_rejects_bad_features(
	callbacks_by_name, toast_ctx, props, geometry, field
):
	gj = {"type": "FeatureCollection", "features": [_feature(props, geometry)]}
	result = callbacks_by_name["load_cached_geojson"](
		_data_url(json.dumps(gj).encode()), "x.geojson", None
	)
	assert result[0] is no_update
	assert _toast_color(toast_ctx) == "red"
	assert field in toast_ctx["notifications-container"]["children"].message


# --------------------------------------------------------------------------- #
# side-by-side group option
# --------------------------------------------------------------------------- #
def test_populate_groups_offers_side_by_side_for_multiple_groups(callbacks_by_name):
	fn = callbacks_by_name["populate_groups"]
	options, default = fn({"control": [], "treated": [], "All (mean)": []})
	assert [o["value"] for o in options] == ["control", "treated", "All (mean)", "Side by side"]
	assert default == "All (mean)"
	# A single group has nothing to compare.
	options, _ = fn({"All": []})
	assert [o["value"] for o in options] == ["All"]


def test_export_slice_side_by_side_passes_every_group(
	callbacks_by_name, toast_ctx, session, monkeypatch
):
	cache.put(session, "geometry", {"by_slice": {}, "orientation": "coronal"})
	captured = {}
	monkeypatch.setattr(
		figure,
		"build_export_figure",
		lambda *, score_records, **kw: captured.update(r=score_records),
	)
	monkeypatch.setattr(geobrain, "save_figure", lambda fig, **kwargs: "/tmp/brain.svg")

	scores = {"control": [{"Region ID": 1}], "treated": [{"Region ID": 2}], "All (mean)": []}
	args = list(_export_args(session, scores, [{"slice_index": 1}]))
	args[6] = "Side by side"  # group
	callbacks_by_name["export_slice"](*args)
	assert captured["r"] == {"control": scores["control"], "treated": scores["treated"]}


def test_export_publication_range_guards(callbacks_by_name, toast_ctx, session):
	"""No geometry, a missing bound, or a range that holds no slice each return a
	message and no download; From/To given in either order select the slices."""
	export = callbacks_by_name["export_publication"]
	slices = [{"slice_index": i, "coordinate_mm": float(i)} for i in range(3)]

	def call(lo, hi, sl=slices):
		return export(
			1,
			session,
			{},
			sl,
			"density",
			"Viridis",
			None,
			None,
			"n",
			"svg",
			[],
			"#fff",
			False,
			lo,
			hi,
		)

	assert call(0, 1)[1] is no_update  # nothing cached yet
	cache.put(
		session,
		"geometry",
		{
			"by_slice": {str(i): [] for i in range(3)},
			"dims": {"w": 4, "h": 4},
			"orientation": "coronal",
		},
	)
	assert call(None, 1)[1] is no_update
	assert call(10, 20)[0] == "No slices fall in that range."
	assert call(2, 1)[0] != "No slices fall in that range."  # reversed bounds are sorted
