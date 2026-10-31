"""Morgonmejl till en person: en spegel av gårdagen som blir rikare ju mer Selvra vet om personen.

Steg 1 (spegel)      från första dagen: gårdagens värden mot personens egna dagar hittills
Steg 2 (ditt normala) från 14 dagar med data: personens eget intervall, avvikelser markeras
Steg 3 och 4 (mönster som frågor, egen studie) kommer senare; mejlet säger vad som krävs.

Mejlet beskriver vad apparaten mätte, källattribuerat, och ger aldrig råd. Synkar klockan
inte säger mejlet det först, i stället för att rapportera tomma värden.

Personen beskrivs i data/personer/<namn>/person.yml (gitignored; e-postadressen är privat):

    namn: Kari
    epost: kari@example.com
    kallor: [garmin]

Utskick via SMTP, inställt i .env: SELVRA_SMTP_USER, SELVRA_SMTP_PASSWORD (för Gmail ett
applösenord), valfritt SELVRA_SMTP_HOST (smtp.gmail.com) och SELVRA_SMTP_PORT (587).

    uv run python -m selvra_analysis.morgonmejl testare-1            # visa mejlet, skicka inget
    uv run python -m selvra_analysis.morgonmejl testare-1 --skicka   # hämta ny data och skicka

Genväg i MVP:n: mejlet läser personens Garmin-dagar direkt (raw.garmin_daily), eftersom
datalagret ännu utgår från CGM-dagar och saknar rader för den som inte har CGM.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from selvra_analysis.ingest_garmin import load as load_garmin
from selvra_analysis.ingest_garmin import person_paths

STAGE2_DAYS = 14          # dagar med data innan personens eget intervall används
BASELINE_DAYS = 28        # det egna normala: de senaste 28 dagarna med data
FETCH_DAYS = 10           # hämtas varje morgon, så sena synkar kommer med
WEEKDAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]


@dataclass
class Measure:
    column: str
    sentence: str        # "{}" is the value, e.g. "Garmin räknade {} steg"
    unit: str            # after a range, e.g. " ms"


MEASURES = [
    Measure("steps", "Garmin räknade {} steg i går", ""),
    Measure("total_sleep_seconds", "Garmin mätte {} sömn i natt", ""),
    Measure("hr_lowest_bpm", "Garmin mätte vilopulsen till {} i går", ""),
    Measure("hrv_avg_ms", "Garmin mätte HRV {} ms i natt", " ms"),
]

# CGM-rader för personer med glukosdata; bara giltiga dagar räknas (is_valid_day).
GLUKOS_MEASURES = [
    Measure("mean_mmol", "CGM:n mätte glukossnittet till {} mmol/L i går", " mmol/L"),
    Measure("tir_pct", "Du var i målområdet {} % av gårdagen", " %"),
]


def _short(m: Measure, v: float) -> str:
    if m.column == "total_sleep_seconds":
        h, mins = divmod(round(v / 60), 60)
        return f"{h} h {mins:02d} min"
    if m.column == "steps":
        return f"{round(v / 100) * 100:,.0f}".replace(",", " ")
    if m.column == "mean_mmol":
        return f"{v:.1f}".replace(".", ",")
    return f"{v:.0f}"


def read_days(db: Path) -> pd.DataFrame:
    with duckdb.connect(str(db), read_only=True) as con:
        df = con.execute("select * from raw.garmin_daily order by reading_date").df()
    df["reading_date"] = pd.to_datetime(df["reading_date"]).dt.date
    return df


def read_glucose(db: Path) -> pd.DataFrame:
    """Giltiga CGM-dagar ur personens marts; tom för personer utan glukosdata."""
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            df = con.execute("select reading_date, mean_mmol, tir_pct from marts.fct_glucose_daily "
                             "where is_valid_day order by reading_date").df()
    except duckdb.Error:
        return pd.DataFrame(columns=["reading_date", "mean_mmol", "tir_pct"])
    df["reading_date"] = pd.to_datetime(df["reading_date"]).dt.date
    return df


NATT_MIN_AVLASNINGAR = 36      # halva natten 00–06 vid 5-minutersgrid
FONSTER_MIN_AVLASNINGAR = 20   # per 3-timmarsfönster för formraden
LAGT_MMOL = 4.0                # säkerhetsgolv: nattraden visas bara vid ett lågt värde


def _natt_rad(db: Path, today: date) -> str | None:
    """Säkerhetsgolvet: nattens 00–06 lyfts BARA när glukosen gick under 4 mmol/L
    — en lågepisod en T1:a måste se. En lugn natt (snittet inom det vanliga) är
    tystnad, inte en rad. Tystnad utan täckning."""
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            r = con.execute(
                "select glucose_mmol, reading_at_local from intermediate.int_cgm_readings "
                "where reading_date = ? and extract(hour from reading_at_local) < 6 "
                "and glucose_mmol is not null order by reading_at_local", [today]).df()
    except duckdb.Error:
        return None
    if len(r) < NATT_MIN_AVLASNINGAR:
        return None
    lagst = r.loc[r["glucose_mmol"].idxmin()]
    if lagst["glucose_mmol"] >= LAGT_MMOL:   # ingen lågepisod → ingen rad
        return None
    kl = pd.to_datetime(lagst["reading_at_local"]).strftime("%H:%M")
    return (f"I natt (00–06) gick CGM:n ned till {lagst['glucose_mmol']:.1f} mmol/L kl {kl}"
            ).replace(".", ",")


def _form_rad(db: Path, yesterday: date) -> str | None:
    """Var dagen hände: stabilaste och oroligaste 3-timmarsfönstret i går."""
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            r = con.execute(
                "select (extract(hour from reading_at_local)::int / 3) * 3 as fonster, "
                "stddev_samp(glucose_mmol) as sd, count(*) as n "
                "from intermediate.int_cgm_readings where reading_date = ? "
                "and glucose_mmol is not null group by 1 having count(*) >= ?",
                [yesterday, FONSTER_MIN_AVLASNINGAR]).df()
    except duckdb.Error:
        return None
    if len(r) < 3 or r["sd"].isna().any():
        return None
    basta, varsta = r.loc[r["sd"].idxmin()], r.loc[r["sd"].idxmax()]
    f = lambda v: f"{int(v):02d}–{int(v) + 3:02d}"
    return (f"I går var {f(basta['fonster'])} stabilast och {f(varsta['fonster'])} "
            f"oroligast (spridning {basta['sd']:.1f} mot {varsta['sd']:.1f} mmol/L)").replace(".", ",")


def _svit_rad(glukos: pd.DataFrame, today: date) -> str | None:
    """Giltiga dagar i rad inom det egna bandet — beskrivning, aldrig streak-konfetti."""
    if glukos is None or glukos.empty or "mean_mmol" not in glukos:
        return None
    g = glukos.dropna(subset=["mean_mmol"]).sort_values("reading_date")
    yesterday = today - timedelta(days=1)
    hist = g[g["reading_date"] < yesterday]["mean_mmol"].tail(BASELINE_DAYS)
    if len(hist) < STAGE2_DAYS or yesterday not in set(g["reading_date"]):
        return None
    lo, hi = hist.quantile(0.1), hist.quantile(0.9)
    svit, dag = 0, yesterday
    per_dag = dict(zip(g["reading_date"], g["mean_mmol"], strict=False))
    while dag in per_dag and lo <= per_dag[dag] <= hi:
        svit += 1
        dag -= timedelta(days=1)
    if svit < 2:
        return None
    return f"{svit} giltiga dagar i rad inom ditt vanliga glukossnitt"


def _handelse_rad(db: Path, yesterday: date) -> str | None:
    """Eko av gårdagens loggade händelser — korrelationen syns utan att påstås."""
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            r = con.execute(
                "select typ, notering from raw.personal_events "
                "where try_cast(left(start, 10) as date) <= ? "
                "and coalesce(try_cast(left(slut, 10) as date), "
                "try_cast(left(start, 10) as date)) >= ?", [yesterday, yesterday]).df()
    except duckdb.Error:
        return None
    if r.empty:
        return None
    delar = [t + (f" ({n})" if isinstance(n, str) and n.strip() else "")
             for t, n in zip(r["typ"], r["notering"], strict=False)]
    return "Loggat i går: " + ", ".join(delar)


def extrarader(db: Path, today: date, glukos: pd.DataFrame | None) -> list[str]:
    """Essens-raderna: säkerhetsgolvet (nattens lågvärde) och gårdagens loggade
    händelser (kontext till en avvikelse). Streak-raden och inom-dags-formraden
    hör till detaljvyn, inte morgonens glans — så de är inte med här."""
    kandidater = [_natt_rad(db, today), _handelse_rad(db, today - timedelta(days=1))]
    return [r + "." for r in kandidater if r]


def _sync_line(df: pd.DataFrame, today: date) -> str | None:
    """Warn first when the watch has not synced, so a gap is noticed in days, not months."""
    if df.empty:
        return "Garmin har ingen data från klockan ännu. Öppna Garmin Connect-appen så att klockan synkar."
    latest = df.loc[df["steps"].notna(), "reading_date"].max()
    if pd.isna(latest) or latest < today - timedelta(days=1):
        since = "aldrig" if pd.isna(latest) else f"sedan {latest.day}/{latest.month}"
        return (f"Klockan har inte synkat {since}. Öppna Garmin Connect-appen på telefonen så att "
                "datan inte går förlorad; klockan sparar bara en begränsad tid.")
    return None


def _measure_line(m: Measure, value: float, history: pd.Series, stage2: bool) -> tuple[str, str]:
    """Raden + var värdet låg mot det egna normala: 'över'/'under'/'inom', eller
    '' i inlärningsfasen (inget band än). Essensen visar bara avvikelser."""
    text = m.sentence.format(_short(m, value))
    if history.empty:
        return text + ".", ""
    if stage2:
        lo, hi = history.quantile(0.1), history.quantile(0.9)
        where = "över" if value > hi else "under" if value < lo else "inom"
        return text + f", {where} ditt vanliga {_short(m, lo)}–{_short(m, hi)}{m.unit}.", where
    return (text + f". Hittills brukar det vara {_short(m, history.median())}{m.unit} "
            f"({len(history)} dagar).", "")


def compose(name: str, df: pd.DataFrame, today: date,
            glukos: pd.DataFrame | None = None,
            extra: list[str] | None = None) -> tuple[str, str]:
    """Subject and body of one morning's mail. CGM-raderna först — de är
    primärsignalen för den som har dem; klockraderna därefter."""
    yesterday = today - timedelta(days=1)
    har_glukos = glukos is not None and not glukos.empty
    n_days = int(df["steps"].notna().sum()) if not df.empty else 0
    lines = [f"God morgon {name},", ""]
    warn = _sync_line(df, today)
    if warn and not (df.empty and har_glukos):
        # En CGM-person utan klocka ännu ska inte mötas av en klockvarning varje morgon.
        lines += [warn, ""]
    glukos_dagar = int(glukos["mean_mmol"].notna().sum()) if har_glukos else 0
    i_stage2 = max(n_days, glukos_dagar) >= STAGE2_DAYS
    shown, doldes = 0, False
    kallor = ([(m, glukos) for m in GLUKOS_MEASURES] if har_glukos else []) \
        + [(m, df) for m in MEASURES]
    for m, frame in kallor:
        # Sleep and HRV belong to the night that ended this morning; steps and pulse to yesterday.
        day = today if m.column in ("total_sleep_seconds", "hrv_avg_ms") else yesterday
        row = frame[frame["reading_date"] == day] if not frame.empty else frame
        if row.empty or pd.isna(row[m.column].iloc[0]):
            continue
        # The person's last BASELINE_DAYS days *with data*: a sync gap must not empty the baseline.
        hist = frame.loc[frame["reading_date"] < day, m.column].dropna().tail(BASELINE_DAYS)
        line, where = _measure_line(m, float(row[m.column].iloc[0]), hist, len(hist) >= STAGE2_DAYS)
        if where == "inom":        # essens: det som låg inom det egna normala tigs
            doldes = True
            continue
        lines.append("- " + line)
        shown += 1
    for rad in (extra or []):
        lines.append("- " + rad)
        shown += 1
    # Essens-avslutning: säg att resten låg inom det vanliga, lista det inte.
    if i_stage2 and not shown:
        lines.append("I går låg allt inom ditt vanliga.")
    elif i_stage2 and doldes:
        lines.append("Resten låg inom ditt vanliga.")
    elif not shown:
        lines.append("Inga nya värden för i går och i natt ännu.")
    # Inlärningsfas-fotnoten bara medan det egna normala växer fram — inte dagligt brus.
    if not i_stage2:
        lines += ["", _stage_footer(max(n_days, glukos_dagar))]
    lines += ["", "Selvra"]
    subject = f"Selvra {WEEKDAYS[today.weekday()]} {today.day}/{today.month}" \
        + (" – klockan har inte synkat" if warn and not (df.empty and har_glukos) else "")
    return subject, "\n".join(lines) + "\n"


def framstegsrad(par_nu: int, par_mal: int, titel: str) -> str | None:
    """Äkta framsteg mot en dom — goal-gradient utan manipulation.

    Forskningen (Kivetz 2006) säger att synligt framsteg mot ett mål bär
    uthållighet; den manipulativa grenen (Nunes & Drèze: påhittat försprång)
    är förbjuden här. Måttet är grindens EGET: väntat antal kompletta par mot
    de par studien kräver — samma tal granskaren räknar, så raden och grinden
    aldrig kan motsäga varandra. Tiger när målet nåtts (då talar
    förslagsgrinden) eller inget mål finns."""
    if par_mal <= 0 or par_nu >= par_mal:
        return None
    kvar = par_mal - par_nu
    return (f"{titel.capitalize()}: {par_nu} av {par_mal} kompletta par finns i underlaget. "
            f"Ännu {kvar} par tills frågan kan prövas — bär klockan, så växer det.")


def _stage_footer(n_days: int) -> str:
    if n_days < STAGE2_DAYS:
        return (f"Selvra har {n_days} dagar med data från dig. Vid {STAGE2_DAYS} dagar lär den sig ditt eget "
                "normala intervall för varje mått, i stället för att bara jämföra med snittet hittills.")
    return (f"Selvra har {n_days} dagar med data från dig och jämför med ditt eget normala. Om några veckor "
            "kan den föreslå en fråga om dig själv som går att pröva.")


def send(to: str, subject: str, body: str) -> None:
    user, password = os.environ.get("SELVRA_SMTP_USER"), os.environ.get("SELVRA_SMTP_PASSWORD")
    if not user or not password:
        raise SystemExit("SELVRA_SMTP_USER och SELVRA_SMTP_PASSWORD saknas i .env")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = f"Selvra <{user}>", to, subject
    msg.set_content(body)
    host = os.environ.get("SELVRA_SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP(host, int(os.environ.get("SELVRA_SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)


def _load_dotenv() -> None:
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, val = line.strip().partition("=")
        if sep and key.startswith("SELVRA_SMTP_") and key not in os.environ:
            os.environ[key.strip()] = val.strip().strip('"').strip("'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("person")
    parser.add_argument("--skicka", action="store_true", help="hämta ny data och skicka mejlet")
    args = parser.parse_args(argv)
    paths = person_paths(args.person)
    conf_path = paths["dir"] / "person.yml"
    if not conf_path.exists():
        raise SystemExit(f"{conf_path} saknas (namn, epost, kallor)")
    conf = yaml.safe_load(conf_path.read_text())
    if args.skicka and paths["token"].exists():
        load_garmin(paths["db"], FETCH_DAYS, paths["token"], paths["snapshots"])
    subject, body = compose(conf["namn"], read_days(paths["db"]), date.today(),
                            glukos=read_glucose(paths["db"]))
    if args.skicka:
        _load_dotenv()
        send(conf["epost"], subject, body)
        print(f"Skickat till {conf['epost']}: {subject}", file=sys.stderr)
    else:
        print(f"Ämne: {subject}\n\n{body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
