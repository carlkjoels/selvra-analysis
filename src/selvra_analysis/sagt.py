"""sagt: ordagrann logg över vad användaren själv sagt — aldrig ett minne som skriver över.

Dialoglagrets sanningskälla (FAS 0, 2026-10-29). Tre regler bär allt:

1. **Append-only på riktigt.** Modulen exponerar ingen update- eller
   delete-funktion; journalen (data/sagt/journal.jsonl, backupad) växer bara.
   DuckDB-schemat `sagt` är en återspelning som kan byggas om när som helst.
2. **Citatet är heligt.** Varje post bär användarens exakta ord (citat +
   offset i källmeddelandet). En post utan citat avvisas i kod.
3. **Status HÄRLEDS ur evidens-länkar, aldrig ur modellsäkerhet.** sagt → mätt →
   prövat lagras inte som ett muterbart fält; det räknas fram ur evidens-länkar
   (matserie → mätt, last_studie → prövat) i uppspelningen. Dras evidensen
   tillbaka faller statusen av sig själv (justifikationsbaserat, TMS). Ingen
   LLM-utdata kan röra en befintlig rad — bara lägga nya poster och länkar.

Vad detta INTE är: ingen extern minnesmotor, ingen sammanfattning som
ersätter orden, ingen tolkning med skrivrätt. Modellen föreslår poster;
människan bekräftar; mätningarna uppgraderar. Domstolsprincipen i dialogform.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import duckdb

JOURNAL = Path("data/sagt/journal.jsonl")
DB = Path("data/selvra.duckdb")

TYPER = ("intention", "handelse", "sjalvbild")
STATUSAR = ["sagt", "matt", "provat"]
KALLOR = ("morgonsvar", "onboarding", "import", "mcp")
POLARITETER = ("bekraftad", "negerad")
# osaker: körningarna är oeniga eller satsen bär ingen tydlig modalitet (steg 3).
MODALITETER = ("faktisk", "avsedd", "hypotetisk", "annans_rost", "osaker")

# Rollvitlista: BARA ett user-meddelande kan bli ett sagt-påstående. assistant,
# third, system och verktyg kan aldrig — och inte heller citerade Selvra-brev
# (innehållsmaskning av egna brev är en senare skiva). Rollen avgör talaren i
# kod; en modell får aldrig välja den.
ROLLER = ("user", "assistant", "third", "system", "verktyg")
ROLL_TILL_TALARE = {"user": "anvandare", "assistant": "assistent", "third": "tredje_part"}
# Typade länkar (append-only). Modellen får föreslå en länk; den redigerar eller
# slår aldrig ihop. supersedes/corrects gör en post inaktiv; contradicts löses
# aldrig i kod; context_differs bär en kvalificerare. De fyra går post↔post via
# lanka(). evidences kopplar en post till en mätserie/studie (inte en post) via
# koppla_evidens() — status HÄRLEDS ur den.
RELER = ("supersedes", "corrects", "contradicts", "context_differs", "evidences")
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


def _nfc(text: str) -> str:
    """NFC före allt: iOS kan leverera å/ä/ö i NFD (a + kombinationstecken), och
    då matchar inte en delsträngskontroll mot NFC-text. Normalisera en gång."""
    return unicodedata.normalize("NFC", str(text or ""))


def far_bli_sagt(roll: str) -> bool:
    """Rollvitlistan: bara user. Allt annat (assistant, third, system, verktyg,
    okänd roll) kan aldrig bli ett sagt-påstående."""
    return roll == "user"


def observe_message(roll: str, text: str, *, kalla: str = "mcp",
                    kallmeddelande_id: str | None = None) -> str | None:
    """Logga ett råmeddelande (op=meddelande), NFC-normaliserat, OAVSETT roll —
    råtexten sparas även när inget extraheras. Tom inmatning ger ett uttryckligt
    utfall: None, och inget loggas. Returnerar annars meddelande-id. Bara roll
    'user' kan senare ge ett sagt-påstående (far_bli_sagt)."""
    ren = _nfc(text).strip()
    if not ren:
        return None  # tom inmatning: uttryckligt utfall, inget loggas
    roll = roll if roll in ROLLER else "system"  # okänd roll kan aldrig bli sagt
    mid = kallmeddelande_id or hashlib.sha256(
        f"{kalla}|{roll}|{ren}".encode()).hexdigest()[:12]
    _skriv({"op": "meddelande", "id": mid, "roll": roll, "kalla": kalla,
            "text": ren, "far_bli_sagt": far_bli_sagt(roll),
            "skapad": datetime.now(UTC).isoformat(timespec="seconds")})
    return mid


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
    # Rollvitlistan vid sagt-gränsen: bara användarens egna ord blir ett sagt-
    # påstående. assistant/third/system/verktyg loggas som meddelande, aldrig här.
    if post.get("talare") != "anvandare":
        raise ValueError("bara användarens egna ord (talare=anvandare) kan bli en "
                         f"sagt-post; fick talare {post.get('talare')!r}")
    post = {**post, "citat": _nfc(post["citat"])}  # NFC före hash och lagring
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


def koppla_evidens(pid: str, evidens: dict) -> None:
    """Koppla evidens till en post (op=evidens, append-only). Status HÄRLEDS ur
    sådana länkar — matserie → mätt, last_studie → prövat — och skrivs aldrig
    direkt. Modellsäkerhet är inte evidens och har ingen väg in."""
    if not isinstance(evidens, dict) or evidens.get("typ") not in EVIDENSTYPER \
            or not str(evidens.get("referens", "")).strip():
        raise ValueError("evidens kräver {typ: matserie|last_studie, referens: ...}")
    if pid not in _aktuella():
        raise ValueError(f"ingen post {pid}")
    _skriv({"op": "evidens", "id": pid,
            "evidens": {"typ": evidens["typ"], "referens": str(evidens["referens"])},
            "vid": datetime.now(UTC).isoformat(timespec="seconds")})


def dra_tillbaka_evidens(pid: str, referens: str) -> None:
    """Dra tillbaka en evidenslänk (op=evidens_retur, append-only). Statusen
    faller av sig själv i uppspelningen — ingen post skrivs om (TMS)."""
    _skriv({"op": "evidens_retur", "id": pid, "referens": str(referens),
            "vid": datetime.now(UTC).isoformat(timespec="seconds")})


POST_RELER = ("supersedes", "corrects", "contradicts", "context_differs")  # post↔post


def lanka(fran: str, till: str, rel: str) -> None:
    """Typad länk mellan två befintliga poster (append-only, op=lank). Modellen
    får FÖRESLÅ; koden skriver bara länken och redigerar aldrig en post.
    supersedes/corrects gör `till` inaktiv (ersatt av `fran`); contradicts löses
    aldrig i kod. evidences går inte här — evidens är inte en post, använd
    koppla_evidens (status härleds ur den)."""
    if rel == "evidences":
        raise ValueError("evidences kopplar en post till en mätserie/studie, "
                         "inte till en post — använd koppla_evidens")
    if rel not in POST_RELER:
        raise ValueError(f"rel måste vara en av {POST_RELER}, fick {rel!r}")
    if fran == till:
        raise ValueError("en länk måste gå mellan två olika poster")
    aktuella = _aktuella()
    for pid in (fran, till):
        if pid not in aktuella:
            raise ValueError(f"länk mot okänd post {pid}")
    _skriv({"op": "lank", "rel": rel, "from": fran, "to": till,
            "skapad": datetime.now(UTC).isoformat(timespec="seconds")})


def _status(pid: str) -> str | None:
    """Härledd status (ur evidens-länkar), eller None om posten inte finns."""
    p = _aktuella().get(pid)
    return p["status"] if p else None


def _harled_status(poster: dict[str, dict], rader: list[dict]) -> None:
    """Status ur evidens-länkar (op=evidens minus op=evidens_retur): last_studie
    → provat, matserie → matt, inget → sagt. Dras evidensen tillbaka faller
    statusen av sig själv (TMS). Legacy op=status läses som en evidens."""
    evidens_per: dict[str, dict[str, str]] = {}   # pid → {referens: typ}
    for r in rader:
        pid = r.get("id")
        if r["op"] == "evidens" and pid in poster:
            evidens_per.setdefault(pid, {})[r["evidens"]["referens"]] = r["evidens"]["typ"]
        elif r["op"] == "evidens_retur" and pid in poster:
            evidens_per.get(pid, {}).pop(r.get("referens"), None)
        elif r["op"] == "status" and pid in poster and r.get("evidens"):  # legacy
            evidens_per.setdefault(pid, {})[r["evidens"]["referens"]] = r["evidens"]["typ"]
    for pid, p in poster.items():
        typer = set(evidens_per.get(pid, {}).values())
        p["status"] = ("provat" if "last_studie" in typer
                       else "matt" if "matserie" in typer else "sagt")
        p["evidens"] = ([{"typ": t, "referens": ref}
                         for ref, t in evidens_per.get(pid, {}).items()] or None)


def _harled_aktiv(poster: dict[str, dict], rader: list[dict]) -> None:
    """aktiv/ersatt_av/linje_id/version_id ur supersedes/corrects-länkar. Ren
    uppspelning — inget skrivs om; gamla poster får aktiv=True, linje_id=egen id."""
    ersatt_av: dict[str, str] = {}   # till → fran  (till ersatt av nyare fran)
    ersatter: dict[str, str] = {}    # fran → till  (fran ersätter äldre till)
    for r in rader:
        if r.get("op") == "lank" and r.get("rel") in ("supersedes", "corrects") \
                and r["to"] in poster and r["from"] in poster:
            ersatt_av[r["to"]] = r["from"]
            ersatter[r["from"]] = r["to"]
    for pid, p in poster.items():
        rot, sedda = pid, {pid}        # linje_id = roten (äldsta) i kedjan, stabilt
        while rot in ersatter and ersatter[rot] not in sedda:
            rot = ersatter[rot]
            sedda.add(rot)
        p["version_id"], p["linje_id"] = pid, rot
        p["ersatt_av"] = ersatt_av.get(pid)
        p["aktiv"] = pid not in ersatt_av


def _aktuella() -> dict[str, dict]:
    """Journalen reducerad till varje posts aktuella tillstånd. Sanningen är
    journalen; detta är bara dess uppspelning (status, evidens, länkar, bekräftelse)."""
    rader = _journal_rader()
    poster: dict[str, dict] = {}
    for r in rader:
        if r["op"] == "post":
            poster[r["id"]] = dict(r)
            # poster från före talare-fältet var alltid användarens egna ord
            poster[r["id"]].setdefault("talare", "anvandare")
        elif r["op"] == "bekraftelse" and r["id"] in poster:
            poster[r["id"]]["bekraftad_av_anvandaren_vid"] = r["vid"]
    _harled_status(poster, rader)
    _harled_aktiv(poster, rader)
    return poster


def hamta(amne: str, person: str = "carl") -> list[dict]:
    """Poster vars citat innehåller `amne` — ordagrant, aldrig omskrivet.

    Enkel textsökning i citaten (ingen embeddings-sökning i v0). Returnerar
    varje posts egna ord och epistemiska status som de sparades; negerade
    poster bär alltid polaritet 'negerad', aldrig utan fältet. v0 är Carls
    lager; annan person ger tom lista (andra personers data bor inte i sagt)."""
    if person != "carl":
        return []
    nal = _nfc(amne).casefold()   # NFC så NFD-å matchar NFC-å
    ut = []
    for p in _aktuella().values():
        if nal in _nfc(p.get("citat", "")).casefold():
            ut.append({
                "citat": p.get("citat"), "citat_offset": p.get("citat_offset"),
                "typ": p.get("typ"), "polaritet": p.get("polaritet"),
                "modalitet": p.get("modalitet"), "talare": p.get("talare", "anvandare"),
                "status": p.get("status", "sagt"),
                "aktiv": p.get("aktiv", True), "ersatt_av": p.get("ersatt_av"),
                "linje_id": p.get("linje_id"), "version_id": p.get("version_id"),
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


HARLEDDA = ("version_id", "linje_id", "ersatt_av", "aktiv")  # ur länkar, ej lagrade


def spela_upp(db: Path = DB) -> None:
    """Journalen → DuckDB-schemat sagt. Schemat är en vy; sanningen är journalen.
    Härledda fält (aktiv/ersatt_av/linje_id/version_id) och länktabellen räknas
    fram ur journalen vid varje uppspelning — inget lagras i posterna."""
    poster = _aktuella()
    with duckdb.connect(str(db)) as con:
        con.execute("create schema if not exists sagt")
        kolumner = ", ".join(f"{f} varchar" for f in FALT if f != "citat_offset") \
            + ", citat_offset integer" \
            + ", version_id varchar, linje_id varchar, ersatt_av varchar, aktiv boolean"
        con.execute(f"create or replace table sagt.post ({kolumner})")
        kol = [f for f in FALT if f != "citat_offset"]
        platser = ", ".join(["?"] * (len(kol) + 1 + len(HARLEDDA)))
        for p in poster.values():
            varden = [json.dumps(p.get(f), ensure_ascii=False)
                      if f in ("lankar", "evidens") and p.get(f) is not None
                      else p.get(f) for f in kol]
            con.execute(
                f"insert into sagt.post values ({platser})",  # noqa: S608
                [*varden, p.get("citat_offset"), p.get("version_id"), p.get("linje_id"),
                 p.get("ersatt_av"), p.get("aktiv", True)])

        con.execute("create or replace table sagt.lank "
                    "(fran varchar, till varchar, rel varchar, skapad varchar)")
        for r in _journal_rader():
            if r.get("op") == "lank":
                con.execute("insert into sagt.lank values (?, ?, ?, ?)",
                            [r["from"], r["to"], r["rel"], r.get("skapad")])
