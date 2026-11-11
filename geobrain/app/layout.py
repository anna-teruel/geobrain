import dash_mantine_components as dmc
import plotly.express as px
from dash import dcc, html

from geobrain.app.figure import SCORE_VALUE_COLUMN
from geobrain.brainglobe_atlas import list_available_atlases
from geobrain.colormaps import CUSTOM_COLORSCALES

DEFAULT_SPECIES = "mouse"
DEFAULT_ATLAS = "allen_mouse"
DEFAULT_ATLAS_NAME = "allen_mouse_25um"
# Start, end, step (mm relative to bregma) for atlases with a bregma reference.
BREGMA_DEFAULT_RANGE = (-3.0, 3.0, 0.5)
ORIENTATIONS = [
	{"label": "Coronal", "value": "coronal"},
	{"label": "Sagittal", "value": "sagittal"},
	{"label": "Horizontal", "value": "horizontal"},
]
POLYGON_MODES = [
	{"label": "Contour (smooth)", "value": "contour"},
	{"label": "Raster (fast)", "value": "raster"},
]
SCORES = [
	{"label": "Rel. abundance", "value": "rel_abundance"},
	{"label": "Frequency", "value": "frequency"},
	{"label": "Density", "value": "density"},
]
COLORSCALES = [{"label": name, "value": name} for name in CUSTOM_COLORSCALES] + [
	{"label": name, "value": name}
	for name in dir(px.colors.sequential)
	if not name.startswith("_") and isinstance(getattr(px.colors.sequential, name), list)
]
REL_METHODS = [
	{"label": "Within", "value": "within"},
	{"label": "Reference", "value": "reference"},
]
REF_MODES = [
	{"label": "Pooled", "value": "pooled"},
	{"label": "Group", "value": "group"},
]
EXPORT_FORMATS = [{"label": f.upper(), "value": f} for f in ("svg", "png", "pdf", "html")]

# Pipeline steps: (key, title, value shown until the step has run). The key ties
# together a top-bar chip, a setup-modal tab and the `has-<key>` class that
# render.js `pipeline` puts on #app-root (styles.css turns the dots into checks).
PIPELINE = [
	("atlas", "Atlas", "Not loaded"),
	("slices", "Slices", "Not built"),
	("scores", "Scores", "Not computed"),
]

# Palette anchored on the logo: its violet is the primary color, and the dark and
# gray ramps are tinted towards it so surfaces and borders sit with the mark.
# In Mantine's dark scheme dark[7] is the body, [6] inputs, [4] borders, [2] dimmed text.
THEME = {
	"primaryColor": "brand",
	"primaryShade": 6,
	"black": "#17163a",
	"defaultRadius": "md",
	"fontFamily": "Inter, system-ui, sans-serif",
	"colors": {
		"brand": [
			"#f1efff",
			"#e0dcff",
			"#c0b8ff",
			"#b0a5ff",
			"#8f80fa",
			"#7868f5",
			"#6554f0",
			"#5646db",
			"#4638b8",
			"#372c94",
		],
		"dark": [
			"#edecfa",
			"#cfcee6",
			"#b1b0d2",
			"#9492be",
			"#34345c",
			"#2d2d52",
			"#262649",
			"#1b1b38",
			"#14142b",
			"#0d0d1f",
		],
		"gray": [
			"#f6f6fc",
			"#f0effa",
			"#e6e5f3",
			"#d6d5ea",
			"#c9c8e0",
			"#a9a8c6",
			"#65648a",
			"#4a4970",
			"#2e2d55",
			"#17163a",
		],
	},
}


def pick_option(options, preferred):
	"""``preferred`` if it is one of the select ``options``, else the first one."""
	values = [o["value"] for o in options]
	if preferred in values:
		return preferred
	return values[0] if values else None


def species_options(catalog):
	"""Select options for each species in the BrainGlobe atlas catalog."""
	return [{"label": sp.capitalize(), "value": sp} for sp in sorted(catalog["species"].unique())]


def atlas_options(catalog, species):
	"""Select options for the atlases (name without resolution) of one species."""
	atlases = catalog.loc[catalog["species"] == species, "atlas"].unique()
	return [{"label": a, "value": a} for a in sorted(atlases)]


def resolution_options(catalog, atlas):
	"""Select options for one atlas's resolutions; values are full atlas names."""
	rows = catalog[catalog["atlas"] == atlas]
	return [
		{
			"label": f"{row.resolution_um:g} µm" + (" (downloaded)" if row.downloaded else ""),
			"value": row.name,
		}
		for row in rows.itertuples(index=False)
	]


def _dot(step: int):
	"""Numbered step marker; becomes a check once its step is done (styles.css)."""
	return html.Span(str(step), className="gb-dot")


def _browse_field(input_id, button_id, label, **input_kwargs):
	"""Path text input with its native-dialog Browse button."""
	return dmc.Flex(
		[
			dmc.TextInput(id=input_id, label=label, style={"flex": 1}, **input_kwargs),
			dmc.Button("Browse", id=button_id, variant="default"),
		],
		gap="xs",
		align="flex-end",
		style={"flex": 1},
	)


# setup modal: the three pipeline steps
def _step(title, blurb, body, status, actions):
	"""One setup step: its form on top, status/progress and actions pinned below."""
	return html.Div(
		[
			html.Div(
				[
					html.Div(
						[
							dmc.Text(title, fw=600, size="lg"),
							dmc.Text(blurb, size="sm", c="dimmed"),
						]
					),
					*body,
				],
				className="gb-step-body",
			),
			html.Div(
				[html.Div(status, className="gb-step-status"), dmc.Group(actions, gap="xs")],
				className="gb-step-foot",
			),
		],
		className="gb-step",
	)


def _dropzone(upload_id, accept, title):
	return dcc.Upload(
		id=upload_id,
		accept=accept,
		multiple=False,
		className="gb-drop",
		children=[
			dmc.Text(title, fw=600, size="sm"),
			dmc.Text(f"Drop a file or click to browse ({accept})", size="xs", c="dimmed"),
		],
	)


def _step_atlas():
	catalog = list_available_atlases()
	species_opts = species_options(catalog)
	species = pick_option(species_opts, DEFAULT_SPECIES)
	atlas_opts = atlas_options(catalog, species)
	atlas = pick_option(atlas_opts, DEFAULT_ATLAS)
	res_opts = resolution_options(catalog, atlas)
	return _step(
		"Atlas",
		"Choose a BrainGlobe atlas, or reopen files saved from an earlier session.",
		[
			dmc.Tabs(
				[
					dmc.TabsList(
						[
							dmc.TabsTab("BrainGlobe atlas", value="atlas"),
							dmc.TabsTab("Saved files", value="processed"),
						]
					),
					dmc.TabsPanel(
						dmc.SimpleGrid(
							[
								dmc.Select(
									id="species-select",
									label="Species",
									data=species_opts,
									value=species,
									searchable=True,
									allowDeselect=False,
								),
								dmc.Select(
									id="atlas-select",
									label="Atlas",
									data=atlas_opts,
									value=atlas,
									searchable=True,
									allowDeselect=False,
								),
								dmc.Select(
									id="resolution-select",
									label="Resolution",
									data=res_opts,
									value=pick_option(res_opts, DEFAULT_ATLAS_NAME),
									allowDeselect=False,
								),
							],
							cols=3,
							spacing="sm",
						),
						value="atlas",
						pt="md",
					),
					dmc.TabsPanel(
						dmc.Stack(
							[
								dmc.SimpleGrid(
									[
										_dropzone(
											"upload-geojson", ".geojson,.json", "Slice GeoJSON"
										),
										_dropzone("upload-scores", ".csv", "Scores"),
									],
									cols=2,
									spacing="sm",
								),
								dmc.Text(
									"Loading saved files skips the Slices and Scores steps.",
									size="xs",
									c="dimmed",
								),
								dmc.Text(id="load-cached-status", size="sm", c="dimmed"),
							],
							gap="xs",
						),
						value="processed",
						pt="md",
					),
				],
				value="atlas",
				variant="pills",
			),
		],
		# While an atlas downloads, load_raw's progress puts is-downloading on
		# this box: styles.css then shows the bar and its label instead of the
		# spinner, which covers reading an atlas that is already on disk.
		html.Div(
			[
				dmc.Group(
					[
						dmc.Loader(id="step1-loader", size="sm", style={"display": "none"}),
						dmc.Text(id="step1-status", size="xs", c="dimmed"),
					],
					gap="xs",
				),
				dmc.Text(id="atlas-progress-label", size="xs", c="dimmed"),
				dmc.Progress(id="atlas-progress", value=0, animated=True, striped=True),
			],
			id="atlas-status",
		),
		[dmc.Button("Load atlas", id="load-raw-btn")],
	)


def _step_slices():
	return _step(
		"Slices",
		"Cut the atlas into region outlines at regular positions.",
		[
			dmc.Stack(
				[
					dmc.Text("Orientation", size="sm", fw=500),
					dmc.SegmentedControl(
						id="orientation-select", data=ORIENTATIONS, value="coronal"
					),
				],
				gap=4,
				align="flex-start",
			),
			dmc.SimpleGrid(
				[
					dmc.NumberInput(
						id="geo-start",
						label="Start (mm)",
						value=BREGMA_DEFAULT_RANGE[0],
						step=0.1,
					),
					dmc.NumberInput(
						id="geo-end",
						label="End (mm)",
						value=BREGMA_DEFAULT_RANGE[1],
						step=0.1,
					),
					dmc.NumberInput(
						id="geo-step",
						label="Step (mm)",
						value=BREGMA_DEFAULT_RANGE[2],
						min=0.0,
						step=0.05,
					),
				],
				cols=3,
				spacing="sm",
			),
			dmc.Text(id="geo-range-hint", size="xs", c="dimmed"),
			dmc.Accordion(
				value=None,
				children=dmc.AccordionItem(
					[
						dmc.AccordionControl("Advanced build options"),
						dmc.AccordionPanel(
							dmc.SimpleGrid(
								[
									dmc.Select(
										id="polygon-mode-select",
										label="Polygon mode",
										data=POLYGON_MODES,
										value="contour",
										allowDeselect=False,
									),
									dmc.NumberInput(
										id="min-area-px",
										label="Min area (px)",
										value=5.0,
										step=1.0,
									),
									dmc.NumberInput(
										id="simplify-px",
										label="Simplify (px)",
										value=0.8,
										step=0.1,
									),
									dmc.NumberInput(
										id="smooth-sigma",
										label="Smooth sigma",
										value=1.0,
										step=0.1,
									),
								],
								cols=4,
								spacing="sm",
							)
						),
					],
					value="adv",
				),
			),
		],
		[
			dmc.Text(id="geo-progress-label", size="xs", c="dimmed"),
			dmc.Progress(id="geo-progress", value=0, animated=False, striped=True),
		],
		[
			dmc.Button("Save GeoJSON", id="save-geo-btn", variant="default", disabled=True),
			dmc.Button("Build slices", id="build-geo-btn", disabled=True),
		],
	)


def _step_scores():
	return _step(
		"Region scores",
		"Point to the QUINT output and the animal metadata to compute a score per region.",
		[
			dmc.Flex(
				[
					_browse_field(
						"score-data-dir",
						"browse-data-dir-btn",
						"QUINT data folder",
						placeholder="Folder with *_RefAtlasRegions.csv",
						debounce=500,
					),
					dmc.TextInput(
						id="score-sep", label="Separator", value="auto", placeholder="auto", w=96
					),
				],
				gap="xs",
				align="flex-end",
			),
			dmc.Flex(
				[
					_browse_field(
						"metadata-path",
						"browse-metadata-btn",
						"Metadata CSV",
						placeholder="Path to the metadata .csv",
						debounce=500,
					),
					dmc.TextInput(id="metadata-sep", label="Separator", value=";", w=96),
				],
				gap="xs",
				align="flex-end",
			),
			dmc.Accordion(
				value=None,
				children=dmc.AccordionItem(
					[
						dmc.AccordionControl("Grouping"),
						dmc.AccordionPanel(
							dmc.SimpleGrid(
								[
									dmc.TextInput(
										id="animal-col", label="Animal column", value="animal"
									),
									dmc.TextInput(
										id="group-col", label="Group column(s)", value="group"
									),
									dmc.Select(
										id="rel-method-select",
										label="Rel. abundance method",
										data=REL_METHODS,
										value="within",
										allowDeselect=False,
									),
									dmc.Select(
										id="ref-mode-select",
										label="Reference mode",
										data=REF_MODES,
										value="pooled",
										allowDeselect=False,
									),
									dmc.TextInput(
										id="ref-group", label="Reference group (if mode=group)"
									),
								],
								cols=3,
								spacing="sm",
							)
						),
					],
					value="meta",
				),
			),
		],
		[
			dmc.Text(id="score-progress-label", size="xs", c="dimmed"),
			dmc.Progress(id="score-progress", value=0, animated=False, striped=True),
		],
		[
			dmc.Button("Save CSV", id="save-scores-btn", variant="default", disabled=True),
			dmc.Button("Compute scores", id="process-data-btn", disabled=True),
		],
	)


def _setup_modal():
	return dmc.Modal(
		dmc.Tabs(
			[
				dmc.TabsList(
					[
						*[
							dmc.TabsTab(
								html.Div(
									[
										dmc.Text(title, fw=600, size="sm"),
										dmc.Text(
											empty, id=f"nav-{step}-value", size="xs", c="dimmed"
										),
									]
								),
								value=step,
								leftSection=_dot(i),
								className=f"gb-step-{step}",
							)
							for i, (step, title, empty) in enumerate(PIPELINE, start=1)
						],
						dmc.Button(
							"Clear session",
							id="clear-cache-btn",
							variant="subtle",
							color="red",
							justify="flex-start",
							mt="auto",
						),
					]
				),
				dmc.TabsPanel(_step_atlas(), value="atlas"),
				dmc.TabsPanel(_step_slices(), value="slices"),
				dmc.TabsPanel(_step_scores(), value="scores"),
			],
			id="setup-tabs",
			value="atlas",
			orientation="vertical",
			className="gb-setup",
		),
		id="setup-modal",
		title="Data setup",
		size=880,
		centered=True,
		# Mounted while closed so every callback can reach the step controls, and
		# inline (no portal) so the has-<step> classes on #app-root reach the nav dots.
		keepMounted=True,
		withinPortal=False,
		styles={
			"body": {"padding": 0},
			"header": {"borderBottom": "1px solid var(--gb-line)"},
			"title": {"fontWeight": 600},
		},
	)


def _popover(trigger, body, width):
	"""Dropdown under a top-bar/toolbar button.

	Plain markup, always in the DOM, opened and closed by a delegated click
	handler in render.js (the ``is-open`` class on the wrapper). Mantine's Popover
	mounts its content a moment after first paint, and a control that mounts after
	a callback has updated it shows its original layout value instead.
	"""
	return html.Div(
		[trigger, html.Div(body, className="gb-pop", style={"width": width})],
		className="gb-popwrap",
	)


# top bar: brand, pipeline status, global actions
def _export_popover():
	return _popover(
		dmc.Button("Export", id="export-open-btn"),
		dmc.Stack(
			[
				dmc.Text("Export figure", fw=600, size="sm"),
				_browse_field("export-dir", "browse-export-dir-btn", "Output folder", value="."),
				dmc.TextInput(id="export-name", label="File name", value="brain_slice"),
				dmc.SegmentedControl(
					id="export-format", data=EXPORT_FORMATS, value="svg", fullWidth=True
				),
				dmc.Group(
					[
						dmc.Button("All slices", id="export-all-btn", variant="default"),
						dmc.Button("This slice", id="export-btn"),
					],
					grow=True,
					gap="xs",
				),
				dmc.Divider(),
				dmc.Text("Publication grid", fw=600, size="sm"),
				dmc.Text(
					"Rows = groups, columns = slices in the range. Range is in mm from "
					"bregma, or slice index when the atlas has no bregma.",
					size="xs",
					c="dimmed",
				),
				dmc.Group(
					[
						dmc.NumberInput(id="pub-from", label="From", step=0.5),
						dmc.NumberInput(id="pub-to", label="To", step=0.5),
					],
					grow=True,
					gap="xs",
				),
				dmc.Button("Export grid", id="export-pub-btn", variant="default"),
				dmc.Progress(id="export-progress", value=0, animated=False, striped=True),
				dmc.Text(id="export-progress-label", size="xs", c="dimmed"),
				dmc.Text(id="export-status", size="xs", c="dimmed"),
			],
			gap="sm",
		),
		340,
	)


def _header():
	return html.Header(
		[
			html.Div(
				[
					html.Img(src="/assets/GeoBrain_mark.png", alt="", className="gb-mark"),
					html.Span("GeoBrain"),
				],
				className="gb-brand",
			),
			html.Nav(
				[
					html.Button(
						[
							_dot(i),
							html.Span(title, className="gb-chip-label"),
							html.Span(empty, id=f"chip-{step}-value"),
						],
						id=f"chip-{step}",
						className=f"gb-chip gb-step-{step}",
					)
					for i, (step, title, empty) in enumerate(PIPELINE, start=1)
				],
				className="gb-pipe",
				**{"aria-label": "Data pipeline"},
			),
			dmc.Group(
				[
					dmc.ActionIcon(
						html.Span(className="gb-icon-panel"),
						id="regions-toggle-btn",
						variant="subtle",
						color="gray",
						size="lg",
						**{"aria-label": "Toggle regions panel"},
					),
					dmc.Switch(
						id="color-scheme-toggle",
						size="lg",
						color="gray",
						checked=True,
						onLabel="🌙",
						offLabel="☀️",
						styles={"track": {"cursor": "pointer"}, "trackLabel": {"fontSize": "1rem"}},
						**{"aria-label": "Dark theme"},
					),
					_export_popover(),
				],
				gap="sm",
				ml="auto",
			),
		],
		className="gb-top",
	)


# stage: the slice figure with its view controls
def _color_popover():
	return _popover(
		dmc.Button(
			html.Span(
				[
					html.Span(id="legend-min"),
					html.Span(id="legend-bar", className="gb-legend-bar"),
					html.Span(id="legend-max"),
				],
				className="gb-legend gb-num",
			),
			id="color-open-btn",
			variant="default",
			rightSection="▾",
			**{"aria-label": "Color settings"},
		),
		dmc.Stack(
			[
				dmc.Text("Color", fw=600, size="sm"),
				# Dropdowns stay inside the popover (no portal) so picking
				# an option doesn't count as a click outside and close it.
				dmc.Select(
					id="colorscale-select",
					label="Colorscale",
					data=COLORSCALES,
					value="Aurora",
					searchable=True,
					allowDeselect=False,
					comboboxProps={"withinPortal": False},
				),
				dmc.Group(
					[
						dmc.NumberInput(id="zmin-input", label="Min", value=-3.0, step=0.5),
						dmc.NumberInput(id="zmax-input", label="Max", value=3.0, step=0.5),
					],
					grow=True,
					gap="sm",
				),
				dmc.Divider(),
				dmc.Group(
					[
						dmc.Switch(
							id="static-color-toggle",
							label="Flat color for selected regions",
							checked=True,
							size="sm",
						),
						dmc.ColorInput(
							id="static-color",
							value="#fa5252",
							format="hex",
							w=120,
							popoverProps={"withinPortal": False},
							**{"aria-label": "Flat color"},
						),
					],
					justify="space-between",
					wrap="nowrap",
					gap="xs",
				),
				dmc.Text(
					"Only applies while rows are selected in the regions list.",
					size="xs",
					c="dimmed",
				),
			],
			gap="sm",
		),
		340,
	)


def _stage():
	return html.Main(
		[
			html.Div(
				[
					dmc.SegmentedControl(id="score-select", data=SCORES, value="rel_abundance"),
					dmc.Select(
						id="group-select",
						data=[],
						placeholder="Group",
						clearable=False,
						w=180,
						**{"aria-label": "Group"},
					),
					html.Div(_color_popover(), className="gb-push"),
				],
				className="gb-toolbar",
			),
			html.Div(
				[
					dcc.Graph(
						id="brain-graph",
						responsive=True,
						config={
							"displayModeBar": False,
							"scrollZoom": True,
						},
					),
					html.Div(
						[
							html.Img(src="/assets/GeoBrain_logo2.png", alt="GeoBrain logo"),
							dmc.Title("Load an atlas to get started", order=2, size="h3"),
							dmc.Text(
								"Pick a BrainGlobe atlas, build slices and compute region "
								"scores, or reopen GeoJSON and score files saved from an "
								"earlier session.",
								size="sm",
								c="dimmed",
								maw=440,
							),
							dmc.Button("Set up data", id="empty-setup-btn"),
						],
						id="empty-state",
						className="gb-empty",
					),
				],
				className="gb-canvas",
			),
			html.Div(
				[
					dmc.Text(id="slice-label", size="sm"),
					dmc.ActionIcon(
						"‹",
						fz=24,
						id="slice-prev-btn",
						variant="subtle",
						color="gray",
						size="lg",
						**{"aria-label": "Previous slice"},
					),
					html.Div(
						dcc.Slider(
							id="slice-slider",
							min=0,
							max=0,
							step=1,
							value=0,
							updatemode="drag",
							included=False,
							marks={},
							allow_direct_input=False,
						),
						id="slice-slider-wrap",
					),
					dmc.ActionIcon(
						"›",
						fz=24,
						id="slice-next-btn",
						variant="subtle",
						color="gray",
						size="lg",
						**{"aria-label": "Next slice"},
					),
				],
				className="gb-slicebar",
			),
		],
		className="gb-stage",
	)


def _regions_panel():
	return html.Aside(
		[
			html.Div(
				[
					dmc.Group(
						[
							dmc.Text("Regions in this slice", fw=600, size="sm"),
							dmc.Text(id="regions-count", size="xs", c="dimmed"),
						],
						justify="space-between",
						wrap="nowrap",
					),
					dmc.TextInput(
						id="region-filter",
						placeholder="Filter by name or ID",
						debounce=200,
						leftSection="⌕",
						**{"aria-label": "Filter regions"},
					),
					dmc.Group(
						[
							dmc.Text(id="regions-sel-text", size="xs", c="dimmed"),
							dmc.Button(
								"Clear", id="deselect-all-btn", variant="subtle", size="compact-xs"
							),
						],
						justify="space-between",
						wrap="nowrap",
					),
				],
				className="gb-panel-head",
			),
			# Filled by render.js `table`: a header row plus one row per region
			# (checkbox, color swatch, ID, name, value). Selected ids live in
			# selected-rids-store; the wrapper is the only scroll container, so the
			# sticky header stays put.
			html.Div(id="results-table", className="gb-regions"),
		],
		id="regions-panel",
		className="gb-panel",
	)


def _stores():
	return [
		dcc.Store(id="session-store", storage_type="memory"),
		dcc.Store(id="atlas-name-store", storage_type="memory"),
		dcc.Store(id="geometry-store", storage_type="memory"),
		dcc.Store(id="scores-store", storage_type="memory"),
		dcc.Store(id="slices-store", storage_type="memory"),
		# Region ids ticked in the regions list; render.js keeps its own copy in sync.
		dcc.Store(id="selected-rids-store", storage_type="memory", data=[]),
		dcc.Store(id="colorscale-stops-store", storage_type="memory"),
		# Single source for render.js's score -> value column lookup.
		dcc.Store(id="score-columns-store", data=SCORE_VALUE_COLUMN),
		dcc.Download(id="download-geojson"),
		dcc.Download(id="download-scores"),
		dcc.Download(id="download-pub"),
	]


def build_layout():
	return dmc.MantineProvider(
		id="mantine-provider",
		forceColorScheme="dark",
		theme=THEME,
		# Single full-viewport page: top bar, then the stage beside the regions
		# panel. Everything else lives in the setup modal and two popovers.
		children=html.Div(
			[
				*_stores(),
				dmc.NotificationProvider(position="top-center", zIndex=2000),
				html.Div(id="notifications-container"),
				_header(),
				html.Div([_stage(), _regions_panel()], className="gb-body"),
				_setup_modal(),
			],
			id="app-root",
			className="gb",
		),
	)
