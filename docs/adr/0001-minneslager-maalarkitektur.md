# ADR 0001 — Minneslagrets målarkitektur

- **Status:** Föreslagen. Målarkitekturen är beslutad; **placeringsbeslutet väntar på Carl** (se nedan).
- **Datum:** 2026-10-31
- **Underlag:** forskningsrapporten "Spara orden, länka ändringar, exportera nuet" (2026-10-31), [[MODELLEN]], [[METODPLAN]], samt det redan byggda (`sagt.py`, `utforskande_samband.py`, MCP-läslagret).

## Varför detta dokument finns

Rapporten är en **målbild, inte en byggorder**. Utan ett beslut ligger 223 rader rapport och väntar på att tolkas igen. Denna ADR fryser *vad* minneslagret ska vara, så att vi kan bygga mot det **en grindad skiva i taget** — inte i ett svep, och inte i det frysta `~/selvra`.

## Kärninsikt (styr allt nedan)

Ordagrannhet, talare och historikbevarande är **konstruktionsproblem** som löses deterministiskt i kod och kan garanteras till 100 %. De verkliga osäkerheterna är två: **modalitet** (särskilt villkorat och annans röst, där även de bästa kliniska modellerna stannar på 0,6–0,9) och **"vad som gäller nu"** (där LLM:er reviderar för mycket eller för lite). Båda hanteras likadant: **modellen föreslår, koden och användaren avgör, felet blir ett granskningsbart objekt** — en flaggad modalitet eller en föreslagen länk — aldrig en tyst mutation.

## Beslut: målarkitekturen (låst)

1. **Append-only händelselogg är sanningen.** Projektioner (aktuell vy, sökindex) byggs om ur loggen och skrivs aldrig direkt. (Prejudikat: Graphiti; antimönster: Mem0:s muterbara lager + revisionstabell.)
2. **Koden sätter fakta, aldrig modellen:** citat (delsträngsverifierat på satsnivå), talare (ur meddelandets roll via vitlista — bara `user` ger `sagt`), tid (ordagrant uttryck + deterministisk sv/en-resolver med ankare; tvetydigt → `olöst`).
3. **Modaliteten är liten och har en utgång:** `faktisk | avsedd | hypotetisk | annans_rost | osaker`. Villkorat = hypotetiskt med villkoret kvar i citatet. Self-consistency (k=3) på polaritet/modalitet → oenighet ger `behöver_bekräftelse`.
4. **Motsägelser blir fem typade länkar, aldrig överskrivning:** `supersedes`, `corrects`, `contradicts`, `context_differs`, `evidences`. Modellen får bara *föreslå* en länk mellan två bestämda poster; den redigerar eller slår aldrig ihop.
5. **Status härleds, lagras inte muterbart:** `sagt | mätt | prövat` räknas fram ur `evidences`-länkar (justifikationsbaserat; dras evidensen tillbaka faller statusen).
6. **Deterministisk "aktuell vy":** policy (vad som gäller nu) skild från extraktion — senast giltiga `sagt` per ämne, med hänsyn till `corrects`/`contradicts`. (Separationen är där forskningens vinster låg.)
7. **Mem0-formad fasad över loggen:** add/search/get/get_all/update/delete/history med **stabilt linje-id** (`id`, pekar på senaste versionen) + `version_id` per händelse. `update`/`delete` blir `ClaimCorrected`/`ClaimRetracted` internt — posten syns bara inte längre i nuet.
8. **Radering via crypto-shredding:** DEK per användare krypterar fritext; radering förstör nyckeln, lägger en `SubjectErased`-gravsten och **bygger om projektioner, embeddings och index** (härledd klartext som nyckeln inte når).

## Beslut som väntar på Carl: var byggs det?

`sagt.py` lever i **selvra-analysis**; `EventStore`/projektionerna i **~/selvra** (fryst). Frågan har legat öppen för länge och måste avgöras här.

**Förslag (Carl beslutar):** bygg vidare **i selvra-analysis**, inkrementellt och grindat, där `sagt.py` + `utforskande_samband.py` redan lever. **`~/selvra` förblir fryst.** Flytt till protokollet utlöses först när **båda** gäller: (a) tenant-spärren är på plats, och (b) en andra vertikal *eller* en extern klient läser faktiskt via MCP — alltså när de tre filtren (pilot-blocker? efterfrågan? bandbredd?) säger ja. Tills dess är selvra-analysis rätt hem.

## Trösklar

Rapportens byggplanstabell (citat 100 %, polaritet ≥0,95, modalitet makro-F1 ≥0,85, annans röst ≥0,90, osv.) är **förslag, inte låsta värden**. De låses i en egen förregistrering innan Selvra körs mot benchens dolda uppsättning — aldrig efteråt.

## Byggs inte nu (med skäl)

- **Hela 11-stegsbygget i ~/selvra** — bryter repo-fokus ([[feedback_repo_focus_2026-10-27]]) och är arkitekturdrift ([[feedback_no_arch_drift]]); avblockerar ingen pilot.
- **Mem0-kompatibelt API** — nämns inte publikt förrän det finns och har tester ([[project_selvra_positioning_2026-10-31]]).
- **Crypto-shredding, event-store för claims/länkar, MCP-skrivlager** — väntar på placeringsbeslutet + grindarna.
- **Riktig faktoranalys** (dolda dimensioner) — eget steg senare när dagarna räcker (METODPLAN).

## Konsekvenser

- Vi har en stabil målbild att bygga mot utan att röra det frysta protokollet.
- Nästa konkreta skiva som passar filtren avgörs separat; ADR:n är kartan, inte ordern.
- Ändras målbilden skrivs en ny ADR som ersätter denna — append-only även för besluten.
