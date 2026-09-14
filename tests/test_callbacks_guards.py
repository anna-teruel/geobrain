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

	def fake_build_export_figure(*, score_records, **kwargs):
		captured["score_records"] = score_records
		return "fig"

	monkeypatch.setattr(figure, "build_export_figure", fake_build_export_figure)
	monkeypatch.setattr(geobrain, "save_figure", lambda fig, **kwargs: "/tmp/brain.svg")

	fn = callbacks_by_name["export_slice"]
	slices = [{"slice_index": 1}]
	out = fn(*_export_args(session, None, slices))  # geometry + slices, no scores

	assert captured["score_records"] == []
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
