"""The study engine: a study is a file, the engine does the rest.

A study is described in `studies/<id>/studie.yml` (format in studies/README.md).
Its life has four steps, each a command:

    validera  check the file; nothing is written
    las       lock it: checksum of the file, the git commit of the pipeline, and for an
              experiment the randomised schedule (drawn from the OS's random source).
              Refused unless `granska` (design review on your own data) has passed for
              exactly this version of the file.
              Commit the folder afterwards: the commit is the public timestamp.
    status    progress and data quality so far. Never the effect: an experiment is
              analysed once, when it is complete, so no one can stop it when it looks good.
    kor       the single confirmatory analysis, when the study is complete: decision by
              the locked rule, a run record and a report.

    python -m selvra_analysis.study status studies/002-promenad/studie.yml --db data/selvra.duckdb

Designs:
    n1           randomised paired periods (A/B), randomisation test on a local-time window
    observation  days after a logged event vs other days, block bootstrap; on data that
                 already exists it is marked retrospective in every report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from selvra_analysis import n1
from selvra_analysis.provenance import PIPELINE_PATHS, ROOT, _git, data_version
from selvra_analysis.rapport import _fmt, _report, _tillforlitlighet, utfallsenhet  # noqa: F401 — återexport för konsumenter
from selvra_analysis.stats import block_bootstrap_difference, daily_series

WINDOW_METRICS = {"medel": "mean_mmol", "topp": "peak_mmol", "tid_over_10": "tar_pct"}
EVENT_COLUMNS = {
    "alkohol": "had_alcohol", "traning": "had_training", "sjukdom": "is_ill",
    "stress": "had_stress", "resa": "is_travelling", "menstruation": "is_menstruating",
    "medicinandring": "had_medication_change", "arbete": "is_workday",
    # Derived from Oura steps, never logged: null days (no ring data) fall out of both groups.
    "hoga_steg": "high_steps",
}
# Wearable outcomes are valid when the value exists; CGM-derived outcomes require a valid
# CGM day. This is what lets a person without a CGM (wearable-only mode) run studies.
WEARABLE_UTFALL = {"sleep_score", "readiness_score", "hrv_avg_ms", "hr_lowest_bpm",
                   "total_sleep_seconds", "deep_sleep_seconds", "rem_sleep_seconds",
                   "sleep_efficiency_pct", "steps", "stress_avg", "stress_max"}


def utfallsgiltig(df: pd.DataFrame, col: str) -> pd.Series:
    """Mask: rows where `col` counts as a valid outcome."""
    if col in WEARABLE_UTFALL:
        return df[col].notna()
    return df["is_valid_day"] == True




REQUIRED_TEXT = ["id", "titel", "fraga", "tes", "motbevis"]
PROTOCOL_HELP = {
    "periodeffekt": "hur tidstrender hanteras (CENT 8a), t.ex. att paren balanserar långsam drift",
    "overforing": "hur eftereffekter hanteras (CENT 3a, 12c), t.ex. tvättdagar och AB mot BA",
    "stoppregel": "när försöket avbryts i förtid (CENT 7b), t.ex. av säkerhetsskäl",
}
# What kind of action the A condition is decides how long its effect can carry over
# (granska checks the spacing of analysed days against it).
ACTION_TYPES = ("traning", "alkohol", "somn", "maltid", "annat")
REVIEW_FILE = "granskning.json"
# Fewest exposed or comparison days an observational study may be run on. With fewer,
# a block bootstrap has too few blocks containing exposed days to say anything.
MIN_DAYS = 10


class StudyError(ValueError):
    pass


@dataclass
class Study:
    path: Path
    spec: dict

    @property
    def folder(self) -> Path:
        return self.path.parent

    @property
    def design(self) -> dict:
        return self.spec["design"]

    @property
    def kind(self) -> str:
        return self.design["typ"]

    @property
    def lock_path(self) -> Path:
        return self.folder / "las.json"

    @property
    def schedule_path(self) -> Path:
        return self.folder / "schema.csv"


# --- Validation -------------------------------------------------------------------------------

def _need(cond: bool, errors: list[str], msg: str) -> None:
    if not cond:
        errors.append(msg)


def load(path: Path) -> Study:
    spec = yaml.safe_load(path.read_text())
    errors = validate(spec)
    if errors:
        raise StudyError(f"{path}:\n  " + "\n  ".join(errors))
    return Study(path, spec)


def validate(spec: dict) -> list[str]:
    """All problems with a study file, in Swedish, or an empty list."""
    if not isinstance(spec, dict):
        return ["filen är inte en YAML-karta"]
    e: list[str] = []
    for key in REQUIRED_TEXT:
        _need(isinstance(spec.get(key), str) and spec[key].strip() != "", e, f"saknar text: {key}")
    design, analysis = spec.get("design") or {}, spec.get("analys") or {}
    kind = design.get("typ")
    _need(kind in {"n1", "observation"}, e, "design.typ måste vara n1 eller observation")
    s = analysis.get("minsta_relevanta_effekt")
    _need(isinstance(s, (int, float)) and s != 0, e,
          "analys.minsta_relevanta_effekt: ett tal skilt från 0; tecknet anger förväntad riktning (A minus B)")
    level = analysis.get("niva", 0.95)
    _need(isinstance(level, float) and 0.5 < level < 1, e, "analys.niva: mellan 0,5 och 1, t.ex. 0.95")
    if kind == "n1":
        _validate_n1(design, analysis, e)
    elif kind == "observation":
        _validate_observation(design, analysis, e)
    _validate_outcome(spec.get("utfall") or {}, "utfall", kind, e)
    _validate_protocol(spec, kind, e)
    return e


def _validate_n1(design: dict, analysis: dict, e: list[str]) -> None:
    for key in ("A", "B"):
        _need(isinstance(design.get(key), str), e, f"design.{key}: beskriv villkoret exakt")
    _need(isinstance(design.get("start"), date), e, "design.start: datum ÅÅÅÅ-MM-DD")
    pairs, days, wash = design.get("par"), design.get("periodlangd_dagar"), design.get("tvatt_dagar", 0)
    _need(isinstance(pairs, int) and pairs >= 6, e, "design.par: minst 6 (med färre kan testet aldrig nå 5 %)")
    _need(isinstance(days, int) and days >= 1, e, "design.periodlangd_dagar: heltal ≥ 1")
    _need(isinstance(wash, int) and isinstance(days, int) and 0 <= wash < days, e,
          "design.tvatt_dagar: mellan 0 och periodlängden − 1")
    _need(analysis.get("metod") == "randomiseringstest", e, "analys.metod: randomiseringstest för n1")
    if "dagar" in design:
        _validate_eligible_days(design, e)
    if "foljsamhet" in design:
        _validate_adherence(design["foljsamhet"], e)
    if "verkan" in design:
        v = design["verkan"] or {}
        _need(v.get("typ") in ACTION_TYPES, e, f"design.verkan.typ: en av {list(ACTION_TYPES)}")
        _need(_is_clock(v.get("borjar")), e, "design.verkan.borjar: klockslag \"HH:MM\" då A tidigast kan verka")


def _is_clock(x: object) -> bool:
    try:
        datetime.strptime(str(x), "%H:%M")
    except ValueError:
        return False
    return isinstance(x, str)


def _validate_adherence(f: dict, e: list[str]) -> None:
    """How each day's condition is verified from data (SCRIBE 17), or `manuell`."""
    f = f or {}
    _need(isinstance(f.get("kolumn"), str), e,
          "design.foljsamhet.kolumn: en kolumn i marts.mart_analysis_days (t.ex. steps) eller manuell")
    if f.get("kolumn") == "manuell":
        return
    for key in ("A", "B"):
        rule = f.get(key) or {}
        _need(isinstance(rule, dict) and rule and set(rule) <= {"min", "max"}
              and all(isinstance(v, (int, float)) for v in rule.values()), e,
              f"design.foljsamhet.{key}: {{min: …}} och/eller {{max: …}} i kolumnens enhet")


def meets(value: float, rule: dict) -> bool:
    """Whether a measured value satisfies an adherence rule such as {min: 10000}."""
    return value >= rule.get("min", -math.inf) and value <= rule.get("max", math.inf)


def _validate_eligible_days(design: dict, e: list[str]) -> None:
    """Restricted randomisation: only days where both A and B are possible and comparable."""
    days = design["dagar"] or {}
    weekdays, dates = days.get("veckodagar"), days.get("datum")
    _need((weekdays is None) != (dates is None), e,
          "design.dagar: ange antingen veckodagar (t.ex. [lordag, sondag]) eller datum (lista), inte båda")
    if weekdays is not None:
        _need(isinstance(weekdays, list) and weekdays and all(w in n1.WEEKDAYS for w in weekdays), e,
              f"design.dagar.veckodagar: en lista av {list(n1.WEEKDAYS)}")
    if dates is not None:
        _need(isinstance(dates, list) and all(isinstance(x, date) for x in dates), e,
              "design.dagar.datum: en lista av datum ÅÅÅÅ-MM-DD")
        if isinstance(dates, list) and isinstance(design.get("par"), int) and isinstance(design.get("start"), date):
            try:
                n1.eligible_dates(design["start"], 2 * design["par"], dates=dates, min_gap=days.get("minsta_avstand", 1))
            except (ValueError, TypeError):
                e.append(f"design.dagar.datum: för få datum från start, med minsta_avstand "
                         f"{days.get('minsta_avstand', 1)}, till {design['par']} par")
    gap = days.get("minsta_avstand", 1)
    _need(isinstance(gap, int) and gap >= 1, e, "design.dagar.minsta_avstand: heltal ≥ 1 (kalenderdagar mellan valda dagar)")
    _need(design.get("periodlangd_dagar") == 1 and design.get("tvatt_dagar", 0) == 0, e,
          "design.dagar kräver periodlangd_dagar: 1 och tvatt_dagar: 0 (varje period är en tillåten dag)")
    _need(isinstance(design.get("dagar_motivering"), str) and design["dagar_motivering"].strip() != "", e,
          "design.dagar_motivering: varför bara dessa dagar (vilket villkor är omöjligt eller förväxlat andra dagar)")


def _validate_observation(design: dict, analysis: dict, e: list[str]) -> None:
    exp = design.get("exponering") or {}
    _need(exp.get("handelse") in EVENT_COLUMNS, e, f"design.exponering.handelse: en av {sorted(EVENT_COLUMNS)}")
    _need(isinstance(exp.get("dagar_efter", 0), int) and exp.get("dagar_efter", 0) >= 0, e,
          "design.exponering.dagar_efter: heltal ≥ 0")
    period = design.get("period")
    _need(isinstance(period, list) and len(period) == 2 and all(isinstance(d, date) for d in period),
          e, "design.period: [från, till] som datum")
    _need(isinstance(design.get("retrospektiv"), bool), e,
          "design.retrospektiv: true om datan redan fanns när studien skrevs")
    _need(analysis.get("metod") == "blockbootstrap", e, "analys.metod: blockbootstrap för observation")
    floor = analysis.get("minsta_underlag") or {}
    _need(all(isinstance(floor.get(k), int) and floor[k] >= MIN_DAYS for k in ("exponerade", "jamforelse")),
          e, f"analys.minsta_underlag: {{exponerade: N, jamforelse: M}}, var och en minst {MIN_DAYS} dagar. "
             "Slutanalysen vägrar köra under det, så studien inte förbrukas på för lite data.")
    _need(isinstance(analysis.get("blocklangd"), int) and analysis["blocklangd"] >= 1, e,
          "analys.blocklangd: dagar, heltal ≥ 1")


def _validate_outcome(outcome: dict, name: str, kind: str | None, e: list[str]) -> None:
    """An outcome is a local-time window (matt + fonster) or a day-table column.

    Windows are CGM-specific. A day column works for both designs — it is what lets a
    person without a CGM (wearable-only mode) run n-of-1 experiments on sleep or pulse."""
    if "kolumn" not in outcome and ("fonster" in outcome or kind == "n1"):
        _need(outcome.get("matt") in WINDOW_METRICS, e, f"{name}.matt: en av {sorted(WINDOW_METRICS)}")
        w = outcome.get("fonster")
        _need(isinstance(w, list) and len(w) == 2 and all(isinstance(t, str) for t in w) and w[0] < w[1],
              e, f'{name}.fonster: ["HH:MM", "HH:MM"] inom samma dygn, t.ex. ["19:00", "22:00"]')
    else:
        _need(isinstance(outcome.get("kolumn"), str), e,
              f"{name}: antingen kolumn (i marts.mart_analysis_days) eller matt + fonster")
        skift = outcome.get("dagar_efter", 0)
        _need(isinstance(skift, int) and skift >= 0, e,
              f"{name}.dagar_efter: heltal ≥ 0 (utfallet läses så många dagar efter villkorsdagen; "
              "wearable-kolumner hör till natten som slutar den morgonen)")


def _validate_protocol(spec: dict, kind: str | None, e: list[str]) -> None:
    """CENT 2015 items a machine can check, and a negative control (Lipsitch et al. 2010)."""
    prot = spec.get("protokoll") or {}
    required = ["periodeffekt"] + (["overforing", "stoppregel"] if kind == "n1" else [])
    for key in required:
        _need(isinstance(prot.get(key), str) and prot[key].strip() != "", e,
              f"protokoll.{key}: {PROTOCOL_HELP[key]}")
    _need(isinstance(prot.get("andringslogg"), list), e,
          "protokoll.andringslogg: lista över ändringar efter låsning (tom lista om inga)")
    neg = spec.get("negativ_kontroll") or {}
    _need(bool(neg), e, "negativ_kontroll: ett utfall som exponeringen inte kan påverka, analyserat på "
                        "samma sätt. Visar det en effekt finns en snedvridning, inte en verkan.")
    if neg:
        _validate_outcome(neg, "negativ_kontroll", kind, e)
        _need(isinstance(neg.get("motivering"), str) and neg["motivering"].strip() != "", e,
              "negativ_kontroll.motivering: varför exponeringen inte kan påverka detta utfall")


# --- Lock -------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_review(study: Study) -> None:
    """The design review must have passed for exactly this version of the study file."""
    path = study.folder / REVIEW_FILE
    if not path.exists():
        raise StudyError("ingen designgranskning: kör `python -m selvra_analysis.granska` på filen först")
    review = json.loads(path.read_text())
    if review.get("spec_sha256") != _sha(study.path):
        raise StudyError("designgranskningen gäller en annan version av studiefilen; granska igen")
    if review.get("verdict") == "STOPP":
        raise StudyError("designgranskningen har stopp kvar; se granskning.md")


def lock(study: Study, seed: int | None = None) -> dict:
    if study.lock_path.exists():
        raise StudyError("studien är redan låst; en ändring kräver en ny studie med nytt id")
    record = {
        "study": study.spec["id"],
        "locked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec_sha256": _sha(study.path),
        "pipeline_commit": _git("rev-parse", "HEAD"),
    }
    if study.kind == "n1":
        d = study.design
        seed = seed if seed is not None else secrets.randbits(32)
        days = None
        if "dagar" in d:
            days = n1.eligible_dates(d["start"], 2 * d["par"], d["dagar"].get("veckodagar"), d["dagar"].get("datum"),
                                     d["dagar"].get("minsta_avstand", 1))
        sched = n1.make_schedule(d["start"], d["par"], d["periodlangd_dagar"], d.get("tvatt_dagar", 0), seed,
                                 days=days)
        record["schedule_sha256"] = n1.write_schedule(sched, study.schedule_path, seed)
        record["schedule_end"] = str(sched["date"].max())
    _vagra_overlapp_med_samband(study, record)
    study.lock_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def _data_window(study: Study, record: dict) -> tuple[str, str] | None:
    """Datumfönstret studiens bekräftande analys använder: n1 = start→schemaslut
    (framtid), observation = design.period [från, till]."""
    d = study.design
    if study.kind == "n1":
        return str(d["start"]), str(record.get("schedule_end", d["start"]))
    period = d.get("period")
    return (str(period[0]), str(period[1])) if period else None


def _vagra_overlapp_med_samband(study: Study, record: dict) -> None:
    """En fråga ur utforskande_samband får bara prövas på data insamlad EFTER
    låsning. Vägra om studiens datafönster överlappar ett analyserat samband-
    fönster — annars prövar studien det skannern redan tittat på, och
    domstolsprincipen faller."""
    from selvra_analysis import utforskande_samband as us  # noqa: PLC0415 — lat: håller study import-lätt + undviker cykel
    # Fail-closed: finns en samband-rapport men loggen saknas kan vi inte veta om
    # studien prövar peekad data — vägra hellre än att tolka saknad logg som "inget".
    if us.RAPPORT.exists() and not us.FONSTER.exists():
        raise StudyError(
            "en utforskande samband-rapport finns men fönsterloggen "
            f"({us.FONSTER}) saknas — kan inte garantera att studien inte prövar "
            "data skannern redan tittat på; återställ loggen innan låsning")
    fonster = _data_window(study, record)
    if fonster is None:
        return
    krock = us.overlappande_fonster(*fonster)
    if krock:
        w = krock[0]
        raise StudyError(
            f"studiens datafönster {fonster[0]}–{fonster[1]} överlappar ett "
            f"utforskande samband-fönster ({w['fran']}–{w['till']}); en fråga "
            "därifrån får bara prövas på data insamlad efter låsning — "
            "välj ett senare fönster eller en ny studie på färsk data")


def check_lock(study: Study) -> dict:
    """The lock must exist, match the files, and the pipeline must not have changed since."""
    if not study.lock_path.exists():
        raise StudyError("studien är inte låst: kör `las` och committa mappen")
    rec = json.loads(study.lock_path.read_text())
    problems = []
    if _sha(study.path) != rec["spec_sha256"]:
        problems.append("studie.yml har ändrats efter låsningen")
    if study.kind == "n1" and _sha(study.schedule_path) != rec["schedule_sha256"]:
        problems.append("schema.csv har ändrats efter låsningen")
    rel = [str(p) for p in (study.path, study.lock_path, study.schedule_path) if p.exists()]
    if _git("status", "--porcelain", "--", *rel):
        problems.append("studiemappen är inte committad: commit är den offentliga tidsstämpeln")
    changed = _git("diff", "--name-only", rec["pipeline_commit"], "HEAD", "--", *PIPELINE_PATHS)
    dirty = _git("status", "--porcelain", "--", *PIPELINE_PATHS)
    if changed or dirty:
        problems.append("pipelinen har ändrats sedan låsningen:\n    " + "\n    ".join(
            (changed + "\n" + dirty).split()))
    if problems:
        raise StudyError("låsningen håller inte:\n  " + "\n  ".join(problems))
    return rec


# --- Data -------------------------------------------------------------------------------------

def _daily_outcome(study: Study, con, o: dict | None = None) -> tuple[pd.DataFrame, str]:
    o = o or study.spec["utfall"]
    if "fonster" in o:
        daily = n1.window_outcomes(con, o["fonster"][0], o["fonster"][1], o.get("min_tackning_pct", 70.0))
        if study.kind == "observation":
            # Context (logged events) comes from the day table; validity from the window itself.
            context = con.execute("select * exclude (is_valid_day) from marts.mart_analysis_days").df()
            context = context.drop(columns=[c for c in daily.columns if c != "reading_date" and c in context])
            daily["reading_date"] = pd.to_datetime(daily["reading_date"])
            context["reading_date"] = pd.to_datetime(context["reading_date"])
            daily = daily.merge(context, on="reading_date", how="left")
        return daily, WINDOW_METRICS[o["matt"]]
    daily = con.execute("select * from marts.mart_analysis_days order by reading_date").df()
    if o["kolumn"] not in daily.columns:
        raise StudyError(f"kolumnen {o['kolumn']!r} finns inte i mart_analysis_days")
    skift = o.get("dagar_efter", 0)
    if skift:
        # Utfallet för villkorsdag d läses d+skift: Garmins sömn och puls på datum x hör
        # till natten som slutar morgon x, så "natten efter dagen d" är kolumnvärdet på d+1.
        daily = daily.copy()
        daily[o["kolumn"]] = daily[o["kolumn"]].shift(-skift)
    return daily, o["kolumn"]


def _observation_series(study: Study, daily: pd.DataFrame, col: str) -> pd.DataFrame:
    d = study.design
    exp = d["exponering"]
    s = daily_series(daily, "reading_date", [col, EVENT_COLUMNS[exp["handelse"]], "is_valid_day"])
    lo, hi = (pd.Timestamp(x) for x in d["period"])
    flag = s[EVENT_COLUMNS[exp["handelse"]]].shift(exp.get("dagar_efter", 0))
    s["exposed"] = flag.map({True: True, False: False})
    s["y"] = s[col].where(utfallsgiltig(s, col))
    return s[(s.index >= lo) & (s.index <= hi)]


def _observation_counts(s: pd.DataFrame) -> tuple[int, int]:
    valid = s["y"].notna()
    return int((s["exposed"].eq(True) & valid).sum()), int((s["exposed"].eq(False) & valid).sum())


# --- Status (blind) ---------------------------------------------------------------------------

def status(study: Study, con, today: date | None = None) -> str:
    rec = check_lock(study)
    today = today or date.today()
    daily, col = _daily_outcome(study, con)
    lines = [f"# Status · {study.spec['titel']}", "", (f"*{today} · studie `{study.spec['id']}` · "
              f"låst {rec['locked_at'][:10]}*"), "",
             ("Statusrapporten visar framsteg och datakvalitet, aldrig effekten. Effekten räknas en gång, "
              "när studien är klar."), ""]
    if study.kind == "n1":
        sched = n1.read_schedule(study.schedule_path)
        periods = n1.period_outcomes(sched, daily, col)
        end = sched.groupby("period")["date"].max()
        periods["klar"] = periods["period"].map(end) < today
        done = periods[periods["klar"]]
        complete_pairs = done.groupby("pair")["value"].apply(lambda v: v.notna().sum() == 2)
        n_pairs = sched["pair"].max()
        lines += [
            f"- **Period:** {sched['date'].min()} till {sched['date'].max()}",
            f"- **Avslutade perioder:** {len(done)} av {2 * n_pairs}",
            f"- **Kompletta par hittills:** {int(complete_pairs.sum())} av {n_pairs}",
            f"- **Avslutade perioder utan giltig data:** {int(done['value'].isna().sum())}",
        ]
        upcoming = sched[sched["date"] >= today].head(3)
        if not upcoming.empty:
            lines += ["", "**Kommande dagar enligt schemat:**", ""]
            for r in upcoming.itertuples():
                cond = study.design[r.condition]
                lines.append(f"- {r.date}: {r.condition} ({cond}){' · tvättdag' if r.washout else ''}")
        lines += ["", f"Slutanalysen kan köras från {date.fromisoformat(rec['schedule_end']) + timedelta(days=1)}."]
    else:
        s = _observation_series(study, daily, col)
        n_exp, n_cmp = _observation_counts(s)
        floor = study.spec["analys"]["minsta_underlag"]
        lines += [
            f"- **Period:** {study.design['period'][0]} till {study.design['period'][1]}",
            f"- **Exponerade dagar med giltigt utfall:** {n_exp} av minst {floor['exponerade']}",
            f"- **Jämförelsedagar med giltigt utfall:** {n_cmp} av minst {floor['jamforelse']}",
        ]
        if study.design["retrospektiv"]:
            lines += ["", "*Retrospektiv: datan fanns när studien skrevs.*"]
    return "\n".join(lines) + "\n"


# --- Final run --------------------------------------------------------------------------------

def decide(estimate: dict, smallest: float) -> str:
    """The locked decision rule. `smallest` carries the expected direction (A minus B)."""
    lo, hi = estimate["ci_low"], estimate["ci_high"]
    if smallest < 0:
        lo, hi, smallest = -hi, -lo, -smallest
    if lo > smallest:
        return "tesen håller: hela intervallet visar minst den minsta relevanta effekten, i förväntad riktning"
    if hi < smallest:
        return "tesen motbevisad: hela intervallet visar en mindre effekt än den minsta relevanta, eller en effekt åt andra hållet"
    return "obestämt: intervallet rymmer både en relevant och en irrelevant effekt"


def _estimate(study: Study, con, outcome: dict) -> tuple[dict, dict]:
    """The locked analysis on one outcome. Returns (estimate, extra record fields)."""
    a = study.spec["analys"]
    daily, col = _daily_outcome(study, con, outcome)
    if study.kind == "n1":
        periods = n1.period_outcomes(n1.read_schedule(study.schedule_path), daily, col,
                                     valid_column=None if col in WEARABLE_UTFALL else "is_valid_day")
        est = n1.randomisation_test(periods, level=a.get("niva", 0.95)).as_dict()
        return est, {"perioder": periods.to_dict("records")}
    s = _observation_series(study, daily, col)
    est = block_bootstrap_difference(s["y"], s["exposed"], block_length=a["blocklangd"],
                                     seed=a.get("seed", 1), level=a.get("niva", 0.95)).as_dict()
    return est, {}


def _adherence(study: Study, con) -> dict | None:
    """Per condition: scheduled days, days with a measurement, days that met the rule.

    The analysis stays as randomised whatever this shows; adherence is reported beside it.
    """
    f = study.design.get("foljsamhet")
    if not f or f["kolumn"] == "manuell":
        return None
    sched = n1.read_schedule(study.schedule_path)
    sched = sched[~sched["washout"]]
    try:
        # The column name was validated as a string and is checked against the table here.
        cols = {r[0] for r in con.execute("select column_name from information_schema.columns where "
                                          "table_schema = 'marts' and table_name = 'mart_analysis_days'").fetchall()}
        if f["kolumn"] not in cols:
            raise StudyError(f"följsamhetskolumnen {f['kolumn']!r} finns inte i mart_analysis_days")
        m = con.execute(f'select reading_date, "{f["kolumn"]}" as x from marts.mart_analysis_days').df()  # noqa: S608
    except duckdb.CatalogException:
        raise StudyError("marts.mart_analysis_days saknas; följsamheten kan inte mätas") from None
    m["reading_date"] = pd.to_datetime(m["reading_date"]).dt.date
    merged = sched.merge(m, left_on="date", right_on="reading_date", how="left")
    out = {}
    for cond in ("A", "B"):
        rows = merged[merged["condition"] == cond]
        measured = rows["x"].notna()
        ok = rows.loc[measured, "x"].map(lambda v, c=cond: meets(float(v), f[c]))
        out[cond] = {"dagar": len(rows), "matta": int(measured.sum()), "uppfyllda": int(ok.sum())}
    return out


def _check_data_complete(con, end: date, strict: bool) -> None:
    """The data must cover the study's last day before the one analysis is spent.

    A run the morning after an experiment ends, before the last day's readings have been
    loaded (failed ingest, an export that lags), would analyse an incomplete study for good.
    An experiment needs data from after its last day, so that day is known to be complete;
    an observational period may end where the data ends.
    """
    try:
        latest = con.execute("select max(cast(reading_at_local as date)) "
                             "from intermediate.int_cgm_flagged").fetchone()[0]
    except duckdb.CatalogException:  # a day-level outcome read only from the marts
        latest = None
    if latest is None:  # wearable-only mode: no CGM readings, the mart carries freshness
        latest = con.execute("select max(reading_date) from marts.mart_analysis_days").fetchone()[0]
    if latest is None or latest < end or (strict and latest == end):
        raise StudyError(f"datan når bara till {latest}, studien slutade {end}; ladda ny data (make live) "
                         "och kör igen. Ingenting har körts; studien är inte förbrukad.")


def _check_ready(study: Study, con, rec: dict, today: date) -> None:
    """Refuse before anything is written: running, already run, or too little data."""
    if any((study.folder / "korningar").glob("*.json")):
        raise StudyError("slutanalysen är redan körd; den körs en gång")
    end = (date.fromisoformat(rec["schedule_end"]) if study.kind == "n1" else study.design["period"][1])
    if today <= end:
        raise StudyError(f"studien pågår till {end}; slutanalysen körs efter det")
    _check_data_complete(con, end, strict=study.kind == "n1")
    if study.kind == "observation":
        daily, col = _daily_outcome(study, con)
        n_exp, n_cmp = _observation_counts(_observation_series(study, daily, col))
        floor = study.spec["analys"]["minsta_underlag"]
        if n_exp < floor["exponerade"] or n_cmp < floor["jamforelse"]:
            raise StudyError(
                f"för lite underlag: {n_exp} exponerade och {n_cmp} jämförelsedagar med giltigt utfall, "
                f"studien kräver {floor['exponerade']} och {floor['jamforelse']}. Ingenting har körts; "
                "studien är inte förbrukad.")


def run(study: Study, con, today: date | None = None) -> tuple[dict, str]:
    rec = check_lock(study)
    _check_ready(study, con, rec, today or date.today())
    # Both estimates are computed before anything is written, so a failure spends nothing.
    est, extra = _estimate(study, con, study.spec["utfall"])
    try:
        neg, _ = _estimate(study, con, study.spec["negativ_kontroll"])
    except ValueError as err:
        raise StudyError(f"den negativa kontrollen kan inte beräknas ({err}); ingenting har körts") from None
    adherence = _adherence(study, con) if study.kind == "n1" else None
    record = {
        "study": study.spec["id"], "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "lock": rec, "commit": _git("rev-parse", "HEAD"), "data": data_version(con),
        "result": est, "beslut": decide(est, study.spec["analys"]["minsta_relevanta_effekt"]),
        "negativ_kontroll": neg, **extra,
    }
    if adherence is not None:
        record["foljsamhet"] = adherence
    runs = study.folder / "korningar"
    runs.mkdir(exist_ok=True)
    (runs / f"{record['run_at'].replace(':', '')}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n")
    report = _report(study, record)
    (study.folder / "slutrapport.md").write_text(report)
    return record, report



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kommando", choices=["validera", "las", "status", "kor"])
    parser.add_argument("studie", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "selvra.duckdb")
    args = parser.parse_args(argv)
    try:
        study = load(args.studie.resolve())
        if args.kommando == "validera":
            print(f"OK: {study.spec['id']} ({study.kind})")
        elif args.kommando == "las":
            require_review(study)
            rec = lock(study)
            print(f"Låst {rec['study']}. Committa nu {study.folder.relative_to(ROOT)}/ — "
                  "commiten är den offentliga tidsstämpeln.")
        else:
            with duckdb.connect(str(args.db), read_only=True) as con:
                if args.kommando == "status":
                    text = status(study, con)
                    out = study.folder / "rapporter" / f"status-{date.today()}.md"
                    out.parent.mkdir(exist_ok=True)
                    out.write_text(text)
                    print(text)
                else:
                    _, report = run(study, con)
                    print(report)
    except StudyError as err:
        print(f"Stopp: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
