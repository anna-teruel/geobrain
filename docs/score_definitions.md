# Understanding Scores

GeoBrain computes region-level scores from QUINT `*_RefAtlasRegions.csv` exports. These scores summarize the distribution of detected objects across brain regions and can be visualized as choropleth maps.

## Overview

Three scores are currently available:

| Score              | Description                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| Relative abundance | Measures whether a region contains more or fewer objects than expected relative to the overall atlas distribution. |
| Frequency          | Measures how consistently a signal is observed across animals.                                                     |
| Density            | Measures how concentrated objects are within a region.                                                             |

---

## 1. Relative Abundance

Relative abundance measures whether a brain region contains more or fewer detected objects than expected compared to the overall distribution of objects across the brain.

For each region, GeoBrain first computes the total number of detected objects across animals. These region totals are then normalized and expressed as z-scores, allowing regions with unusually high or low object counts to be identified.

---

### Normalization Methods

Relative abundance can be computed using different normalization strategies depending on the goal of the analysis. GeoBrain currently supports two approaches:
- **Within normalization**: regions are compared to other regions within the same dataset or cohort.
- **Reference normalization**: regions are compared to a shared reference distribution, allowing more direct comparisons across cohorts.

### 1.1 Within Mode

In **within** mode, z-scores are computed using only the dataset currently being analyzed.

This means that:

* Scores highlight regions that are enriched or depleted relative to other regions within the same cohort.
* Values are **not directly comparable across cohorts** because each cohort uses its own mean and standard deviation.

This mode is useful when the goal is to identify the most enriched regions within a single experimental group.


### 1.2 Reference Mode

In **reference** mode, z-scores are computed using a shared reference distribution.

Instead of calculating the mean and standard deviation from the current dataset, these statistics are obtained from a reference population.

This allows scores from multiple cohorts to be compared using the same normalization.

#### 1.2.1 Pooled Reference

Reference statistics are computed using all available animals.

This approach provides a common normalization across the entire dataset, with different groups.

#### 1.2.2 Group Reference

Reference statistics are computed from a specific reference group, such as a control cohort.

For example:

* Control animals may be used to compute the reference mean and standard deviation.
* Experimental animals are then scored relative to the control distribution.

This makes it easier to identify regions that are enriched or depleted relative to a baseline population.

---

## 2. Frequency

Frequency measures how consistently a signal is observed across animals.

For each region, GeoBrain calculates the fraction of animals with at least one detected object.

### Formula

```text
frequency = animals_with_objects / total_animals
```

### Example

If 7 out of 10 animals contain at least one object in a region:

```text
frequency = 7 / 10 = 0.7
```

### Interpretation

* `1.0` → present in all animals.
* `0.5` → present in half of the animals.
* `0.0` → absent from all animals.

Frequency is independent of object count. A region with a single object in every animal can have the same frequency as a region containing many objects in every animal.

---

## Density

Density measures the concentration of objects within a region.

It is computed for each animal as its object count divided by its region area, then averaged across animals. Every animal counts equally, so groups of different sizes stay comparable. Animals with a zero or missing area for a region are left out of that region's average.

### Formula

```text
density = mean over animals of (objects / region_area)
```

### Interpretation

* Higher values indicate objects are concentrated within a region.
* Lower values indicate objects are more sparsely distributed.

Density is useful when comparing regions of different sizes because it accounts for region area.

A large region and a small region may contain the same number of objects, but the smaller region will have a higher density if those objects occupy less space.

---

## Choosing a Score

The most appropriate score depends on the biological question being asked.

| Goal                                                | Recommended score              |
| --------------------------------------------------- | ------------------------------ |
| Identify enriched brain regions within a cohort     | Relative abundance (within)    |
| Compare cohorts using a common reference population | Relative abundance (reference) |
| Measure consistency across animals                  | Frequency                      |
| Measure concentration of signal within a region     | Density                        |

In many analyses, these scores provide complementary information and are best interpreted together.
