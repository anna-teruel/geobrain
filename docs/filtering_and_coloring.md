# Filtering & coloring rendered slices

This guide explains how regions on a rendered slice get their color, how to use
the regions list to **filter and find** regions, how to **highlight a chosen set** with
the row checkboxes, and how to apply a single **flat color** instead of the
colormap.

All of this happens live in the browser as you drag the slider or change a
control — there is no server round-trip. The logic lives in
[`geobrain/app/assets/render.js`](../geobrain/app/assets/render.js); the
controls are defined in
[`geobrain/app/layout.py`](../geobrain/app/layout.py).

---

## 1. How a region gets its color

For the current slice, each region's fill is decided in this order:

1. **Look up the region's value** for the selected score
   (`rel_abundance` → `relative_abundance_z`, `frequency` → `frequency`,
   `density` → `density`).
2. **Decide whether the region is "gated off"** by the row selection (see §4).
   A gated region is drawn as **NA gray** (`#d9d9d9`).
3. **Pick the fill for non-gated regions:**
   - **Flat mode** (§5 active) → the chosen flat color.
   - Otherwise → a color interpolated from the **colorscale** between `zmin`
     and `zmax`.
4. Regions with no value (or `NaN`) are always **NA gray**.

When the colormap is in use, a colorbar is shown on the right. In flat mode the
colorbar is hidden (the colormap is off).

> **Key model:** which regions stay colored on the brain is controlled by the
> **row checkboxes** (selection), *not* by the list's text filter. The filter
> is a browsing aid for the list only (see §3).

### The coloring controls

| Control | Component | Purpose |
| --- | --- | --- |
| **Score** | `score-select` (segmented) | Which metric drives the value/color: Rel. abundance, Frequency, Density. |
| **Group** | `group-select` | Which experimental group's scores to show, or `Side by side` for one panel per group (same color range, selection and flat color in every panel). |
| **Colorscale** | `colorscale-select` | Plotly sequential colorscale used for value coloring. |
| **zmin / zmax** | `zmin-input` / `zmax-input` | Fixed color range. Leave blank to auto-range to the slice's min/max. |
| **Flat toggle** | `static-color-toggle` | Switches selected regions to a single flat color (see §5). |
| **Flat color** | `static-color` | The flat color (hex). Default `#fa5252`. |

---

## 2. The regions list

The panel to the right of the brain lists **only the regions present on the
current slice**, highest value first. Each row has a checkbox, a swatch showing
the region's current fill, its ID, its name and its value for the selected
score. With **Group** set to `Side by side` there is one value column per group
(headed by the group name) and the swatch moves into each value cell.

The list is built in the browser by `table` in `render.js` into `results-table`;
the ticked IDs live in `selected-rids-store`.

---

## 3. Filtering the list

Type in the filter box above the list to narrow it by region **name or ID**
(case-insensitive); the counter beside the title shows `shown of total`. This
helps you *find* regions quickly.

> **Filtering does not recolor the brain.** It only changes which rows are shown
> in the list. To highlight regions on the brain, tick their checkboxes (§4).
> This keeps the behavior simple and identical between the live view and
> exports.

---

## 4. Highlighting regions (row checkboxes)

Tick one or more rows to **keep only those regions colored**; all
other regions on the slice render as NA gray.

- With **no** rows selected, **all** regions keep their color.
- **Clear** (`deselect-all-btn`) clears the selection.
- If none of the selected regions happen to be on the current slice (e.g. after
  moving the slider), gating is skipped for that frame rather than graying the
  whole slice (an anti-flash guard).

Selection persists as you move through slices, so it's the way to keep a chosen
set of regions highlighted across the stack.

---

## 5. Applying a flat (single) color

Sometimes you want a publication-style figure where a chosen set of regions is
filled with **one solid color** rather than a value gradient.

**How to turn it on:**

1. Enable the **Flat** toggle (`static-color-toggle`).
2. Pick the color in the **Flat** color box (`static-color`).
3. **Select** the regions you want (tick their checkboxes, §4).

When flat mode is active:

- Selected regions are filled with the **flat color**.
- All other regions are **NA gray**.
- The **colorbar is hidden** (the colormap is off).

> **Important:** the flat color only takes effect while a row selection is
> active. If the Flat toggle is on but nothing is selected, regions fall back to
> normal **value-based** coloring — a flat fill of *every* region would just be
> a solid blob.

### Worked examples

**A. Highlight strongly-positive regions in red**
1. Score → *Rel. abundance*.
2. The list is already sorted by value; the top rows are the strongest.
3. Tick the rows you want.
4. Enable **Flat**, set the color to red (`#fa5252`).
→ The ticked regions are solid red; everything else is gray.

**B. Value gradient with a subset isolated**
1. Leave **Flat** off.
2. Tick the regions of interest.
→ The ticked regions keep their colormap colors; the rest are gray, and the
colorbar stays visible.

---

## 6. Behavior summary

| Flat toggle | Rows selected? | Result |
| --- | --- | --- |
| Off | No | All regions colored by value (colormap + colorbar). |
| Off | Yes | Selected regions colored by value; others gray; colorbar shown. |
| On | No | All regions colored by value (flat ignored). |
| On | Yes | Selected regions = flat color; others gray; colorbar hidden. |

NA / missing-value regions are always gray, in every mode. The list's text
filter never changes any of the above — it only filters the list.

---

## 7. Internals (for maintainers)

The render is a clientside callback (`render`) in
[`render.js`](../geobrain/app/assets/render.js), wired in
[`callbacks.py`](../geobrain/app/callbacks.py). Its inputs map to the
controls as:

| Render arg | Source |
| --- | --- |
| `score`, `group` | `score-select`, `group-select` |
| `stops`, `zmin`, `zmax` | `colorscale-stops-store`, `zmin-input`, `zmax-input` |
| `highlight` | `selected-rids-store` |
| `staticColor`, `useFlat` | `static-color`, `static-color-toggle` |

Key gating variables inside `render`:

- `selActive` / `selected` — the row-selection set and whether it gates (false
  when empty, or when none of the selected regions are on this slice).
- `staticMode` — `useFlat && selActive`; the single condition that switches
  selected regions to the flat color and drops the colorbar.

The static (server-side) export path in
[`figure.py`](../geobrain/app/figure.py) takes the same gating as keyword
arguments (`selected_rids`, `flat_color`), so exports match the live view. Both
export buttons read `selected-rids-store` / `static-color` / `static-color-toggle`
directly (`_selected_flat` in [`callbacks.py`](../geobrain/app/callbacks.py)),
and the selection / flat color apply across all slices.
