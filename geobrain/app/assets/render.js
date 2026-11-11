/*
 * Clientside rendering for the GeoBrain dashboard.
 *
 * The brain figure, the results table and the slice label are all assembled in
 * the browser from compact `dcc.Store` payloads, so dragging the slice slider
 * or toggling the score/colorscale gives immediate feedback with no server
 * round-trip. Geometry (polygon rings) is built once on the server; here we only
 * look up each region's value and interpolate a fill color.
 */

window.dash_clientside = window.dash_clientside || {};

const NA_COLOR = "#d9d9d9";
const FALLBACK_STOPS = [
	[0, [68, 1, 84]],
	[0.5, [33, 145, 140]],
	[1, [253, 231, 37]],
];

// Group-select entries that are not a single group (see callbacks.py).
const COMBINED_GROUP = "All (mean)"; // COMBINED_GROUP_LABEL
const SIDE_BY_SIDE = "Side by side"; // SIDE_BY_SIDE_LABEL

function isNum(v) {
	return v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
}

function pickRecords(scores, group) {
	if (!scores) return [];
	if (group && scores[group]) return scores[group];
	const keys = Object.keys(scores);
	return keys.length ? scores[keys[0]] : [];
}

// Groups to draw: the picked one, or every real group for the side-by-side option.
function panelGroups(scores, group) {
	if (group !== SIDE_BY_SIDE || !scores) return [group];
	return Object.keys(scores).filter((g) => g !== COMBINED_GROUP);
}

function buildValueMap(records, valueCol) {
	const map = {};
	for (let i = 0; i < records.length; i++) {
		const row = records[i];
		const rid = row["Region ID"];
		if (rid === null || rid === undefined) continue;
		const v = row[valueCol];
		map[rid] = isNum(v) ? Number(v) : null;
	}
	return map;
}

function colorFromStops(value, stops, vmin, vmax) {
	if (!isNum(value)) return NA_COLOR;
	let t;
	if (!isNum(vmin) || !isNum(vmax) || vmax === vmin) {
		t = 0.5;
	} else {
		t = (Number(value) - vmin) / (vmax - vmin);
		t = Math.max(0, Math.min(1, t));
	}
	for (let i = 0; i < stops.length - 1; i++) {
		const [p0, c0] = stops[i];
		const [p1, c1] = stops[i + 1];
		if (t >= p0 && t <= p1) {
			const f = p1 === p0 ? 0 : (t - p0) / (p1 - p0);
			const r = Math.round(c0[0] + f * (c1[0] - c0[0]));
			const g = Math.round(c0[1] + f * (c1[1] - c0[1]));
			const b = Math.round(c0[2] + f * (c1[2] - c0[2]));
			return `rgb(${r},${g},${b})`;
		}
	}
	const last = stops[stops.length - 1][1];
	return `rgb(${last[0]},${last[1]},${last[2]})`;
}

function emptyFigure(message) {
	return {
		data: [],
		layout: {
			xaxis: { visible: false },
			yaxis: { visible: false },
			paper_bgcolor: "rgba(0,0,0,0)",
			plot_bgcolor: "rgba(0,0,0,0)",
			margin: { l: 10, r: 10, t: 30, b: 10 },
			annotations: [
				{
					text: message,
					showarrow: false,
					xref: "paper",
					yref: "paper",
					x: 0.5,
					y: 0.5,
					font: { size: 14, color: "#868e96" },
				},
			],
		},
	};
}

// One shared range across all panels, so side-by-side groups are comparable.
function autoRange(valueMaps, vmin, vmax) {
	if (isNum(vmin) && isNum(vmax)) return [Number(vmin), Number(vmax)];
	let lo = Infinity;
	let hi = -Infinity;
	for (const valueMap of valueMaps) {
		for (const k in valueMap) {
			const v = valueMap[k];
			if (isNum(v)) {
				if (v < lo) lo = v;
				if (v > hi) hi = v;
			}
		}
	}
	if (lo === Infinity) return [0, 1];
	if (lo === hi) hi = lo + 1;
	return [isNum(vmin) ? Number(vmin) : lo, isNum(vmax) ? Number(vmax) : hi];
}

window.dash_clientside.geobrain = {
	// Coalesce rapid slider drags to one render per animation frame. Each call
	// stashes the latest inputs; a single requestAnimationFrame then rebuilds
	// with the newest values and patches the existing plot via Plotly.react. Fast
	// scrolling thus skips the intermediate slices it can't keep up with instead
	// of queueing a full rebuild for every one of them on the main thread.
	_rafPending: false,
	_latestArgs: null,

	render: function () {
		const ns = window.dash_clientside.geobrain;
		const host = document.getElementById("brain-graph");
		const gd = host && host.querySelector(".js-plotly-plot");
		if (!gd || !window.Plotly) {
			// Plot not initialized yet - let Dash create it from the figure prop.
			return ns.buildFigure.apply(ns, arguments);
		}
		ns._latestArgs = arguments;
		if (!ns._rafPending) {
			ns._rafPending = true;
			window.requestAnimationFrame(function () {
				ns._rafPending = false;
				const args = ns._latestArgs;
				ns._latestArgs = null;
				const fig = ns.buildFigure.apply(ns, args);
				window.Plotly.react(gd, fig.data, fig.layout);
			});
		}
		return window.dash_clientside.no_update;
	},

	// scoreColumns: score -> value column map from figure.SCORE_VALUE_COLUMN (score-columns-store).
	buildFigure: function (sliderVal, score, group, stops, zmin, zmax, geometry, scores, slices, dark, highlight, staticColor, useFlat, scoreColumns) {
		if (!geometry || !geometry.by_slice || !slices || !slices.length) {
			// Blank: the #empty-state overlay in the layout carries the prompt.
			return emptyFigure("");
		}
		const pos = Math.max(0, Math.min(slices.length - 1, sliderVal || 0));
		const sliceIndex = slices[pos].slice_index;
		const regions = geometry.by_slice[String(sliceIndex)] || [];
		if (!regions.length) return emptyFigure("No regions on this slice");
		const dims = geometry.dims;

		if (!stops || !stops.length) stops = FALLBACK_STOPS;
		const valueCol = (scoreColumns || {})[score] || "relative_abundance_z";
		// One panel per group: a single one normally, every group side by side
		// when that option is picked in the group select.
		const groups = panelGroups(scores, group);
		const valueMaps = groups.map((g) => buildValueMap(pickRecords(scores, g), valueCol));
		const [vmin, vmax] = autoRange(valueMaps, zmin, zmax);

		// Coloring is narrowed by the row selection (checkboxes) only: once any
		// rows are selected, just those regions keep their score color and every
		// other region renders as NA (gray). With no selection, all regions keep
		// color. The table's text filter only filters the table list, not the
		// brain. If none of the selected regions are on this slice (e.g. after
		// moving the slider) we skip gating rather than gray it all.
		const selected = new Set(Array.isArray(highlight) ? highlight : []);
		let selActive = selected.size > 0;
		if (selActive && !regions.some((rg) => selected.has(rg.rid))) {
			selActive = false;
		}

		// When the flat-color toggle is on and a selection is narrowing this
		// slice, turn the colormap off: kept regions get one flat color, the rest
		// stay gray (NA). Otherwise, value-based coloring.
		const staticMode = !!useFlat && selActive;
		const staticFill = staticColor || "#fa5252";

		const traces = [];
		for (let i = 0; i < regions.length * groups.length; i++) {
			const panel = Math.floor(i / regions.length);
			const axis = panel ? String(panel + 1) : ""; // x/y, x2/y2, ...
			const region = regions[i % regions.length];
			const gated = selActive && !selected.has(region.rid);
			const value = gated ? null : valueMaps[panel][region.rid];
			const fill = gated
				? NA_COLOR
				: staticMode
					? staticFill
					: colorFromStops(value, stops, vmin, vmax);
			const xs = [];
			const ys = [];
			const cd = [];
			for (let r = 0; r < region.rings.length; r++) {
				const ring = region.rings[r];
				for (let p = 0; p < ring.length; p++) {
					xs.push(ring[p][0]);
					ys.push(ring[p][1]);
					cd.push(region.rid);
				}
				xs.push(null);
				ys.push(null);
				cd.push(null);
			}
			const vTxt = isNum(value) ? Number(value).toFixed(3) : "n/a";
			const groupTxt = groups.length > 1 ? `Group: ${groups[panel]}<br>` : "";
			traces.push({
				type: "scatter",
				x: xs,
				y: ys,
				xaxis: "x" + axis,
				yaxis: "y" + axis,
				customdata: cd,
				mode: "lines",
				fill: "toself",
				fillcolor: fill,
				line: { color: "rgba(255,255,255,0.95)", width: 0.7, shape: "spline", smoothing: 0.6 },
				text: `${groupTxt}Region ID: ${region.rid}<br>Region: ${region.name}<br>${score}: ${vTxt}`,
				hoverinfo: "text",
				hoveron: "fills",
				showlegend: false,
			});
		}

		// Invisible colorbar trace - omitted in static mode (colormap is off).
		if (!staticMode) {
			const plotlyScale = stops.map((s) => [s[0], `rgb(${s[1][0]},${s[1][1]},${s[1][2]})`]);
			traces.push({
				type: "scatter",
				x: [null, null],
				y: [null, null],
				mode: "markers",
				marker: {
					size: 0,
					color: [vmin, vmax],
					colorscale: plotlyScale,
					cmin: vmin,
					cmax: vmax,
					showscale: true,
					colorbar: { title: { text: valueCol, side: "right" }, thickness: 14, len: 0.85 },
				},
				hoverinfo: "skip",
				showlegend: false,
			});
		}

		// Pixel-space geometry: fix the frame to the slice dimensions and put
		// the dorsal side up via a reversed y-range (top = row 0). Cached lon/lat
		// geometry has no dims and is already y-up, so it just autoranges.
		let xaxis;
		let yaxis;
		if (dims && dims.w && dims.h) {
			xaxis = { visible: false, range: [0, dims.w], constrain: "range" };
			yaxis = { visible: false, range: [dims.h, 0], scaleanchor: "x", constrain: "range" };
		} else {
			xaxis = { visible: false };
			yaxis = { visible: false, scaleanchor: "x" };
		}

		const layout = {
			uirevision: geometry.orientation || "brain",
			paper_bgcolor: "rgba(0,0,0,0)",
			plot_bgcolor: "rgba(0,0,0,0)",
			font: { color: dark ? "#b1b0d2" : "#4a4970" },
			margin: { l: 10, r: 10, t: groups.length > 1 ? 36 : 20, b: 10 },
			hovermode: "closest",
			annotations: [],
		};
		// Panels share the width equally. Every extra panel's axes match the
		// first one's, so zooming or panning one group moves them all.
		const n = groups.length;
		for (let p = 0; p < n; p++) {
			const axis = p ? String(p + 1) : "";
			const domain = [(p + 0.02) / n, (p + 0.98) / n];
			layout["xaxis" + axis] = p ? { visible: false, matches: "x", domain: domain } : { ...xaxis, domain: n > 1 ? domain : [0, 1] };
			layout["yaxis" + axis] = p ? { visible: false, matches: "y", anchor: "x" + axis } : yaxis;
			if (n > 1) {
				layout.annotations.push({
					text: groups[p],
					showarrow: false,
					xref: "paper",
					yref: "paper",
					x: (p + 0.5) / n,
					y: 1,
					yanchor: "bottom",
					font: { size: 13 },
				});
			}
		}

		return { data: traces, layout: layout };
	},

	// Rebuild the regions list. Slider drags are debounced so the DOM-heavy rebuild
	// doesn't compete with the figure while scrolling; a selection or filter
	// change is applied at once. The rebuild is pushed via set_props, so the
	// live callback returns no_update.
	_tableTimer: null,
	_tableArgs: null,
	_selected: new Set(), // ticked region ids, kept in sync with selected-rids-store

	table: function () {
		const ns = window.dash_clientside.geobrain;
		ns._tableArgs = arguments;
		ns._selected = new Set(Array.isArray(arguments[10]) ? arguments[10] : []);
		if (ns._tableTimer) clearTimeout(ns._tableTimer);
		const slider = window.dash_clientside.callback_context.triggered_id === "slice-slider";
		ns._tableTimer = setTimeout(function () {
			ns._tableTimer = null;
			const out = ns.buildTable.apply(ns, ns._tableArgs);
			const set = window.dash_clientside.set_props;
			set("results-table", { children: out.children });
			set("regions-count", { children: out.count });
			set("regions-sel-text", { children: out.selText });
		}, slider ? 150 : 0);
		return window.dash_clientside.no_update;
	},

	buildTable: function (sliderVal, score, group, geometry, scores, slices, scoreColumns, stops, zmin, zmax, highlight, staticColor, useFlat, filter) {
		// Component descriptors, as Dash renders them (set_props takes no JSX).
		const h = (type, props, children) => ({
			namespace: "dash_html_components",
			type: type,
			props: Object.assign({}, props, children === undefined ? {} : { children: children }),
		});
		const selected = new Set(Array.isArray(highlight) ? highlight : []);
		const selText = selected.size ? `${selected.size} ticked \u00b7 the rest are greyed out` : "Tick regions to color only those";
		const hint = (text) => ({ children: [h("P", { className: "gb-hint" }, text)], count: "", selText: selText });
		if (!geometry || !geometry.by_slice || !slices || !slices.length || !scores) {
			return hint("Regions and their scores appear here once scores are computed.");
		}
		const pos = Math.max(0, Math.min(slices.length - 1, sliderVal || 0));
		const regions = geometry.by_slice[String(slices[pos].slice_index)] || [];
		const present = new Set(regions.map((r) => r.rid));

		if (!stops || !stops.length) stops = FALLBACK_STOPS;
		const valueCol = (scoreColumns || {})[score] || "relative_abundance_z";
		// One value cell per panel group, as in buildFigure.
		const groups = panelGroups(scores, group);
		const valueMaps = groups.map((g) => buildValueMap(pickRecords(scores, g), valueCol));
		const [vmin, vmax] = autoRange(valueMaps, zmin, zmax);
		// Same gating as the figure: ticked rows keep color (flat or by value), the
		// rest go NA; skipped when no ticked region is on this slice.
		const selActive = selected.size > 0 && regions.some((rg) => selected.has(rg.rid));
		const flat = !!useFlat && selActive;
		const fillFor = (rid, v) =>
			selActive && !selected.has(rid) ? NA_COLOR : flat ? staticColor || "#fa5252" : colorFromStops(v, stops, vmin, vmax);

		const names = new Map();
		pickRecords(scores, groups[0]).forEach((row) => names.set(row["Region ID"], row["Region name"]));
		groups.forEach((g) => pickRecords(scores, g).forEach((row) => names.has(row["Region ID"]) || names.set(row["Region ID"], row["Region name"])));
		let rows = Array.from(present)
			.filter((rid) => names.has(rid))
			.map((rid) => ({ rid: rid, name: String(names.get(rid)), vals: valueMaps.map((m) => m[rid]) }));
		const total = rows.length;
		const q = (filter || "").trim().toLowerCase();
		if (q) rows = rows.filter((r) => r.name.toLowerCase().includes(q) || String(r.rid).includes(q));
		// Highest first; regions without a value last.
		rows.sort((a, b) => (isNum(b.vals[0]) ? b.vals[0] : -Infinity) - (isNum(a.vals[0]) ? a.vals[0] : -Infinity));

		const multi = groups.length > 1;
		const fmt = (v) => (isNum(v) ? String(Number(Number(v).toFixed(3))).replace("-", "\u2212") : "\u2013");
		// checkbox, [swatch], id, name, one value column per group
		const cols = `16px ${multi ? "" : "12px "}56px minmax(0, 1fr) repeat(${groups.length}, ${multi ? 72 : 64}px)`;
		const head = h("Div", { className: "gb-row gb-row-head", style: { gridTemplateColumns: cols } }, [
			h("Span", {}, ""),
			multi ? null : h("Span", {}, ""),
			h("Span", {}, "ID"),
			h("Span", {}, "Region"),
		].concat(groups.map((g) => h("Span", { className: "gb-val", title: g }, multi ? g : "Value"))).filter(Boolean));
		const body = rows.map((r) =>
			// No html.Input in Dash: a role=checkbox row with a drawn box (render.js
			// handles click and Space/Enter on it).
			h("Div", {
				className: "gb-row" + (selected.has(r.rid) ? " is-on" : ""),
				role: "checkbox",
				tabIndex: 0,
				"aria-checked": selected.has(r.rid) ? "true" : "false",
				"data-rid": String(r.rid),
				style: { gridTemplateColumns: cols },
			}, [
				h("Span", { className: "gb-check" }),
				multi ? null : h("Span", { className: "gb-swatch", style: { background: fillFor(r.rid, r.vals[0]) } }),
				h("Span", { className: "gb-num gb-rid" }, String(r.rid)),
				h("Span", { className: "gb-rname", title: r.name }, r.name),
			].concat(r.vals.map((v) => h("Span", { className: "gb-num gb-val" }, [
				multi ? h("Span", { className: "gb-swatch gb-dot-s", style: { background: fillFor(r.rid, v) } }) : null,
				fmt(v),
			].filter(Boolean)))).filter(Boolean))
		);
		return { children: [head].concat(body), count: `${rows.length} of ${total}`, selText: selText };
	},

	// Empty the regions selection (all regions return to their score colors).
	clearSelection: function () {
		return [];
	},

	// ---- shell chrome (top bar, setup modal, slice bar) ----

	// Open the data-setup modal on the step whose chip was clicked.
	openSetup: function () {
		const id = window.dash_clientside.callback_context.triggered_id;
		const step = { "chip-slices": "slices", "chip-scores": "scores" }[id] || "atlas";
		return [true, step];
	},

	// Pipeline status for the top-bar chips and the setup-modal nav. The has-*
	// classes on #app-root drive the done checks and the empty state (styles.css).
	pipeline: function (atlasName, slices, geometry, scores) {
		const nSlices = (slices || []).length;
		const nGroups = Object.keys(scores || {}).filter((g) => g !== COMBINED_GROUP).length;
		// Loaded GeoJSON carries its own geometry, so it satisfies the atlas step too.
		const atlas = atlasName || (nSlices ? "From GeoJSON" : "Not loaded");
		const sl = nSlices ? `${nSlices} ${(geometry && geometry.orientation) || "loaded"}` : "Not built";
		const sc = nGroups ? `${nGroups} group${nGroups === 1 ? "" : "s"}` : "Not computed";
		const cls = ["gb", (atlasName || nSlices) && "has-atlas", nSlices && "has-slices", nGroups && "has-scores"]
			.filter(Boolean)
			.join(" ");
		return [cls, atlas, sl, sc, atlas, sl, sc];
	},

	// Legend chip in the stage toolbar: the active colorscale and its limits.
	legend: function (stops, zmin, zmax) {
		const css = (stops && stops.length ? stops : FALLBACK_STOPS)
			.map((s) => `rgb(${s[1].join(",")}) ${s[0] * 100}%`)
			.join(", ");
		const txt = (v) => (isNum(v) ? String(Number(v)) : "auto");
		return [{ background: `linear-gradient(90deg, ${css})` }, txt(zmin), txt(zmax)];
	},

	stepSlice: function (prev, next, value, min, max) {
		const prevClicked = window.dash_clientside.callback_context.triggered_id === "slice-prev-btn";
		return Math.max(min, Math.min(max, (value || 0) + (prevClicked ? -1 : 1)));
	},

	togglePanel: function (nClicks) {
		return nClicks % 2 ? "gb-panel is-hidden" : "gb-panel";
	},

	sliceLabel: function (sliderVal, slices) {
		if (!slices || !slices.length) return "";
		const pos = Math.max(0, Math.min(slices.length - 1, sliderVal || 0));
		const s = slices[pos];
		const mm = s.coordinate_mm;
		const mmTxt = mm === null || mm === undefined ? "" : ` • ${mm >= 0 ? "+" : ""}${mm.toFixed(2)} mm`;
		return `Slice index ${s.slice_index}${mmTxt}  (${pos + 1}/${slices.length})`;
	},
};

// Ticking a region: toggle its id in the selection store. Delegated, because the
// rows are rebuilt on every slice/score change.
function toggleRegionRow(e) {
	const row = e.target && e.target.closest && e.target.closest("#results-table .gb-row[data-rid]");
	if (!row) return false;
	const ns = window.dash_clientside.geobrain;
	const id = Number(row.dataset.rid);
	const next = new Set(ns._selected);
	if (!next.delete(id)) next.add(id);
	ns._selected = next;
	window.dash_clientside.set_props("selected-rids-store", { data: Array.from(next) });
	return true;
}
document.addEventListener("click", toggleRegionRow);
document.addEventListener("keydown", function (e) {
	if ((e.key === " " || e.key === "Enter") && toggleRegionRow(e)) e.preventDefault();
});

// Dropdowns (color settings, export): a click on a .gb-popwrap's button toggles
// it, a click anywhere else closes it. composedPath, not e.target: picking an
// option inside a Select removes the option from the DOM before this runs.
document.addEventListener("click", function (e) {
	const path = e.composedPath();
	const wrap = path.find((el) => el.classList && el.classList.contains("gb-popwrap"));
	const onTrigger = wrap && path.some((el) => el.tagName === "BUTTON" && el.parentElement === wrap);
	const keep = wrap && (!onTrigger || !wrap.classList.contains("is-open"));
	document.querySelectorAll(".gb-popwrap").forEach((w) => w.classList.toggle("is-open", w === wrap && keep));
});
document.addEventListener("keydown", function (e) {
	if (e.key === "Escape") document.querySelectorAll(".gb-popwrap.is-open").forEach((w) => w.classList.remove("is-open"));
});
