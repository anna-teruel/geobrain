"""
Utilities for loading atlases, score tables, GeoJSON files and saving
Plotly figures generated from region-level brain atlas analyses.
"""

import json
import os

import pandas as pd
import plotly.graph_objects as go

from geobrain.brainglobe_atlas import BrainGlobeProvider


def load_atlas(
	atlas_name: str = "allen_mouse_25um",
) -> BrainGlobeProvider:
	"""
	Load a BrainGlobe atlas.

	The atlas is downloaded into BrainGlobe's local cache (~/.brainglobe)
	on first use and read from there afterwards.

	Args:
	    atlas_name : str, default="allen_mouse_25um"
	        Any BrainGlobe atlas name (see `brainglobe list`). The Allen
	        mouse atlases (allen_mouse_{10,25,50,100}um) give the same
	        volume and ontology as load_annotation_volume() /
	        load_structure_graph().

	Returns:
	    BrainGlobeProvider
	        Atlas exposing annotation, structure_df, resolution_um and
	        species for build_geojson().

	Examples:
	    >>> atlas = load_atlas("allen_mouse_25um")
	    >>> geojson = build_geojson(
	    ...     volume=atlas.annotation,
	    ...     structure_df=atlas.structure_df,
	    ...     resolution_um=atlas.resolution_um,
	    ...     species=atlas.species,
	    ...     orientation="coronal",
	    ...     coords_mm=[-2.0],
	    ... )
	"""
	return BrainGlobeProvider(atlas_name)


def load_score(
	score_csv: str,
	id_col: str = "Region ID",
	name_col: str = "Region name",
) -> pd.DataFrame:
	"""
	Load a region-level score table.

	Args:
	    score_csv : str
	        Path to a score table file.
	    id_col : str, default="Region ID"
	        Column containing Allen structure IDs.
	    name_col : str, default="Region name"
	        Column containing region names.

	Returns:
	    pd.DataFrame
	        Score dataframe containing all saved score columns.
	"""
	score_df = pd.read_csv(score_csv)
	return score_df


def load_geojson(
	geojson_path: str,
) -> dict:
	"""
	Load a slice GeoJSON file.

	Args:
	    geojson_path : str
	        Path to a slice GeoJSON file.

	Returns:
	    dict
	        GeoJSON FeatureCollection.
	"""
	with open(geojson_path, "r", encoding="utf-8") as f:
		return json.load(f)


def save_figure(
	fig: go.Figure,
	out_dir: str,
	filename: str = "figure",
	extension: str = "svg",
) -> str:
	"""
	Save plotly figure to disk.

	Supported formats depend on the output file extension
	and Plotly's image export backend (kaleido).

	Args:
	    fig: go.Figure
	        Plotly figure to save
	    out_dir: str
	        output directory
	     filename : str, default="figure"
	        Figure filename without extension.
	    extension : {"svg", "pdf", "png", "jpg", "html"},
	        default="svg"
	        Output file format.

	Returns:
	    str:
	        Absolute path to saved file.
	"""
	os.makedirs(out_dir, exist_ok=True)

	out_path = os.path.join(
		out_dir,
		f"{filename}.{extension}",
	)

	if extension == "html":
		fig.write_html(out_path)
	else:
		fig.write_image(out_path)
	return os.path.abspath(out_path)
