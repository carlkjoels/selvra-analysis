"""API-jämförelsens diffning: facit mot källor, ärliga luckor, dagsgränser."""

from datetime import date, datetime

import pandas as pd

from selvra_analysis import api_jamforelse as aj
from selvra_analysis import rorlogg

FACIT = pd.DataFrame([
    {"reading_date": date(2026, 10, 30), "steps": 8000, "total_sleep_seconds": 25200,
     "deep_sleep_seconds": 5400, "rem_sleep_seconds": 4800, "hr_lowest_bpm": 46, "hrv_avg_ms": 70.0},
])


def test_diff_raknas_falt_for_falt() -> None:
    kalla = pd.DataFrame([{"reading_date": date(2026, 10, 30), "steps": 7850,
                           "total_sleep_seconds": 25200, "deep_sleep_seconds": 5100,
                           "rem_sleep_seconds": 4800, "hr_lowest_bpm": 47, "hrv_avg_ms": None}])
    diff = aj.diffa(FACIT, {"api": kalla})
    steg = diff[diff["falt"] == "steps"].iloc[0]
    assert steg["api_diff"] == -150
    hrv = diff[diff["falt"] == "hrv_avg_ms"].iloc[0]
    assert pd.isna(hrv["api_diff"])  # saknat värde är en lucka (NaN), aldrig en nolla


def test_saknad_dag_hos_kallan_blir_streck() -> None:
    kalla = pd.DataFrame([{"reading_date": date(2026, 10, 29), "steps": 1}])
    diff = aj.diffa(FACIT, {"api": kalla})
    assert pd.isna(diff[diff["falt"] == "steps"].iloc[0]["api"])


def test_rapporten_ar_bara_aggregat() -> None:
    kalla = FACIT.copy()
    text = aj.rapport(aj.diffa(FACIT, {"api": kalla}), ["not: test"], ["api"])
    assert "FIT (facit)" in text
    assert "rådatan bor i data/fit/" in text
    assert "not: test" in text


def test_natt_tillhor_uppvakningsdagen() -> None:
    # sleep_level 23:30 → nästa dag; 06:30 → samma dag: natten tillhör
    # uppvakningsdagen. Ändras regeln i _ta_somn måste detta test ändras medvetet.
    a = aj._Ack()
    aj._ta_somn(a, {"sleep_level": 3}, datetime(2026, 10, 29, 23, 30))
    aj._ta_somn(a, {"sleep_level": 4}, datetime(2026, 10, 30, 6, 30))
    assert set(a.somn) == {date(2026, 10, 30)}
    assert a.somn[date(2026, 10, 30)]["total_sleep_seconds"] == 120


def test_rorloggen_beskriver_roret_aldrig_manniskan(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rad = rorlogg.logga("garminconnect", "x", bibliotek="0.2.0", enhet="Venu 3",
                        firmware="12.18", dagar=10, rader=9, falt=["steps", "hrv_avg_ms"])
    assert rad["falt"] == ["hrv_avg_ms", "steps"]
    text = (tmp_path / "data" / "rorlogg.jsonl").read_text()
    assert "Venu 3" in text
    for forbjudet in ("mmol", "bpm_varde", "sleep_seconds_varde"):
        assert forbjudet not in text  # form, aldrig mätvärden


# --- Punkt 2: låsta trösklar + SIGNAL/INGEN SIGNAL per mått ---

def test_troskel_sista_raden_ar_fryst() -> None:
    # Fryst 2026-10-29. Ändra ett tal → lägg en NY datumrad i TROSKEL_HISTORIK
    # och uppdatera denna frysning medvetet. Annars failar testet — så ingen
    # tröskel kan glida utan att en datumrad skrivs.
    assert aj.TROSKLAR["datum"] == "2026-10-29"
    assert aj.TROSKLAR["somn_min"] == 15
    assert aj.TROSKLAR["somn_andel"] == 0.10
    assert aj.TROSKLAR["hrv_ms"] == 5
    assert aj.TROSKLAR["hrv_andel"] == 0.10
    assert aj.TROSKLAR["steg_vilopuls"] == "flyttad dag eller saknat värde"
    assert aj.TROSKLAR is aj.TROSKEL_HISTORIK[-1]  # aktiv = sista raden


def test_troskel_datum_unika_och_vaxande() -> None:
    datum = [r["datum"] for r in aj.TROSKEL_HISTORIK]
    assert datum == sorted(datum)
    assert len(datum) == len(set(datum))


def _diff(kalla: pd.DataFrame) -> pd.DataFrame:
    return aj.diffa(FACIT, {"api": kalla})


def test_somn_signal_over_troskeln() -> None:
    # 1 natt, djupsömn 20 min (1200 s) under facit → >15 min → 1/1 = 100 % > 10 %
    kalla = FACIT.copy()
    kalla["deep_sleep_seconds"] = 5400 - 1200
    s = {r["falt"]: r for r in aj.bedom_signal(_diff(kalla))}
    assert s["deep_sleep_seconds"]["signal"] is True


def test_somn_ingen_signal_under_troskeln() -> None:
    # avvikelse 10 min (600 s) < 15 min → ingen signal
    kalla = FACIT.copy()
    kalla["deep_sleep_seconds"] = 5400 - 600
    s = {r["falt"]: r for r in aj.bedom_signal(_diff(kalla))}
    assert s["deep_sleep_seconds"]["signal"] is False


def test_hrv_signal_over_fem_ms() -> None:
    kalla = FACIT.copy()
    kalla["hrv_avg_ms"] = 70.0 - 6  # 6 ms > 5 ms
    s = {r["falt"]: r for r in aj.bedom_signal(_diff(kalla))}
    assert s["hrv_avg_ms"]["signal"] is True


def test_steg_saknat_varde_ar_signal() -> None:
    kalla = FACIT.copy()
    kalla["steps"] = None  # facit finns, källan saknar → signal
    s = {r["falt"]: r for r in aj.bedom_signal(_diff(kalla))}
    assert s["steps"]["signal"] is True
    assert "saknat värde" in s["steps"]["motivering"]


def test_steg_flyttad_dag_ar_signal() -> None:
    # facit har steg på 30/10; källan har samma värde på 29/10, inget på 30/10
    facit = pd.DataFrame([{"reading_date": date(2026, 10, 30), "steps": 8000}])
    kalla = pd.DataFrame([{"reading_date": date(2026, 10, 29), "steps": 8000}])
    s = {r["falt"]: r
         for r in aj.bedom_signal(aj.diffa(facit, {"api": kalla}), {"api": kalla})}
    assert s["steps"]["signal"] is True
    assert "flyttad dag" in s["steps"]["motivering"]


def test_rapporten_slutar_med_signal_per_matt() -> None:
    text = aj.rapport(_diff(FACIT.copy()), [], ["api"])
    assert "## Signal per mått" in text
    assert "INGEN SIGNAL" in text  # identiska värden → ingen signal
    # signalavsnittet ligger sist
    assert text.rstrip().endswith(text.rstrip().split("## Signal per mått")[-1].rstrip())
