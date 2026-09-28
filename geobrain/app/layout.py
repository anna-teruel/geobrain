import dash_mantine_components as dmc
import plotly.express as px
from dash import dash_table, dcc, html

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
EXPORT_FORMATS = [{"label": f, "value": f} for f in ("svg", "png", "pdf", "html")]


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


def _section_title(step: str, title: str):
	return dmc.Group(
		[
			dmc.Badge(step, variant="filled", radius="sm", size="lg"),
			dmc.Text(title, fw=600, size="md"),
		],
		gap="xs",
	)


def _card(children, p="md", **kwargs):
	return dmc.Card(children, withBorder=True, radius="md", shadow="xs", p=p, **kwargs)


# Steps 1 and 2 share what the logo leaves of the top row, 3:2 in favour of
# step 1 (flex-basis 0, so the split doesn't depend on their contents). Each
# scrolls internally; the floors make the whole row scroll on short screens
# instead of squashing a card to its header.
STEP1_CARD = {"flex": "3 1 0", "minHeight": 150, "overflowY": "auto"}
CARD_FILL = {"flex": "2 1 0", "minHeight": 150, "overflowY": "auto"}

# definite column height = viewport minus app chrome (padding 12+12 + header 38+4)
COL_HEIGHT = "calc(100vh - 66px)"

# Both columns are split into the same two rows: top (logo + steps 1-2 | slice
# display) and bottom (step 3 | controls + table). Using identical flex rules,
# column heights and gaps on both sides keeps the rows level by construction,
# whatever the viewport, zoom or card contents. Each row scrolls internally.
# The row boxes themselves must be plain wrappers (no padding/border): flexbox
# scales shrinking by each box's content size, so a padded card on one side
# would end up a fraction of a pixel off the unpadded box on the other.
TOP_ROW = {"flex": "1 1 70%", "minHeight": "320px"}
BOTTOM_ROW = {"flex": "1 1 30%", "minHeight": "320px"}
ROW_FILL = {"display": "flex", "flexDirection": "column"}
# A card filling its row wrapper.
FILL_ROW = {"flex": "1 1 auto", "minHeight": 0}
COLUMN = {"height": COL_HEIGHT, "overflowY": "auto", "overflowX": "hidden"}


# left panel : processing pipeline
def _step1_load():
	catalog = list_available_atlases()
	species_opts = species_options(catalog)
	species = pick_option(species_opts, DEFAULT_SPECIES)
	atlas_opts = atlas_options(catalog, species)
	atlas = pick_option(atlas_opts, DEFAULT_ATLAS)
	res_opts = resolution_options(catalog, atlas)
	return _card(
		dmc.Stack(
			[
				_section_title("1", "Load atlas"),
				dmc.Tabs(
					[
						dmc.TabsList(
							[
								dmc.TabsTab("Load atlas", value="atlas"),
								dmc.TabsTab("Load processed files", value="processed"),
							]
						),
						dmc.TabsPanel(
							dmc.Stack(
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
									dmc.Button("Load atlas", id="load-raw-btn", fullWidth=True),
									dmc.Group(
										[
											dmc.Loader(
												id="step1-loader",
												size="sm",
												style={"display": "none"},
											),
											dmc.Text(id="step1-status", size="sm", c="dimmed"),
										],
										gap="xs",
									),
								],
								gap="sm",
								pt="sm",
							),
							value="atlas",
						),
						dmc.TabsPanel(
							dmc.Stack(
								[
									dcc.Upload(
										id="upload-geojson",
										accept=".geojson,.json",
										multiple=False,
										children=dmc.Button(
											"Load GeoJSON", variant="light", fullWidth=True
										),
									),
									dcc.Upload(
										id="upload-scores",
										accept=".csv",
										multiple=False,
										children=dmc.Button(
											"Load scores", variant="light", fullWidth=True
										),
									),
									dmc.Text(id="load-cached-status", size="xs", c="dimmed"),
								],
								gap="sm",
								pt="sm",
							),
							value="processed",
						),
					],
					value="atlas",
				),
			],
			gap="sm",
		),
		style=STEP1_CARD,
	)


def _step2_geojson():
	return _card(
		dmc.Stack(
			[
				_section_title("2", "Build slice GeoJSONs"),
				dmc.Select(
					id="orientation-select",
					label="Orientation",
					data=ORIENTATIONS,
					value="coronal",
					allowDeselect=False,
				),
				dmc.Group(
					[
						dmc.NumberInput(
							id="geo-start",
							label="Start (mm)",
							value=BREGMA_DEFAULT_RANGE[0],
							step=0.1,
							w="31%",
						),
						dmc.NumberInput(
							id="geo-end",
							label="End (mm)",
							value=BREGMA_DEFAULT_RANGE[1],
							step=0.1,
							w="31%",
						),
						dmc.NumberInput(
							id="geo-step",
							label="Step (mm)",
							value=BREGMA_DEFAULT_RANGE[2],
							min=0.0,
							step=0.05,
							w="31%",
						),
					],
					grow=True,
					gap="xs",
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
									cols=2,
									spacing="xs",
									verticalSpacing="xs",
								)
							),
						],
						value="adv",
					),
				),
				dmc.Group(
					[
						dmc.Button(
							"Build GeoJSONs", id="build-geo-btn", disabled=True, style={"flex": 1}
						),
						dmc.Button("Save", id="save-geo-btn", variant="light", disabled=True),
					],
					gap="xs",
				),
				dmc.Progress(id="geo-progress", value=0, animated=False, striped=True),
				dmc.Text(id="geo-progress-label", size="xs", c="dimmed"),
			],
			gap="sm",
		),
		style=CARD_FILL,
	)


def _step3_scores():
	return _card(
		dmc.Stack(
			[
				_section_title("3", "Compute region scores"),
				dmc.Grid(
					[
						dmc.GridCol(
							dmc.Flex(
								[
									dmc.TextInput(
										id="score-data-dir",
										label="QUINT data folder",
										placeholder="path to *_RefAtlasRegions.csv",
										debounce=500,
										style={"flex": 1},
									),
									dmc.Button(
										"Browse",
										id="browse-data-dir-btn",
										variant="light",
									),
								],
								gap="xs",
								align="flex-end",
							),
							span=9,
						),
						dmc.GridCol(
							dmc.TextInput(
								id="score-sep",
								label="Separator",
								value="auto",
								placeholder="auto",
							),
							span=3,
						),
						dmc.GridCol(
							dmc.Flex(
								[
									dmc.TextInput(
										id="metadata-path",
										label="Metadata CSV",
										placeholder="path to metadata csv",
										debounce=500,
										style={"flex": 1},
									),
									dmc.Button(
										"Browse",
										id="browse-metadata-btn",
										variant="light",
									),
								],
								gap="xs",
								align="flex-end",
							),
							span=9,
						),
						dmc.GridCol(
							dmc.TextInput(
								id="metadata-sep",
								label="Separator",
								value=";",
							),
							span=3,
						),
					],
					gutter="xs",
				),
				dmc.Accordion(
					value=None,
					children=dmc.AccordionItem(
						[
							dmc.AccordionControl("Grouping"),
							dmc.AccordionPanel(
								dmc.Stack(
									[
										dmc.SimpleGrid(
											[
												dmc.TextInput(
													id="animal-col",
													label="Animal column",
													value="animal",
												),
												dmc.TextInput(
													id="group-col",
													label="Group column(s)",
													value="group",
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
											],
											cols=2,
											spacing="xs",
											verticalSpacing="xs",
										),
										dmc.TextInput(
											id="ref-group",
											label="Reference group (if mode=group)",
										),
									],
									gap="xs",
								)
							),
						],
						value="meta",
					),
				),
				dmc.Group(
					[
						dmc.Button(
							"Compute scores",
							id="process-data-btn",
							disabled=True,
							style={"flex": 1},
						),
						dmc.Button("Save", id="save-scores-btn", variant="light", disabled=True),
					],
					gap="xs",
				),
				dmc.Progress(id="score-progress", value=0, animated=False, striped=True),
				dmc.Text(id="score-progress-label", size="xs", c="dimmed"),
			],
			gap="sm",
		),
		style={**FILL_ROW, "overflowY": "auto"},
	)


def _header():
	return dmc.Group(
		[
			dmc.Badge("dashboard", variant="light", color="grape"),
			dmc.Group(
				[
					dmc.Button(
						"Clear",
						id="clear-cache-btn",
						variant="light",
						color="red",
					),
					dmc.Switch(
						id="color-scheme-toggle",
						size="xl",
						checked=True,
						onLabel="🌙",
						offLabel="☀️",
						styles={
							"track": {"cursor": "pointer"},
							"trackLabel": {"fontSize": "1.2rem"},
						},
					),
				],
				gap="sm",
				align="center",
			),
		],
		justify="space-between",
		align="center",
		h=38,
		style={"marginBottom": "4px"},
	)


def _left_panel():
	return dmc.Stack(
		[
			dmc.Stack(
				[
					html.Img(
						src="/assets/GeoBrain_logo2.png",
						style={
							"width": "100%",
							"maxWidth": "300px",
							"height": "auto",
							"display": "block",
							"margin": "0 auto",
							"flex": "0 0 auto",
						},
						alt="GeoBrain logo",
					),
					_step1_load(),
					_step2_geojson(),
				],
				gap="md",
				# Short screens: this row scrolls rather than squashing step 2.
				style={**TOP_ROW, "overflowY": "auto", "overflowX": "hidden"},
			),
			html.Div(_step3_scores(), style={**BOTTOM_ROW, **ROW_FILL}),
		],
		gap="md",
		style=COLUMN,
	)


# right panel: figure, controls, table
def _brain_graph():
	return _card(
		dmc.Stack(
			[
				# The figure takes all remaining height (minHeight:0 lets it shrink
				# within the flex column); the slice slider sits pinned at the bottom.
				html.Div(
					dcc.Graph(
						id="brain-graph",
						style={"height": "100%", "width": "100%"},
						config={
							"displaylogo": False,
							"scrollZoom": True,
							"modeBarButtonsToRemove": ["select2d", "lasso2d"],
						},
					),
					style={"flex": "1 1 auto", "minHeight": 0},
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
				dmc.Text(id="slice-label", size="xs", c="dimmed", ta="center"),
			],
			gap="xs",
			style={"height": "100%"},
		),
		p="xs",
		# The graph takes ~70% of the column so the lower Flex below it roughly lines
		# up with the left column's step-3 card. A px floor (not 58vh) avoids forcing
		# overflow; it still drives the column's scroll fallback on very short screens.
		style=FILL_ROW,
	)


def _controls_panel():
	return _card(
		dmc.Stack(
			[
				dmc.Text("Score", fw=600, size="sm"),
				dmc.SegmentedControl(
					id="score-select", data=SCORES, value="rel_abundance", fullWidth=True
				),
				dmc.Select(
					id="group-select", label="Group", data=[], placeholder="-", clearable=False
				),
				dmc.Group(
					[
						dmc.Select(
							id="colorscale-select",
							label="Colorscale",
							data=COLORSCALES,
							value="Aurora",
							style={"flex": 1},
							allowDeselect=False,
						),
						dmc.NumberInput(id="zmin-input", label="zmin", value=-3.0, step=0.5, w=68),
						dmc.NumberInput(id="zmax-input", label="zmax", value=3.0, step=0.5, w=68),
						dmc.Switch(
							id="static-color-toggle",
							checked=True,
							size="sm",
							style={"marginBottom": 8},
						),
						dmc.ColorInput(
							id="static-color",
							label="Flat",
							value="#fa5252",
							format="hex",
							w=110,
						),
					],
					gap="xs",
					align="flex-end",
				),
				dmc.Divider(label="Export", labelPosition="center"),
				dmc.Group(
					[
						dmc.Flex(
							[
								dmc.TextInput(
									id="export-dir",
									label="Output folder",
									value=".",
									style={"flex": 1},
								),
								dmc.Button("Browse", id="browse-export-dir-btn", variant="light"),
							],
							gap="xs",
							align="flex-end",
							style={"flex": 1},
						),
						dmc.TextInput(
							id="export-name", label="File name", value="brain_slice", w=120
						),
						dmc.Select(
							id="export-format",
							label="Format",
							data=EXPORT_FORMATS,
							value="svg",
							w=92,
							allowDeselect=False,
						),
					],
					gap="xs",
					align="flex-end",
					wrap="nowrap",
				),
				dmc.Group(
					[
						dmc.Button("Export current slice", id="export-btn", variant="light"),
						dmc.Button("Export all slices", id="export-all-btn", variant="light"),
					],
					grow=True,
					gap="xs",
				),
				dmc.Progress(id="export-progress", value=0, animated=False, striped=True),
				dmc.Text(id="export-progress-label", size="xs", c="dimmed"),
				dmc.Text(id="export-status", size="xs", c="dimmed"),
			],
			gap="sm",
		),
		style={"height": "100%", "overflowY": "auto"},
	)


def _table_panel():
	return _card(
		dmc.Stack(
			[
				dmc.Group(
					[
						dmc.Text(
							"Region scores (current slice) - select rows to keep colored",
							fw=600,
							size="sm",
						),
						dmc.Button(
							"Deselect all",
							id="deselect-all-btn",
							variant="subtle",
							size="compact-xs",
						),
					],
					justify="space-between",
					align="center",
					wrap="nowrap",
				),
				# The table fills the remaining card height and scrolls. The scroll
				# lives on this wrapper (a flex child with minHeight:0 so it can
				# shrink below content size) - a percentage height on the table's
				# own container collapses to content height and never scrolls.
				html.Div(
					dash_table.DataTable(
						id="results-table",
						columns=[],
						data=[],
						sort_action="native",
						filter_action="native",
						row_selectable="multi",
						page_size=11,
						style_table={"overflowX": "auto"},
						style_cell={
							"fontFamily": "Inter, system-ui, sans-serif",
							"fontSize": "12px",
							"padding": "4px 8px",
							"textAlign": "left",
							"maxWidth": 160,
							"overflow": "hidden",
							"textOverflow": "ellipsis",
						},
						style_header={"fontWeight": "600", "backgroundColor": "#f1f3f5"},
					),
					style={"flex": "1 1 auto", "minHeight": 0, "overflowY": "auto"},
				),
			],
			gap="xs",
			style={"height": "100%"},
		),
		style={"height": "100%"},
	)


def _right_panel():
	return dmc.Stack(
		[
			html.Div(_brain_graph(), style={**TOP_ROW, **ROW_FILL}),
			dmc.Flex(
				[
					html.Div(_controls_panel(), style={"flex": "5 1 0", "minWidth": 0}),
					html.Div(_table_panel(), style={"flex": "7 1 0", "minWidth": 0}),
				],
				gap="md",
				style=BOTTOM_ROW,
			),
		],
		gap="md",
		# The graph grows to ~70% and won't shrink below its floor, so on short
		# viewports this column overflows here and scrolls rather than squeezing
		# the figure; the lower cards manage their own inner overflow (see
		# _controls_panel / _table_panel).
		style=COLUMN,
	)


def _stores():
	return [
		dcc.Store(id="session-store", storage_type="memory"),
		dcc.Store(id="geometry-store", storage_type="memory"),
		dcc.Store(id="scores-store", storage_type="memory"),
		dcc.Store(id="slices-store", storage_type="memory"),
		dcc.Store(id="colorscale-stops-store", storage_type="memory"),
		dcc.Download(id="download-geojson"),
		dcc.Download(id="download-scores"),
	]


def build_layout():
	return dmc.MantineProvider(
		id="mantine-provider",
		forceColorScheme="dark",
		theme={
			"primaryColor": "indigo",
			"defaultRadius": "md",
			"fontFamily": "Inter, system-ui, sans-serif",
		},
		children=html.Div(
			[
				*_stores(),
				dmc.NotificationProvider(position="top-center", zIndex=2000),
				html.Div(id="notifications-container"),
				_header(),
				dmc.Grid(
					[
						# Cap the pipeline column at 500px; the view column uses
						# span="auto" so it grows to fill the space freed by the cap
						# (rather than leaving a gap) on wide monitors.
						dmc.GridCol(
							_left_panel(),
							span={"base": 12, "md": 3},
							style={"maxWidth": "500px"},
						),
						# minWidth:0 lets this column shrink below its content's
						# min-content width (the native-filter table is wide). Without
						# it the column can't shrink and Mantine's flex-wrap Grid drops
						# it onto the next line - collapsing it below the left column on
						# resize. The table's own overflowX scrolls instead.
						dmc.GridCol(
							_right_panel(),
							span={"base": 12, "md": "auto"},
							style={"minWidth": 0},
						),
					],
					gutter="md",
				),
			],
			id="app-root",
			style={
				"padding": "12px",
				"backgroundColor": "var(--mantine-color-body)",
				"minHeight": "100vh",
			},
		),
	)
