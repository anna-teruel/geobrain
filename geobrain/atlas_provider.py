"""
Integration of the BrainGlobe atlas API into GeoBrain: a minimal protocol
(annotation volume, structure table, resolution, per-orientation axis
lookup) any atlas source can satisfy, plus a brainglobe_atlasapi-backed
implementation of it.
"""

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
from brainglobe_atlasapi import BrainGlobeAtlas

from geobrain.coord_system import Orientation

# Anatomical-direction letters (per brainglobe_space.AnatomicalSpace's
# origin string) that identify which physical axis a given orientation
# slices along.
_ANATOMICAL_LETTERS_BY_ORIENTATION: dict[Orientation, set[str]] = {
	"coronal": {"a", "p"},
	"sagittal": {"l", "r"},
	"horizontal": {"s", "i"},
}


class AtlasProvider(ABC):
	"""
	Adapts one atlas source into the data shape GeoBrain's slice-building
	pipeline expects.

	Subclasses must implement:
	    annotation : np.ndarray
	        3D integer structure-ID volume.
	    structure_df : pd.DataFrame
	        Ontology table with columns [id, acronym, name,
	        parent_structure_id, structure_id_path, color_hex_triplet].
	    resolution_um : float
	        Isotropic voxel size in microns.
	    axis(orientation) : int
	        Array axis to index for a given slicing orientation.
	"""

	@property
	@abstractmethod
	def annotation(self) -> np.ndarray: ...

	@property
	@abstractmethod
	def structure_df(self) -> pd.DataFrame: ...

	@property
	@abstractmethod
	def resolution_um(self) -> float: ...

	@abstractmethod
	def axis(self, orientation: Orientation) -> int: ...


class BrainGlobeProvider(AtlasProvider):
	"""
	AtlasProvider backed by `brainglobe_atlasapi.BrainGlobeAtlas`.

	Args:
	    atlas_name : str
	        Name of a BrainGlobe atlas, e.g. "allen_mouse_25um" or
	        "allen_human_500um". Downloaded into BrainGlobe's own local
	        cache (~/.brainglobe) on first use.
	"""

	def __init__(self, atlas_name: str) -> None:
		self._atlas = BrainGlobeAtlas(atlas_name)

	@property
	def annotation(self) -> np.ndarray:
		"""3D integer structure-ID volume."""
		return self._atlas.annotation

	@property
	def structure_df(self) -> pd.DataFrame:
		"""
		Ontology table reshaped from atlas.structures into GeoBrain's
		`structure_df` schema.

		Returns:
		    pd.DataFrame
		        Columns: id, acronym, name, parent_structure_id,
		        structure_id_path, color_hex_triplet.
		"""
		rows = []
		for node in self._atlas.structures.values():
			r, g, b = node["rgb_triplet"]
			rows.append(
				{
					"id": node["id"],
					"acronym": node["acronym"],
					"name": node["name"],
					"parent_structure_id": node["parent_structure_id"],
					"structure_id_path": node["structure_id_path"],
					"color_hex_triplet": f"{r:02X}{g:02X}{b:02X}",
				}
			)
		return pd.DataFrame(rows)

	@property
	def resolution_um(self) -> float:
		"""Isotropic voxel size in microns.

		Raises:
		    ValueError
		        If the atlas resolution is not isotropic.
		"""
		resolution = self._atlas.resolution
		if len(set(resolution)) != 1:
			raise ValueError(f"Non-isotropic atlas resolution {resolution} is not supported.")
		return float(resolution[0])

	def axis(self, orientation: Orientation) -> int:
		"""
		Resolve which annotation-volume axis to index for a given slicing
		orientation, from the atlas's own anatomical space definition
		(atlas.space.origin) rather than assuming a fixed axis order.

		Args:
		    orientation : {"coronal", "sagittal", "horizontal"}

		Returns:
		    int
		        Array axis index.

		Raises:
		    ValueError
		        If orientation is unknown, or no axis in the atlas's origin
		        matches it.
		"""
		letters = _ANATOMICAL_LETTERS_BY_ORIENTATION.get(orientation)
		if letters is None:
			raise ValueError(f"Unknown orientation: {orientation}")

		origin = self._atlas.space.origin
		for axis_index, origin_letter in enumerate(origin):
			if origin_letter in letters:
				return axis_index

		raise ValueError(f"Could not resolve a {orientation!r} axis from atlas origin {origin!r}.")
