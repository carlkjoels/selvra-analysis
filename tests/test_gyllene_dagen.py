"""Gyllene dagen: hela morgonupplevelsen, från rå klockdata till push-payload.

Varje del av kedjan har egna tester; det här är testet som kör dem ihop, som en
riktig morgon: trettio dagars syntetisk Garmin-data i en riktig duckdb-fil →
read_days → compose → payload — och verifierar att brevet innehåller rätt fakta
i rätt ordning, att varningen tänds när klockan tystnat, och att inget som
lämnar motorn skulle fastna i språkgrinden. Ingen framtida ändring ska tyst
kunna göra morgonen konstig.
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from selvra_analysis import morgonmejl as mm
from selvra_analysis import morgonpush as mp
from selvra_analysis import sprakgrind
from selvra_analysis.dreamer import _svar_ur_rapport

IDAG = date(2026, 10, 28)


def _dagar(idag: date = IDAG, antal: int = 30) -> pd.DataFrame:
    rows = []
    for i in range(antal - 1, -1, -1):
        d = idag - timedelta(days=i)
        rows.append({"reading_date": d,
                     "sleep_score": 80, "readiness_score": 70,
                     "total_sleep_seconds": 25200 + (i % 4) * 300,
                     "deep_sleep_seconds": 5400, "rem_sleep_seconds": 4800,
                     "sleep_efficiency_pct": 90.0,
                     "hrv_avg_ms": 85.0 + (i % 4),
                     "hr_lowest_bpm": 52.0 + (i % 3),
                     "steps": 6000 + (i % 5) * 200})
    df = pd.DataFrame(rows)
    # Nattens värden ligger på dagens datum; gårdagen var en ovanligt lång promenaddag.
    df.loc[df["reading_date"] == idag, ["total_sleep_seconds", "hrv_avg_ms"]] = [27900, 78.0]
    df.loc[df["reading_date"] == idag - timedelta(days=1), ["steps", "hr_lowest_bpm"]] = [9800, 51.0]
    return df


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "selvra.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create schema raw")
        con.execute(
            "create table raw.garmin_daily (reading_date date, sleep_score integer, "
            "readiness_score integer, total_sleep_seconds integer, deep_sleep_seconds integer, "
            "rem_sleep_seconds integer, sleep_efficiency_pct double, hrv_avg_ms double, "
            "hr_lowest_bpm double, steps integer)")
        dagar = _dagar()  # noqa: F841 — läses av duckdbs replacement scan på raden under
        con.execute("insert into raw.garmin_daily select * from dagar")
    return path


def test_morgonen_fran_db_till_payload(db):
    df = mm.read_days(db)
    subject, body = mm.compose("Kari", df, IDAG)

    assert subject == f"Selvra {mm.WEEKDAYS[IDAG.weekday()]} {IDAG.day}/{IDAG.month}"
    assert body.startswith("God morgon Kari,")
    assert "synkat" not in body

    # Rätt fakta i rätt ordning: steg, sömn, vilopuls, HRV.
    ordning = ["steg i går", "sömn i natt", "vilopulsen", "HRV"]
    lagen = [body.index(s) for s in ordning]
    assert lagen == sorted(lagen)

    # 9 800 steg ligger över hans vanliga band och ska sägas så.
    stegrad = next(line for line in body.splitlines() if "steg i går" in line)
    assert "över ditt vanliga" in stegrad
    assert body.rstrip().endswith("Selvra")

    # Brevet är rådfritt och lagom långt — samma grind som AI-texten möter.
    ok, skal = sprakgrind.granska_text(body, body)
    assert ok, skal

    p = mp.payload(subject, body, IDAG, timme=7)
    assert p["titel"] == subject
    assert p["text"] == body
    assert p["datum"] == f"{IDAG.day}/{IDAG.month}"
    assert p["kort"]
    assert not p["kort"].startswith("Garmin")
    assert len(p["kort"]) <= mp.SHORT_MAX

    # Rubriken följer klockslaget: en kvällsdom får inte stå under "Morgonen".
    assert p["rubrik"] == "Morgonen"
    assert mp.payload(subject, body, IDAG, timme=12)["rubrik"] == "Dagen"
    assert mp.payload(subject, body, IDAG, timme=20)["rubrik"] == "Kvällen"


def test_tyst_klocka_varnar_forst():
    df = _dagar(idag=IDAG - timedelta(days=6))
    subject, body = mm.compose("Kari", df, IDAG)
    assert "klockan har inte synkat" in subject
    assert "synka" in body.splitlines()[2]

    p = mp.payload(subject, body, IDAG)
    assert "synkat" in p["kort"]


def test_tom_databas_sags_rakt_ut():
    tom = _dagar().iloc[0:0]  # tabellens kolumner, inga rader — som read_days före första synken
    _, body = mm.compose("Kari", tom, IDAG)
    assert "Garmin har ingen data" in body


# ---------------------------------------------------------------------------
# Språkgrinden: det pinsamma som aldrig får skickas.
# ---------------------------------------------------------------------------

KALLOR = ("Skattning +0,47 mmol/L (95 % intervall -1,60 till +1,24). "
          "12 av 23 dagar, vilopuls 52 slag/min.")


def test_grinden_stoppar_pahittade_matvarden():
    ok, skal = sprakgrind.granska_text("Effekten blev 0,8 mmol/L.", KALLOR)
    assert not ok
    assert "0.8" in skal


def test_grinden_slapper_arliga_matvarden():
    text = "Skattningen var 0,47 mmol/L med 95 % intervall från -1,60 till +1,24."
    ok, skal = sprakgrind.granska_text(text, KALLOR)
    assert ok, skal


def test_grinden_stoppar_rad():
    ok, skal = sprakgrind.granska_text("Du borde öka dosen på kvällen.", KALLOR)
    assert not ok
    assert "rådgivningsspråk" in skal


def test_grinden_stoppar_for_langt():
    ok, skal = sprakgrind.granska_text("x" * 3000, KALLOR, max_tecken=2000)
    assert not ok
    assert "för lång" in skal


def test_rena_antal_utan_enhet_ar_fria():
    # "17 dagar" är ett antal, inte ett mätvärde — grinden bryr sig om enheter.
    ok, _ = sprakgrind.granska_text("Efter 17 dagar till går frågan att pröva.", KALLOR)
    assert ok


def test_reserven_ar_rapportens_eget_svar():
    rapport = ("# Titel\n\n## Svar\n\n**Tesen motbevisad.** Skattning +0,00 slag/min.\n\n"
               "## Metod\n\nBlockbootstrap.\n")
    svar = _svar_ur_rapport(rapport)
    assert svar.startswith("**Tesen motbevisad.**")
    assert "språkgrinden" in svar
    assert "Blockbootstrap" not in svar


def test_cgm_rader_forst_med_egna_band():
    """En CGM-person ser glukossnitt + målområde först, mot sina egna percentiler,
    och möts inte av klockvarning innan klockan ens finns."""
    dagar = [IDAG - timedelta(days=i) for i in range(29, 0, -1)]
    mean = [9.0 + (i % 5) * 0.5 for i in range(29)]
    tir = [60.0 + (i % 4) * 5 for i in range(29)]
    mean[-1], tir[-1] = 14.5, 25.0   # i går avvek tydligt → essensen visar raderna
    glukos = pd.DataFrame({"reading_date": dagar, "mean_mmol": mean, "tir_pct": tir})
    subject, body = mm.compose("Carl", pd.DataFrame(), IDAG, glukos=glukos)
    assert "glukossnittet" in body
    assert "målområdet" in body
    assert "ditt vanliga" in body
    assert "mmol/L" in body.split("\n")[2]  # CGM-raden är första faktaraden
    assert "synkat" not in subject
    assert "Garmin har ingen data" not in body

    p = mp.payload(subject, body, IDAG, timme=7)
    assert "glukossnittet" in p["kort"]


def test_extrarader_ar_faktarader_och_raknas() -> None:
    tom = _dagar().iloc[0:0]
    _, body = mm.compose("Carl", tom, IDAG, extra=["CGM:n i natt 00–06: snitt 6,8 mmol/L."])
    assert "- CGM:n i natt" in body
    assert "Inga nya värden" not in body  # en extrarad är ett värde


def test_sviten_beskriver_aldrig_konfetti() -> None:
    dagar = [IDAG - timedelta(days=i) for i in range(25, 0, -1)]
    glukos = pd.DataFrame({"reading_date": dagar, "mean_mmol": [8.0] * 25})
    rad = mm._svit_rad(glukos, IDAG)
    assert rad is not None
    assert "i rad inom ditt vanliga" in rad
    assert "🔥" not in rad  # beskrivning, inte streak-konfetti
    assert "!" not in rad

    # Gårdagen utanför bandet → ingen svit, ingen rad.
    glukos.loc[glukos["reading_date"] == IDAG - timedelta(days=1), "mean_mmol"] = 15.0
    assert mm._svit_rad(glukos, IDAG) is None


def test_natt_och_form_tiger_utan_tabell(tmp_path) -> None:
    # En databas utan intermediate-schema (wearable-only-person) ger tystnad, inte krasch.
    db = tmp_path / "t.duckdb"
    duckdb.connect(str(db)).close()
    assert mm._natt_rad(db, IDAG) is None
    assert mm._form_rad(db, IDAG) is None
    assert mm._handelse_rad(db, IDAG) is None


def test_framstegsraden_ar_akta_aldrig_fabricerad() -> None:
    # äkta framsteg mot en dom, aldrig gamification
    rad = mm.framstegsrad(5, 12, "din sömnstudie")
    assert rad is not None
    assert "5 av 12 kompletta par" in rad
    assert "Ännu 7 par" in rad
    for konfetti in ("🎉", "🔥", "grattis", "!"):
        assert konfetti not in rad

    # målet nått → tystnad (då talar förslagsgrinden), och inget mål → tystnad
    assert mm.framstegsrad(12, 12, "x") is None
    assert mm.framstegsrad(15, 12, "x") is None
    assert mm.framstegsrad(5, 0, "x") is None


def _lugn(antal: int = 20, idag: date = IDAG) -> pd.DataFrame:
    """Lugna dagar med konstanta värden, så i går/i natt ligger inom det egna bandet."""
    return pd.DataFrame([{
        "reading_date": idag - timedelta(days=i), "sleep_score": 80, "readiness_score": 70,
        "total_sleep_seconds": 25200, "deep_sleep_seconds": 5400, "rem_sleep_seconds": 4800,
        "sleep_efficiency_pct": 90.0, "hrv_avg_ms": 85.0, "hr_lowest_bpm": 52.0, "steps": 6000,
    } for i in range(antal - 1, -1, -1)])


def test_essens_tiger_om_allt_ligger_inom_vanliga() -> None:
    _, body = mm.compose("Kari", _lugn(), IDAG)
    assert "I går låg allt inom ditt vanliga." in body
    assert "- " not in body            # inga faktarader
    assert "steg i går" not in body
    assert "vilopulsen" not in body
    assert "i rad" not in body         # ingen streak (konstitutionen)
    assert "Selvra har" not in body    # ingen inlärnings-fotnot i stage2


def test_essens_visar_bara_avvikelsen() -> None:
    df = _lugn()
    df.loc[df["reading_date"] == IDAG - timedelta(days=1), "steps"] = 16000  # i går avvek
    _, body = mm.compose("Kari", df, IDAG)
    assert "16 000 steg" in body
    assert "över ditt vanliga" in body
    assert "vilopulsen" not in body    # inom → tyst
    assert "Resten låg inom ditt vanliga." in body


def test_essens_inlarningsfas_visar_matt_och_fotnot() -> None:
    _, body = mm.compose("Kari", _lugn(antal=8), IDAG)   # < STAGE2_DAYS
    assert "steg i går" in body                          # inlärning: måtten visas
    assert "Hittills brukar det vara" in body
    assert "Selvra har" in body                          # inlärnings-fotnoten kvar
    assert "inom ditt vanliga" not in body               # inget band än
