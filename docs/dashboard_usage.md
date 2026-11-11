# Using the GeoBrain dashboard

The dashboard turns atlas-registered region data (e.g. from QUINT) into an
interactive, colored slice viewer with high-resolution export. This guide walks
through launching it and the full workflow. For how to highlight/recolor
regions once they're rendered, see
[Filtering & coloring rendered slices](filtering_and_coloring.md).

---

## Launching

After installing (see the [README](../README.md)):

```
geobrain
```

A browser tab opens automatically at `http://127.0.0.1:8050`. To use another
port:

```
geobrain --port 8060
```

The dashboard only listens on `127.0.0.1`, so it is reachable from your own
machine only. This is deliberate: it saves files to your disk and opens file
dialogs on your screen, which nobody else on the network should be able to do.

---

## Layout at a glance

The app is a single page that fills the window; the slice takes most of it and
everything you only need now and then opens on demand.

- **Top bar** — the logo, the **pipeline status** (three chips: *Atlas*,
  *Slices*, *Scores*, each showing what is loaded and a check once that step is
  done), a button that shows/hides the regions panel, the **light/dark
  toggle**, and the **Export** button.
- **Stage** — the brain figure. Above it sit the **Score** and **Group**
  selectors and the **color legend**; below it the **slice slider**.
- **Regions panel** (right) — the table of regions on the current slice.
- **Data setup** (a dialog) — the processing pipeline, one step per tab:
  1. Atlas (or load previously saved files)
  2. Slices
  3. Region scores

Click a pipeline chip to open **Data setup** on that step. On first launch the
stage shows a **Set up data** button that does the same.

Each step unlocks the next: the brain only renders once **geometry** (slices)
exist, and is colored once **scores** exist. You produce those either by running
steps 1→3, or by loading files you saved earlier.

---

## Step 1 — Atlas

Two tabs:

### "BrainGlobe atlas"
1. Pick a **Species**, an **Atlas** and a **Resolution**. Every
   [BrainGlobe](https://brainglobe.info) atlas is listed; ones already on disk are
   marked *(downloaded)*. Lower µm is finer but slower and heavier; for the Allen
   mouse atlas, 25 and 50 µm are a good middle ground.
2. Click **Load atlas**. The first load of an atlas downloads it into
   BrainGlobe's cache (`~/.brainglobe`) and shows a **progress bar** counting
   the files of the current download batch (a few small metadata batches, then
   the annotation volume). An atlas that is already on disk shows a **spinner**
   while it is read. The status then shows the loaded volume shape.

This enables **Step 2**.

### "Saved files" (resume a previous session)
If you already exported geometry and/or scores before, skip the atlas entirely:
- **Slice GeoJSON** — drop or pick a `brain_slices.geojson` you saved in Step 2.
  This reconstructs the slices and populates the slider. Every feature needs a
  `Region ID`, a `slice_index` and 2D Polygon/MultiPolygon geometry; otherwise a
  red toast names the first field that is missing or wrong.
- **Scores** — drop or pick a `region_scores.csv` you saved in Step 3. It needs
  a `Region ID` column and at least one score column
  (`relative_abundance_z`, `frequency` or `density`).

Loading both gets you straight to the view with no atlas processing.

---

## Step 2 — Slices

Defines which slices to cut and turns the atlas volume into polygon geometry.

1. **Orientation** — Coronal, Sagittal, or Horizontal. This sets which axis the
   slice coordinates refer to (coronal → AP, sagittal → ML, horizontal → DV).
2. **Start / End / Step (mm)** — the range to slice and the spacing between
   slices. How positions are measured depends on the atlas (the hint under the
   inputs says which applies):
   - **Allen mouse atlases** (`allen_mouse_*`): stereotaxic mm relative to
     bregma. Slices outside the atlas are skipped.
   - **Every other atlas**: mm from the first slice along the chosen axis. The
     inputs are pre-filled with the span of the brain tissue.
3. **Advanced build options** (collapsed by default):
   - **Polygon mode** — *Contour (smooth)* for clean curved outlines, or
     *Raster (fast)* for speed.
   - **Min area (px)** — drop regions smaller than this on a slice.
   - **Simplify (px)** — polygon simplification tolerance.
   - **Smooth sigma** — outline smoothing strength.
4. Click **Build slices**. A progress bar reports each slice as it's built.
5. **Save GeoJSON** (optional) — downloads the geometry as
   `brain_slices.geojson` so you can reload it later via Step 1's "Saved files"
   tab.

Once slices exist, the brain figure appears on the stage and the **slice slider
beneath it** is populated (the label next to the slider shows the slice index
and its mm coordinate).

---

## Step 3 — Region scores

Loads your QUINT output and computes per-region metrics.

1. **QUINT data folder** — folder containing the `*_RefAtlasRegions.csv` files
   (one per animal). Use **Browse** to pick it with a native folder dialog.
2. **Separator** — column separator for those CSVs. Leave as `auto` to detect
   it, or set it explicitly (e.g. `,` or `;`).
3. **Metadata CSV** — path to a metadata table (one row per animal). **This is
   required to compute scores.** Use **Browse** to select the file.
4. **Separator** (metadata) — defaults to `;`.
5. **Grouping** (collapsed by default) — how animals are grouped and how the
   relative-abundance reference is defined:
   - **Animal column** — metadata column identifying each animal (default
     `animal`).
   - **Group column(s)** — metadata column(s) to group by (default `group`;
     comma-separate for multiple).
   - **Rel. abundance method** — *Within* or *Reference*. Details are covered in
      [Understanding Scores](score_definitions.md).
   - **Reference mode** — *Pooled* or *Group*. Details are covered in
      [Understanding Scores](score_definitions.md).
   - **Reference group (if mode = group)** — which group is the reference.
6. Click **Compute scores**. This computes **relative abundance**, **frequency**
   and **density** for every region, per group. A progress bar reports status.
7. **Save CSV** (optional) — downloads `region_scores.csv` (all groups
   concatenated with a `group_label` column) for reloading later.

> **The "Compute scores" button stays disabled until all three are true:**
> slices have been built/loaded, the QUINT folder is valid, and the metadata
> CSV exists. The folder/metadata fields are debounced, so the button enables a
> moment after you stop typing.

---

## The view

Once geometry **and** scores are present, the brain is colored region-by-region.

- **Slice slider** (under the figure) — drag to move through slices, or step
  with the **‹ ›** buttons; the label beside it shows the slice index, mm
  coordinate, and position (e.g. `3/12`).
- **Score** — choose *Rel. abundance*, *Frequency*, or *Density*. Switching it
  resets the color range to that score's sensible default.
  Details are covered in [Understanding Scores](score_definitions.md).
- **Group** — choose which group's scores to display. When multiple groups
  exist, two extra entries are added automatically: `All (mean)` (the per-region
  mean across groups) and `Side by side`, which draws every group as its own
  panel on one shared color range. Zooming or panning one panel moves them all,
  the regions table gets one value column per group, and exports keep the
  panels.
- **Color legend** (top right of the stage) — shows the active colorscale and
  its range. Click it for the color settings:
  - **Colorscale**, **Min / Max** — the colormap and its range (blank = auto).
  - **Flat color for selected regions** — fill a highlighted subset with one
    solid color.
- **Regions panel** — lists the regions on the current slice, highest value
  first, each with a swatch of its current color, its ID, name and value (one
  value column per group in side-by-side mode). The filter box narrows the list
  by name or ID, and the checkboxes control which regions stay colored on the
  brain (**Clear** unticks all). The panel button in the top bar hides it to give
  the figure the full width.

Row selection, flat color, and the table filter are covered in detail in
[Filtering & coloring rendered slices](filtering_and_coloring.md).

---

## Exporting figures

Click **Export** in the top bar:

1. **Output folder** — where files are written (**Browse** opens a folder
   dialog). Defaults to the current directory (`.`).
2. **File name** — base name (default `brain_slice`).
3. **Format** — `SVG`, `PNG`, `PDF`, or `HTML`.
4. **This slice** — saves the slice you're viewing.
   **All slices** — saves every slice; each filename gets the slice's
   coordinate appended (e.g. `brain_slice_AP_+1.50mm.svg`), using the axis for
   the current orientation (AP/ML/DV). A progress bar tracks the batch.

Exports reproduce the **current view**: the row selection and flat color carry
into the exported figure (for both current-slice and all-slices exports). The
table's text filter is browse-only and does not affect coloring, so it does not
change the export. See
[Filtering & coloring rendered slices](filtering_and_coloring.md).

---

## Two typical workflows

**Fresh run**
1. Step 1 → Load atlas at your resolution.
2. Step 2 → set orientation + mm range → Build slices (Save GeoJSON if you want
   to reuse them).
3. Step 3 → point at your QUINT folder + metadata → Compute scores (Save CSV if
   you want to reuse them).
4. Close the dialog, explore, and export figures.

**Resume from saved files**
1. Step 1 → "Saved files" → load your `brain_slices.geojson` and
   `region_scores.csv`.
2. Explore and export — no atlas processing needed.

---

## Notifications & inline status

The app reports what's happening in two complementary ways:

- **Toasts** — pop-up notifications at the **top-center** of the window, with a
  colored border (and a matching icon, so the type reads without relying on
  color alone):
  - **green** — success (e.g. an export finished)
  - **teal** — information
  - **yellow** — warning (e.g. a missing folder or an empty slice range)
  - **red** — error (something failed)

  Error toasts are **sticky** — they stay until you dismiss them with the × —
  while the others fade on their own; any toast can be closed early. Toasts are
  reserved for the things you might otherwise miss: errors, warnings, and
  "invisible" successes such as a completed export or a cleared cache.
- **Inline status text** — each Data setup step shows a short status line next
  to its buttons (e.g. the loaded volume shape, or `Built 12 slice(s).`). It
  turns **green** on success and **red** on failure, so a step's result is
  visible in place without watching for a toast.

---

## Clearing the session (reset)

**Clear session**, at the bottom of the Data setup step list, wipes the current
session: it deletes the session's cached data from disk and resets the
in-browser state — the figure and slider, all of the stores, every step's
buttons and progress bars, and the input fields — back to a clean slate (an info
toast confirms `Cache cleared.`). Use it to start over without restarting the
app.

It only clears the working session; it does **not** delete any files you already
exported or saved (`brain_slices.geojson`, `region_scores.csv`, exported
figures).

---

## Light / dark theme

The toggle in the top bar switches the whole app between the light and dark
themes. It only changes appearance, not data or exports.
