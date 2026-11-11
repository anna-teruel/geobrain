"""Browser integration tests for the Dash app, driven by ``dash.testing``.

These spin up the real ``create_app()`` in a headless Chrome via the ``dash_duo``
fixture and confirm the callbacks wire up correctly end to end - the serverside
callbacks, the background ``process_data`` worker, and the three clientside
callbacks in ``assets/render.js`` (figure / table / slice-label).

The suite is network-free: instead of downloading the Allen atlas (the
``load_raw`` callback, and ``build_geo`` which needs the downloaded volume), the
stores are seeded by driving the GeoJSON / scores upload callbacks and the score
computation runs against the synthetic QUINT files from ``conftest``. The atlas
download path's internals are covered by the unit suite (test_build_geojson.py).

Run just these:        pytest tests/test_app_callbacks.py
Skip them (fast unit): pytest -m "not browser"
"""

import json

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from geobrain.app.server import create_app

pytestmark = pytest.mark.browser


# --------------------------------------------------------------------------- #
# Fixtures: write the synthetic conftest data out to files the uploads accept.
# --------------------------------------------------------------------------- #
@pytest.fixture
def geojson_file(tmp_path, sample_geojson):
	"""sample_geojson (regions 315/672/997 on slice 1) written to a .geojson."""
	path = tmp_path / "slices.geojson"
	path.write_text(json.dumps(sample_geojson), encoding="utf-8")
	return str(path)


@pytest.fixture
def scores_file(tmp_path):
	"""Scores CSV with two groups so populate_groups also yields 'All (mean)'.

	Columns match what render.js reads (relative_abundance_z / frequency /
	density) for region ids that exist in geojson_file.
	"""
	path = tmp_path / "scores.csv"
	path.write_text(
		"group_label,Region ID,Region name,relative_abundance_z,frequency,density\n"
		"control,315,Isocortex,1.5,0.8,0.30\n"
		"control,672,Caudoputamen,-1.0,0.4,0.20\n"
		"treated,315,Isocortex,2.0,0.9,0.50\n"
		"treated,672,Caudoputamen,-0.5,0.5,0.25\n",
		encoding="utf-8",
	)
	return str(path)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _start(dash_duo):
	"""Start the real app, with a desktop-sized window so the stage and the regions
	panel sit side by side (the default 800x600 headless window stacks them)."""
	dash_duo.driver.set_window_size(1500, 1000)
	dash_duo.start_server(create_app())


def _set_input(dash_duo, cid, value):
	"""Replace the text of a controlled (dmc) input - .clear() doesn't fire the
	React onChange, so select-all then type over it."""
	el = _input(dash_duo, cid)
	el.send_keys(Keys.CONTROL, "a")
	el.send_keys(value)


def _input(dash_duo, cid):
	"""Return the actual <input> for a component id (dmc wraps some of them)."""
	el = dash_duo.find_element(f"#{cid}")
	if el.tag_name != "input":
		el = el.find_element(By.CSS_SELECTOR, "input")
	return el


def _upload(dash_duo, container_id, path):
	"""Send a file to a dcc.Upload's hidden <input type=file>."""
	dash_duo.find_element(f"#{container_id} input[type=file]").send_keys(path)


def _js_click(dash_duo, element):
	"""Click via JS - needed for the hidden checkbox inputs behind dmc switches."""
	dash_duo.driver.execute_script("arguments[0].click()", element)


def _open(dash_duo, trigger, control_id):
	"""Click a trigger (CSS selector) and wait for a control in the modal step or
	popover it opens. Both are always in the DOM; the modal's hidden steps only
	catch up with callback updates once shown, so open one before reading state."""
	dash_duo.find_element(trigger).click()
	_wait(dash_duo, lambda: dash_duo.find_element(f"#{control_id}").is_displayed())


# Setup-modal nav tab for the scores step (the top bar is covered once the modal is open).
SCORES_TAB = ".gb-setup .gb-step-scores"


def _ticked(row):
	"""Whether a regions-list row (a role=checkbox div) is ticked."""
	return row.get_attribute("aria-checked") == "true"


def _trace_count(dash_duo):
	"""Number of traces currently on the brain-graph plotly figure (0 if none)."""
	return dash_duo.driver.execute_script(
		"var h=document.getElementById('brain-graph');"
		"var el=h&&h.querySelector('.js-plotly-plot');"
		"return el&&el.data?el.data.length:0;"
	)


def _color_scheme(dash_duo):
	return dash_duo.driver.execute_script(
		"return document.documentElement.getAttribute('data-mantine-color-scheme')"
	)


def _wait(dash_duo, predicate, timeout=20):
	WebDriverWait(dash_duo.driver, timeout).until(lambda d: predicate())


def _load_geojson_and_scores(dash_duo, geojson_file, scores_file):
	"""Common setup: load both files and wait for the brain + table to render."""
	_upload(dash_duo, "upload-geojson", geojson_file)
	dash_duo.wait_for_contains_text("#slice-label", "Slice index 1", timeout=20)
	_upload(dash_duo, "upload-scores", scores_file)
	dash_duo.wait_for_contains_text("#results-table", "Isocortex", timeout=20)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_app_boots_clean(dash_duo):
	"""App mounts, shows the empty state, and logs no severe errors."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)
	dash_duo.wait_for_contains_text("#empty-state", "Load an atlas", timeout=20)

	# Buttons that gate on stores start disabled (toggle_* callbacks).
	assert not dash_duo.find_element("#build-geo-btn").is_enabled()
	assert not dash_duo.find_element("#save-geo-btn").is_enabled()
	assert not dash_duo.find_element("#process-data-btn").is_enabled()
	assert not dash_duo.find_element("#save-scores-btn").is_enabled()

	errors = [
		e
		for e in (dash_duo.get_logs() or [])
		if e["level"] == "SEVERE" and "favicon" not in e["message"]
	]
	assert not errors, errors


def test_load_geojson_renders_brain(dash_duo, geojson_file):
	"""Upload GeoJSON -> load_cached_geojson seeds stores -> clientside render
	draws the slice, slice-label updates, and the GeoJSON Save button enables."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)

	_upload(dash_duo, "upload-geojson", geojson_file)

	dash_duo.wait_for_contains_text("#slice-label", "Slice index 1", timeout=20)
	dash_duo.wait_for_contains_text("#slice-label", "(1/1)", timeout=20)
	_wait(dash_duo, lambda: _trace_count(dash_duo) >= 2)
	# save-geo-btn is enabled by toggle_save_geo once slices exist.
	_open(dash_duo, "#chip-slices", "save-geo-btn")
	_wait(dash_duo, lambda: dash_duo.find_element("#save-geo-btn").is_enabled())


def test_load_scores_populates_groups_and_table(dash_duo, geojson_file, scores_file):
	"""Upload scores -> load_cached_scores + populate_groups fill the group select
	(defaulting to 'All (mean)'), the clientside table lists slice regions, and the
	scores Save button enables."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)

	_load_geojson_and_scores(dash_duo, geojson_file, scores_file)

	assert _input(dash_duo, "group-select").get_attribute("value") == "All (mean)"
	dash_duo.wait_for_contains_text("#results-table", "Caudoputamen", timeout=20)
	_open(dash_duo, "#chip-scores", "save-scores-btn")
	_wait(dash_duo, lambda: dash_duo.find_element("#save-scores-btn").is_enabled())


def test_score_select_updates_limits(dash_duo):
	"""Switching the score segmented control fires default_limits, which writes the
	score's default zmin/zmax into the inputs."""
	_start(dash_duo)
	dash_duo.wait_for_element("#score-select", timeout=20)

	dash_duo.driver.find_element(
		By.XPATH, "//div[@id='score-select']//label[contains(normalize-space(.),'Frequency')]"
	).click()

	_open(dash_duo, "#color-open-btn", "zmin-input")
	_wait(dash_duo, lambda: float(_input(dash_duo, "zmin-input").get_attribute("value")) == 0.0)
	assert float(_input(dash_duo, "zmax-input").get_attribute("value")) == 1.0


def test_static_color_toggle_disables_picker(dash_duo):
	"""toggle_static_color_enabled disables the flat-color picker when the flat
	toggle is switched off."""
	_start(dash_duo)
	dash_duo.wait_for_element("#static-color-toggle", timeout=20)
	_open(dash_duo, "#color-open-btn", "static-color")

	# Starts checked -> picker enabled.
	assert _input(dash_duo, "static-color").is_enabled()
	_js_click(dash_duo, _input(dash_duo, "static-color-toggle"))
	_wait(dash_duo, lambda: not _input(dash_duo, "static-color").is_enabled())


def test_theme_toggle_switches_scheme(dash_duo):
	"""set_color_scheme flips the whole app between dark and light."""
	_start(dash_duo)
	dash_duo.wait_for_element("#color-scheme-toggle", timeout=20)

	_wait(dash_duo, lambda: _color_scheme(dash_duo) == "dark")
	_js_click(dash_duo, _input(dash_duo, "color-scheme-toggle"))
	_wait(dash_duo, lambda: _color_scheme(dash_duo) == "light")


def test_row_selection_and_deselect_all(dash_duo, geojson_file, scores_file):
	"""Selecting a table row keeps the brain rendering (render.js gating) and the
	Deselect-all button (deselect_all_rows) clears every selection."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)
	_load_geojson_and_scores(dash_duo, geojson_file, scores_file)

	def checkboxes():
		return dash_duo.find_elements("#results-table [role=checkbox]")

	_wait(dash_duo, lambda: len(checkboxes()) >= 1)
	checkboxes()[0].click()
	_wait(dash_duo, lambda: any(_ticked(c) for c in checkboxes()))
	assert _trace_count(dash_duo) >= 2  # still rendering with a selection active

	dash_duo.find_element("#deselect-all-btn").click()
	_wait(dash_duo, lambda: not any(_ticked(c) for c in checkboxes()))


def test_clear_cache_resets(dash_duo, geojson_file, scores_file):
	"""clear_cache empties the stores, re-disables the Save buttons, and clears the
	slice label."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)
	_load_geojson_and_scores(dash_duo, geojson_file, scores_file)
	_open(dash_duo, "#chip-slices", "save-geo-btn")
	_wait(dash_duo, lambda: dash_duo.find_element("#save-geo-btn").is_enabled())

	dash_duo.find_element("#clear-cache-btn").click()

	# load-cached-status lives in an inactive tab (hidden -> no readable text), so
	# assert on the other resets: the Save buttons re-disable, the slice bar hides
	# and the empty state comes back.
	_wait(dash_duo, lambda: not dash_duo.find_element("#save-geo-btn").is_enabled())
	_open(dash_duo, SCORES_TAB, "save-scores-btn")
	_wait(dash_duo, lambda: not dash_duo.find_element("#save-scores-btn").is_enabled())
	_wait(dash_duo, lambda: dash_duo.find_element("#slice-label").text == "")
	dash_duo.wait_for_contains_text("#empty-state", "Load an atlas", timeout=20)


def test_downloads_emit_files(dash_duo, geojson_file, scores_file):
	"""download_geojson / download_scores stream files to the browser."""
	import os

	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)
	_load_geojson_and_scores(dash_duo, geojson_file, scores_file)
	# Each Save button lives on its own step of the setup modal.
	_open(dash_duo, "#chip-slices", "save-geo-btn")
	_wait(dash_duo, lambda: dash_duo.find_element("#save-geo-btn").is_enabled())
	dash_duo.find_element("#save-geo-btn").click()
	_open(dash_duo, SCORES_TAB, "save-scores-btn")
	_wait(dash_duo, lambda: dash_duo.find_element("#save-scores-btn").is_enabled())
	dash_duo.find_element("#save-scores-btn").click()

	def downloaded(name):
		return os.path.exists(os.path.join(dash_duo.download_path, name))

	_wait(dash_duo, lambda: downloaded("brain_slices.geojson"), timeout=20)
	_wait(dash_duo, lambda: downloaded("region_scores.csv"), timeout=20)


def test_export_current_slice(dash_duo, geojson_file, scores_file, tmp_path):
	"""export_slice builds the static figure and saves it (figure.build_export_figure
	+ save_figure)."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)
	_load_geojson_and_scores(dash_duo, geojson_file, scores_file)

	out_dir = tmp_path / "export"
	out_dir.mkdir()
	_open(dash_duo, "#export-open-btn", "export-dir")
	_set_input(dash_duo, "export-dir", str(out_dir))

	dash_duo.find_element("#export-btn").click()
	dash_duo.wait_for_contains_text("#export-status", "Saved", timeout=60)

	assert list(out_dir.glob("brain_slice.*")), "no exported file written"


def test_process_data_background(dash_duo, geojson_file, quint_dir, metadata_csv):
	"""The background process_data callback runs score_table on real QUINT files
	(network-free), populating the scores store and the group select via
	populate_groups - exercising toggle_process_btn and the background worker."""
	_start(dash_duo)
	dash_duo.wait_for_element("#brain-graph", timeout=20)

	# Slices must exist for the process button gate (toggle_process_btn).
	_upload(dash_duo, "upload-geojson", geojson_file)
	dash_duo.wait_for_contains_text("#slice-label", "Slice index 1", timeout=20)

	_open(dash_duo, "#chip-scores", "score-data-dir")
	_input(dash_duo, "score-data-dir").send_keys(quint_dir)
	_input(dash_duo, "metadata-path").send_keys(metadata_csv)
	# metadata_csv is comma-separated; the metadata-sep input defaults to ';'.
	_set_input(dash_duo, "metadata-sep", ",")

	# debounced (500ms) inputs -> toggle_process_btn enables the button. JS-click
	# it (the brain-graph's transparent drag layer can sit over the button).
	_wait(dash_duo, lambda: dash_duo.find_element("#process-data-btn").is_enabled(), timeout=20)
	_js_click(dash_duo, dash_duo.find_element("#process-data-btn"))

	# Background worker spawns, imports, and computes - allow generous time.
	_wait(
		dash_duo,
		lambda: _input(dash_duo, "group-select").get_attribute("value") not in (None, "", "-"),
		timeout=90,
	)
	dash_duo.wait_for_contains_text("#results-table", "Isocortex", timeout=20)
