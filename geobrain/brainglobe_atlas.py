"""
Integration of the BrainGlobe atlas API into GeoBrain
"""

import configparser
import re
from functools import cached_property, lru_cache

import numpy as np
import pandas as pd

# Aliased: GeoBrain's own BrainGlobeAtlas (below) wraps this class.
from brainglobe_atlasapi import BrainGlobeAtlas as _BGAtlas
from brainglobe_atlasapi import list_atlases
from brainglobe_atlasapi.descriptors import ATLAS_ORIENTATION

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
	# OSError: offline / no cache; configparser.Error, KeyError: captive-portal
	# HTML or a corrupt last_versions.conf cache.
	except (OSError, configparser.Error, KeyError):
		remote = []
	try:
		downloaded = set(list_atlases.get_downloaded_atlases())
	except OSError:
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


class BrainGlobeAtlas:
	"""
	Atlas backed by `brainglobe_atlasapi.BrainGlobeAtlas`, exposing the data
	GeoBrain's slice-building pipeline needs: name, species, annotation,
	structure_df, voxel_size_um and resolution_um.

	The annotation volume uses BrainGlobe's standard axis order
	(ATLAS_ORIENTATION, "asr": axis 0 = AP, axis 1 = DV, axis 2 = LR), which
	is what get_slice_view and app.figure._screen_xy index by.

	Args:
	    atlas_name : str
	        Name of a BrainGlobe atlas, e.g. "allen_mouse_25um" or
	        "allen_human_500um". Downloaded into BrainGlobe's own local
	        cache (~/.brainglobe) on first use.

	Raises:
	    ValueError
	        If the atlas is not in BrainGlobe's standard axis order
	        (ATLAS_ORIENTATION). Every BrainGlobe v3 atlas is, so this only
	        guards against custom atlases or a future BrainGlobe change.
	"""

	def __init__(self, atlas_name: str) -> None:
		self._atlas = _BGAtlas(atlas_name)

		origin = "".join(self._atlas.space.origin)
		if origin != ATLAS_ORIENTATION:
			raise ValueError(
				f"Atlas {atlas_name!r} has origin {origin!r}; GeoBrain expects "
				f"BrainGlobe's standard {ATLAS_ORIENTATION!r} (AP, DV, LR axis order)."
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
		parent_structure_id: brainglobe_atlasapi up to 3.0.2 reads the latter
		as uint16, so parent IDs above 65535 wrap around (e.g. Allen's
		182305689 becomes 50073). Fixed upstream in
		brainglobe/brainglobe-atlasapi#974 (merged 2026-09-30, not yet in a
		release); once GeoBrain requires a release that includes it,
		parent_structure_id can be read directly.

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
	def voxel_size_um(self) -> tuple[float, float, float]:
		"""
		Voxel size in microns along each volume axis (AP, DV, LR). Some
		atlases are anisotropic, e.g. kocher_bumblebee_2.542um is
		(2.542, 1.2407, 1.2407).
		"""
		return tuple(float(r) for r in self._atlas.resolution)

	@property
	def resolution_um(self) -> float:
		"""Isotropic voxel size in microns.

		Raises:
		    ValueError
		        If the atlas is anisotropic; use voxel_size_um instead.
		"""
		voxel = self.voxel_size_um
		if len(set(voxel)) != 1:
			raise ValueError(
				f"Atlas {self.name!r} has anisotropic voxels {voxel} µm; use voxel_size_um."
			)
		return voxel[0]
