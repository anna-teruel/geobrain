"""
Subtract two region-level score tables into a per-region delta.
"""

import re
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, ttest_1samp, ttest_ind

from geobrain.types import DeltaTest

_TEST_FNS = {
	"mannwhitney": lambda a, b: mannwhitneyu(a, b, alternative="two-sided"),
	"ttest": lambda a, b: ttest_ind(a, b, equal_var=False),
}


def compute_delta(
	df_a: pd.DataFrame,
	df_b: pd.DataFrame,
	value_col: str,
	col_id: str = "Region ID",
	col_name: str = "Region name",
	label_a: str = "A",
	label_b: str = "B",
) -> pd.DataFrame:
	"""
	Subtract two region-level score tables into a per-region delta
	(delta = df_a - df_b), so two groups can be compared on one
	diverging-colormap figure instead of two side-by-side atlas plots.

	Args:
	    df_a, df_b : pd.DataFrame
	        Region-level score tables (one row per region), e.g. the
	        output of score_table().
	    value_col : str
	        Score column to compare (e.g. "density", "relative_abundance_z").
	    col_id : str, default="Region ID"
	        Column containing Allen structure IDs.
	    col_name : str, default="Region name"
	        Column containing region names.
	    label_a, label_b : str, default="A", "B"
	        Group labels used to name the per-group value columns in the
	        output (e.g. "density_A", "density_B").

	Returns:
	    pd.DataFrame
	        Columns: [col_id, col_name, f"{value_col}_{label_a}",
	        f"{value_col}_{label_b}", "delta"]. Only regions present in
	        both df_a and df_b are kept (inner join).

	Raises:
	    KeyError: If value_col is missing from either input table.
	    ValueError: If label_a and label_b are equal.

	Example:
	    >>> score_females = scores[scores["group_label"] == "female"]
	    >>> score_males = scores[scores["group_label"] == "male"]
	    >>> delta_df = compute_delta(
	    ...     score_females,
	    ...     score_males,
	    ...     value_col="relative_abundance_z",
	    ...     label_a="Female",
	    ...     label_b="Male",
	    ... )
	    >>> delta_df["delta"]  # relative_abundance_z_Female - relative_abundance_z_Male
	"""
	if value_col not in df_a.columns or value_col not in df_b.columns:
		raise KeyError(f"'{value_col}' must be present in both score tables.")

	if label_a == label_b:
		raise ValueError("label_a and label_b must be different.")

	col_a = f"{value_col}_{label_a}"
	col_b = f"{value_col}_{label_b}"

	merged = df_a[[col_id, col_name, value_col]].merge(
		df_b[[col_id, col_name, value_col]],
		on=[col_id, col_name],
		how="inner",
		suffixes=(f"_{label_a}", f"_{label_b}"),
	)

	merged["delta"] = merged[col_a] - merged[col_b]

	return merged


def _benjamini_hochberg(pvalues: np.ndarray) -> np.ndarray:
	"""
	Benjamini-Hochberg FDR correction for multiple comparisons.

	Args:
	    pvalues : np.ndarray
	        Raw p-values.

	Returns:
	    np.ndarray
	        Adjusted p-values, in the same order as the input.
	"""
	n = len(pvalues)
	order = np.argsort(pvalues)
	ranked = pvalues[order] * n / (np.arange(n) + 1)
	# Enforce monotonicity by taking a running minimum from the largest
	# p-value down, which is the standard BH step-up procedure.
	ranked = np.minimum.accumulate(ranked[::-1])[::-1]

	adjusted = np.empty(n)
	adjusted[order] = np.clip(ranked, 0, 1)

	return adjusted


def _add_fdr(df: pd.DataFrame, alpha: float, group_col: str | None = None) -> pd.DataFrame:
	"""Add p_adj/significant columns, correcting within group_col if given."""
	if df.empty:
		df["p_adj"] = pd.Series(dtype=float)
		df["significant"] = pd.Series(dtype=bool)
		return df

	if group_col is None:
		df["p_adj"] = _benjamini_hochberg(df["p_value"].to_numpy())
	else:
		# Correct each term's p-values against each other, not pooled with
		# the other terms (e.g. "sex" shouldn't be corrected together with
		# "group" or the "group:sex" interaction).
		df["p_adj"] = df.groupby(group_col)["p_value"].transform(
			lambda p: _benjamini_hochberg(p.to_numpy())
		)

	df["significant"] = df["p_adj"] < alpha

	return df


def test_two_sample(
	long_a: pd.DataFrame,
	long_b: pd.DataFrame,
	value_col: str,
	col_id: str = "Region ID",
	col_name: str = "Region name",
	test: DeltaTest = "ttest",
	alpha: float = 0.05,
) -> pd.DataFrame:
	"""
	Per-region two-group significance testing.

	Runs a per-region two-sample test on per-animal values (e.g. object
	counts), then applies Benjamini-Hochberg FDR correction across all
	tested regions.

	Args:
	    long_a, long_b : pd.DataFrame
	        Per-animal, per-region tables (one row per animal per region),
	        e.g. the output of compute_animal_region_counts().
	    value_col : str
	        Per-animal numeric column to test (e.g. "objects").
	    col_id : str, default="Region ID"
	        Column containing Allen structure IDs.
	    col_name : str, default="Region name"
	        Column containing region names.
	    test : {"ttest", "mannwhitney"}, default="ttest"
	        Statistical test used per region.
	    alpha : float, default=0.05
	        Significance threshold applied to FDR-adjusted p-values.

	Returns:
	    pd.DataFrame
	        Columns: [col_id, col_name, n_a, n_b, statistic, p_value,
	        effect, p_adj, significant], where "effect" is
	        mean(long_a) - mean(long_b), matching compute_delta()'s sign
	        convention. Only regions with at least 2 animals in both
	        groups are tested.

	Raises:
	    ValueError: If test is not one of {"ttest", "mannwhitney"}.
	"""
	if test not in _TEST_FNS:
		raise ValueError(f"test must be one of {list(_TEST_FNS)}, got '{test}'.")

	shared_regions = set(zip(long_a[col_id], long_a[col_name])) & set(
		zip(long_b[col_id], long_b[col_name])
	)

	rows = []
	for rid, rname in shared_regions:
		a_vals = (
			long_a.loc[(long_a[col_id] == rid) & (long_a[col_name] == rname), value_col]
			.dropna()
			.to_numpy()
		)
		b_vals = (
			long_b.loc[(long_b[col_id] == rid) & (long_b[col_name] == rname), value_col]
			.dropna()
			.to_numpy()
		)

		if len(a_vals) < 2 or len(b_vals) < 2:
			continue

		statistic, p_value = _TEST_FNS[test](a_vals, b_vals)
		rows.append(
			{
				col_id: rid,
				col_name: rname,
				"n_a": len(a_vals),
				"n_b": len(b_vals),
				"statistic": float(statistic),
				"p_value": float(p_value),
				"effect": float(a_vals.mean() - b_vals.mean()),
			}
		)

	result = pd.DataFrame(
		rows, columns=[col_id, col_name, "n_a", "n_b", "statistic", "p_value", "effect"]
	)

	return _add_fdr(result, alpha)


def test_one_sample(
	long_df: pd.DataFrame,
	value_col: str,
	col_id: str = "Region ID",
	col_name: str = "Region name",
	popmean: float = 0.0,
	alpha: float = 0.05,
) -> pd.DataFrame:
	"""
	Per-region one-sample t-test against a fixed reference value.

	Tests whether each region's per-animal values differ significantly
	from popmean (0 by default). Useful when there is no second group to
	compare against, e.g. to find regions with significantly elevated
	relative abundance in a single cohort.

	Args:
	    long_df : pd.DataFrame
	        Per-animal, per-region table, e.g. the output of
	        compute_animal_region_counts().
	    value_col : str
	        Per-animal numeric column to test (e.g. "objects").
	    col_id : str, default="Region ID"
	        Column containing Allen structure IDs.
	    col_name : str, default="Region name"
	        Column containing region names.
	    popmean : float, default=0.0
	        Reference value tested against.
	    alpha : float, default=0.05
	        Significance threshold applied to FDR-adjusted p-values.

	Returns:
	    pd.DataFrame
	        Columns: [col_id, col_name, n, statistic, p_value, effect,
	        p_adj, significant], where "effect" is mean(long_df) -
	        popmean. Only regions with at least 2 animals are tested.
	"""
	rows = []
	for (rid, rname), region_df in long_df.groupby([col_id, col_name], dropna=True):
		vals = region_df[value_col].dropna().to_numpy()

		if len(vals) < 2:
			continue

		statistic, p_value = ttest_1samp(vals, popmean=popmean)
		rows.append(
			{
				col_id: rid,
				col_name: rname,
				"n": len(vals),
				"statistic": float(statistic),
				"p_value": float(p_value),
				"effect": float(vals.mean() - popmean),
			}
		)

	result = pd.DataFrame(rows, columns=[col_id, col_name, "n", "statistic", "p_value", "effect"])

	return _add_fdr(result, alpha)


def _normalize_term(term: str) -> str:
	"""Turn a patsy ANOVA term like "C(Q('group')):C(Q('sex'))" into "group:sex"."""
	names = re.findall(r"C\(Q\('([^']+)'\)\)", term)
	return ":".join(names) if names else term


def test_multi_sample(
	long_df: pd.DataFrame,
	value_col: str,
	factor_cols: str | Sequence[str],
	col_id: str = "Region ID",
	col_name: str = "Region name",
	alpha: float = 0.05,
) -> pd.DataFrame:
	"""
	Per-region n-way ANOVA across one or more categorical factors.

	For each region, fits value_col ~ factor_1 * factor_2 * ... (full
	factorial, Type II sum of squares) and extracts one row per ANOVA
	term (each main effect and each interaction). This is how comparisons
	across more than two groups, or across two crossed factors such as
	group and sex, are handled.

	Args:
	    long_df : pd.DataFrame
	        Per-animal, per-region table containing value_col and all
	        factor_cols (e.g. compute_animal_region_counts() merged with
	        metadata).
	    value_col : str
	        Per-animal numeric column to test (e.g. "objects").
	    factor_cols : str | Sequence[str]
	        One or more categorical columns to test as ANOVA factors
	        (e.g. "group", or ["group", "sex"]).
	    col_id : str, default="Region ID"
	        Column containing Allen structure IDs.
	    col_name : str, default="Region name"
	        Column containing region names.
	    alpha : float, default=0.05
	        Significance threshold applied to FDR-adjusted p-values.

	Returns:
	    pd.DataFrame in long format with columns:
	        [col_id, col_name, term, statistic, p_value, p_adj,
	        significant]
	    where "term" is one of factor_cols or their interaction (e.g.
	    "group", "sex", "group:sex"). p-values are FDR-corrected
	    separately within each term. Regions where the model can't be
	    fit (e.g. fewer observations than parameters, or a factor with
	    only one level) are skipped. There is no "effect"/direction
	    column: with more than two groups per factor there is no single
	    sign, so results here are always plotted as unsigned
	    significance.

	Raises:
	    ValueError: If fewer than one factor column is given.
	"""
	from statsmodels.formula.api import ols
	from statsmodels.stats.anova import anova_lm

	if isinstance(factor_cols, str):
		factor_cols = [factor_cols]
	factor_cols = list(factor_cols)

	if not factor_cols:
		raise ValueError("factor_cols must contain at least one column.")

	formula = f"Q('{value_col}') ~ " + " * ".join(f"C(Q('{c}'))" for c in factor_cols)

	rows = []
	for (rid, rname), region_df in long_df.groupby([col_id, col_name], dropna=True):
		region_df = region_df.dropna(subset=[value_col, *factor_cols])

		if any(region_df[c].nunique() < 2 for c in factor_cols):
			continue
		if len(region_df) <= len(region_df[factor_cols].drop_duplicates()):
			continue

		try:
			model = ols(formula, data=region_df).fit()
			anova_table = anova_lm(model, typ=2)
		except Exception:
			# Fitting can fail for regions with too few observations per
			# factor combination (singular design matrix); skip those.
			continue

		for term, row in anova_table.iterrows():
			if term == "Residual":
				continue
			rows.append(
				{
					col_id: rid,
					col_name: rname,
					"term": _normalize_term(term),
					"statistic": float(row["F"]),
					"p_value": float(row["PR(>F)"]),
				}
			)

	result = pd.DataFrame(rows, columns=[col_id, col_name, "term", "statistic", "p_value"])

	return _add_fdr(result, alpha, group_col="term")


def significance_color(
	sig_df: pd.DataFrame,
	effect_col: str | None = "effect",
	eps: float = 1e-300,
) -> pd.Series:
	"""
	Convert p-values into a color value for a significance-based colormap.

	Args:
	    sig_df : pd.DataFrame
	        Output of test_two_sample(), test_one_sample() or
	        test_multi_sample(). Must contain "p_adj".
	    effect_col : str | None, default="effect"
	        Column giving the direction of the effect. If present in
	        sig_df, the result is signed by sign(effect) so a diverging
	        colormap can show direction alongside significance. Pass
	        None for test_multi_sample() results, which have no single
	        direction and should use an unsigned, sequential colormap.
	    eps : float, default=1e-300
	        Floor applied to p_adj before taking log10, to avoid -inf for
	        p_adj == 0.

	Returns:
	    pd.Series
	        -log10(p_adj), optionally signed. Higher magnitude means more
	        significant; 0 corresponds to a p_adj of 1.
	"""
	neg_log_p = -np.log10(sig_df["p_adj"].clip(lower=eps))

	if effect_col and effect_col in sig_df.columns:
		return neg_log_p * np.sign(sig_df[effect_col])

	return neg_log_p


def apply_significance_mask(
	value_df: pd.DataFrame,
	sig_df: pd.DataFrame,
	value_col: str = "delta",
	col_id: str = "Region ID",
) -> pd.DataFrame:
	"""
	Merge significance results into a value table and gray out
	non-significant regions.

	Args:
	    value_df : pd.DataFrame
	        Table containing value_col, e.g. the output of
	        compute_delta() ("delta") or a single-group score table.
	    sig_df : pd.DataFrame
	        Output of test_two_sample() or test_one_sample(). Must
	        contain col_id and "significant".
	    value_col : str, default="delta"
	        Column in value_df to mask.
	    col_id : str, default="Region ID"
	        Column containing Allen structure IDs.

	Returns:
	    pd.DataFrame
	        value_df with "p_value", "p_adj", "significant" (and
	        "effect", if present in sig_df) merged in, plus a
	        f"{value_col}_masked" column equal to value_col where
	        significant and NaN elsewhere. Regions without a test result
	        (e.g. too few animals) are treated as not significant.
	"""
	sig_cols = [
		c for c in ("statistic", "p_value", "p_adj", "significant", "effect") if c in sig_df.columns
	]

	merged = value_df.merge(sig_df[[col_id, *sig_cols]], on=col_id, how="left")
	merged["significant"] = merged["significant"].fillna(False)
	merged[f"{value_col}_masked"] = merged[value_col].where(merged["significant"])

	return merged
