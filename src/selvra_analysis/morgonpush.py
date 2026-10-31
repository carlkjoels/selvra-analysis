"""Morgonrapporten som pushnotis till telefonen, via webbsidan i web/morgon.

Rapporten är densamma som morgonmejlet (morgonmejl.compose). Den skickas krypterad direkt
till telefonen (Web Push); webbsidan sparar den bara i telefonen. Ingen server lagrar den.

En gång, på datorn som skickar:
    uv run python -m selvra_analysis.morgonpush nycklar          # nyckelpar; committa web/morgon/config.js
En gång per telefon (koden kommer från sidan när notiserna slagits på):
    uv run python -m selvra_analysis.morgonpush koppla testare-1 KOD
Varje morgon:
    uv run python -m selvra_analysis.morgonpush skicka testare-1      # hämta ny data och skicka
    uv run python -m selvra_analysis.morgonpush visa testare-1        # visa vad som skulle skickas

Den privata nyckeln ligger i data/push/ (gitignored) och lämnar aldrig datorn.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import yaml
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from selvra_analysis import granska
from selvra_analysis import study as st
from selvra_analysis.forslag import forslagsrad
from selvra_analysis.ingest_garmin import load as load_garmin
from selvra_analysis.ingest_garmin import person_paths
from selvra_analysis.morgonmejl import (
    FETCH_DAYS,
    compose,
    extrarader,
    framstegsrad,
    read_days,
    read_glucose,
)
from selvra_analysis.trendvakt import trendrad

KEY_DIR = Path("data/push")
PRIVATE_KEY = KEY_DIR / "vapid_private.pem"
PUBLIC_CONFIG = Path("web/morgon/config.js")
CONTACT = "mailto:hello@selvra.ai"
SHORT_MAX = 170           # what a lock-screen notification shows
FIT_DIR = Path("data/fit")
FIT_PAMINNELSE_DAGAR = 7  # carl: påminn om senaste FIT-filen är äldre än så


def _public_key_b64(v: Vapid01) -> str:
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_keys(force: bool = False) -> str:
    if PRIVATE_KEY.exists() and not force:
        raise SystemExit(f"{PRIVATE_KEY} finns redan. Nya nycklar kopplar bort alla telefoner; använd --ny om du menar det.")
    v = Vapid01()
    v.generate_keys()
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    v.save_key(str(PRIVATE_KEY))
    public = _public_key_b64(v)
    PUBLIC_CONFIG.write_text("// Publik nyckel för morgonnotiser (den privata ligger bara på datorn som skickar)\n"
                             f'window.SELVRA_VAPID_PUBLIC = "{public}";\n')
    return public


def connect(person: str, code: str) -> Path:
    """Store the phone's push subscription, from the code the page shows (base64 JSON, or JSON)."""
    text = code.strip()
    try:
        sub = json.loads(text)
    except json.JSONDecodeError:
        sub = json.loads(base64.b64decode(text + "=" * (-len(text) % 4)).decode())
    if not sub.get("endpoint") or not (sub.get("keys") or {}).get("p256dh"):
        raise SystemExit("koden är inte en giltig push-prenumeration")
    out = person_paths(person)["dir"] / "push.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sub))
    return out


def payload(subject: str, body: str, today: date, timme: int | None = None) -> dict:
    """Title, the short lock-screen text, and the full report for the page."""
    facts = [line[2:] for line in body.splitlines() if line.startswith("- ")]
    warning = next((line for line in body.splitlines()[1:4] if "synkat" in line), None)
    short = warning or " · ".join(f.split(", ")[0].replace("Garmin ", "") for f in facts) or "Ingen ny data i natt."
    # Sidan rubricerar rapporten efter när den skickades — en dom som går ut på
    # kvällen ska inte stå under "Morgonen" (testare-1:s vidarebefordran 27/10).
    timme = datetime.now().hour if timme is None else timme
    rubrik = "Morgonen" if timme < 11 else "Dagen" if timme < 18 else "Kvällen"
    return {"titel": subject, "kort": short[:SHORT_MAX], "text": body,
            "rubrik": rubrik, "datum": f"{today.day}/{today.month}"}


def send(person: str, data: dict) -> None:
    sub_path = person_paths(person)["dir"] / "push.json"
    if not sub_path.exists():
        raise SystemExit(f"{person} har ingen kopplad telefon: kör `morgonpush koppla {person} KOD`")
    if not PRIVATE_KEY.exists():
        raise SystemExit("nycklarna saknas: kör `morgonpush nycklar`")
    try:
        webpush(subscription_info=json.loads(sub_path.read_text()), data=json.dumps(data, ensure_ascii=False),
                vapid_private_key=str(PRIVATE_KEY), vapid_claims={"sub": CONTACT}, ttl=12 * 3600)
    except WebPushException as err:
        status = getattr(err.response, "status_code", None)
        if status in (404, 410):
            raise SystemExit(f"telefonen har avregistrerat notiserna; öppna Selvra på telefonen, slå på igen "
                             f"och koppla den nya koden ({status})") from err
        raise


def _framstegsrad_for(person: str, paths: dict) -> str | None:
    """Äkta framsteg mot personens aktiva studieutkast, annars tystnad.
    Räknar giltiga utfallsdagar de senaste 90 dagarna mot studiens dagmål."""
    mapp = paths["dir"] / "forslag"
    if not mapp.exists():
        return None
    try:
        # Aktivt n1-utkast: har ett dagmål och är inte låst. Grindens egen
        # par-räkning är måttet — aldrig en lösare dagräkning som kan motsäga den.
        for fil in sorted(mapp.glob("*/studie.yml")):
            if (fil.parent / "las.json").exists():
                continue
            spec = yaml.safe_load(fil.read_text())
            if ((spec.get("design") or {}).get("dagar") or {}).get("datum"):
                break
        else:
            return None
        studie = st.load(fil)
        with duckdb.connect(str(paths["db"]), read_only=True) as con:
            res = granska.review(studie, con)
        for c in res.get("checks", []):
            m = re.search(r"kompletta par (\d+) av (\d+)", c.get("text", ""))
            if m:
                return framstegsrad(int(m.group(1)), int(m.group(2)),
                                    spec.get("titel", "din studie").lower())
        return None
    except (st.StudyError, duckdb.Error, KeyError, OSError):
        return None


def _las_schema(path: Path) -> list[dict]:
    """schema.csv → rader, kommentarraden (# seed=…) hoppas över."""
    rader = [r for r in path.read_text().splitlines() if r and not r.startswith("#")]
    return list(csv.DictReader(rader))


def _n1_studiemappar(person: str, paths: dict):
    """Mappar med en LÅST n1-studie (las.json) som har en schema.csv. Personens
    egna utkast + för carl repots studies/."""
    mappar = (list((paths["dir"] / "forslag").glob("*"))
              if (paths["dir"] / "forslag").exists() else [])
    if person == "carl" and Path("studies").exists():
        mappar += list(Path("studies").glob("[0-9][0-9][0-9]-*"))
    for mapp in mappar:
        if not (mapp.is_dir() and (mapp / "schema.csv").exists()
                and (mapp / "las.json").exists() and (mapp / "studie.yml").exists()):
            continue
        spec = yaml.safe_load((mapp / "studie.yml").read_text())
        if (spec.get("design") or {}).get("typ") == "n1":
            yield mapp, spec


def n1_villkorsrad(person: str, paths: dict, today: date) -> str | None:
    """En saklig rad med dagens villkor för en låst n1-studie, ordagrant ur
    schema.csv och studiens egna A/B-text. Tyst om ingen låst n1-studie har en
    rad för idag — aldrig en påhittad studie."""
    iso = today.isoformat()
    for mapp, spec in _n1_studiemappar(person, paths):
        rad = next((r for r in _las_schema(mapp / "schema.csv") if r.get("date") == iso), None)
        if not rad:
            continue
        design = spec.get("design") or {}
        nr = str(spec.get("id", mapp.name))[:3]
        par, total = rad.get("pair"), design.get("par")
        parstr = f"par {par}/{total}" if par and total else f"par {par}" if par else "pågår"
        if str(rad.get("washout")).lower() == "true":
            return f"Studie {nr} idag ({parstr}): tvättdag — inget villkor att hålla."
        villkor = design.get(rad.get("condition"), rad.get("condition"))
        return f"Studie {nr} idag ({parstr}): {rad.get('condition')} — {villkor}"
    return None


def fit_paminnelse(today: date, mapp: Path = FIT_DIR) -> str | None:
    """Carl: påminn när senaste FIT-filen är äldre än FIT_PAMINNELSE_DAGAR (eller
    saknas) — klockans facit för källjämförelsen ruttnar annars i tysthet."""
    filer = list(mapp.glob("**/*.[fF][iI][tT]")) if mapp.exists() else []
    if not filer:
        return ("Påminnelse: inga FIT-filer i data/fit/ än — koppla klockan via USB "
                "så får källjämförelsen sitt facit.")
    alder = (today - date.fromtimestamp(max(f.stat().st_mtime for f in filer))).days
    if alder > FIT_PAMINNELSE_DAGAR:
        return (f"Påminnelse: senaste FIT-filen är {alder} dagar gammal — koppla klockan "
                "via USB och lägg filerna i data/fit/ för färsk källjämförelse.")
    return None


def _report(person: str, fetch: bool) -> dict:
    paths = person_paths(person)
    conf = yaml.safe_load((paths["dir"] / "person.yml").read_text())
    if fetch and paths["token"].exists():  # CGM-person utan klocka ännu: inget att hämta
        load_garmin(paths["db"], FETCH_DAYS, paths["token"], paths["snapshots"])
    today = date.today()
    glukos = read_glucose(paths["db"])
    subject, body = compose(conf["namn"], read_days(paths["db"]), today,
                            glukos=glukos, extra=extrarader(paths["db"], today, glukos))
    if person == "carl" and not glukos.empty:
        body = body.rstrip() + "\n\nAGP-vyn uppdaterad i morse: selvra-morgonvy.html i Downloads.\n"
    frad = _framstegsrad_for(person, paths)
    if frad:
        body = body.rstrip() + "\n\n" + frad + "\n"
    trad = trendrad(person, paths["db"], today, skriv=fetch)
    if trad:
        body = body.rstrip() + "\n\n" + trad + "\n"
    rad = forslagsrad(person, paths["db"], today, bygg=fetch)
    if rad:
        body = body.rstrip() + "\n\n" + rad + "\n"
    n1rad = n1_villkorsrad(person, paths, today)
    if n1rad:
        body = body.rstrip() + "\n\n" + n1rad + "\n"
    if person == "carl":
        prad = fit_paminnelse(today)
        if prad:
            body = body.rstrip() + "\n\n" + prad + "\n"
    return payload(subject, body, today)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="kommando", required=True)
    k = sub.add_parser("nycklar", help="skapa nyckelpar (en gång)")
    k.add_argument("--ny", action="store_true")
    c = sub.add_parser("koppla", help="koppla en telefon till en person")
    c.add_argument("person")
    c.add_argument("kod")
    for name in ("skicka", "visa"):
        sub.add_parser(name).add_argument("person")
    args = parser.parse_args(argv)
    if args.kommando == "nycklar":
        make_keys(args.ny)
        print(f"Klart. Committa och pusha {PUBLIC_CONFIG} så att sidan får den publika nyckeln.")
    elif args.kommando == "koppla":
        print(f"Kopplad: {connect(args.person, args.kod)}")
    elif args.kommando == "visa":
        d = _report(args.person, fetch=False)
        print(f"Notis: {d['titel']}\n{d['kort']}\n\nPå sidan:\n{d['text']}")
    else:
        d = _report(args.person, fetch=True)
        send(args.person, d)
        print(f"Skickad till {args.person}: {d['titel']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
