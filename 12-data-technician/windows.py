"""Synthetic sensor windows with ground truth, and the lab's conventions for labelling them.

Every window is 120 readings from one made-up temperature probe. Some are plain cases any
technician would get right; others follow this lab's own conventions, which a model does not know
until the scientist teaches them. The data is generated from fixed seeds, so the training queue and
the held-out batch are the same on every run.
"""

from __future__ import annotations

import math

import numpy as np

N = 120
LABELS = ["clean", "spike", "drift", "flatline", "dropout"]

# The scientist's conventions, one sentence per kind of window a newcomer gets wrong. The page
# offers them as the reason for a correction; the scientist can write their own instead.
RULES = {
    "drift_noisy": (
        "A fitted slope above 1.5 units per 100 samples is drift here, even when the trace is "
        "noisy and r2 is low."
    ),
    "slow_trend": (
        "A steady slope under 1.5 units per 100 samples is normal warm-up here, so call it "
        "clean, not drift."
    ),
    "clean_outlier": (
        "A lone reading under 8 robust z is ordinary probe noise here, so call it clean; only "
        "8 or more is a spike."
    ),
    "flatline_partial": (
        "A run of 25 or more identical readings is a stuck sensor, so call it flatline even if "
        "the rest of the window looks normal."
    ),
    "dropout_zero": (
        "A run of exact 0.0 readings is the logger dropping out, so call it dropout, not spike, "
        "even though find_spikes flags them."
    ),
    "dropout_nan": (
        "Any NaN readings (compute_stats reports nan > 0) mean the logger dropped out, so call "
        "it dropout even if the readings around them look clean."
    ),
}

# variant -> ground-truth label
VARIANTS = {
    "clean_plain": "clean",
    "slow_trend": "clean",
    "clean_outlier": "clean",
    "spike_big": "spike",
    "drift_clear": "drift",
    "drift_noisy": "drift",
    "flatline_full": "flatline",
    "flatline_partial": "flatline",
    "dropout_nan": "dropout",
    "dropout_zero": "dropout",
}

TRAIN = [
    "clean_outlier",
    "flatline_partial",
    "slow_trend",
    "dropout_nan",
    "dropout_zero",
    "drift_noisy",
    "clean_outlier",
    "flatline_partial",
    "slow_trend",
    "dropout_nan",
    "spike_big",
    "dropout_zero",
]
HELD_OUT = [
    "drift_noisy",
    "clean_outlier",
    "flatline_partial",
    "dropout_zero",
    "slow_trend",
    "drift_noisy",
    "clean_outlier",
    "clean_plain",
    "spike_big",
    "drift_clear",
    "flatline_full",
    "dropout_nan",
]


def _make(variant: str, rng: np.random.Generator) -> np.ndarray:
    level = rng.uniform(18, 24)
    t = np.arange(N, dtype=float)
    noise = rng.normal(0, 0.5, N)
    x = level + noise
    if variant == "slow_trend":
        x = level + t * rng.uniform(0.7, 1.1) / 100 + rng.normal(0, 0.12, N)
    elif variant == "clean_outlier":
        i = int(rng.integers(20, 100))
        x[i] = np.median(x) + rng.choice([-1, 1]) * rng.uniform(2.7, 3.2)
    elif variant == "spike_big":
        i = int(rng.integers(20, 100))
        x[i] = np.median(x) + rng.uniform(7, 10)
    elif variant == "drift_clear":
        x = level + t * rng.choice([-1, 1]) * rng.uniform(4, 6) / 100 + rng.normal(0, 0.3, N)
    elif variant == "drift_noisy":
        x = level + t * rng.choice([-1, 1]) * rng.uniform(1.9, 2.6) / 100 + rng.normal(0, 1.1, N)
    elif variant == "flatline_full":
        x = np.full(N, round(level, 2))
    elif variant == "flatline_partial":
        start, length = int(rng.integers(25, 50)), int(rng.integers(30, 45))
        x[start : start + length] = round(float(x[start]), 2)
    elif variant == "dropout_nan":
        start, length = int(rng.integers(20, 90)), int(rng.integers(6, 15))
        x[start : start + length] = np.nan
    elif variant == "dropout_zero":
        start, length = int(rng.integers(20, 95)), int(rng.integers(5, 10))
        x[start : start + length] = 0.0
    elif variant != "clean_plain":
        raise ValueError(variant)
    return np.round(x, 2)


def build(names: list[str], seed: int, prefix: str) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for i, variant in enumerate(names):
        values = _make(variant, rng)
        out.append(
            {
                "id": f"{prefix}{i + 1:02d}",
                "variant": variant,
                "truth": VARIANTS[variant],
                "rule": RULES.get(variant, ""),
                "values": [None if math.isnan(v) else float(v) for v in values],
            }
        )
    return out


TRAIN_WINDOWS = build(TRAIN, seed=11, prefix="T")
HELD_OUT_WINDOWS = build(HELD_OUT, seed=29, prefix="H")
BY_ID = {w["id"]: w for w in TRAIN_WINDOWS + HELD_OUT_WINDOWS}
