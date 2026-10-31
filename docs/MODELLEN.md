# MODELLEN — kartan som syr ihop allt

De andra dokumenten är konstitutioner för var sitt lager: benchmark/PROTOKOLL.md
för metodiken, docs/UPPLEVELSEN.md för det som når en människa, docs/METODPLAN.md
för statistikens nästa steg. Det här dokumentet är kartan ovanför dem: vad
modellen *är*, i vilken ordning den byggs, och hur den förbättrar sig själv.
Läses i början av varje session som rör riktning. Uppdateras när ett lager
byter läge — inte oftare.

Senast uppdaterad: 2026-10-31.

## Modellen i en mening

Selvra gör vardagsdata till bevisade svar om en person — domar, inte insikter —
och håller tyst när täckning saknas. Positionen (kanon): *Selvra är ett
protokoll med stora databaser, som connectas med MCP:er. Selvra-app är dess
första klient. Selvra Diabetes är dess första vertikal.*

## Formen: motor, inte yta (positionering låst 2026-10-29)

Selvra är en intelligensmotor, inte en yta: den levererar grindade meningar
med täckningsmetadata till andras grafer. Egna ytor (breven, morgonsidan) är
motorns laboratorium — där varje mening prövas mot riktiga människor — aldrig
dess produkt. Grafarbete byggs inte nytt; det som finns (morgonvyn) är Carls
instrument. L4 (andra system frågar Selvra) är därmed huvudspåret, inte
slutsteget. Förebild i formen: Firstbeat — motorn inuti andras produkter.

## Rollerna — motor, testbädd, granskare (2026-10-31)

Tre delar, tre jobb, aldrig sammanblandade:

- **Selvra är motorn.** Ett minneslager med tre nivåer: *sagt* (personens egna
  ord, ordagrant), *mätt* (en mätserie bär det) och *prövat* (en låst studie har
  dömt). Nisch: vården.
- **Selvra Health är testbädden.** Rapporter och studier — där motorns meningar
  prövas mot riktiga människor innan de får lämna huset.
- **serrier är granskaren.** Benchmarkar motorn, mäter rörens trohet, håller
  registret. serrier gör aldrig eget vin: den dömer andras arbete och
  producerar inget eget att bära fram. Och eftersom den granskar Selvra
  redovisas den kopplingen alltid — granskaren utger sig aldrig för att vara
  oberoende.

## Lagren

| # | Lager | Vad det är | Läge 2026-10-28 |
|---|-------|-----------|------------------|
| L0 | **Data** | Källor → raw → marts per person (Dexcom Share, Nightscout, Garmin; dbt-kontrakt, 159 tester) | Live, n=2 (Carl CGM+klocka, testare-1 klocka) |
| L1 | **Motor** | fråga → granska → lås → kör en gång → dom (block bootstrap, randomiseringstest, negativ kontroll, styrka ur egen variation) | Live, benchmarkad (motortest, chaos monkey, LLM-arm) |
| L2 | **Upplevelse** | brev, push, morgonvy, förslagsgrind, språkgrind | Live; grindad (gyllene dagen, make syn) |
| L3 | **Distribution** | selvra.ai, studiesidan (ScholarlyArticle, engelska), Substack | Sajt live; Substack vilande (Carls beslut) |
| L4 | **Integration** | MCP-läslager (andra system frågar Selvra), protokollskrivning | Byggs ej ännu; ~/selvra på is tills tenant-spärr |

Värdet flödar nedifrån och upp: utan L0-baslinje ingen L1-dom, utan dom inget
att visa i L2/L3, utan domregister inget värt att integrera i L4. Därför byggs
och förbättras lagren i den ordningen när de konkurrerar om tid.

## Bevisat hittills (därför är modellen trovärdig)

- Motorn fäller hellre än friar: första förslagsstudien på en wearable-person
  (p00) slutade **motbevisad** med negativ kontroll godkänd — och domen
  skickades till personen som den var. (Mätvärdena är personens egna och bor i
  den gitignorerade personmappen, inte här — se docs/INTEGRITET.md.)
- Granskaren stoppar på riktigt: p01 stoppad (1 väntat komplett par av 12),
  rate-fix skrotad när datan inte bar.
- Benchmarken biter sin författare: f17/f18-cykeln, styrka-rättningen,
  LLM-jämförelsen (0 falska godkännanden mot 13–20 för råa modeller).
- Onboarding av person nr 2 tog en kväll; första dom inom ett dygn
  (retrospektivt) tack vare wearable-only-läget.

## Planen — grindar, inte datum

Varje steg har en grind som öppnar nästa. Datum är prognoser; grindarna är
beslut.

**Nu (oktober–november 2026)**
1. **Testare-1:s p02 (promenad → sömn)** genom hela cykeln: inbjudan → lås → 24
   studiedagar → dom. Grind: testare-1 tackar ja. Detta är modellens första
   *prospektiva* n=1 på en wearable-person — hela kedjan på riktigt.
2. **Carls klocka (torsdag)** → hans steg/sömn/puls-baslinje börjar växa →
   studie 003 (träning, prospektiv) designas när granskaren släpper igenom.
3. **Sekventiella stoppregler** (METODPLAN §2) — största enskilda
   UX-förbättringen: kortare tid till dom utan att fella felrisken. Byggs
   fall-först enligt PROTOKOLL. Grind: p02/003 behöver den på riktigt.
4. **dold4** författas av någon som inte sett styrka/strata-fixarna (inte
   Claude i denna session). Grind för varje framtida motorändring.

**Nästa (vintern 2026/27)**
5. **n = 3–5**: fler personer (vänner/familj, Garmin/klocka räcker).
   Onboarding är redan ~15 min + cron. Grind: p02 har visat att en
   wearable-person kan gå hela varvet utan Carl som driftstekniker.
6. **Hierarkisk styrkedelning** (METODPLAN §3) när minst två personer har
   körda studier — individer lånar styrka utan att dela rådata.
7. **MCP-läslager** (L4): läs-bara verktyg ovanpå körjournaler och marts, så
   att andra system kan fråga "vad är bevisat?". Grind: de tre filtren
   (pilot-blocker? efterfrågan? bandbredd?) måste säga ja — byggs inte på
   spekulation.

**Sedan (2027)**
8. **iOS/HealthKit H1 2027** (Framna-beslutet ligger hos Carl) — tar bort
   Garmin-inloggningen som friktionsgolv och öppnar Apple Watch-världen.
9. **Pilot Selvra Diabetes** — tekniskt redo sedan maj; externa blockers är
   Carls (kliniska kontakter). Motorn fortsätter bevisa sig på n=2–5 under
   tiden.
10. **Vertikaler bortom hälsa** (ERP/Business-sporet) — först när domregistret
    och MCP-lagret finns. "Ditt data vet redan svaret. Selvra bevisar det"
    gäller även en verksamhet — men inte före bevis på människor.

## Förbättringsloopen — hur modellen förbättrar sig själv

"Hela tiden förbättra" är inte ambition utan mekanik; varje lager har sin loop:

- **L0:** rörens fel mäts mot källans egna filer (FIT-facit, METODPLAN §6):
  spegeln får inte kalla något "avvikelse" som ryms i rörets mätfel, och rörets
  per-dag-spridning hör hemma i styrkeberäkningen. Gräns: bara apparater och
  rör som redan är i drift.
- **L1:** produktionsmissar blir benchmarkfall (PROTOKOLL §6); varje
  motorändring möter fall-först + motortest + chaos monkey; dolda uppsättningar
  förbrukas och ersätts blint.
- **L2:** gyllene dagen-testet i CI + `make syn` före deploy + språkgrinden i
  körning. Assertioner mjukas aldrig upp i smyg (UPPLEVELSEN §6).
- **Kunskap:** varje dom skrivs till Dreamers minne → nästa förslag ställer en
  bättre fråga. Registret av domar *är* produkten som växer.
- **Metod:** METODPLAN:s prioritering styrs av verkliga studiers behov, aldrig
  av vad som är intressant.
- **Meta:** självstudien (METODPLAN §7) forskar dagligen på systemets egna
  journaler — rör-drift, grindbeteende, domregister. Fynd blir hypoteser och
  frusna fall, aldrig automatiska ändringar.

## Domstolsprincipen — varför förbättringsloopen fungerar

Varaktigt ackumulerande system har alltid samma fyra delar: en billig
**generator** av kandidater (hypoteser, förslag — gärna en LLM, de blir bättre
gratis), en **omutlig domare** (verklighetskontakt: lottade dagar, frusna
regler, facit som aldrig redigeras), ett **minne** där vinster består (domar,
benchmarkfall, rörloggen), och **självreferens** — loopens utdata förbättrar
loopen, *inklusive domaren själv* (misser blir frusna fall, dolda uppsättningar
förbrukas, blinda författare krävs). Den dubbla självreferensen är det ovanliga:
systemet blir klokare, och dess förmåga att veta det blir också klokare.

Flaskhalsen är alltid domen, aldrig generatorn. Systemets tillväxttakt sätts av
hur snabbt verkligheten kan döma utan att domaren korrumperas — en natt tar en
natt, tolv par tar tio veckor. Kurvan böjs uppåt på exakt tre hederliga sätt,
och alla tre står redan i planen: **parallellisera verklighetskontakten**
(fler personer), **gör domen snabbare utan att försvaga den** (sekventiella
gränser, METODPLAN §2) och **återanvänd bevisad kunskap** (hierarkisk Bayes,
§3). Genvägen — låta systemet döma sig självt, optimera egna utfall — ger en
exponentialkurva i självförtroende, inte i kunskap (ML-reglerna i METODPLAN).
Man skapar inte intelligensen; man skapar domstolen och ser till att den
skalar.

## Vad vi säger nej till (lika viktigt som planen)

- **Tre filter före allt nytt:** pilot-blocker? klinisk/verklig efterfrågan?
  bandbredd? Minst ett ja, annars nej.
- **Slowburn-pakten:** konstitution före tillväxtkurva. Aldrig push, streaks,
  scores, FOMO. Framsteg mäts i tid *utanför* appen.
- **Repo-fokus:** selvra-analysis + selvra-diabetes. ~/selvra rörs inte före
  tenant-spärren.
- **Byggs inte-listan** (METODPLAN): bandit-allokering, LLM-bedömning i
  granskningen. LLM föreslår; koden beslutar.

## Måtten som räknas

Inte MAU. I ordning:
1. **Tid till första dom** per ny person (nu: ~1 dygn retrospektivt, mål:
   dagar även prospektivt via sekventiella gränser).
2. **Domar i registret** (nu: 3 körda studier, varav 1 motbevisad — nejen
   räknas lika mycket).
3. **Andel dagar med giltig data** per person (synkvakt försvarar den).
4. **Benchmarkens träffsäkerhet** (falska godkännanden = 0 försvaras).

## Ändringslogg

- 2026-10-28: Första versionen.
- 2026-10-29: Mätlagret in i L0:s förbättringsloop (METODPLAN §6).
- 2026-10-29: Domstolsprincipen — generator, omutlig domare, minne, dubbel självreferens; flaskhalsen är domen.
- 2026-10-29: Formen låst — motor, inte yta; meningar till andras grafer; egna ytor är laboratoriet.
- 2026-10-31: Rollerna — Selvra (motor, nisch vården), Selvra Health (testbädd), serrier (granskare som alltid redovisar kopplingen till Selvra).
