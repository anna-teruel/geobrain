"""Tests for scale_cartesian_to_lonlat (pixel space -> pseudo lon/lat)."""

import math

import pytest

from geobrain.build_geoJSON import scale_cartesian_to_lonlat


def _fc(coords):
	return {
		"type": "FeatureCollection",
		"features": [
			{
				"type": "Feature",
				"properties": {"feature_id": "x"},
				"geometry": {"type": "MultiPolygon", "coordinates": [[coords]]},
			}
		],
	}


def test_scale_keep_aspect_false_maps_extremes_to_range_corners():
	# Square spanning x in [0,10], y in [0,10], stretched to fill both ranges.
	square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
	out = scale_cartesian_to_lonlat(
		_fc(square), lon_range=(-15.0, 15.0), lat_range=(-10.0, 10.0), keep_aspect=False
	)

	pts = out["features"][0]["geometry"]["coordinates"][0][0]
	lons = [p[0] for p in pts]
	lats = [p[1] for p in pts]

	assert min(lons) == pytest.approx(-15.0)
	assert max(lons) == pytest.approx(15.0)
	assert min(lats) == pytest.approx(-10.0)
	assert max(lats) == pytest.approx(10.0)


def test_scale_inverts_y_axis():
	# Pixel y increases downward; latitude increases upward, so the
	# smallest pixel-y must map to the largest latitude.
	square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
	out = scale_cartesian_to_lonlat(_fc(square), lon_range=(-15.0, 15.0), lat_range=(-10.0, 10.0))
	pts = out["features"][0]["geometry"]["coordinates"][0][0]

	# First vertex had pixel-y 0 (top) -> max latitude.
	assert pts[0][1] == pytest.approx(10.0)
	# Third vertex had pixel-y 10 (bottom) -> min latitude.
	assert pts[2][1] == pytest.approx(-10.0)


def test_scale_returns_same_object_mutated_in_place():
	square = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
	fc = _fc(square)
	out = scale_cartesian_to_lonlat(fc)
	assert out is fc


def test_scale_handles_degenerate_extent():
	# All vertices share the same y (a horizontal sliver) -> ymax == ymin.
	# The min-max scaling must not divide by zero and emit NaN/inf.
	sliver = [[0.0, 5.0], [10.0, 5.0], [10.0, 5.0], [0.0, 5.0], [0.0, 5.0]]
	out = scale_cartesian_to_lonlat(_fc(sliver), lon_range=(-15.0, 15.0), lat_range=(-10.0, 10.0))
	pts = out["features"][0]["geometry"]["coordinates"][0][0]
	assert all(math.isfinite(p[0]) and math.isfinite(p[1]) for p in pts)


def test_scale_rejects_non_multipolygon():
	fc = {
		"type": "FeatureCollection",
		"features": [
			{
				"type": "Feature",
				"properties": {},
				"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
			}
		],
	}
	with pytest.raises(ValueError):
		scale_cartesian_to_lonlat(fc)


def test_scale_keep_aspect_preserves_proportions_and_centres():
	# A square in a 30x20 box: one scale factor for both axes, so it fills
	# the tighter lat range and stays square, centred in lon.
	square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
	out = scale_cartesian_to_lonlat(_fc(square), lon_range=(-15.0, 15.0), lat_range=(-10.0, 10.0))
	pts = out["features"][0]["geometry"]["coordinates"][0][0]
	lons = [p[0] for p in pts]
	lats = [p[1] for p in pts]
	assert (min(lons), max(lons)) == (pytest.approx(-10.0), pytest.approx(10.0))
	assert (min(lats), max(lats)) == (pytest.approx(-10.0), pytest.approx(10.0))


def test_scale_keep_aspect_tall_shape_fits_lat_range():
	# 5 wide x 20 tall into 30x20: limited by lat, so width becomes 5 deg.
	tall = [[0.0, 0.0], [5.0, 0.0], [5.0, 20.0], [0.0, 20.0], [0.0, 0.0]]
	out = scale_cartesian_to_lonlat(_fc(tall), lon_range=(-15.0, 15.0), lat_range=(-10.0, 10.0))
	pts = out["features"][0]["geometry"]["coordinates"][0][0]
	lons = [p[0] for p in pts]
	assert (min(lons), max(lons)) == (pytest.approx(-2.5), pytest.approx(2.5))
