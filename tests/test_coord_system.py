"""Tests for coordinate <-> slice-index conversions and range generation."""

import pytest

from geobrain.coord_system import (
	_require_mouse,
	get_ccf_config,
	coord_mm_to_slice_index,
	slice_index_to_coordinate_mm,
	range_mm_to_slice_indices,
)


def test_get_ccf_config_bregma_indices():
	cfg = get_ccf_config(25)
	assert cfg.resolution_um == 25
	assert cfg.bregma_ml_index == 216  # round(5400 / 25)
	assert cfg.bregma_dv_index == 18  # round(450 / 25)
	assert cfg.bregma_ap_index == 228  # round(5700 / 25)


@pytest.mark.parametrize(
	"resolution, expected_ap",
	[(10, 570), (25, 228), (50, 114), (100, 57)],
)
def test_get_ccf_config_scales_with_resolution(resolution, expected_ap):
	assert get_ccf_config(resolution).bregma_ap_index == expected_ap


def test_coord_mm_to_slice_index_doc_example():
	# AP = -2.0 mm at 25 um -> coronal slice index 308 (see docstring example).
	assert coord_mm_to_slice_index(-2.0, orientation="coronal", resolution_um=25) == 308


def test_coord_mm_to_slice_index_bregma_is_zero_offset():
	cfg = get_ccf_config(25)
	assert coord_mm_to_slice_index(0.0, "coronal", 25) == cfg.bregma_ap_index
	assert coord_mm_to_slice_index(0.0, "sagittal", 25) == cfg.bregma_ml_index
	assert coord_mm_to_slice_index(0.0, "horizontal", 25) == cfg.bregma_dv_index


def test_coord_mm_to_slice_index_unknown_orientation():
	with pytest.raises(ValueError):
		coord_mm_to_slice_index(0.0, orientation="oblique", resolution_um=25)


@pytest.mark.parametrize("orientation", ["coronal", "sagittal", "horizontal"])
@pytest.mark.parametrize("coord_mm", [-3.0, -1.5, 0.0, 2.4])
def test_coord_index_roundtrip(orientation, coord_mm):
	idx = coord_mm_to_slice_index(coord_mm, orientation, 25)
	back = slice_index_to_coordinate_mm(idx, orientation, 25)
	# Round-trip is exact up to the voxel quantization (resolution / 1000 mm).
	assert back == pytest.approx(coord_mm, abs=25 / 1000.0)


def test_slice_index_to_coordinate_unknown_orientation():
	with pytest.raises(ValueError):
		slice_index_to_coordinate_mm(100, orientation="oblique", resolution_um=25)


def test_range_from_coords_list_sorted_and_unique():
	# Duplicate coordinates collapse; result is sorted ascending.
	out = range_mm_to_slice_indices(coords_mm=[2.0, -2.0, 2.0], resolution_um=25)
	expected = sorted({coord_mm_to_slice_index(c, "coronal", 25) for c in [2.0, -2.0]})
	assert out == expected


def test_range_interval_no_step_returns_contiguous():
	out = range_mm_to_slice_indices(start_mm=-3.0, end_mm=-2.0, resolution_um=25)
	i0 = coord_mm_to_slice_index(-3.0, "coronal", 25)
	i1 = coord_mm_to_slice_index(-2.0, "coronal", 25)
	lo, hi = sorted((i0, i1))
	assert out == list(range(lo, hi + 1))
	# Contiguous: every consecutive pair differs by 1.
	assert all(b - a == 1 for a, b in zip(out, out[1:]))


def test_range_interval_with_step_samples_and_dedupes():
	out = range_mm_to_slice_indices(start_mm=-3.0, end_mm=-1.0, step_mm=0.5, resolution_um=25)
	assert out == sorted(set(out))
	assert len(out) >= 2


def test_range_requires_coords_or_bounds():
	with pytest.raises(ValueError):
		range_mm_to_slice_indices()
	with pytest.raises(ValueError):
		range_mm_to_slice_indices(start_mm=-2.0)  # missing end_mm


def test_range_step_must_be_positive():
	with pytest.raises(ValueError):
		range_mm_to_slice_indices(start_mm=-3.0, end_mm=-1.0, step_mm=0.0)
	with pytest.raises(ValueError):
		range_mm_to_slice_indices(start_mm=-3.0, end_mm=-1.0, step_mm=-0.5)


def test_range_step_does_not_overshoot_end():
	# A step that does not evenly divide the interval must not sample a
	# coordinate beyond end_mm (np.arange(..., hi + step, step) overshoots).
	out = range_mm_to_slice_indices(start_mm=-3.0, end_mm=-1.0, step_mm=0.7, resolution_um=25)
	i0 = coord_mm_to_slice_index(-3.0, "coronal", 25)
	i1 = coord_mm_to_slice_index(-1.0, "coronal", 25)
	lo, hi = sorted((i0, i1))
	assert min(out) >= lo
	assert max(out) <= hi


@pytest.mark.parametrize("orientation", ["sagittal", "horizontal"])
def test_range_interval_other_orientations(orientation):
	out = range_mm_to_slice_indices(
		start_mm=-1.0,
		end_mm=1.0,
		orientation=orientation,
		resolution_um=25,
	)

	assert len(out) > 0
	assert out == sorted(out)


# --- species guard (bregma is mouse-only, see issue #40 discussion) ---------


@pytest.mark.parametrize("species", ["human", "Mouse "])  # real species, and no whitespace trimming
def test_require_mouse_rejects_non_mouse(species):
	with pytest.raises(ValueError):
		_require_mouse(species)


def test_require_mouse_accepts_case_insensitive_mouse():
	_require_mouse("mouse")
	_require_mouse("MOUSE")


@pytest.mark.parametrize(
	"func, kwargs",
	[
		(get_ccf_config, dict(resolution_um=25)),
		(coord_mm_to_slice_index, dict(coord_mm=-2.0, resolution_um=25)),
		(slice_index_to_coordinate_mm, dict(slice_index=308, resolution_um=25)),
		(range_mm_to_slice_indices, dict(coords_mm=[0.0], resolution_um=25)),
	],
)
def test_species_guard_propagates_to_public_api(func, kwargs):
	# Each public function must forward species= to get_ccf_config() rather
	# than silently defaulting to "mouse" internally.
	with pytest.raises(ValueError):
		func(species="human", **kwargs)
