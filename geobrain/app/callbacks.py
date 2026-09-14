import base64
import glob
import io
import json
import math
import os
import subprocess
import sys
import uuid

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import ClientsideFunction, Input, Output, State, dcc, no_update, set_props

import geobrain
from geobrain.app import cache, figure


# Toast levels -> (Mantine color used for the border + icon box, default title,
# icon glyph). Dual-coded (color *and* glyph) so the level reads without relying
# on color alone.
_NOTIFY = {
	"success": ("green", "Success", "✓"),
	"info": ("teal", "Info", "ℹ"),
	"warning": ("yellow", "Warning", "⚠"),
	"error": ("red", "Error", "✕"),
}


def _notify(
	message: str, level: str = "info", title: str | None = None, autoClose: int = 4000
) -> None:
	"""Push a toast into the notifications container with a level-colored border.

	Levels map to the border color the user expects: success=green, info=teal,
	warning=yellow, error=red, each paired with a glyph icon. Errors are sticky
	(``autoClose=False``) so the one thing the user must not miss can't vanish
	before it's read; everything is dismissible via the close button. Emitted
	through ``set_props`` so any callback - including the background processing
	ones - can raise a toast without wiring an extra Output into its signature.
	"""
	color, default_title, glyph = _NOTIFY.get(level, _NOTIFY["info"])
	set_props(
		"notifications-container",
		{
			"children": dmc.Notification(
				id=str(uuid.uuid4()),
				action="show",
				color=color,
				title=title or default_title,
				message=message,
				icon=dmc.Text(glyph, c="white", fw=700, fz="lg"),
				autoClose=False if level == "error" else autoClose,
				withCloseButton=True,
				withBorder=True,
				styles={"root": {"border": f"1px solid var(--mantine-color-{color}-6)"}},
			)
		},
	)


def _status(message: str, color: str):
	"""Inline status text colored by outcome (green=done, red=failed).

	Returned as a status component's ``children`` so completion/failure recolors
	the existing inline text in place - complementing the toast - without adding
	a separate Output for the color. ``inherit`` keeps the parent's font size.
	"""
	return dmc.Text(message, c=color, span=True, inherit=True)


def _df_records(df: pd.DataFrame) -> list[dict]:
	"""DataFrame -> JSON-safe records (NaN -> None, ints where sensible)."""
	clean = df.replace({np.nan: None}).copy()
	if "Region ID" in clean.columns:
		clean["Region ID"] = clean["Region ID"].apply(
			lambda v: int(v) if v is not None and not _is_nan(v) else None
		)
	return clean.to_dict("records")


def _is_nan(v) -> bool:
	return isinstance(v, float) and math.isnan(v)


def _decode_upload(contents: str) -> bytes:
	"""Decode a ``dcc.Upload`` ``contents`` data URL into raw bytes."""
	_, b64 = contents.split(",", 1)
	return base64.b64decode(b64)


def _payload_to_geojson(geometry: dict, slices: list[dict] | None) -> dict:
	"""Convert the app's geometry payload back into a GeoJSON FeatureCollection.

	Produces the same shape the "Load GeoJSON" path consumes
	(``figure.geojson_to_payload``): one feature per region-per-slice, with
	``Region ID`` / ``Region name`` / ``slice_index`` / ``coordinate_mm`` props
	and Polygon/MultiPolygon geometry built from the cached rings.
	"""
	coord_by_index = {int(s["slice_index"]): s.get("coordinate_mm") for s in (slices or [])}
	orientation = geometry.get("orientation")

	# Freshly built geometry is in pixel/screen space where y increases downward;
	# the live figure corrects this with a reversed y-range. Saved GeoJSON, by
	# contrast, is expected to be y-up (the load path applies no reversal), so we
	# flip y here. Geometry that was itself loaded from a y-up GeoJSON has no
	# dims and is already y-up, so it is left untouched to avoid a double flip.
	dims = geometry.get("dims")
	flip_h = float(dims["h"]) if dims and dims.get("h") else None

	def _ring(ring):
		if flip_h is None:
			return [[x, y] for x, y in ring]
		return [[x, flip_h - y] for x, y in ring]

	features: list[dict] = []
	for si_str, regions in geometry.get("by_slice", {}).items():
		si = int(si_str)
		coord_mm = coord_by_index.get(si)
		for region in regions:
			rings = region.get("rings", [])
			if not rings:
				continue
			if len(rings) == 1:
				geom = {"type": "Polygon", "coordinates": [_ring(rings[0])]}
			else:
				geom = {"type": "MultiPolygon", "coordinates": [[_ring(r)] for r in rings]}
			features.append(
				{
					"type": "Feature",
					"properties": {
						"feature_id": f"{si}_{region['rid']}",
						"Region ID": region["rid"],
						"Region name": region.get("name"),
						"slice_index": si,
						"coordinate_mm": coord_mm,
						"orientation": orientation,
					},
					"geometry": geom,
				}
			)
	return {"type": "FeatureCollection", "features": features}


COMBINED_GROUP_LABEL = "All (mean)"


def _combine_groups_mean(groups: dict[str, pd.DataFrame]) -> pd.DataFrame:
	"""Per-region mean of every numeric score column across all groups.

	Region name is carried over from the first group a region appears in.
	"""
	all_df = pd.concat(groups.values(), ignore_index=True)
	mean_df = all_df.groupby("Region ID", as_index=False).mean(numeric_only=True)
	names = all_df.drop_duplicates("Region ID").set_index("Region ID")["Region name"]
	mean_df["Region name"] = mean_df["Region ID"].map(names)
	return mean_df


def _scores_to_store(result) -> dict:
	"""Normalize score_table / loaded-CSV output to ``{group_label: records}``.

	Grouping is always applied: the store holds one entry per group, plus a
	combined ``"All (mean)"`` entry (per-region mean across groups) whenever
	there is more than one group. Accepts either a ``{group: df}`` dict (grouped
	``score_table`` output) or a single DataFrame - a loaded CSV is split back
	into groups on its ``group_label`` column when present.
	"""
	if isinstance(result, dict):
		groups = {str(k): v for k, v in result.items()}
	elif "group_label" in result.columns:
		groups = {
			str(g): sub.drop(columns=["group_label"])
			for g, sub in result.groupby("group_label", sort=False)
		}
	else:
		groups = {"All": result}

	store = {label: _df_records(df) for label, df in groups.items()}
	if len(groups) > 1:
		store[COMBINED_GROUP_LABEL] = _df_records(_combine_groups_mean(groups))
	return store


def _resolve_sep(value: str | None, data_dir: str) -> str:
	"""Resolve the CSV delimiter, auto-detecting from the data when unset.

	QUINT ``*_RefAtlasRegions.csv`` exports are semicolon-separated, but users
	often assume comma. Rather than trust a hand-typed field, sniff the header of
	the first file and pick the most frequent of ``; , \\t``. Common aliases
	("auto", "tab", "\\t") are also accepted.
	"""
	aliases = {"tab": "\t", "\\t": "\t", "semicolon": ";", "comma": ","}
	if value:
		v = value.strip()
		if v and v.lower() != "auto":
			return aliases.get(v.lower(), v)

	files = sorted(glob.glob(os.path.join(data_dir, "*_RefAtlasRegions.csv")))
	if not files:
		return ";"
	try:
		with open(files[0], "r", encoding="utf-8", errors="ignore") as f:
			header = f.readline()
	except OSError:
		return ";"
	counts = {";": header.count(";"), ",": header.count(","), "\t": header.count("\t")}
	best = max(counts, key=counts.get)
	return best if counts[best] > 0 else ";"


def _parse_cols(text: str | None):
	if not text:
		return None
	cols = [c.strip() for c in str(text).split(",") if c.strip()]
	if not cols:
		return None
	return cols[0] if len(cols) == 1 else cols


def _slider_config(slices: list[dict]):
	"""Return (min, max, value, marks) for the slice slider given slice metadata."""
	n = len(slices)
	if n == 0:
		return 0, 0, 0, {}
	marks = {}
	positions = sorted({0, n // 2, n - 1})
	for pos in positions:
		cm = slices[pos].get("coordinate_mm")
		marks[pos] = f"{cm:+.1f}" if cm is not None else str(slices[pos]["slice_index"])
	return 0, n - 1, 0, marks


_ORIENTATION_AXIS = {"coronal": "AP", "sagittal": "ML", "horizontal": "DV"}


def _slice_filename(name: str, orientation: str | None, coordinate_mm, slice_index: int) -> str:
	"""Build a per-slice export filename embedding the slice coordinate.

	Uses the axis implied by the slicing orientation (coronal->AP, sagittal->ML,
	horizontal->DV), e.g. ``brain_slice_AP_+1.50mm``. Falls back to the slice
	index when orientation or coordinate is unavailable (e.g. loaded GeoJSON).
	"""
	axis = _ORIENTATION_AXIS.get(orientation)
	if axis is not None and coordinate_mm is not None:
		return f"{name}_{axis}_{float(coordinate_mm):+.2f}mm"
	return f"{name}_slice{slice_index}"


# Child script for the tkinter dialog (Linux/Windows). Runs in its own process
# so tkinter can own the main thread (Dash callbacks run on worker threads). The
# dialog name (askdirectory / askopenfilename) is passed as argv[1].
_DIALOG_SCRIPT = r"""
import sys, tkinter, tkinter.filedialog

root = tkinter.Tk()
root.withdraw()
root.wm_attributes("-topmost", True)
root.lift()
root.focus_force()
root.update_idletasks()

picker = getattr(tkinter.filedialog, sys.argv[1])
sys.stdout.write(picker(parent=root) or "")
"""


def _macos_path_dialog(directory: bool) -> str | None:
	"""macOS path picker via AppleScript's built-in chooser.

	A CLI Python subprocess is a background process on macOS and cannot become
	the foreground app, so a Tk dialog would open hidden behind the browser.
	AppleScript's ``choose file``/``choose folder`` runs inside the osascript
	runtime (a real foreground app), so it reliably comes to the front, and it
	needs no Tk build or extra permissions.
	"""
	chooser = "choose folder" if directory else "choose file"
	prompt = "Select a folder" if directory else "Select a file"
	script = f'POSIX path of ({chooser} with prompt "{prompt}")'
	result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
	if result.returncode != 0:
		# Cancelling raises AppleScript error -128 ("User canceled"); that's the
		# normal no-selection path. Anything else is a real failure worth raising.
		if "-128" in result.stderr or "User canceled" in result.stderr:
			return None
		raise RuntimeError(result.stderr.strip() or "AppleScript file dialog failed")
	return result.stdout.strip() or None


def _native_path_dialog(directory: bool) -> str | None:
	"""Open a native OS dialog and return the chosen path, or None if cancelled.

	Server-side only, so this works while the app is served locally (server and
	user on the same machine). macOS uses AppleScript (see
	``_macos_path_dialog``); other platforms run a short tkinter script in a
	subprocess (tkinter must own the main thread, Dash callbacks do not).
	"""
	if sys.platform == "darwin":
		return _macos_path_dialog(directory)

	picker = "askdirectory" if directory else "askopenfilename"
	result = subprocess.run(
		[sys.executable, "-c", _DIALOG_SCRIPT, picker],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		# Most often: tkinter isn't available (Linux missing python3-tk, or a
		# pyenv/system Python built without Tk). Raise so the caller can surface
		# it as a toast instead of the click silently doing nothing.
		raise RuntimeError(
			f"native file dialog failed (is tkinter installed?)\n{result.stderr.strip()}"
		)
	return result.stdout.strip() or None


def _data_range(scores, group, score):
	"""Min/max of a score's values across the selected group's records.

	Used to seed blank axis limits (e.g. ``density``) with the real data spread,
	mirroring ``autoRange`` in assets/render.js. Returns ``(None, None)`` when no
	data is loaded yet so the inputs simply stay empty.
	"""
	if not scores:
		return None, None
	group = group if group in scores else next(iter(scores), None)
	records = scores.get(group) if group else None
	if not records:
		return None, None
	value_col = figure.SCORE_VALUE_COLUMN.get(score)
	nums = []
	for row in records:
		val = row.get(value_col)
		if val is None:
			continue
		try:
			num = float(val)
		except (TypeError, ValueError):
			continue
		if not math.isnan(num):
			nums.append(num)
	if not nums:
		return None, None
	lo, hi = min(nums), max(nums)
	if lo == hi:
		hi = lo + 1.0
	return round(lo, 3), round(hi, 3)


def _selected_flat(selected_ids, static_color, use_flat):
	"""Resolve the export gating from the live controls: the set of selected
	region ids and the flat color (``None`` when the flat toggle is off, so the
	colormap is used)."""
	selected = {int(i) for i in (selected_ids or [])}
	flat = (static_color or "#fa5252") if use_flat else None
	return selected, flat


def _browse_path(directory: bool):
	"""Open the native picker for a Browse button, toasting on a real failure.

	Returns the chosen path, or ``no_update`` when the dialog was cancelled (no
	toast) or failed (an error toast is raised so the click isn't a silent no-op).
	"""
	try:
		path = _native_path_dialog(directory=directory)
	except Exception as exc:
		_notify(str(exc), "error", title="File dialog failed")
		return no_update
	return path or no_update


def register_callbacks(app) -> None:
	@app.callback(
		Output("score-data-dir", "value"),
		Input("browse-data-dir-btn", "n_clicks"),
		prevent_initial_call=True,
	)
	def browse_data_dir(n_clicks):
		return _browse_path(directory=True)

	@app.callback(
		Output("metadata-path", "value"),
		Input("browse-metadata-btn", "n_clicks"),
		prevent_initial_call=True,
	)
	def browse_metadata(n_clicks):
		return _browse_path(directory=False)

	@app.callback(
		Output("export-dir", "value"),
		Input("browse-export-dir-btn", "n_clicks"),
		prevent_initial_call=True,
	)
	def browse_export_dir(n_clicks):
		return _browse_path(directory=True)

	@app.callback(
		Output("session-store", "data"),
		Output("step1-status", "children"),
		Output("build-geo-btn", "disabled"),
		Input("load-raw-btn", "n_clicks"),
		State("resolution-select", "value"),
		background=True,
		running=[
			(Output("load-raw-btn", "disabled"), True, False),
			(Output("step1-loader", "style"), {"display": "block"}, {"display": "none"}),
		],
		prevent_initial_call=True,
	)
	def load_raw(n_clicks, resolution):
		res = int(resolution)
		try:
			session_id = cache.new_session()
			volume = geobrain.load_annotation_volume(resolution_um=res)
			structure_df = geobrain.load_structure_graph()
		except Exception as exc:  # download / disk / atlas errors
			_notify(f"Could not load atlas: {exc}", "error")
			return no_update, _status("Atlas load failed.", "red"), no_update
		cache.put(session_id, "volume", volume)
		cache.put(session_id, "structure_df", structure_df)
		cache.put(session_id, "resolution_um", res)
		status = f"Loaded atlas at {res} µm - volume {volume.shape}."
		return session_id, _status(status, "green"), False

	@app.callback(
		Output("geometry-store", "data"),
		Output("slices-store", "data"),
		Output("slice-slider", "min"),
		Output("slice-slider", "max"),
		Output("slice-slider", "value"),
		Output("slice-slider", "marks"),
		Input("build-geo-btn", "n_clicks"),
		State("session-store", "data"),
		State("orientation-select", "value"),
		State("geo-start", "value"),
		State("geo-end", "value"),
		State("geo-step", "value"),
		State("polygon-mode-select", "value"),
		State("min-area-px", "value"),
		State("simplify-px", "value"),
		State("smooth-sigma", "value"),
		background=True,
		progress=[Output("geo-progress", "value"), Output("geo-progress-label", "children")],
		running=[(Output("build-geo-btn", "disabled"), True, False)],
		prevent_initial_call=True,
	)
	def build_geo(
		set_progress,
		n_clicks,
		session_id,
		orientation,
		start_mm,
		end_mm,
		step_mm,
		polygon_mode,
		min_area_px,
		simplify_px,
		smooth_sigma,
	):
		volume = cache.get(session_id, "volume")
		structure_df = cache.get(session_id, "structure_df")
		if volume is None or structure_df is None:
			set_progress((0, "Load raw data first (step 1)."))
			_notify("Load the atlas first (step 1).", "warning")
			return no_update, no_update, no_update, no_update, no_update, no_update

		res = int(cache.get(session_id, "resolution_um", 25))
		step = float(step_mm) if step_mm else None
		try:
			indices = geobrain.range_mm_to_slice_indices(
				start_mm=float(start_mm),
				end_mm=float(end_mm),
				step_mm=step,
				orientation=orientation,
				resolution_um=res,
			)
		except Exception as exc:
			set_progress((0, _status(f"Invalid slice range: {exc}", "red")))
			_notify(f"Invalid slice range: {exc}", "error")
			return no_update, no_update, no_update, no_update, no_update, no_update

		n = len(indices)
		if n == 0:
			set_progress((0, "That range produced no slices."))
			_notify("That start/end/step range produced no slices.", "warning")
			return no_update, no_update, no_update, no_update, no_update, no_update

		def _report(i, total, idx):
			set_progress((int(100 * i / total), f"Slice {i}/{total} (index {idx})"))

		try:
			geometry, slices = figure.build_slice_geometry(
				volume=volume,
				structure_df=structure_df,
				orientation=orientation,
				resolution_um=res,
				slice_indices=indices,
				min_area_px=float(min_area_px),
				simplify_px=float(simplify_px),
				smooth_sigma=float(smooth_sigma),
				polygon_mode=polygon_mode,
				progress=_report,
			)
		except Exception as exc:
			set_progress((0, _status(f"Could not build slices: {exc}", "red")))
			_notify(f"Could not build slices: {exc}", "error")
			return no_update, no_update, no_update, no_update, no_update, no_update

		cache.put(session_id, "geometry", geometry)

		smin, smax, sval, marks = _slider_config(slices)
		set_progress((100, _status(f"Built {n} slice(s).", "green")))
		return geometry, slices, smin, smax, sval, marks

	@app.callback(
		Output("scores-store", "data"),
		Input("process-data-btn", "n_clicks"),
		State("score-data-dir", "value"),
		State("score-sep", "value"),
		State("metadata-path", "value"),
		State("metadata-sep", "value"),
		State("animal-col", "value"),
		State("group-col", "value"),
		State("rel-method-select", "value"),
		State("ref-mode-select", "value"),
		State("ref-group", "value"),
		background=True,
		progress=[Output("score-progress", "value"), Output("score-progress-label", "children")],
		running=[(Output("process-data-btn", "disabled"), True, False)],
		prevent_initial_call=True,
	)
	def process_data(
		set_progress,
		n_clicks,
		data_dir,
		sep,
		metadata_path,
		metadata_sep,
		animal_col,
		group_col,
		rel_method,
		ref_mode,
		ref_group,
	):
		if not data_dir or not os.path.isdir(data_dir):
			set_progress((0, "Provide a valid QUINT data folder."))
			_notify("Provide a valid QUINT data folder.", "warning")
			return no_update

		files = glob.glob(os.path.join(data_dir, "*_RefAtlasRegions.csv"))
		if not files:
			set_progress((0, "No *_RefAtlasRegions.csv files in that folder."))
			_notify("No *_RefAtlasRegions.csv files in that folder.", "warning")
			return no_update
		use_sep = _resolve_sep(sep, data_dir)
		set_progress((15, f"Loading {len(files)} QUINT file(s) (sep={use_sep!r})…"))

		try:
			result = geobrain.score_table(
				data_dir=data_dir,
				scores=["rel_abundance", "frequency", "density"],
				sep=use_sep,
				metadata_path=metadata_path or None,
				metadata_sep=metadata_sep or None,
				animal_col=animal_col or "animal",
				group_col=_parse_cols(group_col),
				rel_abundance_method=rel_method or "within",
				reference_mode=ref_mode or "pooled",
				reference_group=_parse_cols(ref_group),
			)
		except Exception as exc:  # surface a clean message instead of a traceback
			set_progress((0, _status(f"Could not compute scores: {exc}", "red")))
			_notify(f"Could not compute scores: {exc}", "error")
			return no_update

		set_progress((80, "Assembling score tables…"))
		store = _scores_to_store(result)
		set_progress((100, _status(f"Computed scores for {len(store)} group(s).", "green")))
		return store

	@app.callback(
		Output("process-data-btn", "disabled"),
		Input("slices-store", "data"),
		Input("score-data-dir", "value"),
		Input("metadata-path", "value"),
	)
	def toggle_process_btn(slices, data_dir, metadata_path):
		"""Enable 'Compute scores' only once slices exist, a valid data folder is
		given, and the (required) metadata CSV exists.

		The data-folder and metadata inputs are debounced (see layout), so this
		fires after the user stops typing rather than on every keystroke.
		"""
		geojson_ready = bool(slices)
		data_dir = str(data_dir).strip() if data_dir else ""
		metadata_path = str(metadata_path).strip() if metadata_path else ""
		dir_ready = bool(data_dir) and os.path.isdir(data_dir)
		metadata_ready = bool(metadata_path) and os.path.isfile(metadata_path)
		return not (geojson_ready and dir_ready and metadata_ready)

	@app.callback(
		Output("save-geo-btn", "disabled"),
		Input("slices-store", "data"),
	)
	def toggle_save_geo(slices):
		"""Enable the GeoJSON 'Save' button only once geometry exists."""
		return not bool(slices)

	@app.callback(
		Output("save-scores-btn", "disabled"),
		Input("scores-store", "data"),
	)
	def toggle_save_scores(scores):
		"""Enable the scores 'Save' button only once scores have been computed."""
		return not bool(scores)

	@app.callback(
		Output("download-geojson", "data"),
		Input("save-geo-btn", "n_clicks"),
		State("geometry-store", "data"),
		State("slices-store", "data"),
		prevent_initial_call=True,
	)
	def download_geojson(n_clicks, geometry, slices):
		"""Serialize the current geometry to GeoJSON and stream it as a download.

		Returning a ``dcc.Download`` payload triggers the browser's file download,
		so the user picks the save location via the browser's save dialog.
		"""
		if not geometry or not geometry.get("by_slice"):
			return no_update
		gj = _payload_to_geojson(geometry, slices)
		return dcc.send_string(json.dumps(gj, indent=2), "brain_slices.geojson")

	@app.callback(
		Output("download-scores", "data"),
		Input("save-scores-btn", "n_clicks"),
		State("scores-store", "data"),
		prevent_initial_call=True,
	)
	def download_scores(n_clicks, scores):
		"""Serialize the computed scores to CSV and stream them as a download.

		Multiple groups are concatenated into one file with a ``group_label``
		column; a single ungrouped table is written as-is. The derived
		``"All (mean)"`` entry is not persisted - it is recomputed on load.
		"""
		if not scores:
			return no_update
		groups = {k: v for k, v in scores.items() if k != COMBINED_GROUP_LABEL}
		frames = []
		for group, records in groups.items():
			df = pd.DataFrame(records)
			if len(groups) > 1:
				df.insert(0, "group_label", group)
			frames.append(df)
		out = pd.concat(frames, ignore_index=True)
		return dcc.send_data_frame(out.to_csv, "region_scores.csv", index=False)

	@app.callback(
		Output("geometry-store", "data", allow_duplicate=True),
		Output("slices-store", "data", allow_duplicate=True),
		Output("slice-slider", "min", allow_duplicate=True),
		Output("slice-slider", "max", allow_duplicate=True),
		Output("slice-slider", "value", allow_duplicate=True),
		Output("slice-slider", "marks", allow_duplicate=True),
		Output("load-cached-status", "children"),
		Output("session-store", "data", allow_duplicate=True),
		Input("upload-geojson", "contents"),
		State("upload-geojson", "filename"),
		State("session-store", "data"),
		prevent_initial_call=True,
	)
	def load_cached_geojson(contents, filename, session_id):
		if not contents:
			return (no_update,) * 6 + ("Choose a GeoJSON file to load.", no_update)
		try:
			gj = json.loads(_decode_upload(contents).decode("utf-8"))
		except Exception as exc:
			_notify(f"Could not read GeoJSON: {exc}", "error")
			return (no_update,) * 6 + (_status(f"Could not read GeoJSON: {exc}", "red"), no_update)
		if not session_id:
			session_id = cache.new_session()
		geometry, slices = figure.geojson_to_payload(gj)
		if not slices:
			_notify("No slices found in that GeoJSON.", "warning")
			return (no_update,) * 6 + ("No slices found in that GeoJSON.", no_update)
		cache.put(session_id, "geometry", geometry)
		smin, smax, sval, marks = _slider_config(slices)
		return (
			geometry,
			slices,
			smin,
			smax,
			sval,
			marks,
			_status(f"Loaded {len(slices)} slice(s).", "green"),
			session_id,
		)

	@app.callback(
		Output("scores-store", "data", allow_duplicate=True),
		Output("load-cached-status", "children", allow_duplicate=True),
		Input("upload-scores", "contents"),
		State("upload-scores", "filename"),
		prevent_initial_call=True,
	)
	def load_cached_scores(contents, filename):
		if not contents:
			return no_update, "Choose a scores CSV to load."
		try:
			df = pd.read_csv(io.BytesIO(_decode_upload(contents)))
		except Exception as exc:
			_notify(f"Could not read scores CSV: {exc}", "error")
			return no_update, _status(f"Could not read scores CSV: {exc}", "red")
		store = _scores_to_store(df)
		n_groups = sum(1 for k in store if k != COMBINED_GROUP_LABEL)
		return store, _status(f"Loaded scores: {len(df)} rows, {n_groups} group(s).", "green")

	@app.callback(
		Output("group-select", "data"),
		Output("group-select", "value"),
		Input("scores-store", "data"),
		prevent_initial_call=True,
	)
	def populate_groups(scores):
		if not scores:
			return [], None
		keys = list(scores.keys())
		options = [{"label": k, "value": k} for k in keys]
		default = COMBINED_GROUP_LABEL if COMBINED_GROUP_LABEL in scores else keys[0]
		return options, default

	@app.callback(
		Output("zmin-input", "value"),
		Output("zmax-input", "value"),
		Input("score-select", "value"),
		State("scores-store", "data"),
		State("group-select", "value"),
		prevent_initial_call=True,
	)
	def default_limits(score, scores, group):
		"""Seed the axis limits when the score changes.

		Scores with a fixed default range use it; scores without one (density)
		get the actual min/max of the loaded data so the inputs reflect real
		values. This keeps the export — which reads these inputs — colored like
		the live view instead of flattening to the colormap midpoint.
		"""
		zmin, zmax = figure.SCORE_DEFAULT_RANGE.get(score, (None, None))
		if zmin is None or zmax is None:
			lo, hi = _data_range(scores, group, score)
			zmin = lo if zmin is None else zmin
			zmax = hi if zmax is None else zmax
		return zmin, zmax

	@app.callback(
		Output("colorscale-stops-store", "data"),
		Input("colorscale-select", "value"),
	)
	def resolve_stops(name):
		return figure.resolve_colorscale(name)

	@app.callback(
		Output("results-table", "selected_rows"),
		Output("results-table", "selected_row_ids"),
		Input("deselect-all-btn", "n_clicks"),
		prevent_initial_call=True,
	)
	def deselect_all_rows(n_clicks):
		"""Clear every selected table row (so all regions return to colormap)."""
		return [], []

	@app.callback(
		Output("static-color", "disabled"),
		Input("static-color-toggle", "checked"),
	)
	def toggle_static_color_enabled(use_flat):
		"""Disable the flat-color picker when flat coloring is switched off."""
		return not use_flat

	@app.callback(
		Output("session-store", "data", allow_duplicate=True),
		Output("geometry-store", "data", allow_duplicate=True),
		Output("scores-store", "data", allow_duplicate=True),
		Output("slices-store", "data", allow_duplicate=True),
		Output("load-cached-status", "children", allow_duplicate=True),
		Output("build-geo-btn", "disabled", allow_duplicate=True),
		Output("save-geo-btn", "disabled", allow_duplicate=True),
		Output("process-data-btn", "disabled", allow_duplicate=True),
		Output("save-scores-btn", "disabled", allow_duplicate=True),
		Output("geo-progress", "value", allow_duplicate=True),
		Output("geo-progress-label", "children", allow_duplicate=True),
		Output("score-progress", "value", allow_duplicate=True),
		Output("score-progress-label", "children", allow_duplicate=True),
		Output("export-progress", "value", allow_duplicate=True),
		Output("export-progress-label", "children", allow_duplicate=True),
		Output("export-status", "children", allow_duplicate=True),
		Output("step1-status", "children", allow_duplicate=True),
		Output("score-data-dir", "value", allow_duplicate=True),
		Output("score-sep", "value", allow_duplicate=True),
		Output("metadata-path", "value", allow_duplicate=True),
		Output("metadata-sep", "value", allow_duplicate=True),
		Output("animal-col", "value", allow_duplicate=True),
		Output("group-col", "value", allow_duplicate=True),
		Output("ref-group", "value", allow_duplicate=True),
		Output("export-dir", "value", allow_duplicate=True),
		Output("export-name", "value", allow_duplicate=True),
		Input("clear-cache-btn", "n_clicks"),
		State("session-store", "data"),
		prevent_initial_call=True,
	)
	def clear_cache(n_clicks, session_id):
		"""Drop the session's cached data from disk and reset the in-browser stores,
		buttons, progress bars, and text inputs so the app returns to a clean slate."""
		cache.clear(session_id)
		_notify("Cache cleared.", "info")
		return (
			None,  # session-store
			None,  # geometry-store
			None,  # scores-store
			None,  # slices-store
			"Cache cleared.",  # load-cached-status
			True,  # build-geo-btn disabled
			True,  # save-geo-btn disabled
			True,  # process-data-btn disabled
			True,  # save-scores-btn disabled
			0,  # geo-progress
			"",  # geo-progress-label
			0,  # score-progress
			"",  # score-progress-label
			0,  # export-progress
			"",  # export-progress-label
			"",  # export-status
			"",  # step1-status
			"",  # score-data-dir
			"auto",  # score-sep
			"",  # metadata-path
			";",  # metadata-sep
			"animal",  # animal-col
			"group",  # group-col
			"",  # ref-group
			".",  # export-dir
			"brain_slice",  # export-name
		)

	@app.callback(
		Output("mantine-provider", "forceColorScheme"),
		Input("color-scheme-toggle", "checked"),
	)
	def set_color_scheme(dark):
		"""Switch the whole app between light and dark Mantine schemes."""
		return "dark" if dark else "light"

	@app.callback(
		Output("slice-slider-wrap", "className"),
		Input("color-scheme-toggle", "checked"),
	)
	def slider_wrap_theme(dark):
		"""Tag the slider wrapper so CSS can lighten the tick labels in dark mode.

		The dcc.Slider mark text isn't a Mantine element, so it doesn't re-theme
		on its own; this class drives the override in styles.css.
		"""
		return "slider-dark" if dark else ""

	@app.callback(
		Output("results-table", "style_header"),
		Output("results-table", "style_data"),
		Output("results-table", "style_filter"),
		Output("results-table", "css"),
		Input("color-scheme-toggle", "checked"),
	)
	def style_table_theme(dark):
		"""Theme the DataTable (header/data/filter rows) to match the color scheme.

		The DataTable is not a Mantine component, so it does not re-theme on its
		own - its colors are set explicitly here. The ``css`` prop reaches inner
		elements that ``style_*`` cannot, such as the filter input's typed text
		and its "filter data..." placeholder.
		"""
		if dark:
			border = "1px solid #34345a"
			header = {
				"fontWeight": "600",
				"backgroundColor": "#20203b",
				"color": "#c1c2c5",
				"border": border,
			}
			data = {"backgroundColor": "#191930", "color": "#c1c2c5", "border": border}
			filt = {"backgroundColor": "#20203b", "color": "#c1c2c5", "border": border}
			css = [
				{"selector": ".dash-filter input", "rule": "color: #c1c2c5 !important;"},
				{
					"selector": ".dash-filter input::placeholder",
					"rule": "color: #c1c2c5 !important; opacity: 1;",
				},
			]
		else:
			border = "1px solid #c1d7f7"
			header = {
				"fontWeight": "600",
				"backgroundColor": "#dde8fb",
				"color": "#2b3450",
				"border": border,
			}
			data = {"backgroundColor": "white", "color": "#2b3450", "border": border}
			filt = {"backgroundColor": "#dde8fb", "color": "#2b3450", "border": border}
			css = []
		return header, data, filt, css

	@app.callback(
		Output("export-status", "children"),
		Input("export-btn", "n_clicks"),
		State("session-store", "data"),
		State("scores-store", "data"),
		State("slices-store", "data"),
		State("slice-slider", "value"),
		State("score-select", "value"),
		State("group-select", "value"),
		State("colorscale-select", "value"),
		State("zmin-input", "value"),
		State("zmax-input", "value"),
		State("export-dir", "value"),
		State("export-name", "value"),
		State("export-format", "value"),
		State("results-table", "selected_row_ids"),
		State("static-color", "value"),
		State("static-color-toggle", "checked"),
		prevent_initial_call=True,
	)
	def export_slice(
		n_clicks,
		session_id,
		scores,
		slices,
		slider_val,
		score,
		group,
		colorscale,
		zmin,
		zmax,
		out_dir,
		name,
		fmt,
		selected_ids,
		static_color,
		use_flat,
	):
		geometry = cache.get(session_id, "geometry")
		if geometry is None:
			_notify("Build or load slices first.", "warning")
			return "No geometry in memory - build or load slices first."
		if not slices:
			_notify("Nothing to export yet.", "warning")
			return "Nothing to export yet."

		if scores:
			group = group if group in scores else next(iter(scores))
			records = scores[group]
		else:
			records = []
		slice_index = int(slices[int(slider_val)]["slice_index"])

		# Match the live view: the row selection narrows coloring and the flat
		# color carries over. The table's text filter is browse-only.
		selected, flat = _selected_flat(selected_ids, static_color, use_flat)

		try:
			fig = figure.build_export_figure(
				geometry_payload=geometry,
				score_records=records,
				slice_index=slice_index,
				score=score,
				colorscale=colorscale,
				zmin=zmin,
				zmax=zmax,
				title=f"{score} - slice {slice_index}",
				selected_rids=selected,
				flat_color=flat,
			)
			path = geobrain.save_figure(
				fig, out_dir=out_dir or ".", filename=name or "brain_slice", extension=fmt or "svg"
			)
		except Exception as exc:  # bad path, missing kaleido, etc.
			_notify(f"Export failed: {exc}", "error")
			return _status(f"Export failed: {exc}", "red")
		_notify(f"Saved: {path}", "success")
		return _status(f"Saved: {path}", "green")

	@app.callback(
		Output("export-status", "children", allow_duplicate=True),
		Input("export-all-btn", "n_clicks"),
		State("session-store", "data"),
		State("scores-store", "data"),
		State("slices-store", "data"),
		State("score-select", "value"),
		State("group-select", "value"),
		State("colorscale-select", "value"),
		State("zmin-input", "value"),
		State("zmax-input", "value"),
		State("export-dir", "value"),
		State("export-name", "value"),
		State("export-format", "value"),
		State("results-table", "selected_row_ids"),
		State("static-color", "value"),
		State("static-color-toggle", "checked"),
		background=True,
		progress=[Output("export-progress", "value"), Output("export-progress-label", "children")],
		running=[
			(Output("export-all-btn", "disabled"), True, False),
			(Output("export-btn", "disabled"), True, False),
		],
		prevent_initial_call=True,
	)
	def export_all_slices(
		set_progress,
		n_clicks,
		session_id,
		scores,
		slices,
		score,
		group,
		colorscale,
		zmin,
		zmax,
		out_dir,
		name,
		fmt,
		selected_ids,
		static_color,
		use_flat,
	):
		geometry = cache.get(session_id, "geometry")
		if geometry is None:
			_notify("Build or load slices first.", "warning")
			return "No geometry in memory - build or load slices first."
		if not slices:
			_notify("Nothing to export yet.", "warning")
			return "Nothing to export yet."

		if scores:
			group = group if group in scores else next(iter(scores))
			records = scores[group]
		else:
			records = []
		orientation = geometry.get("orientation")

		# Match the live view: the row selection narrows coloring and the flat
		# color carries over, applied across all slices. The text filter is
		# browse-only, so it does not affect the exported coloring.
		selected, flat = _selected_flat(selected_ids, static_color, use_flat)

		n = len(slices)
		try:
			for i, meta in enumerate(slices, start=1):
				slice_index = int(meta["slice_index"])
				set_progress((int(i / n * 100), f"Exporting slice {i}/{n}…"))
				fig = figure.build_export_figure(
					geometry_payload=geometry,
					score_records=records,
					slice_index=slice_index,
					score=score,
					colorscale=colorscale,
					zmin=zmin,
					zmax=zmax,
					title=f"{score} - slice {slice_index}",
					selected_rids=selected,
					flat_color=flat,
				)
				filename = _slice_filename(
					name or "brain_slice", orientation, meta.get("coordinate_mm"), slice_index
				)
				geobrain.save_figure(
					fig, out_dir=out_dir or ".", filename=filename, extension=fmt or "svg"
				)
		except Exception as exc:  # bad path, missing kaleido, etc.
			set_progress((0, _status(f"Export failed: {exc}", "red")))
			_notify(f"Export failed: {exc}", "error")
			return _status(f"Export failed: {exc}", "red")

		set_progress((100, ""))
		_notify(f"Saved {n} slice(s) to {out_dir or '.'}", "success")
		return _status(f"Saved {n} slice(s) to {out_dir or '.'}", "green")

	app.clientside_callback(
		ClientsideFunction(namespace="geobrain", function_name="render"),
		Output("brain-graph", "figure"),
		Input("slice-slider", "value"),
		Input("score-select", "value"),
		Input("group-select", "value"),
		Input("colorscale-stops-store", "data"),
		Input("zmin-input", "value"),
		Input("zmax-input", "value"),
		Input("geometry-store", "data"),
		Input("scores-store", "data"),
		Input("slices-store", "data"),
		Input("color-scheme-toggle", "checked"),
		Input("results-table", "selected_row_ids"),
		Input("static-color", "value"),
		Input("static-color-toggle", "checked"),
	)

	app.clientside_callback(
		ClientsideFunction(namespace="geobrain", function_name="table"),
		Output("results-table", "data"),
		Output("results-table", "columns"),
		Output("results-table", "style_data_conditional"),
		Input("slice-slider", "value"),
		Input("score-select", "value"),
		Input("group-select", "value"),
		Input("geometry-store", "data"),
		Input("scores-store", "data"),
		Input("slices-store", "data"),
		Input("color-scheme-toggle", "checked"),
	)

	app.clientside_callback(
		ClientsideFunction(namespace="geobrain", function_name="sliceLabel"),
		Output("slice-label", "children"),
		Input("slice-slider", "value"),
		Input("slices-store", "data"),
	)
