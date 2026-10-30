"""Dagboksagent för träning och sömn — minnet är Selvras, inte agentens.

Steg 4 i MCP-testet. En liten agent (Claude Agent SDK) som BARA använder
selvra-minne-serverns verktyg för att minnas något. Ingen egen minneslösning:
inget den "kommer ihåg" mellan turer finns utanför sagt-lagret, och den får
inga andra verktyg (ingen fil, ingen databas, ingen webb).

Svarsformen är fast och ärlig: **"du sa …, klockan mätte …, det är prövat /
inte prövat."** Agenten återger dina ord ordagrant (via hamta_om), klockans
tal via visa_matning, och säger prövat bara när en låst studie gör det. Den
tolkar aldrig, råder aldrig, diagnostiserar aldrig — den läser det Selvra
redan vet och säger det tillbaka.

Kräver ANTHROPIC_API_KEY (i .env) och att selvra-minne finns i .mcp.json.

    uv run python -m selvra_analysis.dagboksagent "sover jag sämre efter kvällspass?"
"""

from __future__ import annotations

import asyncio
import sys

from claude_agent_sdk import ClaudeAgentOptions, query

SYSTEM = """\
Du är Selvras dagboksagent för träning och sömn. Du har INGET eget minne.
Allt du minns kommer ur selvra-minne-verktygen, ordagrant. Du hittar aldrig på.

Regler:
- Vill användaren spara något den själv sagt: anropa spara_sagt med deras EXAKTA
  ord (ordagrant, ingen omskrivning). Bevara negationer ("inte", "aldrig").
- Vill användaren veta vad som gäller om ett ämne: anropa hamta_om och återge
  de tre grupperna (sagt / mätt / prövat) var för sig.
- Gäller frågan ett mätvärde över tid: anropa visa_matning.
- Gäller den en dom: anropa lista_domar.
- Svara i formen: "Du sa '…'. Klockan mätte …. Det är prövat / inte prövat än."
  Utelämna de led som saknar täckning i stället för att gissa.
- Aldrig råd, aldrig medicinsk tolkning, aldrig en siffra du inte fått ur ett
  verktyg. Säger ett verktyg inget, säg att Selvra inte vet det än.
"""

# Agenten får BARA selvra-minne-verktygen — ingen fil, databas eller webb.
TILLATNA = [
    "mcp__selvra-minne__spara_sagt",
    "mcp__selvra-minne__hamta_om",
    "mcp__selvra-minne__visa_matning",
    "mcp__selvra-minne__lista_domar",
]

MCP = {
    "selvra-minne": {
        "command": "uv",
        "args": ["run", "python", "-m", "selvra_analysis.mcp_server"],
    }
}


async def fraga(text: str) -> None:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM,
        mcp_servers=MCP,
        allowed_tools=TILLATNA,
        # Non-interaktivt: verktygen är redan vitlistade till selvra-minnes
        # läs/spara mot eget lager, så de godkänns utan prompt. Budgettak så ett
        # test aldrig skenar. cwd ärvs (kör från repo-roten) — ingen absolut sökväg.
        permission_mode="bypassPermissions",
        max_budget_usd=2.00,
        max_turns=6,
    )
    async for message in query(prompt=text, options=options):
        for block in getattr(message, "content", []) or []:
            namn = getattr(block, "name", None)
            if getattr(block, "type", None) == "text":
                print(block.text)
            elif namn:  # verktygsanrop — visa att minnet är Selvras, inte agentens
                print(f"  [använder {namn}]", file=sys.stderr)
        # Slutsvaret kan ligga i ResultMessage.result i stället för ett textblock.
        slut = getattr(message, "result", None)
        if slut and not getattr(message, "content", None):
            print(slut)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('Ge en fråga, t.ex.: ... dagboksagent "sover jag sämre efter kvällspass?"',
              file=sys.stderr)
        return 1
    asyncio.run(fraga(" ".join(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
