"""Unit tests for the motion classifier's pure logic.

These tests exercise `_classify` directly with synthetic feature vectors —
no Resolve, no ffmpeg, no real video file required. Run with:

    pytest tests/test_motion.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.motion import _classify


WIDTH = 640


def features(mean_dx=0.0, mean_dy=0.0, divergence=0.0, curl=0.0, rms=0.0):
    """Build one synthetic feature dict — values are in raw flow units (pixels/step)."""
    return {
        "mean_dx": mean_dx,
        "mean_dy": mean_dy,
        "divergence": divergence,
        "curl": curl,
        "rms": rms,
    }


# Feature values are in raw flow units; the classifier divides by width/100,
# so to get a normalized "1.0" we multiply by width/100 = 6.4.
def n(value):
    return value * (WIDTH / 100.0)


# --- Static detection -------------------------------------------------------

def test_static_low_rms():
    feats = [features(rms=n(0.1))]
    out = _classify(feats, WIDTH)
    assert out["classification"] == "static"
    assert out["components"] == []


def test_static_threshold_boundary():
    # rms just below 0.3 -> static; just above -> not static
    just_below = [features(rms=n(0.29))]
    just_above = [features(rms=n(0.31), mean_dx=n(0.5))]
    assert _classify(just_below, WIDTH)["classification"] == "static"
    assert _classify(just_above, WIDTH)["classification"] != "static"


# --- Push-in / pull-out -----------------------------------------------------

def test_push_in_dominant():
    # Negative divergence -> push-in. Big enough to clear DIV_MIN (0.05).
    feats = [features(divergence=n(-0.2), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert out["classification"].startswith("push-in")


def test_pull_out_dominant():
    feats = [features(divergence=n(0.2), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert out["classification"].startswith("pull-out")


# --- Pan / truck horizontal -------------------------------------------------

def test_pan_truck_right():
    # Negative dx in image flow = scene moves left = camera moves right
    feats = [features(mean_dx=n(-0.4), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "pan/truck-R" in out["classification"]


def test_pan_truck_left():
    feats = [features(mean_dx=n(0.4), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "pan/truck-L" in out["classification"]


# --- Tilt / pedestal vertical ----------------------------------------------

def test_tilt_up():
    # Positive dy -> objects move down -> camera tilts up
    feats = [features(mean_dy=n(0.4), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "tilt-U" in out["classification"] or "pedestal-U" in out["classification"]


def test_tilt_down():
    feats = [features(mean_dy=n(-0.4), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "tilt-D" in out["classification"] or "pedestal-D" in out["classification"]


# --- Curl handling: the noisy roll component -------------------------------

def test_curl_alone_above_threshold():
    # Curl present, divergence near zero -> curl trusted
    feats = [features(curl=n(0.2), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "roll" in out["classification"]


def test_curl_suppressed_when_divergence_dominates():
    # |curl| < |divergence|: curl is treated as a distortion artifact
    feats = [features(divergence=n(-0.3), curl=n(0.15), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "roll" not in out["classification"]
    assert "push-in" in out["classification"]


def test_curl_below_threshold_dropped():
    # Curl below CURL_MIN (0.12) but rms still triggers motion -> no roll
    feats = [features(curl=n(0.05), mean_dx=n(0.3), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "roll" not in out["classification"]


# --- Combined components ---------------------------------------------------

def test_push_in_with_pan():
    feats = [features(divergence=n(-0.2), mean_dx=n(-0.3), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "push-in" in out["classification"]
    assert "pan/truck-R" in out["classification"]


def test_components_sorted_by_weight():
    # Larger-magnitude push should appear before smaller-magnitude pan
    feats = [features(divergence=n(-0.3), mean_dx=n(-0.16), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    labels = [c["label"] for c in out["components"]]
    assert labels[0] == "push-in"


# --- Subtle motion ---------------------------------------------------------

def test_subtle_motion_above_static_below_components():
    # rms just above static threshold but no individual component crosses its bar
    feats = [features(rms=n(0.4), divergence=n(0.04), curl=n(0.03),
                      mean_dx=n(0.1), mean_dy=n(0.1))]
    out = _classify(feats, WIDTH)
    assert out["classification"] == "subtle / mixed"


# --- Stability across multiple feature samples -----------------------------

def test_averages_across_samples():
    # Two samples, opposite sign on dx -> should cancel to roughly zero
    feats = [
        features(mean_dx=n(0.4), rms=n(2.0)),
        features(mean_dx=n(-0.4), rms=n(2.0)),
    ]
    out = _classify(feats, WIDTH)
    # No translation should pass threshold after averaging
    assert "pan/truck" not in out["classification"]


# --- Output shape ----------------------------------------------------------

def test_output_shape():
    feats = [features(divergence=n(-0.2), rms=n(2.0))]
    out = _classify(feats, WIDTH)
    assert "classification" in out
    assert "components" in out
    assert "normalized" in out
    assert set(out["normalized"]) == {"dx", "dy", "divergence", "curl", "rms"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
