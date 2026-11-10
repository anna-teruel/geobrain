"""
Metadata loading and grouping utilities.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class MetadataConfig:
	"""
	Configuration for loading metadata of experimental groups

	Args:
	    metadata_path : str | None, default=None
	        Path to a metadata CSV file. For now, only csv is supported.
	    sep : str | None, default=None
	        Metadata file separator passed to pandas.read_csv().
	    animal_col : str, default="id"
	        Column used to identify individuals and merge metadata with
	        QUINT-derived data.
	    group_col : str | list[str] | None, default=None
	        Metadata column(s) used to define experimental groups.
	    group_name_sep : str, default="_"
	        Separator used when combining multiple grouping columns into
	        a single group label.
	"""

	metadata_path: str | None = None
	sep: str | None = None
	animal_col: str = "id"
	group_col: str | list[str] | None = None
	group_name_sep: str = "_"

	def load(self) -> pd.DataFrame | None:
		"""
		Load metadata from disk.

		Returns:
		    pd.DataFrame | None
		        Metadata table. Returns None if metadata_path is None.

		Raises:
		    KeyError
		        If animal_col is not present in the metadata file.
		"""
		if self.metadata_path is None:
			return None

		meta = pd.read_csv(
			self.metadata_path,
			sep=self.sep,
			dtype=str,  # IDs like "12" must stay text to match IDs parsed from filenames
		)
		meta.columns = meta.columns.str.strip()  # remove whitespaces in columns
		if self.animal_col not in meta.columns:
			raise KeyError(
				f"Column '{self.animal_col}' not found in metadata file. "
				f"Available columns: {list(meta.columns)}"
			)

		return meta

	def group_cols(self) -> list[str] | None:
		"""
		Normalize group_col into a list of column names.

		Returns:
		    list[str] | None
		        Grouping columns as a list, or None if no grouping
		        was requested.
		"""
		if self.group_col is None:
			return None

		if isinstance(self.group_col, str):
			return [self.group_col]

		return self.group_col

	def merge_and_add_groups(
		self,
		df: pd.DataFrame,
	) -> tuple[pd.DataFrame, list[str] | None]:
		"""
		Merge metadata into a dataframe and create group labels.

		If metadata is available, it is merged using animal_col. If
		group_col is provided, a new column named "group_label" is
		created by concatenating the grouping columns.

		Args:
		    df : pd.DataFrame
		        Input dataframe containing one row per animal.

		Returns:
		    tuple[pd.DataFrame, list[str] | None]
		        - Dataframe with metadata merged and optional group labels.
		        - List of grouping columns used, or None.

		Raises:
		    KeyError
		        If one or more grouping columns are not present after
		        merging metadata.
		"""
		meta = self.load()

		if meta is not None:
			# QUINT-derived tables always call the ID column "animal".
			meta[self.animal_col] = meta[self.animal_col].str.strip()
			df = df.merge(meta, left_on="animal", right_on=self.animal_col, how="left")
			if self.animal_col != "animal":
				df = df.drop(columns=self.animal_col)

		group_cols = self.group_cols()

		if group_cols is None:
			return df, None

		missing = [c for c in group_cols if c not in df.columns]

		if missing:
			raise KeyError(
				f"Grouping column(s) not found after merging data: {missing}. "
				f"Available columns: {list(df.columns)}"
			)

		# Animals with no metadata match have NA group values. Under pandas
		# StringDtype, astype(str) leaves those as NA (not "nan"), which would
		# crash the join below; fillna makes every entry a real string.
		df["group_label"] = (
			df[group_cols].astype(str).fillna("nan").agg(self.group_name_sep.join, axis=1)
		)

		return df, group_cols
