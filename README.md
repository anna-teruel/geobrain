<div align="center">

<p align="center">
  <img src="https://raw.githubusercontent.com/anna-teruel/geobrain/main/docs/logos/GeoBrain_logo1.png" width="75%">
</p>
</div>

GeoBrain is an interactive Python framework for atlas-based visualization of quantitative histological data. It maps region-wise metrics derived from atlas-registered workflows, such as QUINT [1], onto the Allen Mouse Brain Common Coordinate Framework (CCFv3) [2]. Built on Plotly, geobrain provides interactive 2D atlas navigation, group comparisons, customizable color mapping, web-based dashboard for exploratory analysis and publication-quality exports.


## Installation

Requires Python 3.12+. Install from PyPI:

```
uv venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows
uv pip install geobrain
```

Or from source:

```
git clone https://github.com/anna-teruel/geobrain
cd geobrain
uv venv
.venv\Scripts\activate
uv pip install .
```

Then launch the dashboard with:

```
geobrain
```

## Documentation

- [Using the dashboard](docs/dashboard_usage.md) — launching the app and the full workflow: load atlas, build slices, compute scores, view and export.
- [Filtering & coloring rendered slices](docs/filtering_and_coloring.md) — how to color regions by score, filter and select which regions stay highlighted, and apply a flat color.
- [Understanding Scores](docs/score_definitions.md) — score definitions, normalization methods and interpretation.
- [Tutorial](examples/demo_API.ipynb) — end-to-end example using the API. To run it, install the notebook extra: `uv pip install "geobrain[notebook]"`.

## License

This project is licensed under the MIT License © 2026
Anna Teruel-Sanchis and Konrad Danielewski.

See the [LICENSE](LICENSE) file for details.

## References

[1] Yates, S. C., et al. (2019). *QUINT: Workflow for Quantification and Spatial Analysis of Features in Histological Images From Rodent Brain*. Frontiers in Neuroinformatics, 13, 75.

[2] Wang, Q., et al. (2020). *The Allen Mouse Brain Common Coordinate Framework: A 3D Reference Atlas*. Cell, 181(4), 936–953.e20.
