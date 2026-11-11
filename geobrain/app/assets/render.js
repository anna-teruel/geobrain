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

function isNum(v) {
	return v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
}

function pickRecords(scores, group) {
	if (!scores) return [];
	if (group && scores[group]) return scores[group];
	const keys = Object.keys(scores);
	return keys.length ? scores[keys[0]] : [];
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

function autoRange(valueMap, vmin, vmax) {
	if (isNum(vmin) && isNum(vmax)) return [Number(vmin), Number(vmax)];
	let lo = Infinity;
	let hi = -Infinity;
	for (const k in valueMap) {
		const v = valueMap[k];
		if (isNum(v)) {
			if (v < lo) lo = v;
			if (v > hi) hi = v;
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
			return emptyFigure("Build or load slices to begin");
		}
		const pos = Math.max(0, Math.min(slices.length - 1, sliderVal || 0));
		const sliceIndex = slices[pos].slice_index;
		const regions = geometry.by_slice[String(sliceIndex)] || [];
		if (!regions.length) return emptyFigure("No regions on this slice");
		const dims = geometry.dims;

		if (!stops || !stops.length) stops = FALLBACK_STOPS;
		const valueCol = (scoreColumns || {})[score] || "relative_abundance_z";
		const valueMap = buildValueMap(pickRecords(scores, group), valueCol);
		const [vmin, vmax] = autoRange(valueMap, zmin, zmax);

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
		for (let i = 0; i < regions.length; i++) {
			const region = regions[i];
			const gated = selActive && !selected.has(region.rid);
			const value = gated ? null : valueMap[region.rid];
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
			traces.push({
				type: "scatter",
				x: xs,
				y: ys,
				customdata: cd,
				mode: "lines",
				fill: "toself",
				fillcolor: fill,
				line: { color: "rgba(255,255,255,0.95)", width: 0.7, shape: "spline", smoothing: 0.6 },
				text: `Region ID: ${region.rid}<br>Region: ${region.name}<br>${score}: ${vTxt}`,
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

		return {
			data: traces,
			layout: {
				uirevision: geometry.orientation || "brain",
				xaxis: xaxis,
				yaxis: yaxis,
				paper_bgcolor: "rgba(0,0,0,0)",
				plot_bgcolor: "rgba(0,0,0,0)",
				font: { color: dark ? "#c1c2c5" : "#444444" },
				margin: { l: 10, r: 10, t: 20, b: 10 },
				hovermode: "closest",
			},
		};
	},

	// Debounce the results table so it only rebuilds once the slider settles,
	// not on every drag tick. The DataTable re-render is DOM-heavy and would
	// otherwise compete with the figure for the main thread while scrolling. The
	// trailing rebuild is pushed straight onto the table via set_props, so the
	// live callback returns no_update for every intermediate value.
	_tableTimer: null,
	_tableArgs: null,

	table: function () {
		const ns = window.dash_clientside.geobrain;
		ns._tableArgs = arguments;
		if (ns._tableTimer) clearTimeout(ns._tableTimer);
		ns._tableTimer = setTimeout(function () {
			ns._tableTimer = null;
			const out = ns.buildTable.apply(ns, ns._tableArgs);
			window.dash_clientside.set_props("results-table", {
				data: out[0],
				columns: out[1],
				style_data_conditional: out[2],
			});
		}, 150);
		return [
			window.dash_clientside.no_update,
			window.dash_clientside.no_update,
			window.dash_clientside.no_update,
		];
	},

	buildTable: function (sliderVal, score, group, geometry, scores, slices, dark, scoreColumns) {
		const emptyCols = [
			{ name: "Region ID", id: "rid" },
			{ name: "Region", id: "name" },
			{ name: "Value", id: "value" },
		];
		if (!geometry || !geometry.by_slice || !slices || !slices.length || !scores) {
			return [[], emptyCols, []];
		}
		const pos = Math.max(0, Math.min(slices.length - 1, sliderVal || 0));
		const sliceIndex = slices[pos].slice_index;
		const regions = geometry.by_slice[String(sliceIndex)] || [];
		const present = {};
		regions.forEach((r) => (present[r.rid] = true));

		const valueCol = (scoreColumns || {})[score] || "relative_abundance_z";
		const records = pickRecords(scores, group);
		const rows = [];
		for (let i = 0; i < records.length; i++) {
			const row = records[i];
			const rid = row["Region ID"];
			if (!present[rid]) continue;
			const v = row[valueCol];
			rows.push({
				id: rid,
				rid: rid,
				name: row["Region name"],
				value: isNum(v) ? Number(Number(v).toFixed(3)) : null,
			});
		}
		const columns = [
			{ name: "Region ID", id: "rid", type: "numeric" },
			{ name: "Region", id: "name" },
			{ name: score, id: "value", type: "numeric" },
		];
		const styleData = [
			{ if: { column_id: "value" }, backgroundColor: dark ? "#2a2f45" : "#eef2ff" },
		];
		return [rows, columns, styleData];
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
