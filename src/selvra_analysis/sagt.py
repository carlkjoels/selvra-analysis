"""sagt: ordagrann logg över vad användaren själv sagt — aldrig ett minne som skriver över.

Dialoglagrets sanningskälla (FAS 0, 2026-10-29). Tre regler bär allt:

1. **Append-only på riktigt.** Modulen exponerar ingen update- eller
   delete-funktion; journalen (data/sagt/journal.jsonl, backupad) växer bara.
   DuckDB-schemat `sagt` är en återspelning som kan byggas om när som helst.
2. **Citatet är heligt.** Varje post bär användarens exakta ord (citat +
   offset i källmeddelandet). En post utan citat avvisas i kod.
3. **Status uppgraderas av evidens, aldrig av modellsäkerhet.** sagt → mätt →
   prövat kräver en länkad evidenspost (mätserie eller låst studie), ett steg
   i taget. Ingen LLM-utdata kan röra en befintlig rad — bara lägga nya
   poster, som i sin tur väntar på användarens bekräftelse.

Vad detta INTE är: ingen extern minnesmotor, ingen sammanfattning som
ersätter orden, ingen tolkning med skrivrätt. Modellen föreslår poster;
människan bekräftar; mätningarna uppgraderar. Domstolsprincipen i dialogform.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

JOURNAL = Path("data/sagt/journal.jsonl")
DB = Path("data/selvra.duckdb")

TYPER = ("intention", "handelse", "sjalvbild")
STATUSAR = ["sagt", "matt", "provat"]
KALLOR = ("morgonsvar", "onboarding", "import", "mcp")
POLARITETER = ("bekraftad", "negerad")
MODALITETER = ("faktisk", "avsedd", "hypotetisk", "annans_rost")
# Vem som yttrade citatet. Sätts ALLTID av koden utifrån meddelandets roll,
# aldrig av en modell — polariteten/modaliteten kan en modell föreslå, men
# vem som talade är ett faktum ur källan. anvandare = personen själv,
# assistent = Selvra/modellen, tredje_part = någon annan (jfr modalitet
# annans_rost, som är OM någon annan; talare är VEM som sa det).
TALARE = ("anvandare", "assistent", "tredje_part")
EVIDENSTYPER = ("matserie", "last_studie")

FALT = ("id", "typ", "status", "kalla", "kallmeddelande_id", "citat", "citat_offset",
        "polaritet", "modalitet", "talare", "said_at", "tidsuttryck_ratt",
        "refers_to_from", "refers_to_to", "resolverversion",
        "bekraftad_av_anvandaren_vid", "modell", "promptversion", "lankar", "evidens")


def _journal_rader() -> list[dict]:
    if not JOURNAL.exists():
        return []
    return [json.loads(r) for r in JOURNAL.read_text().splitlines() if r.strip()]


def _skriv(rad: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")


def spara(post: dict) -> str:
    """Ny sagt-post. Citatet är obligatoriskt och heligt; enums valideras hårt.
    Returnerar id. Detta är modulens ENDA väg in för nytt innehåll."""
    if not str(post.get("citat", "")).strip():
        raise ValueError("en post utan citat är en tolkning, inte en logg — avvisad")
    for falt, tillatna in (("typ", TYPER), ("kalla", KALLOR),
                           ("polaritet", POLARITETER), ("modalitet", MODALITETER),
                           ("talare", TALARE)):
        if post.get(falt) not in tillatna:
            raise ValueError(f"{falt} måste vara en av {tillatna}, fick {post.get(falt)!r}")
    pid = hashlib.sha256(
        f"{post['kalla']}|{post.get('kallmeddelande_id')}|{post['citat']}|"
        f"{post.get('citat_offset')}".encode()).hexdigest()[:12]
    if any(r.get("id") == pid and r.get("op") == "post" for r in _journal_rader()):
        return pid  # exakt samma citat ur samma meddelande: redan loggat
    rad = {"op": "post", "id": pid, "status": "sagt",
           "skapad": datetime.now(UTC).isoformat(timespec="seconds"),
           "bekraftad_av_anvandaren_vid": None, "evidens": None, "lankar": post.get("lankar"),
           **{f: post.get(f) for f in FALT if f not in
              ("id", "status", "bekraftad_av_anvandaren_vid", "evidens", "lankar")}}
    _skriv(rad)
    return pid


def bekrafta(pid: str, vid: str) -> None:
    """Användarens bekräftelse — den enda som gör en post användbar i ett brev."""
    if _status(pid) is None:
        raise ValueError(f"ingen post {pid}")
    _skriv({"op": "bekraftelse", "id": pid, "vid": vid})


def uppgradera_status(pid: str, ny_status: str, evidens: dict) -> None:
    """sagt → mätt → prövat: bara via länkad evidens, ett steg i taget.
    Modellens säkerhet är inte evidens och har ingen väg in här."""
    if ny_status not in STATUSAR[1:]:
        raise ValueError(f"okänd status: {ny_status}")
    if not isinstance(evidens, dict) or evidens.get("typ") not in EVIDENSTYPER \
            or not str(evidens.get("referens", "")).strip():
        raise ValueError("statusuppgradering kräver evidens: "
                         "{typ: matserie|last_studie, referens: ...}")
    nuvarande = _status(pid)
    if nuvarande is None:
        raise ValueError(f"ingen post {pid}")
    if STATUSAR.index(ny_status) != STATUSAR.index(nuvarande) + 1:
        raise ValueError(f"{nuvarande} → {ny_status} hoppar i trappan")
    _skriv({"op": "status", "id": pid, "status": ny_status, "evidens": evidens,
            "vid": datetime.now(UTC).isoformat(timespec="seconds")})


def _status(pid: str) -> str | None:
    status = None
    for r in _journal_rader():
        if r.get("id") != pid:
            continue
        if r["op"] == "post" or r["op"] == "status":
            status = r["status"]
    return status


def _aktuella() -> dict[str, dict]:
    """Journalen reducerad till varje posts aktuella tillstånd. Sanningen är
    journalen; detta är bara dess uppspelning (status, evidens, bekräftelse)."""
    poster: dict[str, dict] = {}
    for r in _journal_rader():
        if r["op"] == "post":
            poster[r["id"]] = dict(r)
            # poster från före talare-fältet var alltid användarens egna ord
            poster[r["id"]].setdefault("talare", "anvandare")
        elif r["op"] == "status" and r["id"] in poster:
            poster[r["id"]]["status"] = r["status"]
            poster[r["id"]]["evidens"] = r["evidens"]
        elif r["op"] == "bekraftelse" and r["id"] in poster:
            poster[r["id"]]["bekraftad_av_anvandaren_vid"] = r["vid"]
    return poster


def hamta(amne: str, person: str = "carl") -> list[dict]:
    """Poster vars citat innehåller `amne` — ordagrant, aldrig omskrivet.

    Enkel textsökning i citaten (ingen embeddings-sökning i v0). Returnerar
    varje posts egna ord och epistemiska status som de sparades; negerade
    poster bär alltid polaritet 'negerad', aldrig utan fältet. v0 är Carls
    lager; annan person ger tom lista (andra personers data bor inte i sagt)."""
    if person != "carl":
        return []
    nal = amne.casefold()
    ut = []
    for p in _aktuella().values():
        if nal in str(p.get("citat", "")).casefold():
            ut.append({
                "citat": p.get("citat"), "citat_offset": p.get("citat_offset"),
                "typ": p.get("typ"), "polaritet": p.get("polaritet"),
                "modalitet": p.get("modalitet"), "talare": p.get("talare", "anvandare"),
                "status": p.get("status", "sagt"),
                "kalla": p.get("kalla"), "said_at": p.get("said_at"),
                "evidens": p.get("evidens"),
                "bekraftad_av_anvandaren_vid": p.get("bekraftad_av_anvandaren_vid"),
            })
    return sorted(ut, key=lambda r: str(r.get("said_at") or ""))


def migrera_talare(talare: str = "anvandare") -> int:
    """Engångs-backfyllnad av talare på befintliga poster. Fältet var alltid
    implicit — sagt har bara loggat användarens egna ord — så standard är
    'anvandare'. Detta är en schemamigrering, inte en innehållsändring: citat,
    status, polaritet och allt övrigt lämnas orört, bara talare tillkommer.
    Idempotent: poster som redan har talare rörs inte. Returnerar antal ändrade.

    Till skillnad från spara/bekrafta/uppgradera_status rör denna funktion
    historiska rader — den körs en gång vid införandet av fältet, aldrig i drift."""
    if talare not in TALARE:
        raise ValueError(f"talare måste vara en av {TALARE}, fick {talare!r}")
    if not JOURNAL.exists():
        return 0
    rader = _journal_rader()
    andrade = 0
    for r in rader:
        if r.get("op") == "post" and "talare" not in r:
            r["talare"] = talare
            andrade += 1
    if andrade:
        with JOURNAL.open("w") as f:
            for r in rader:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return andrade


def spela_upp(db: Path = DB) -> None:
    """Journalen → DuckDB-schemat sagt. Schemat är en vy; sanningen är journalen."""
    poster = _aktuella()
    with duckdb.connect(str(db)) as con:
        con.execute("create schema if not exists sagt")
        kolumner = ", ".join(f"{f} varchar" for f in FALT if f != "citat_offset") \
            + ", citat_offset integer"
        con.execute(f"create or replace table sagt.post ({kolumner})")
        for p in poster.values():
            varden = [json.dumps(p.get(f), ensure_ascii=False)
                      if f in ("lankar", "evidens") and p.get(f) is not None
                      else p.get(f) for f in FALT if f != "citat_offset"]
            con.execute(
                f"insert into sagt.post values ({', '.join(['?'] * (len(FALT) - 1))}, ?)",  # noqa: S608
                [*varden, p.get("citat_offset")])
