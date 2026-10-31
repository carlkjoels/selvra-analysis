"""Scanner: hitta mönster i data och föreslå studier.

Skannar mart_analysis_days efter avvikelser, kluster och händelsekorrelationer.
Föreslår studiefrågor utan att avslöja effektstorlekar (det är studiens jobb).

Usage:
    uv run python -m selvra_analysis.scanner
    make skanna
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from selvra_analysis.dreamer import lagg_till_hypoteser

DB_DEFAULT = Path("data/selvra.duckdb")
MIN_DAYS_FOR_BASELINE = 14
MIN_EVENTS_FOR_CORRELATION = 3
MIN_SLEEP_DAYS = 14


@dataclass
class Pattern:
    typ: str          # avvikelse | korrelation | kluster | trend
    beskrivning: str
    fragor: list[str]
    vikt: int         # 1-3, hur intressant


def _load(db_path: Path) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute("SELECT * FROM marts.mart_analysis_days ORDER BY reading_date").df()


def _baseline_avvikelser(df: pd.DataFrame) -> list[Pattern]:
    valid = df[df["is_valid_day"] == True].copy()
    if len(valid) < MIN_DAYS_FOR_BASELINE:
        return []

    mean_tir = valid["tir_pct"].mean()
    sd_tir = valid["tir_pct"].std()
    threshold_low = mean_tir - 1.5 * sd_tir
    threshold_high = mean_tir + 1.5 * sd_tir

    bad = valid[valid["tir_pct"] < threshold_low]
    good = valid[valid["tir_pct"] > threshold_high]
    patterns = []

    if len(bad) >= 3:
        bad_no_event = bad[bad["n_events"] == 0]
        pct = len(bad_no_event) / len(bad) * 100
        patterns.append(Pattern(
            typ="avvikelse",
            beskrivning=(
                f"{len(bad)} dagar med TIR markant under din baseline ({mean_tir:.0f}%). "
                f"{len(bad_no_event)} av dem ({pct:.0f}%) saknar loggad händelse — "
                "okänd faktor påverkar kontrollen."
            ),
            fragor=[
                "Finns det ett mönster i veckodag för de sämsta dagarna?",
                "Föregås dåliga dagar konsekvent av en viss händelsetyp?",
            ],
            vikt=2,
        ))

    if len(good) >= 3:
        patterns.append(Pattern(
            typ="avvikelse",
            beskrivning=(
                f"{len(good)} dagar med TIR markant över din baseline. "
                "Vad är annorlunda de dagarna?"
            ),
            fragor=["Vad skiljer dina bästa dagar från resten?"],
            vikt=1,
        ))

    return patterns


def _event_korrelationer(df: pd.DataFrame) -> list[Pattern]:
    valid = df[df["is_valid_day"] == True].copy()
    if len(valid) < MIN_DAYS_FOR_BASELINE:
        return []

    event_cols = {
        "had_training": "traning",
        "had_stress": "stress",
        "is_ill": "sjukdom",
        "had_alcohol": "alkohol",
        "is_travelling": "resa",
        "had_medication_change": "medicinandring",
        "high_steps": "höga steg (≥10 000)",
    }
    patterns = []
    baseline_tir = valid["tir_pct"].mean()

    for col, namn in event_cols.items():
        if col not in valid.columns:
            continue  # databas byggd före kolumnen; nästa make build lägger till den
        exposed = valid[valid[col] == True]["tir_pct"]
        if len(exposed) < MIN_EVENTS_FOR_CORRELATION:
            continue
        diff = _within_daytype_diff(valid, col)
        if diff is None:
            patterns.append(_follows_daytype(namn, len(exposed)))
            continue
        patterns.append(Pattern(
            typ="korrelation",
            beskrivning=(
                f"{namn.capitalize()}: {len(exposed)} dagar. "
                f"TIR skiljer sig från övriga dagar av samma typ, vardag mot vardag och helg mot helg "
                f"(baseline {baseline_tir:.0f}%). Sambandets riktning och storlek kräver en studie för att avgöra."
            ),
            fragor=[
                f"Påverkar {namn} mitt TIR samma dag?",
                f"Påverkar {namn} mitt TIR dagen efter?",
                f"Påverkar {namn} medelglukos natten efter (00:00–06:00)?",
            ],
            vikt=3 if abs(diff) > 5 else 2,
        ))

    return patterns


def _within_daytype_diff(valid: pd.DataFrame, col: str) -> float | None:
    """Exposed minus unexposed TIR inside weekdays and inside weekends, weighted by exposed days.

    Comparing exposed days with all other days mixes in the day type whenever the exposure
    follows it (10,000 steps on work days, few on days off). None when no day type has both.
    """
    weekend = pd.to_datetime(valid["reading_date"]).dt.day_of_week >= 5
    diffs, weights = [], []
    for stratum in (valid[~weekend], valid[weekend]):
        exp = stratum.loc[stratum[col] == True, "tir_pct"]
        ctl = stratum.loc[stratum[col] == False, "tir_pct"]
        if len(exp) >= MIN_EVENTS_FOR_CORRELATION and len(ctl) >= MIN_EVENTS_FOR_CORRELATION:
            diffs.append(exp.mean() - ctl.mean())
            weights.append(len(exp))
    if not diffs:
        return None
    return float(np.average(diffs, weights=weights))


def _follows_daytype(namn: str, n: int) -> Pattern:
    return Pattern(
        typ="korrelation",
        beskrivning=(
            f"{namn.capitalize()}: {n} dagar, men exponeringen följer dagstypen (vardag/helg) så nära att "
            "den inte går att skilja från den i observationsdata. En jämförelse skulle mäta arbetsdag mot ledig."
        ),
        fragor=[f"Påverkar {namn} mitt TIR på dagar av samma typ, lottat i ett n-of-1-försök?"],
        vikt=1,
    )


def _kluster(df: pd.DataFrame) -> list[Pattern]:
    valid = df[df["is_valid_day"] == True].copy()
    patterns = []

    valid = valid.sort_values("reading_date").reset_index(drop=True)
    valid["bad"] = valid["tir_pct"] < 40

    run_len = 0
    longest = 0
    for _, row in valid.iterrows():
        if row["bad"]:
            run_len += 1
            longest = max(longest, run_len)
        else:
            run_len = 0

    if longest >= 4:
        patterns.append(Pattern(
            typ="kluster",
            beskrivning=(
                f"Längsta sammanhängande period med TIR < 40%: {longest} dagar. "
                "Utdragna perioder med dålig kontroll indikerar ofta en bakomliggande faktor."
            ),
            fragor=[
                "Vad inledde den längsta dåliga perioden?",
                "Är utdragna dåliga perioder kopplade till sjukdom eller stress?",
            ],
            vikt=3,
        ))

    return patterns


def _trend(df: pd.DataFrame) -> list[Pattern]:
    valid = df[df["is_valid_day"] == True].tail(21).copy()
    if len(valid) < 14:
        return []

    x = np.arange(len(valid))
    y = valid["tir_pct"].values
    slope = np.polyfit(x, y, 1)[0]
    slope_per_week = slope * 7

    if abs(slope_per_week) < 2:
        return []

    riktning = "uppåt" if slope_per_week > 0 else "nedåt"
    return [Pattern(
        typ="trend",
        beskrivning=(
            f"TIR rör sig {riktning} de senaste 21 dagarna "
            f"({slope_per_week:+.1f} procentenheter per vecka). "
            + ("Vad driver förbättringen?" if slope_per_week > 0
               else "Vad driver försämringen?")
        ),
        fragor=[
            "Har något förändrats i din rutin de senaste tre veckorna?",
            "Finns det en händelse som sammanfaller med trendbrottet?",
        ],
        vikt=2 if abs(slope_per_week) < 5 else 3,
    )]


def _somn(df: pd.DataFrame) -> list[Pattern]:
    """Oura-sömn mot TIR. Bara om tillräckligt många nätter har data."""
    if "sleep_score" not in df.columns:
        return []
    valid = df[df["is_valid_day"] & df["sleep_score"].notna()].copy()
    if len(valid) < MIN_SLEEP_DAYS:
        return []

    r = valid["sleep_score"].corr(valid["tir_pct"])
    if pd.isna(r) or abs(r) < 0.2:
        return []

    return [Pattern(
        typ="korrelation",
        beskrivning=(
            f"Sömn: {len(valid)} nätter med Oura-data. Sömnkvalitet och TIR samvarierar. "
            "Riktning och storlek kräver en studie för att avgöra."
        ),
        fragor=[
            "Påverkar en natt med dålig sömn mitt TIR dagen efter?",
            "Påverkar kort sömn (under 6 timmar) medelglukos nästa förmiddag?",
        ],
        vikt=3 if abs(r) > 0.4 else 2,
    )]


MIN_WEARABLE_DAGAR = 14


def _vilopuls_trend(df: pd.DataFrame) -> list[Pattern]:
    """Vilopulsens riktning senaste tre veckorna — wearable-motsvarigheten till TIR-trenden."""
    if "hr_lowest_bpm" not in df.columns:
        return []
    v = df[df["hr_lowest_bpm"].notna()].tail(21)
    if len(v) < MIN_WEARABLE_DAGAR:
        return []
    lutning = float(np.polyfit(np.arange(len(v)), v["hr_lowest_bpm"].values, 1)[0]) * 7
    if abs(lutning) < 1.0:
        return []
    riktning = "uppåt" if lutning > 0 else "nedåt"
    return [Pattern(
        typ="trend",
        beskrivning=(f"Vilopulsen rör sig {riktning} de senaste tre veckorna "
                     f"({lutning:+.1f} slag per vecka)."),
        fragor=["Har något förändrats i rutinen de senaste tre veckorna?",
                "Påverkar en promenaddag nattens vilopuls?"],
        vikt=2 if abs(lutning) < 2.5 else 3,
    )]


def _somn_under_normalt(df: pd.DataFrame) -> list[Pattern]:
    """Nätter i följd under personens eget P10 — inte en norm, hans egen baslinje."""
    if "total_sleep_seconds" not in df.columns:
        return []
    v = df[df["total_sleep_seconds"].notna()].copy()
    if len(v) < MIN_WEARABLE_DAGAR:
        return []
    p10 = float(v["total_sleep_seconds"].quantile(0.10))
    svit = 0
    for x in reversed(v["total_sleep_seconds"].tolist()):
        if x < p10:
            svit += 1
        else:
            break
    if svit < 2:
        return []
    return [Pattern(
        typ="kluster",
        beskrivning=(f"{svit} nätter i följd under din egen tionde percentil för sömnlängd "
                     f"({p10 / 3600:.1f} h)."),
        fragor=["Sammanfaller korta nätter med någon händelse dagen före?"],
        vikt=2,
    )]


def _steg_nattpuls(df: pd.DataFrame) -> list[Pattern]:
    """Steg i dag mot nattens vilopuls — frågan som kan bli ett riktigt försök."""
    if "steps" not in df.columns or "hr_lowest_bpm" not in df.columns:
        return []
    v = df[["steps", "hr_lowest_bpm"]].copy()
    v["puls_natten_efter"] = v["hr_lowest_bpm"].shift(-1)
    v = v.dropna()
    if len(v) < MIN_WEARABLE_DAGAR:
        return []
    r = float(v["steps"].corr(v["puls_natten_efter"]))
    if abs(r) < 0.25:
        return []
    return [Pattern(
        typ="korrelation",
        beskrivning=(f"Dagens steg och nattens vilopuls samvarierar över {len(v)} dygn. "
                     "Riktning och storlek kräver ett lottat försök för att avgöra."),
        fragor=["Sänker en dag med minst 8 000 steg nattens vilopuls?"],
        vikt=3 if abs(r) > 0.4 else 2,
    )]


def scan(db_path: Path) -> list[Pattern]:
    df = _load(db_path)
    patterns: list[Pattern] = []
    patterns += _baseline_avvikelser(df)
    patterns += _event_korrelationer(df)
    patterns += _kluster(df)
    patterns += _trend(df)
    patterns += _somn(df)
    patterns += _vilopuls_trend(df)
    patterns += _somn_under_normalt(df)
    patterns += _steg_nattpuls(df)
    return sorted(patterns, key=lambda p: -p.vikt)


def spara_hypoteser(patterns: list[Pattern], studies_dir: Path = Path("studies")) -> int:
    """Skriv skanningens studiefrågor till Dreamer-minnets öppna hypoteser.
    studies_dir är styrbar så tester kan skriva till tmp_path i stället för den
    riktiga studies/minne.yml (conftest-vakten fäller den som rör riktiga filer)."""
    fragor = [f for p in patterns for f in p.fragor]
    return lagg_till_hypoteser(fragor, studies_dir)


def _format(patterns: list[Pattern]) -> str:
    if not patterns:
        return "Inga mönster hittade — för lite data eller jämn kontroll."
    lines = ["# Skanning — mönster i datan", ""]
    for i, p in enumerate(patterns, 1):
        vikt_str = "●" * p.vikt + "○" * (3 - p.vikt)
        lines += [f"## {i}. {p.typ.capitalize()}  {vikt_str}", "", p.beskrivning, ""]
        if p.fragor:
            lines.append("**Möjliga studiefrågor:**")
            for f in p.fragor:
                lines.append(f"- {f}")
        lines.append("")
    lines += [
        "---",
        "Kör `make dreamer fraga=\"...\"` för att designa en studie kring en fråga ovan.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    args = parser.parse_args(argv)

    patterns = scan(args.db)
    print(_format(patterns))

    out = Path("data/rapporter/skanning.md")
    out.parent.mkdir(exist_ok=True)
    out.write_text(_format(patterns) + "\n")
    print(f"\nSparad: {out}", file=sys.stderr)

    nya = spara_hypoteser(patterns)
    if nya:
        print(f"{nya} nya hypoteser i Dreamer-minnet (make minne).", file=sys.stderr)


if __name__ == "__main__":
    main()
