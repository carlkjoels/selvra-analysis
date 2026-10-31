"""Källjämförelsen: klockans egna filer är facit, hämtvägarna jämförs mot det.

Mätlagret (METODPLAN §6): vad tappas eller förvanskas mellan klockan och ett
API-svar? Facit är FIT-filerna från egen klocka (egen data, läst via USB →
data/fit/, gitignorerad). Jämförelsen diffar dagliga aggregat fält för fält
mot de hämtvägar Selvra använder: steg, sömn per stadium, vilopuls, HRV —
plus det lömska: tidszoner och dagsgränser (en natt som slutar 07:10 — vilken
dag tillhör den, enligt vem?).

Bara aggregat lämnar skriptet; inga rådata i repot. Utdata:
data/rapporter/api-jamforelse.md (gitignorerat som allt under data/).

    make api-jamforelse                 # FIT mot garminconnect (person: carl)
    ... --kalla-json data/kalla.json    # + ytterligare källa, ur exporterad dump

Ärlighetsnoter, tills riktiga filer setts (klockan kommer 2026-10-30):
- Stegen i monitoring-FIT är kumulativa per aktivitetstyp; dagssumman är
  summan av max per typ. Verifieras mot klockans egen display första dagen.
- "Vilopuls" har olika definitioner per källa; när FIT saknar uttryckligt
  resting_heart_rate rapporteras min(samples) och MÄRKS som sådan — skillnaden
  är ett fynd, inte ett fel i skriptet.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import fitdecode
import pandas as pd

from selvra_analysis.ingest_garmin import _fetch, _login_with_token, person_paths

FIT_DIR = Path("data/fit")
UT = Path("data/rapporter/api-jamforelse.md")
FALT = ["steps", "total_sleep_seconds", "deep_sleep_seconds", "rem_sleep_seconds",
        "hr_lowest_bpm", "hrv_avg_ms"]
GARMIN_EPOCH = datetime(1989, 12, 31)

# Trösklar låsta 2026-10-29 (mätlagret, METODPLAN §6). En "signal" betyder att
# en hämtväg avviker meningsfullt från klockans egna filer — ett fynd om vägen,
# inte ett fel i skriptet. Trösklarna är versionerade: den AKTIVA uppsättningen
# är alltid sista raden i TROSKEL_HISTORIK. Att ändra ett tal = lägga en NY rad
# med nytt datum. test_troskel_sista_raden_ar_fryst fryser sista raden och
# failar om ett värde ändras utan en ny datumrad.
TROSKEL_HISTORIK = [
    {
        "datum": "2026-10-29",
        "somn_min": 15,      # minuter per sömnstadium (total, djup, REM)
        "somn_andel": 0.10,  # signal om gränsen överskrids på fler än 10 % av nätterna
        "hrv_ms": 5,         # millisekunder
        "hrv_andel": 0.10,   # på fler än 10 % av nätterna
        # steg och vilopuls har ingen talgräns — signalen är strukturell:
        # flyttad dag (värdet landade på fel dygn) eller saknat värde.
        "steg_vilopuls": "flyttad dag eller saknat värde",
    },
]
TROSKLAR = TROSKEL_HISTORIK[-1]

SOMNFALT = ("total_sleep_seconds", "deep_sleep_seconds", "rem_sleep_seconds")
STRUKTURFALT = ("steps", "hr_lowest_bpm")  # bedöms på flyttad dag / saknat värde


def _fit_tid(v) -> datetime | None:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, int):
        return GARMIN_EPOCH + timedelta(seconds=v)
    return None


class _Ack:
    """Ackumulator för dagliga aggregat under FIT-läsningen."""

    def __init__(self) -> None:
        self.steg_max: dict[tuple[date, int], int] = defaultdict(int)
        self.somn: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.puls_min: dict[date, int] = {}
        self.rhr: dict[date, int] = {}
        self.hrv: dict[date, float] = {}
        self.offset_sek: set[int] = set()
        self.noter: list[str] = []


def _ta_monitoring(a: _Ack, f: dict, dag: date) -> None:
    if isinstance(f.get("steps"), int):
        typ = int(f.get("activity_type") or 0)
        a.steg_max[(dag, typ)] = max(a.steg_max[(dag, typ)], f["steps"])
    if isinstance(f.get("heart_rate"), int) and f["heart_rate"] > 0:
        a.puls_min[dag] = min(a.puls_min.get(dag, 300), f["heart_rate"])


def _ta_somn(a: _Ack, f: dict, ts: datetime) -> None:
    # nivåer per Garmin: 1 vaken, 2 lätt, 3 djup, 4 REM; natten tillhör
    # uppvakningsdagen — dagsgränsregeln är låst i test_api_jamforelse
    niva = f.get("sleep_level")
    dag = ts.date() if ts.hour < 12 else (ts + timedelta(days=1)).date()
    if niva in (2, 3, 4):
        a.somn[dag]["total_sleep_seconds"] += 60
    namn = {3: "deep_sleep_seconds", 4: "rem_sleep_seconds"}.get(niva)
    if namn:
        a.somn[dag][namn] += 60


def _ta_frame(a: _Ack, frame) -> None:
    f = {x.name: x.value for x in frame.fields}
    ts, lokal = _fit_tid(f.get("timestamp")), _fit_tid(f.get("local_timestamp"))
    if ts and lokal:
        a.offset_sek.add(int((lokal - ts).total_seconds()))
    if not ts:
        return
    dag = (lokal or ts).date()
    if frame.name == "monitoring":
        _ta_monitoring(a, f, dag)
    elif frame.name == "monitoring_info" and isinstance(f.get("resting_heart_rate"), int):
        a.rhr[dag] = f["resting_heart_rate"]
    elif frame.name == "sleep_level":
        _ta_somn(a, f, ts)
    elif frame.name in ("hrv_status_summary", "hrv_summary"):
        v = f.get("last_night_average") or f.get("weekly_average")
        if v:
            a.hrv[dag] = float(v)


def _las_fil(a: _Ack, fil: Path, sedda: dict[str, int] | None = None) -> None:
    try:
        with fitdecode.FitReader(fil) as fr:
            datameddelanden = (f for f in fr if isinstance(f, fitdecode.FitDataMessage))
            for frame in datameddelanden:
                if sedda is not None:
                    sedda[frame.name] += 1
                _ta_frame(a, frame)
    except Exception as err:  # noqa: BLE001 — en trasig fil fäller inte jämförelsen
        a.noter.append(f"{fil.name}: kunde inte läsas ({err})")


def las_fit_mapp(mapp: Path) -> tuple[pd.DataFrame, list[str]]:
    """Dagliga aggregat ur alla FIT-filer i mappen, plus noter om vad som saknades."""
    a = _Ack()
    filer = sorted(mapp.glob("**/*.[fF][iI][tT]"))
    if not filer:
        a.noter.append(f"inga FIT-filer i {mapp} — lägg klockans GARMIN/Monitor + Sleep där")
    for fil in filer:
        _las_fil(a, fil)

    dagssteg: dict[date, int] = defaultdict(int)
    for (d, _typ), v in a.steg_max.items():
        dagssteg[d] += v
    dagar = sorted(set(dagssteg) | set(a.somn) | set(a.puls_min) | set(a.rhr) | set(a.hrv))
    rader = [{
        "reading_date": d,
        "steps": dagssteg.get(d),
        "total_sleep_seconds": a.somn[d].get("total_sleep_seconds") or None,
        "deep_sleep_seconds": a.somn[d].get("deep_sleep_seconds") or None,
        "rem_sleep_seconds": a.somn[d].get("rem_sleep_seconds") or None,
        "hr_lowest_bpm": a.rhr.get(d, a.puls_min.get(d)),
        "hrv_avg_ms": a.hrv.get(d),
    } for d in dagar]
    a.noter += [f"{d}: FIT saknar resting_heart_rate; min(samples)={a.puls_min[d]} används, märkt"
                for d in dagar if d in a.puls_min and d not in a.rhr]
    if a.offset_sek:
        a.noter.append("FIT lokal UTC-offset: "
                       + ", ".join(f"{s / 3600:+.0f} h" for s in sorted(a.offset_sek)))
    return pd.DataFrame(rader), a.noter


FALT_KALLKRAV = {
    # Vilket FIT-meddelande som måste finnas i klockans filer för att fältet
    # ska ha ett klock-facit. Saknas det räknas värdet ut på Garmins servrar,
    # och jämförelsen för det fältet blir Connect mot aggregator — svagare,
    # och ska redovisas så.
    "steps": "monitoring",
    "hr_lowest_bpm": "monitoring_info (resting_heart_rate), annars min(samples)",
    "total_sleep_seconds": "sleep_level",
    "deep_sleep_seconds": "sleep_level",
    "rem_sleep_seconds": "sleep_level",
    "hrv_avg_ms": "hrv_status_summary/hrv_summary",
}


def inventera(mapp: Path) -> str:
    """Första dagen klockan är kopplad: finns facit i klockans filer, per fält?

    Tabellen avgör vad jämförelsen får påstå: klock-facit = riktig jämförelse;
    server-beräknat = Connect mot aggregator, vilket bara mäter transport."""
    a = _Ack()
    sedda: dict[str, int] = defaultdict(int)
    for fil in sorted(mapp.glob("**/*.[fF][iI][tT]")):
        _las_fil(a, fil, sedda)
    har = {
        "steps": bool(a.steg_max), "hr_lowest_bpm": bool(a.rhr or a.puls_min),
        "total_sleep_seconds": bool(a.somn), "deep_sleep_seconds": bool(a.somn),
        "rem_sleep_seconds": bool(a.somn), "hrv_avg_ms": bool(a.hrv),
    }
    rader = ["| fält | facit i klockan? | källa | kräver |", "|---|---|---|---|"]
    for falt in FALT:
        kalla = ("KLOCKAN" if har[falt] else "SERVERN (Connect — svagare jämförelse)")
        if falt == "hr_lowest_bpm" and a.puls_min and not a.rhr:
            kalla = "KLOCKAN, men som min(samples) — inte Garmins RHR-definition"
        rader.append(f"| {falt} | {'ja' if har[falt] else 'NEJ'} | {kalla} | {FALT_KALLKRAV[falt]} |")
    rader += ["", "Meddelandetyper i filerna: "
              + (", ".join(f"{k}×{v}" for k, v in sorted(sedda.items())) or "(inga)")]
    rader += [f"- {n}" for n in a.noter]
    return "\n".join(rader)


def las_garminconnect(person: str, dagar: list[date]) -> pd.DataFrame:
    g = _login_with_token(person_paths(person)["token"])
    df = _fetch(g, min(dagar), max(dagar))
    df["reading_date"] = pd.to_datetime(df["reading_date"]).dt.date
    return df[df["reading_date"].isin(set(dagar))]


def las_kalla_json(fil: Path) -> pd.DataFrame:
    """Extern källdump (exporterad för hand) → samma kolumnnamn; redan-
    harmoniserad JSON accepteras tills en riktig mappning behövs."""
    rader = json.loads(fil.read_text())
    df = pd.DataFrame(rader)
    df["reading_date"] = pd.to_datetime(df["reading_date"]).dt.date
    return df


def diffa(facit: pd.DataFrame, kallor: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """En rad per dag × fält: facit, varje källas värde och avvikelse."""
    rader = []
    for _, fr in facit.iterrows():
        d = fr["reading_date"]
        for falt in FALT:
            rad = {"datum": d, "falt": falt, "fit": fr.get(falt)}
            for namn, df in kallor.items():
                tr = df[df["reading_date"] == d]
                v = tr[falt].iloc[0] if (not tr.empty and falt in tr) else None
                rad[namn] = v
                rad[f"{namn}_diff"] = (
                    None if v is None or pd.isna(v) or rad["fit"] is None or pd.isna(rad["fit"])
                    else float(v) - float(rad["fit"]))
            rader.append(rad)
    return pd.DataFrame(rader)


def _strukturfynd(f: pd.DataFrame, kalla: str, falt: str,
                  kalladf: pd.DataFrame | None = None) -> tuple[int, int]:
    """Steg/vilopuls: räkna dagar där facit finns men källan saknar värdet.
    Finns samma värde (inom tolerans) på en grannedag räknas det som en flyttad
    dag, annars som saknat värde — båda är en signal. Granndagarna läses helst
    ur källans fulla serie (kalladf, kolumn=fältnamn); annars ur de facit-dagar
    som finns i f (kolumn=källans namn)."""
    if kalladf is not None and "reading_date" in kalladf and falt in kalladf:
        varden = {r["reading_date"]: r[falt] for _, r in kalladf.iterrows()}
    else:
        varden = {r["datum"]: r[kalla] for _, r in f.iterrows()}
    saknade = flyttade = 0
    for _, r in f[f["fit"].notna()].iterrows():
        v = r[kalla]
        if v is not None and not pd.isna(v):
            continue
        facitv = float(r["fit"])
        tol = max(1.0, 0.05 * abs(facitv))
        grannar = [varden.get(r["datum"] - timedelta(days=1)),
                   varden.get(r["datum"] + timedelta(days=1))]
        if any(g is not None and not pd.isna(g) and abs(float(g) - facitv) <= tol
               for g in grannar):
            flyttade += 1
        else:
            saknade += 1
    return saknade, flyttade


def bedom_signal(diff: pd.DataFrame,
                 kallor_df: dict[str, pd.DataFrame] | None = None) -> list[dict]:
    """Per fält × källa: SIGNAL eller INGEN SIGNAL mot de låsta trösklarna.

    Sömn och HRV: signal om avvikelsen överskrider talgränsen på fler än andelen
    av nätterna. Steg och vilopuls: signal vid flyttad dag eller saknat värde.
    Ges källornas fulla serier (kallor_df) kan en flyttad dag ses även utanför
    facit-dagarna. Returnerar rader {falt, kalla, signal (bool), motivering}."""
    kallor = [c for c in diff.columns
              if c not in ("datum", "falt", "fit") and not c.endswith("_diff")]
    kallor_df = kallor_df or {}
    ut = []
    for falt in FALT:
        f = diff[diff["falt"] == falt]
        facit_rader = f[f["fit"].notna()]
        n = len(facit_rader)
        for kalla in kallor:
            if falt in SOMNFALT or falt == "hrv_avg_ms":
                somn = falt in SOMNFALT
                grans = TROSKLAR["somn_min"] * 60 if somn else TROSKLAR["hrv_ms"]
                andel_grans = TROSKLAR["somn_andel"] if somn else TROSKLAR["hrv_andel"]
                visat = TROSKLAR["somn_min"] if somn else TROSKLAR["hrv_ms"]
                enhet = "min" if somn else "ms"
                over = facit_rader[facit_rader[f"{kalla}_diff"].abs() > grans]
                andel = len(over) / n if n else 0.0
                signal = n > 0 and andel > andel_grans
                mot = (f"{len(over)}/{n} nätter avviker >{visat} {enhet} "
                       f"({andel:.0%} mot gräns {andel_grans:.0%})")
            else:  # steg, vilopuls — strukturellt
                saknade, flyttade = _strukturfynd(f, kalla, falt, kallor_df.get(kalla))
                signal = (saknade + flyttade) > 0
                delar = (([f"{flyttade} flyttad dag"] if flyttade else [])
                         + ([f"{saknade} saknat värde"] if saknade else []))
                mot = ", ".join(delar) if delar else "alla dagar på plats"
            ut.append({"falt": falt, "kalla": kalla, "signal": signal, "motivering": mot})
    return ut


def rapport(diff: pd.DataFrame, noter: list[str], kallor: list[str],
            signaler: list[dict] | None = None) -> str:
    rader = ["# API-jämförelse: FIT-facit mot API-svar", "",
             (f"*{diff['datum'].nunique()} dagar · källor: {', '.join(kallor)} · "
              "bara aggregat — rådatan bor i data/fit/ (gitignorerad)*"), ""]
    for falt in FALT:
        f = diff[diff["falt"] == falt]
        rader += [f"## {falt}", "", "| datum | FIT (facit) | " + " | ".join(
            f"{k} | diff" for k in kallor) + " |",
            "|---|---|" + "---|---|" * len(kallor)]
        for _, r in f.iterrows():
            celler = [str(r["datum"]), _c(r["fit"])]
            for k in kallor:
                celler += [_c(r[k]), _c(r.get(f"{k}_diff"))]
            rader.append("| " + " | ".join(celler) + " |")
        rader.append("")
    if noter:
        rader += ["## Noter (definitioner, saknade fält, tidszoner)", ""]
        rader += [f"- {n}" for n in noter]
    signaler = bedom_signal(diff) if signaler is None else signaler
    bildtext = (f"*sömn >{TROSKLAR['somn_min']} min och HRV >{TROSKLAR['hrv_ms']} ms på "
                f">{TROSKLAR['somn_andel']:.0%} av nätterna; steg och vilopuls: "
                f"{TROSKLAR['steg_vilopuls']}*")
    rader += ["", f"## Signal per mått (trösklar låsta {TROSKLAR['datum']})", "",
              bildtext, ""]
    for s in signaler:
        etikett = "**SIGNAL**" if s["signal"] else "INGEN SIGNAL"
        rader.append(f"- {s['falt']} · {s['kalla']}: {etikett} — {s['motivering']}")
    return "\n".join(rader) + "\n"


def _c(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:+.0f}" if isinstance(v, float) else str(v)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--person", default="carl")
    p.add_argument("--fit", type=Path, default=FIT_DIR)
    p.add_argument("--kalla-json", type=Path, default=None)
    p.add_argument("--dagar", type=int, default=14)
    p.add_argument("--inventera", action="store_true",
                   help="per fält: kommer facit från klockan eller servern?")
    args = p.parse_args(argv)

    if args.inventera:
        print(inventera(args.fit))
        return 0

    facit, noter = las_fit_mapp(args.fit)
    if facit.empty:
        print("\n".join(noter), file=sys.stderr)
        return 1
    dagar = sorted(facit["reading_date"])[-args.dagar:]
    facit = facit[facit["reading_date"].isin(dagar)]

    kallor = {"garminconnect": las_garminconnect(args.person, dagar)}
    if args.kalla_json:
        kallor["extern"] = las_kalla_json(args.kalla_json)

    diff = diffa(facit, kallor)
    signaler = bedom_signal(diff, kallor)
    UT.parent.mkdir(parents=True, exist_ok=True)
    UT.write_text(rapport(diff, noter, list(kallor), signaler))
    print(f"skrev {UT} ({len(dagar)} dagar)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
