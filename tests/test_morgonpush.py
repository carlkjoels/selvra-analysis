"""Keys, connecting a phone, the notification text, and encryption to a real subscription key."""

import base64
import json
import os
import time
from datetime import date
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPusher

from selvra_analysis import morgonpush as mp


def _subscription() -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return {"endpoint": "https://push.example/abc", "keys": {"p256dh": b64(raw), "auth": b64(b"0123456789abcdef")}}


def test_keys_write_only_the_public_key_to_the_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "web" / "morgon").mkdir(parents=True)
    public = mp.make_keys()
    assert len(base64.urlsafe_b64decode(public + "==")) == 65, "uncompressed P-256 point"
    assert public in (tmp_path / "web/morgon/config.js").read_text()
    assert "PRIVATE" not in (tmp_path / "web/morgon/config.js").read_text()
    assert (tmp_path / "data/push/vapid_private.pem").exists()


def test_the_code_from_the_page_connects_the_phone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sub = _subscription()
    out = mp.connect("testare-1", base64.b64encode(json.dumps(sub).encode()).decode())
    assert json.loads(out.read_text()) == sub
    assert out.is_relative_to(Path("data/personer/testare-1"))


def test_the_lock_screen_text_is_short_and_the_warning_comes_first() -> None:
    body = ("God morgon Kari,\n\nKlockan har inte synkat sedan 22/10. Öppna Garmin Connect-appen.\n\n"
            "- Garmin räknade 4 100 steg i går, inom ditt vanliga 2 500–5 700.\n\nSelvra\n")
    d = mp.payload("Selvra onsdag 28/10 – klockan har inte synkat", body, date(2026, 10, 28))
    assert d["kort"].startswith("Klockan har inte synkat")
    assert len(d["kort"]) <= mp.SHORT_MAX
    assert d["text"] == body


def test_the_report_encrypts_to_a_real_subscription_key() -> None:
    data = json.dumps(mp.payload("Selvra", "- Garmin räknade 4 100 steg i går.\n", date(2026, 10, 28)))
    encoded = WebPusher(_subscription()).encode(data.encode(), content_encoding="aes128gcm")
    assert encoded["body"]
    assert data.encode() not in encoded["body"]


# --- Punkt 3: n1-villkorsrad ur schema.csv + FIT-påminnelse för carl ---

def _lock_n1(mapp: Path, schema_rader: str) -> None:
    mapp.mkdir(parents=True)
    (mapp / "studie.yml").write_text(yaml.safe_dump({
        "id": mapp.name,
        "design": {"typ": "n1", "par": 12,
                   "A": "Styrkepass minst 60 minuter",
                   "B": "Vilodag, högst 15 minuter träning"},
    }, allow_unicode=True))
    (mapp / "schema.csv").write_text("# seed=1\ndate,pair,period,condition,order,washout\n" + schema_rader)
    (mapp / "las.json").write_text('{"locked_at": "2026-11-01"}')


def test_n1_villkorsrad_ger_dagens_villkor(tmp_path: Path) -> None:
    paths = {"dir": tmp_path / "p"}
    _lock_n1(paths["dir"] / "forslag" / "003-styrka-somn",
             "2026-11-02,3,5,A,AB,False\n")
    rad = mp.n1_villkorsrad("testare-1", paths, date(2026, 11, 2))
    assert rad is not None
    assert "003" in rad
    assert "par 3/12" in rad
    assert "A" in rad
    assert "Styrkepass minst 60 minuter" in rad


def test_n1_tvattdag_sags_rakt_ut(tmp_path: Path) -> None:
    paths = {"dir": tmp_path / "p"}
    _lock_n1(paths["dir"] / "forslag" / "003-x", "2026-11-02,3,5,B,AB,True\n")
    rad = mp.n1_villkorsrad("testare-1", paths, date(2026, 11, 2))
    assert "tvättdag" in rad


def test_n1_tyst_utan_rad_for_idag(tmp_path: Path) -> None:
    paths = {"dir": tmp_path / "p"}
    _lock_n1(paths["dir"] / "forslag" / "003-x", "2026-11-02,3,5,A,AB,False\n")
    assert mp.n1_villkorsrad("testare-1", paths, date(2026, 12, 24)) is None


def test_n1_tyst_utan_lock(tmp_path: Path) -> None:
    paths = {"dir": tmp_path / "p"}
    mapp = paths["dir"] / "forslag" / "003-x"
    _lock_n1(mapp, "2026-11-02,3,5,A,AB,False\n")
    (mapp / "las.json").unlink()  # inte låst → ingen rad
    assert mp.n1_villkorsrad("testare-1", paths, date(2026, 11, 2)) is None


def test_fit_paminnelse_nar_gammal(tmp_path: Path) -> None:
    fit = tmp_path / "fit"
    fit.mkdir()
    gammal = fit / "2026-10-20.fit"
    gammal.write_bytes(b"x")
    atta_dagar_sen = time.time() - 8 * 86400
    os.utime(gammal, (atta_dagar_sen, atta_dagar_sen))
    rad = mp.fit_paminnelse(date.today(), mapp=fit)
    assert rad is not None
    assert "FIT-filen" in rad


def test_fit_paminnelse_tyst_om_farsk(tmp_path: Path) -> None:
    fit = tmp_path / "fit"
    fit.mkdir()
    (fit / "idag.fit").write_bytes(b"x")  # nyss skriven → färsk
    assert mp.fit_paminnelse(date.today(), mapp=fit) is None


def test_fit_paminnelse_nar_inga_filer(tmp_path: Path) -> None:
    rad = mp.fit_paminnelse(date.today(), mapp=tmp_path / "tom")
    assert rad is not None
    assert "inga FIT-filer" in rad
