# Metodplan: motorns nästa metodologiska steg

Prioriterad lista. Varje punkt landar enligt benchmark/PROTOKOLL.md: fall först,
fix sedan, ny dold uppsättning efter varje batch. Ingen punkt byggs för att den
är intressant — bara när den blockerar en verklig studie eller en verklig miss.

## 1. Strata-SD (j08-rättningen) — pågår, fall-först

När de tillåtna dagarna är färre än MIN_SD_DAYS poolas SD i dag över alla dagar.
Skiljer sig dagstyperna åt (arbetsdagens lunchpromenad mot helgens sovmorgon)
räknas skillnaden *mellan* dagstyper som brus, styrkan underskattas och giltiga
studier stoppas (benchmark: j08, sann styrka 84 % mot skattade 66 %).
Rättning: skatta variationen inom dagstyp (residualer efter dagstypens medel ur
loggade pass), med graciös reträtt till dagens beteende när inga pass finns.

## Klart: wearable-only-läget (2026-10-27)

Dagsryggraden är nu unionen av CGM- och wearable-dagar; glukoskolumnerna är null på
dagar utan CGM, och utfallsgiltighet bedöms per kolumn (wearable-utfall gäller när
värdet finns, CGM-utfall kräver giltig CGM-dag). Kolumn-utfall tillåts i n1.
En person utan CGM får därmed hela kedjan: marts (159/159 tester på testare-1:s databas),
studievalidering, granskning med power ur egen variation. Första beviset: granskaren
stoppade p01-promenad-vilopuls korrekt — 35 dagars baslinje ger 1 väntat komplett par
av 12. `make person-build PERSON=namn` bygger en persons marts.

## 2. Sekventiella stoppregler — nästa stora

I dag: fast antal par, en analys vid slutet. Modern n-of-1-praxis
(Platform-of-1 2025; Senn/Shrestha Bayesian adaptive) är för-registrerade
sekventiella gränser: avläsningspunkter och beslutsgränser låses före start,
och studien får avgöras tidigt när bevisen räcker. Bryter inte en-körning-
principen — regeln är låst, den har bara flera förutbestämda avläsningar.
Kräver: utökning av studie.yml (avlasningar + gränser), las/kor-stöd,
kalibreringstest av total felrisk, granska-kontroll av gränserna.
Kodreferens före bygge: StudyU (HPI, open source) implementerar digital
n-of-1-körning med randomisering — läs deras lösningar först (SOTA-svep 2026-10-29).

## 3. Hierarkisk styrkedelning — n ≥ 2-metoden

Aggregerade n-of-1 med Bayesiansk shrinkage: individer lånar styrka av
population utan att dela rådata (Shrestha & Jenkins 2021; HDSR specialnummer).
Byggs först när en andra användare finns med egna körda studier. Det är också
RWE-pitchens metodologiska ryggrad: heterogenitet i behandlingseffekt.

## 4. Mikro-randomiserade studier (MRT) — parkerad på principbeslut

Fältets standard för mobil hälsa (Murphy m.fl.): randomisering per
beslutstillfälle, hundratals per person, excursion-effekter. Enorm styrka per
kalendertid — men kräver att motorn skickar prompts vid beslutstillfällen,
vilket nuddar konstitutionens push-förbud. Möjlig linje: opt-in-prompts enbart
inom en låst studie är inte engagemangspush. **Beslutet är Carls**, inte
teknikens. Byggs inte före det beslutet.

## 5. Prior-bibliotek för design — vilande tills ett förslag behöver det

Publicerad statistik (metaanalyser, MCID-värden) som litet bibliotek
(YAML per påstående: källa, population, effektstorlek, KI) — läst av
**förslagsgrinden, aldrig av domen**. Tre legitima användningar: rangordna
vilka frågor som är värda att ställa, förankra `minsta_relevanta_effekt`
när personens baslinje är tunn, och sätta realistiska styrkeförväntningar
(litteraturen förutsade p00: dagseffekt av promenad på vilopuls är liten).
Gräns satt av uppmätt resultat: kunskapsbas i *bedömningen* gjorde LLM-
granskaren sämre (RESULTAT.md, 20 falska godkännanden) — litteratur får
forma frågan, aldrig fria svaret. Mot ditt eget normala, aldrig en norm.
Grind: byggs först den dag ett konkret förslag behöver en litteratur-
förankrad effektstorlek. Relaterat: T1DEXI/OhioT1DM/DiaTrend (Carls
Vivli-ansökan) laddas när de beviljas — men in i **benchmarken** som
planterade effekter på riktiga serier, inte som priors.

## Bevisaxlarna — vad som är en slutsats på riktigt (källgranskat 2026-10-28)

Carls krav: "vi måste kunna reglera vad som är en slutsats på riktigt — inte
bara: efter 1 timme, nej, det finns ingen korrelation, sen var studien över."
Djupsökningen visar att fältet inte använder en trappa utan **två axlar**, och
att måttet aldrig är kalendertid utan design + täckta lottade dagar.

### Axel 1 — design (OCEBM 2011, frågan "hjälper insatsen?")

Oxford-nivåerna, ordagrant ur tabellen (CEBM Levels of Evidence 2.1):
nivå 1 = *"systematic review of randomized trials or n-of-1 trials"*,
nivå 2 = randomiserad studie (eller observation med dramatisk effekt),
nivå 3 = icke-randomiserad kohort, nivå 4 = fallserier/case-control,
nivå 5 = mekanismresonemang. För biverkningsfrågan är nivå 1 uttryckligen
*"n-of-1 trial with the patient you are raising the question about"*.

Det avgörande: **en randomiserad n-of-1 på personen själv är nivå 1-bevis för
den personen** — inte en svagare kusin till "riktiga" studier. Selvras
kärndesign sitter alltså högst på axeln, för exakt den fråga Selvra ställer.

Mappning: skanner-mönster = nivå 5 (mekanism/hypotes — aldrig en slutsats);
retrospektiv självkontrollerad körning (p00) = observationsstudie;
prospektiv lottad förregistrerad n-of-1 (001, p02) = nivå 1 för personen.

### Axel 2 — tillförlitlighet (GRADE)

Fyra betyg: hög, måttlig, låg, mycket låg. Randomiserat startar **hög**;
observation startar **låg**. Nedgradering (fem domäner): risk för bias,
inkonsistens, indirekthet, imprecision, publikationsbias. Uppgradering
(endast observation): stor effekt, dos–respons, motriktad confounding.

Selvras maskineri är redan GRADE-format utan att ha hetat så:
"**obestämt**" = imprecision (intervallet rymmer både relevant och irrelevant
effekt); dagstyp-VARNING = risk för bias; negativ kontroll = bias-detektion;
periodeffekt-avsnittet = indirekthet. Konsekvensen för p00: en retrospektiv
dom startar **låg** och kan aldrig bli hög hur snäv skattningen än är —
därför är den en dörr, inte ett lås.

### Replikationens två platser (här satt utkastet fel)

- **Inom personen:** replikationen är paren/cyklerna i n-of-1-designen själv —
  fler lottade par = starkare dom. Det är *tidens* legitima roll: tid köper
  par, inte mognad. 24 lottade dagar över tio veckor slår 32 historiska nätter
  beräknade på en timme — av designskäl, inte av kalenderskäl.
- **Mellan personer:** aggregering (hierarkisk modell, §3) svarar på en
  *annan* fråga — populationseffekt och heterogenitet — och är ingen "högre
  nivå" för individen. Generaliserbarhet och individuell bevisstyrka är
  olika axlar och ska aldrig blandas i språket.

### Regler i drift

1. **Varje slutrapport och tolkning anger båda axlarna**: design i rubriken
   (görs redan: "retrospektiv observation") och tillförlitlighet i
   Svar-avsnittet (infört 2026-10-28: `_tillforlitlighet` i study.py —
   n1 startar hög, observation låg, obestämt beslut sänker en nivå för
   imprecision).
2. **En observationsdom (låg tillförlitlighet) stänger aldrig frågan** — den
   kvalificerar eller diskvalificerar den för en nivå 1-prövning. p00:s nej
   betyder: inte värt 24 lottade dagar på vilopuls, pröva sömnen. Det är dess
   hela auktoritet.
3. **Retrospektiva körningar följer target trial-emulering** (Hernán m.fl.):
   protokollet — tidsnoll, regel, utfall, analys — låses före beräkning, som
   p00 gjorde. Ramverket botar tidsnoll-fel men aldrig confounding; därav
   startbetyget låg.
4. **Snabbhet får bara komma från förregistrering, aldrig från iver.**
   Sekventiella gränser (§2) kortar kalendertid via i förväg låsta
   avläsningspunkter; de sänker aldrig paren under golvet och flyttar inget
   på axlarna.
5. **Grinden får vägra av underlagsskäl** — p02-stoppet är axel 2 i förväg:
   hellre en senare nivå 1-dom än en som föds obestämd.

Källor: OCEBM Levels of Evidence Working Group, "The Oxford 2011 Levels of
Evidence" (CEBM 2.1-tabellen); GRADE handbook-domänerna (BMJ-serien);
Hernán m.fl., "Target Trial Emulation" (JAMA 2022); Kravitz & Duan (red.),
*Design and Implementation of N-of-1 Trials: A User's Guide* (AHRQ 2014);
CENT 2015 (redan motorns rapportstandard).

## 6. Mätlagret — rörets fel är en del av variansen (vilande tills 14-dagarstabellen finns)

Selvra lovar källattribuering: "Garmin mätte X". Om röret mellan källan och
Selvra förvränger X är attribueringen falsk precision. Mätlagret jämför de rör
Selvra faktiskt använder mot källans egna filer (FIT-facit) och ger tre saker,
oavsett om det någonsin blir en tjänst av det:

1. **Spegeln blir ärlig**: morgonrapporten slutar säga "över ditt vanliga" när
   avvikelsen är mindre än rörets kända mätfel (UPPLEVELSEN §5).
2. **Studierna blir bättre**: rörets spridning per dag är en del av variansen i
   varje n-of-1-test. Känd spridning → vet vilka effekter som alls går att
   upptäcka; den hör hemma i styrkeberäkningen. Ändringen i granska görs
   fall-först enligt PROTOKOLL när tabellen finns.
3. **Oberoende av mellanled**: Selvra blir ett system som vet hur bra dess
   egna källor är, i stället för ett som litar på dem. Om värdet ligger i
   modellen av användaren måste modellen veta hur mycket den kan lita på
   sina egna data.

**Avgränsningen som alltid följer med: rörets trohet är inte fysiologisk
sanning.** Jämförelsen mot enhetens fil svarar "levererade röret det enheten
registrerade?" — aldrig "stämmer pulsen?". Fel som träffar fil och API lika
syns inte i rörjämförelsen utan bara som förändringspunkter i personens
tidsserie vid versionsbyten — därför loggas firmware per hämtning (rörloggen),
och de två dimensionerna är komplementära. Motivet är belagt i litteraturen:
mjukvaruuppdateringar flyttar mått 3–13 % inom samma person (Sturrock m.fl.,
PLOS Digital Health 2025) och en tredjedel av firmwareuppdateringar kan
ogiltigförklara en validering (Woolley m.fl., BMJ HCI 2019). Inte heller
enhetens fil är neutralt facit — även rådataprodukter versioneras.

**Gränsen, så att mätlagret inte blir ett eget projekt:** det gäller de
personers apparater som redan är i drift och de rör Selvra faktiskt använder —
ingenting mer. Jämförelsebänkar och källor Selvra inte använder ligger
utanför detta och prövas i så fall separat, mot egna grindar.

## 7. Självstudien — systemet som forskningsobjekt åt sig själv (i drift)

Domstolsprincipens meta-varv: journalerna om systemets eget arbete får samma
mönsterletning som människornas data. Varje morgon (`sjalvstudie.py`):
rörloggen mot sig själv (formändringar = seriebrotts-kandidater — driftlarm
utan facit), förslagsgrindens dombeteende över tid (ett stoppskäl som
dominerar länge är en hypotes om granskaren, inte bara om datan —
styrka-rättningen hittades manuellt ur exakt det mönstret; grindbesluten
persisteras i grindloggen), domregistret och datadagarna räknade ur journaler
i stället för prosa. Beskrivande rapport, aldrig push — tystnad före brus
gäller även metalagret. Fynd härifrån blir hypoteser och frusna fall enligt
PROTOKOLL, aldrig automatiska ändringar.

## 8. Käll-reliability ur egna prediktionsfel — vilande tills tabellen motiverar den

Metakognitions-mekanik (HOT-2-mönstret ur selvra-brain): en prediktor som
förutsäger sitt eget fel ger, inverterat, en löpande pålitlighetsskattning per
källa — "den här källan är ostabil just nu". Studie-nivå-versionen finns redan
(granskarens SD-osäkerhetsband); detta vore dagliga per-rör-versionen, som
kunde mata trendvakten ("trenden vilar på en ostabil källa — säg det") och
mätfelsregeln (UPPLEVELSEN §5). Grind: byggs först om 14-dagarstabellen visar
att källors pålitlighet varierar nog att behöva skattas löpande. Fall-först
enligt PROTOKOLL när den byggs.

## ML-reglerna — föreslå och attackera, aldrig döma

Grundregeln är uppmätt, inte tyckt: som domare släppte frontier-LLM:en igenom
17–20 av 30 trasiga designer där den deterministiska granskaren släppte 0, och
en kunskapsbas gjorde den sämre (RESULTAT.md). Samma modell var hederlig på
ren sifferläsning (motortestets LLM-arm). Därav tre roller:

1. **Generera.** LLM skriver studieutkast, tolkningar och synteser — alltid
   genom grindarna (granskaren fäller utkast, språkgrinden fäller prosa,
   reserven är deterministisk). Bättre modeller ger bättre förslag; leverans-
   vägen ändras aldrig. Skannern förblir med flit modellfri: lutningar,
   korrelationer, sviter — detektorer som går att citera.
2. **Attackera.** Agenter författar benchmarkfall, chaos monkey (PROTOKOLL 7)
   och motortestets LLM-arm är stående mätbänkar. En modell som försöker fälla
   systemet kan bara göra nytta: en träff blir en rättning, en miss ett bevis.
   Varje ny modellgeneration mäts om i LLM-armen — "har AI blivit bättre på
   metodgranskning?" är en empirisk fråga med facit.
3. **Lära, modellfritt.** Systemets förbättring är ett data-svänghjul utan
   viktuppdateringar: personliga percentiler, styrka ur egen varians,
   Dreamer-minnet, misser som blir frusna fall, veckokalibrering. Planerat
   statistiskt lärande är klassiskt och granskbart: hierarkisk Bayes (§3),
   förändringspunkter vid versionsbyten.

**Aldrig i domsvägen.** Ingen tränad modell avgör håller/motbevisad/obestämd,
och ingen optimering sker på systemets egna utfall — det bygger en maskin som
blir skickligare på att låta rätt, inte på att ha rätt.

**Om en tränad modell någonsin får plats i kedjan** (t.ex. artefakt-
klassificering): den behandlas som ett rör. Versionsloggas i rörloggen som en
firmware, byts aldrig tyst, får fruset facit före driftsättning enligt
PROTOKOLL, och ett modellbyte markerar seriebrott i serierna den rört.

## Regression — bara i skannern och faktoranalysen, aldrig i domen

Regression är ett generator- och utforskningsverktyg, inte en domare. Den får
bo på exakt två ställen — **skannern** (för att föreslå frågor) och **det
utforskande sambandet** (`utforskande_samband`, förvalda faktorer mot ett
utfall) — och aldrig i den konfirmerande körningen eller i
håller/motbevisad/obestämd. Samma gräns som ML-reglerna, av samma skäl: det som
föreslår får vara rikt, det som dömer måste vara förregistrerat och citerbart.

`utforskande_samband` (byggd 2026-10-31) bär fyra spärrar: allt märkt observerat
(GRADE: låg); faktorer valda i förväg i `faktorer.yml` (förbjudna kolumner —
insulin, kolhydratkvoter, hypobehandling m.m. — vägras i kod); tidsordning
inbyggd (faktor dag t mot utfall natten t→t+1, aldrig del av utfallet); och en
datagräns — de dagar den rangordnat på är förbrukade, så en fråga därifrån får
bara prövas på data efter låsning (låsflödet vägrar överlapp, PROTOKOLL §3b).
Metod: OLS + cirkulär block-bootstrap (dag-beroende), firmwarebyte redovisas
före/efter separat. Under `min_dagar`: "inget underlag", ingen rangordning.

**Riktig faktoranalys** — att leta några få *dolda dimensioner* bakom många
korrelerade mått (t.ex. att HRV, vilopuls och sömn kan mäta samma "återhämtning")
— är något annat än regressionen ovan och byggs **senare, som eget steg**, när
antalet dagar räcker. Inte nu.

Fyra villkor när den används:

1. **Alltid märkt observerat.** En regressionskoefficient är en association i
   historisk data, aldrig en effekt. Den ärver observationens startbetyg
   (GRADE: låg) och presenteras aldrig som en dom.
2. **Faktorer valda i förväg.** Vilka prediktorer som ingår bestäms innan
   modellen körs — ingen stegvis sökning, ingen jakt på det som råkar bli
   signifikant. Fiske är fiske även utan ett p-värde i domsvägen.
3. **Hänsyn till beroende mellan dagar.** Dagar ur ett liv är inte oberoende
   (samma autokorrelation som block-bootstrapen hanterar i domen). Standardfel
   och intervall tar hänsyn till det, annars blir precisionen falsk.
4. **Apparat och firmware alltid med som faktorer.** Mjukvaruuppdateringar
   flyttar mått 3–13 % inom samma person (§6); en regression som utelämnar
   apparat och firmware tillskriver den förskjutningen fel orsak. De är
   obligatoriska kovariater, inte valfria.

## Byggs inte, med skäl

- **Bandit-allokering för behandlingsval** (adaptiv randomisering mot "bästa
  armen"): optimerar val, inte kunskap; svårare felkontroll; fel passform för
  bevis-varumärket innan sekventiella gränser finns.
- **LLM-bedömning i granskningen**: uppmätt sämre än deterministisk beräkning
  (RESULTAT.md: 0 mot 17–20 falska godkännanden). LLM föreslår; koden beslutar.
