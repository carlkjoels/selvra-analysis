"""Utforskande samband: planterad effekt hittas, ingen effekt sticker inte ut,
firmware tillskrivs firmware, för lite data ger null, saknat är inte noll,
förbjudna kolumner vägras, överlappande datafönster vägras i låsflödet.

All data är syntetisk — inga riktiga hälsodata i tester.
"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from selvra_analysis import study
from selvra_analysis import utforskande_samband as us

TOM = Path("/nonexistent-studies-dir")  # hermetiskt: läs aldrig riktiga studies/ i tester

TESTCFG = {
    "min_dagar": 60, "blocklangd": 7, "n_boot": 300,
    "faktorer": ["steg", "traningsminuter", "traning_efter_18", "dagstyp"],
    "kovariater": ["apparat", "firmware"],
    "utfall": ["nattglukos"],
    "del_av": {"nattglukos": []},
    "forbjudet": ["insulin", "kolhydratkvot", "hypobehandling"],
    "uppskattning": ["stress"],
}


def _syntetisk(n: int, *, seed: int, effekt: float = 0.0, faktor: str = "steg",
               firmware: str = "12.18", start: str = "2026-01-01", brus: float = 0.3) -> pd.DataFrame:
    """n på varandra följande dagar. Utfallet dag d beror på faktorn dag d-1
    (natten t→t+1), aldrig samma dygn."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n, freq="D")
    df = pd.DataFrame({
        "reading_date": dates.astype(str),
        "steg": rng.integers(2000, 12000, n).astype(float),
        "traningsminuter": rng.integers(0, 90, n).astype(float),
        "traning_efter_18": rng.integers(0, 2, n).astype(float),
        "dagstyp": (dates.day_of_week >= 5).astype(float),
        "apparat": "Venu 3",
        "firmware": firmware,
    })
    base = rng.normal(6.5, brus, n)
    drive = df[faktor].to_numpy()
    z = (drive - drive.mean()) / drive.std() if drive.std() > 0 else drive * 0.0
    base[1:] += effekt * z[:-1]      # faktor dag d-1 → utfall dag d
    df["nattglukos"] = base
    return df


def _rad(res: list[dict], faktor: str) -> dict:
    return next(f for f in res[0]["faktorer"] if f["faktor"] == faktor)


# 1. Planterad effekt hittas; intervallet täcker det sanna värdet.
def test_planterad_effekt_hittas() -> None:
    df = _syntetisk(120, seed=1, effekt=1.0, faktor="steg")
    res = us.kor(df, TESTCFG, "nattglukos", seed=1, studies_dir=TOM)
    assert res[0]["underlag"] is True
    steg = _rad(res, "steg")
    assert steg["ci_low"] <= 1.0 <= steg["ci_high"]   # intervallet täcker sanningen
    assert steg["ci_low"] > 0                          # och utesluter noll


# 2. Ingen effekt → faktorn sticker inte ut (intervallet rymmer noll).
def test_ingen_effekt_sticker_inte_ut() -> None:
    df = _syntetisk(120, seed=2, effekt=0.0)
    res = us.kor(df, TESTCFG, "nattglukos", seed=2, studies_dir=TOM)
    steg = _rad(res, "steg")
    assert steg["ci_low"] < 0 < steg["ci_high"]        # rymmer noll
    assert len(us.fragor(res)) <= 1                     # inga/knappt falska förslag


# 3. Planterat firmwarehopp tillskrivs firmware, inte en faktor.
def test_firmwarehopp_tillskrivs_firmware() -> None:
    a = _syntetisk(90, seed=3, effekt=0.0, firmware="12.18", start="2026-01-01")
    b = _syntetisk(90, seed=4, effekt=0.0, firmware="13.00", start="2026-04-01")
    b["nattglukos"] = b["nattglukos"] + 2.0            # nivåhopp vid firmwarebytet
    df = pd.concat([a, b], ignore_index=True)
    res = us.kor(df, TESTCFG, "nattglukos", seed=3, studies_dir=TOM)
    assert len(res) == 2                                # ett segment per firmware
    for seg in res:
        steg = next(f for f in seg["faktorer"] if f["faktor"] == "steg")
        assert steg["ci_low"] < 0 < steg["ci_high"]    # hoppet blev inte en faktoreffekt


# 4. För få dagar → "inget underlag", ingen rangordning.
def test_for_fa_dagar_ger_inget_underlag() -> None:
    df = _syntetisk(40, seed=5, effekt=1.0)
    res = us.kor(df, TESTCFG, "nattglukos", seed=5, studies_dir=TOM)
    assert res[0]["underlag"] is False
    assert "min_dagar" in res[0]["skal"]
    assert "faktorer" not in res[0]


# 5. Saknade dagar räknas aldrig som noll — raden tappas, täckning redovisas.
def test_saknat_ar_inte_noll() -> None:
    df = _syntetisk(120, seed=6, effekt=1.0, faktor="steg")
    df.loc[df.index[:30], "steg"] = np.nan             # 30 dagar utan steg
    res = us.kor(df, TESTCFG, "nattglukos", seed=6, studies_dir=TOM)
    assert res[0]["tackning"]["steg"] < 0.8            # täckning < 100 %
    assert res[0]["n_dagar"] < 120                     # raderna tappades, inte nollade


# 6. Förbjuden kolumn i faktorlistan → vägras.
def test_forbjuden_kolumn_vagras() -> None:
    cfg = {**TESTCFG, "faktorer": ["steg", "insulin"]}
    df = _syntetisk(120, seed=7)
    with pytest.raises(ValueError, match="förbjudna"):
        us.kor(df, cfg, "nattglukos", seed=7, studies_dir=TOM)


# 6b. En faktor som är del av utfallet → vägras.
def test_faktor_som_ar_del_av_utfallet_vagras() -> None:
    cfg = {**TESTCFG, "faktorer": ["djupsomn_min"], "del_av": {"somnlangd": ["djupsomn_min"]}}
    df = _syntetisk(120, seed=8)
    df["somnlangd"] = df["nattglukos"]
    with pytest.raises(ValueError, match="del av utfallet"):
        us.kor(df, cfg, "somnlangd", seed=8, studies_dir=TOM)


# 7. Överlappande datafönster i låsflödet → vägras.
def test_overlappande_fonster_vagras_i_lasflodet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    us.spara_fonster("nattglukos", "2026-01-01", "2026-03-31")
    # observationsstudie vars period överlappar det analyserade fönstret
    krock = SimpleNamespace(kind="observation", design={"period": [date(2026, 3, 1), date(2026, 4, 15)]})
    with pytest.raises(study.StudyError, match="överlappar"):
        study._vagra_overlapp_med_samband(krock, {})
    # ett senare fönster passerar
    ok = SimpleNamespace(kind="observation", design={"period": [date(2026, 4, 1), date(2026, 5, 1)]})
    study._vagra_overlapp_med_samband(ok, {})          # ska inte kasta
    assert us.overlappande_fonster("2026-04-01", "2026-05-01") == []


# 9. Dagar i en LÅST studies fönster exkluderas och redovisas (omvänd spärr).
def test_lasta_studiens_dagar_exkluderas(tmp_path) -> None:
    sdir = tmp_path / "studies" / "001-x"
    sdir.mkdir(parents=True)
    (sdir / "studie.yml").write_text(yaml.safe_dump(
        {"id": "001-x", "design": {"typ": "observation", "period": ["2026-02-01", "2026-02-20"]}},
        allow_unicode=True))
    (sdir / "las.json").write_text('{"locked_at": "2026-02-21"}')
    df = _syntetisk(120, seed=9, effekt=1.0, faktor="steg", start="2026-01-01")
    res = us.kor(df, TESTCFG, "nattglukos", seed=9, studies_dir=tmp_path / "studies")
    exk = res[0]["exkluderade_dagar"]
    assert exk, "låsta studiens dagar ska exkluderas"
    assert all("2026-02-01" <= d <= "2026-02-20" for d in exk)      # exakt studiens fönster
    assert "001-x" in [w["studie"] for w in res[0]["lasta_studiefonster"]]
    assert res[0]["underlag"] is True                                # kvar räcker ändå


# 10. Saknad logg men befintlig rapport → låsning vägras (fail-closed).
def test_lasning_vagras_om_logg_saknas_men_rapport_finns(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    us.RAPPORT.parent.mkdir(parents=True, exist_ok=True)
    us.RAPPORT.write_text("# samband\n")               # rapport finns, men ingen fönsterlogg
    assert not us.FONSTER.exists()
    s = SimpleNamespace(kind="observation", design={"period": [date(2026, 4, 1), date(2026, 5, 1)]})
    with pytest.raises(study.StudyError, match="fönsterloggen"):
        study._vagra_overlapp_med_samband(s, {})
