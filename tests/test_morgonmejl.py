"""The morning mail mirrors, never advises, and says first when the watch has not synced."""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from selvra_analysis.morgonmejl import STAGE2_DAYS, compose

TODAY = date(2026, 10, 28)


def days(n: int, last: date, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = [{"reading_date": last - timedelta(days=i), "steps": float(rng.integers(2000, 6000)),
             "total_sleep_seconds": float(rng.integers(5 * 3600, 8 * 3600)),
             "hr_lowest_bpm": float(rng.integers(42, 48)), "hrv_avg_ms": float(rng.integers(25, 45))}
            for i in range(n)]
    return pd.DataFrame(rows).sort_values("reading_date").reset_index(drop=True)


def test_first_days_mirror_against_the_average_so_far() -> None:
    subject, body = compose("Kari", days(5, TODAY), TODAY)
    assert "Garmin räknade" in body
    assert "Hittills brukar det vara" in body
    assert "inte synkat" not in body
    assert "inte synkat" not in subject
    assert f"Vid {STAGE2_DAYS} dagar" in body


def test_after_two_weeks_the_persons_own_range_is_used() -> None:
    df = days(30, TODAY)
    df.loc[df["reading_date"] == TODAY - timedelta(days=1), "steps"] = 20000.0  # avvikelse i går
    _, body = compose("Kari", df, TODAY)
    assert re.search(r"(över|under) ditt vanliga", body)   # essens visar bara avvikelser


def test_a_watch_that_has_not_synced_is_said_first() -> None:
    subject, body = compose("Kari", days(20, TODAY - timedelta(days=6)), TODAY)
    assert "inte synkat sedan 22/10" in body.splitlines()[2]
    assert "klockan har inte synkat" in subject


def test_never_advice() -> None:
    _, body = compose("Kari", days(30, TODAY), TODAY)
    assert not re.search(r"\b(borde|bör|försök|rekommender|ska du)\b", body, re.IGNORECASE)


def test_a_long_sync_gap_does_not_empty_the_baseline() -> None:
    """Weeks without sync, then two days: the baseline is the last days with data, not the calendar."""
    df = pd.concat([days(28, date(2026, 8, 30), seed=3), days(2, TODAY, seed=4)]).reset_index(drop=True)
    df.loc[df["reading_date"] == TODAY - timedelta(days=1), "hr_lowest_bpm"] = 60.0  # avvikelse (ett tal) → bandet visas
    _, body = compose("Kari", df, TODAY)
    ranges = re.findall(r"ditt vanliga (\d+)–(\d+)", body)
    assert ranges
    assert all(lo != hi for lo, hi in ranges)
