"""Selvras minne som MCP-server: stdio, lokalt, bara Carl.

Exponerar bara det som redan finns och följer sagt.py:s regler. Inga nya
principer, ingen språkmodell som skriver om, inga verktyg för uppdatering,
radering eller statusändring — status uppgraderas bara i sagt.py via evidens.
All text passerar sprakgrind innan den lämnar servern (beskriva, aldrig råda;
ingen medicinsk tolkning). Glukos/mätdata läses skrivskyddat. Bara person carl:
andra personers data når aldrig servern.

Transport är enbart stdio. mcp-SDK:n har en HTTP-transport och drar in
starlette/uvicorn, men de importeras aldrig här och ingen port öppnas.

    uv run python -m selvra_analysis.mcp_server      # kör över stdio
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer

from selvra_analysis import sagt, sprakgrind

PERSON = "carl"
DB = Path("data/selvra.duckdb")
STUDIES = Path("studies")
RORLOGG = Path("data/rorlogg.jsonl")

mcp = MCPServer("selvra-minne")


def _grinda(text: str) -> str:
    """Varje textsvar prövas mot reflektionsgrinden; faller det, säg det rakt
    ut i stället för att skicka något som bryter konstitutionen."""
    ok, skal = sprakgrind.granska_reflektion(text, text, max_tecken=4000)
    if not ok:
        return f"(svaret stoppades av språkgrinden: {skal})"
    return text


@mcp.tool()
def spara_sagt(citat: str, typ: str, polaritet: str, modalitet: str,
               kalla: str = "mcp") -> str:
    """Spara användarens egna ord, ordagrant. Status blir alltid 'sagt'.

    citat: användarens exakta ord. typ: intention|handelse|sjalvbild.
    polaritet: bekraftad|negerad. modalitet: faktisk|avsedd|hypotetisk|annans_rost.
    Ingen omskrivning, ingen tolkning — bara det som sades, loggat."""
    try:
        # talare sätts i koden, inte av modellen: spara_sagt loggar personens
        # egna ord, så talaren är alltid 'anvandare' — aldrig något verktyget
        # låter agenten välja.
        pid = sagt.spara({"citat": citat, "typ": typ, "polaritet": polaritet,
                          "modalitet": modalitet, "talare": "anvandare", "kalla": kalla,
                          "kallmeddelande_id": None, "citat_offset": 0,
                          "said_at": str(date.today()), "tidsuttryck_ratt": None,
                          "modell": "mcp", "promptversion": "v0"})
    except ValueError as err:
        return f"(sparades inte: {err})"
    return _grinda(f"Sparat som sagt: ”{citat}” (id {pid}). "
                   "Status blir mätt eller prövat först när data eller en låst studie bär det.")


@mcp.tool()
def hamta_om(amne: str) -> str:
    """Vad Selvra vet om ett ämne, i tre grupper var för sig: sagt, mätt, prövat.
    Varje rad bär sina egna ord och källa. Inget slås ihop, inget tolkas."""
    poster = sagt.hamta(amne, PERSON)
    sagt_rader = [p for p in poster if p["status"] == "sagt"]
    matt_rader = [p for p in poster if p["status"] in ("matt", "provat")]

    delar = ["SAGT (dina egna ord, ej prövat):"]
    delar += [f"  • ”{p['citat']}” [{p['polaritet']}, {p['modalitet']}]"
              f" — {p.get('kalla') or '?'}, {p.get('said_at') or '?'}"
              for p in sagt_rader] or ["  (inget)"]
    delar += ["", "MÄTT (stöds av en mätserie):"]
    delar += [f"  • ”{p['citat']}” — evidens: "
              f"{(p.get('evidens') or {}).get('referens', '?')}"
              for p in matt_rader if p["status"] == "matt"] or ["  (inget)"]
    delar += ["", "PRÖVAT (dom ur en låst studie):"]
    domar = _provat_om(amne)
    delar += [f"  • {d}" for d in domar] or ["  (inget)"]
    return _grinda("\n".join(delar))


def _provat_om(amne: str) -> list[str]:
    """Domar ur låsta studiers slutrapporter som rör ämnet (textsökning), plus
    Dreamer-minnets lärdomar. Ordagrant ur Svar-avsnittet."""
    nal = amne.casefold()
    ut = []
    for rapport in sorted(STUDIES.glob("*/slutrapport.md")):
        text = rapport.read_text()
        if nal not in text.casefold():
            continue
        m = re.search(r"## Svar\n+(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            svar = " ".join(m.group(1).split())[:300]
            ut.append(f"{rapport.parent.name}: {svar}")
    return ut


@mcp.tool()
def visa_matning(matt: str, fran: str, till: str) -> str:
    """Dagsvärden för ett mått ur marts (skrivskyddat), med källa, apparat,
    firmware och rör ur rörloggen. Beskrivande tal, ingen tolkning, inga råd."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", matt):
        return "(okänt mått)"
    try:
        with duckdb.connect(str(DB), read_only=True) as con:
            kols = {r[0] for r in con.execute(
                "select column_name from information_schema.columns "
                "where table_name = 'mart_analysis_days'").fetchall()}
            if matt not in kols:
                return f"(måttet {matt} finns inte i marten)"
            sql = (f"select reading_date, {matt} from marts.mart_analysis_days "  # noqa: S608 — matt mot kolumnmängd
                   f"where reading_date between ? and ? and {matt} is not null order by reading_date")
            df = con.execute(sql, [fran, till]).df()
    except duckdb.Error as err:
        return f"(kunde inte läsas: {err})"
    enhet = _senaste_ror()
    rader = [f"{r.reading_date}: {r[matt]}" for r in df.itertuples()]
    if not rader:
        return _grinda(f"Inga värden för {matt} mellan {fran} och {till}.")
    return _grinda(f"{matt}, {fran}–{till} (källa: {enhet}):\n" + "\n".join(rader))


def _senaste_ror() -> str:
    if not RORLOGG.exists():
        return "okänd källa"
    for r in reversed(RORLOGG.read_text().splitlines()):
        if r.strip():
            d = json.loads(r)
            if d.get("person") == PERSON:
                return (f"{d.get('kalla', '?')} · {d.get('enhet', '?')} · "
                        f"firmware {d.get('firmware') or '?'}")
    return "okänd källa"


@mcp.tool()
def lista_domar() -> str:
    """De låsta studiernas domar, ordagrant ur slutrapporternas Svar-avsnitt."""
    ut = []
    for rapport in sorted(STUDIES.glob("*/slutrapport.md")):
        text = rapport.read_text()
        m = re.search(r"## Svar\n+(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            ut.append(f"{rapport.parent.name}: {' '.join(m.group(1).split())[:400]}")
    return _grinda("\n".join(ut) if ut else "Inga körda studier ännu.")


if __name__ == "__main__":
    mcp.run()
