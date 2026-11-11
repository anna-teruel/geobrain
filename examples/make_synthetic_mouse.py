"""Generate synthetic QUINT exports + metadata + a scores CSV for trying out the app.

Usage: python examples/make_synthetic_mouse.py [out_dir]
Writes to out_dir (default: examples/synthetic_mouse):
  <id>-1_RefAtlasRegions.csv   QUINT-style, ';' separated (load via the app's folder/QUINT input)
  metadata.csv                 columns: animal, group; ";"-separated  (control / treated)
  scores.csv                   output of score_table(), for the app's "load scores CSV" button
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from geobrain.io import load_atlas
from geobrain.scores import score_table

out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/synthetic_mouse")
out.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(0)

atlas = load_atlas("allen_mouse_25um")
sdf = atlas.structure_df
# Keep leaf-ish, mid-sized set of regions: deepest structures by path length.
regions = sdf.sort_values("id").iloc[:: max(1, len(sdf) // 300)].head(300)
ids, names = regions["id"].to_numpy(), regions["name"].to_numpy()

# Region "hotspots": treated animals get a boost in a random 15% of regions.
hot = rng.random(len(ids)) < 0.15
base_area = rng.integers(2_000, 200_000, len(ids))
base_rate = rng.gamma(2.0, 1.0, len(ids)) * 1e-3  # objects per area unit

animals = [(f"{i:02d}", "control" if i <= 4 else "treated") for i in range(1, 9)]
for aid, grp in animals:
	area = base_area * rng.uniform(0.8, 1.2, len(ids))
	rate = base_rate * (np.where(hot, 3.0, 1.0) if grp == "treated" else 1.0)
	counts = rng.poisson(area * rate)
	pd.DataFrame(
		{"Region ID": ids, "Region name": names, "Object count": counts, "Region area": area.round()}
	).to_csv(out / f"{aid}-1_RefAtlasRegions.csv", sep=";", index=False)

pd.DataFrame(animals, columns=["animal", "group"]).to_csv(out / "metadata.csv", sep=";", index=False)

scores = score_table(str(out), metadata_path=str(out / "metadata.csv"), metadata_sep=";", animal_col="animal", group_col="group")
scores.to_csv(out / "scores.csv", index=False)
print(f"Wrote {len(animals)} animals, {len(ids)} regions, {scores.shape} scores to {out.resolve()}")
