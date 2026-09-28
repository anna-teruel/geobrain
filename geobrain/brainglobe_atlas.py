"""
Integration of the BrainGlobe atlas API into GeoBrain
"""

import re
from abc import ABC, abstractmethod
from functools import cached_property, lru_cache

import numpy as np
import pandas as pd
from brainglobe_atlasapi import BrainGlobeAtlas, list_atlases

from geobrain.coord_system import Orientation

# Anatomical-direction letters (per brainglobe_space.AnatomicalSpace's
# origin string) that identify which physical axis a given orientation
# slices along.
_ANATOMICAL_LETTERS_BY_ORIENTATION: dict[Orientation, set[str]] = {
	"coronal": {"a", "p"},
	"sagittal": {"l", "r"},
	"horizontal": {"s", "i"},
}

# Axis order GeoBrain's slicing (get_slice_view) and screen mapping
# (app.figure._screen_xy) assume: axis 0 = AP, axis 1 = DV, axis 2 = LR.
# This is the Allen CCF order and BrainGlobe's v3 ATLAS_ORIENTATION.
GEOBRAIN_ORIGIN = ("a", "s", "r")

# BrainGlobe metadata stores the binomial name; GeoBrain's coordinate
# system (coord_system._require_mouse) uses common names.
_COMMON_SPECIES_NAMES = {
	"mus musculus": "mouse",
}

# BrainGlobe's atlas list only carries names and versions; the species is
# in each atlas's metadata, which needs the atlas downloaded. For the UI
# catalog we read it off the name instead: first underscore-separated token
# found here wins ("mouselemur" is its own token, so it doesn't hit "mouse").
_SPECIES_BY_NAME_TOKEN = {
	"mouse": "mouse",
	"cord": "mouse",  # allen_cord: mouse spinal cord
	"rat": "rat",
	"molerat": "african mole-rat",
	"vole": "prairie vole",
	"human": "human",
	"macaque": "macaque",
	"mouselemur": "mouse lemur",
	"cat": "cat",
	"zfish": "zebrafish",
	"cavefish": "cavefish",
	"danionella": "danionella",
	"axolotl": "axolotl",
	"blackcap": "eurasian blackcap",
	"dragon": "tawny dragon",
	"cuttlefish": "cuttlefish",
	"bumblebee": "bumblebee",
	"drosophila": "fruit fly",
	"fly": "fruit fly",
}
OTHER_SPECIES = "other"

# Offline, with nothing downloaded: still offer the Allen mouse atlases.
_FALLBACK_ATLASES = [f"allen_mouse_{r}um" for r in (10, 25, 50, 100)]

_ATLAS_NAME_RE = re.compile(r"^(?P<base>.+)_(?P<res>\d+(?:\.\d+)?)um$")


def atlas_species_from_name(atlas_name: str) -> str:
	"""
	Guess an atlas's common species name from its BrainGlobe name, e.g.
	"whs_sd_rat_39um" -> "rat". Returns OTHER_SPECIES if no token matches.
	"""
	for token in atlas_name.lower().split("_"):
		if token in _SPECIES_BY_NAME_TOKEN:
			return _SPECIES_BY_NAME_TOKEN[token]
	return OTHER_SPECIES


@lru_cache(maxsize=1)
def list_available_atlases() -> pd.DataFrame:
	"""
	Catalog of BrainGlobe atlases, for picking one by species and resolution.

	Uses BrainGlobe's online atlas list plus any locally downloaded atlases,
	so it still works offline for atlases already in ~/.brainglobe. Cached
	for the lifetime of the process.

	Returns:
	    pd.DataFrame
	        Columns: name (full atlas name, e.g. "allen_mouse_25um"),
	        atlas (name without resolution, e.g. "allen_mouse"), species
	        (see atlas_species_from_name), resolution_um (float), downloaded
	        (bool). Sorted by species, atlas and resolution.
	"""
	try:
		remote = list(list_atlases.get_all_atlases_lastversions())
	except Exception:  # offline / GitHub unreachable
		remote = []
	try:
		downloaded = set(list_atlases.get_downloaded_atlases())
	except Exception:
		downloaded = set()
	names = set(remote) | downloaded or set(_FALLBACK_ATLASES)

	rows = []
	for name in names:
		match = _ATLAS_NAME_RE.match(name)
		if match is None:
			continue
		rows.append(
			{
				"name": name,
				"atlas": match["base"],
				"species": atlas_species_from_name(name),
				"resolution_um": float(match["res"]),
				"downloaded": name in downloaded,
			}
		)
	df = pd.DataFrame(rows, columns=["name", "atlas", "species", "resolution_um", "downloaded"])
	return df.sort_values(["species", "atlas", "resolution_um"], ignore_index=True)


class AtlasProvider(ABC):
	"""
	Adapts one atlas source into the data shape GeoBrain's slice-building
	pipeline expects.

	Subclasses must implement:
	    name : str
	        Atlas identifier, e.g. "allen_mouse_25um".
	    species : str
	        Common species name ("mouse", ...) used to decide whether
	        bregma-relative coordinates are available.
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
	def name(self) -> str: ...

	@property
	@abstractmethod
	def species(self) -> str: ...

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

	Raises:
	    ValueError
	        If the atlas is not stored in GeoBrain's expected "asr" axis
	        order (see GEOBRAIN_ORIGIN).
	"""

	def __init__(self, atlas_name: str) -> None:
		self._atlas = BrainGlobeAtlas(atlas_name)

		origin = tuple(self._atlas.space.origin)
		if origin != GEOBRAIN_ORIGIN:
			raise ValueError(
				f"Atlas {atlas_name!r} has origin {''.join(origin)!r}; GeoBrain "
				f"expects {''.join(GEOBRAIN_ORIGIN)!r} (AP, DV, LR axis order)."
			)

	@property
	def name(self) -> str:
		"""BrainGlobe atlas name."""
		return self._atlas.atlas_name

	@property
	def species(self) -> str:
		"""
		Common species name from the atlas metadata, e.g. "Mus musculus"
		-> "mouse". Species without a known common name are returned as
		stored in the metadata.
		"""
		species = self._atlas.metadata.get("species", "")
		return _COMMON_SPECIES_NAMES.get(species.strip().lower(), species)

	@property
	def annotation(self) -> np.ndarray:
		"""3D integer structure-ID volume."""
		return self._atlas.annotation

	@cached_property
	def structure_df(self) -> pd.DataFrame:
		"""
		Ontology table reshaped from atlas.structures into GeoBrain's
		`structure_df` schema.

		IDs are plain Python ints and the root's parent is None (not NaN),
		so the values serialize cleanly into GeoJSON properties.

		The parent ID is taken from structure_id_path rather than
		parent_structure_id: brainglobe_atlasapi 3.0.1 reads the latter as
		uint16, so parent IDs above 65535 wrap around (e.g. Allen's
		182305689 becomes 50073).

		Returns:
		    pd.DataFrame
		        Columns: id, acronym, name, parent_structure_id,
		        structure_id_path, color_hex_triplet.
		"""
		rows = []
		for node in self._atlas.structures.values():
			r, g, b = node["rgb_triplet"]
			path = [int(i) for i in node["structure_id_path"]]
			rows.append(
				{
					"id": int(node["id"]),
					"acronym": node["acronym"],
					"name": node["name"],
					"parent_structure_id": path[-2] if len(path) > 1 else None,
					"structure_id_path": path,
					"color_hex_triplet": f"{r:02X}{g:02X}{b:02X}",
				}
			)
		df = pd.DataFrame(rows)
		# Keep parent IDs as Python ints/None rather than letting pandas
		# upcast the column to float64 with NaN.
		df["parent_structure_id"] = pd.Series(
			[row["parent_structure_id"] for row in rows], dtype=object
		)
		return df

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
