# Protokoll: hur granskningen får utvecklas

Benchmarken är inte en engångsmätning utan motorns utvecklingsmekanism. Reglerna
nedan är det som gör siffrorna trovärdiga över tid. De ändras bara genom att en
ny version av den här filen committas med motivering.

## 1. Fall först, fix sedan

Ingen metodrättning utan ett fallerande fryst fall. Ordningen är alltid:

1. Skriv fallet (studie + scenario + facit med motivering och källa) som
   återskapar felet.
2. Frys (`benchmark frys`) och committa — commiten bevisar att fallet fanns
   före fixen.
3. Kör och bokför att fallet fallerar.
4. Implementera rättningen.
5. Kör igen: fallet grönt, hela regressionssviten grön.

Regressionsfall (`fall/`) får skrivas av den som skriver rättningen.

## 2. Facit ändras aldrig i efterhand

Ett fel i ett facit rättas genom ett nytt fall, aldrig genom att ändra det gamla
efter att resultat setts. Felaktiga facit bokförs som facitfel i RESULTAT.md och
står kvar.

## 3. Skiljedom görs aldrig av systemet som testas

När granskning och facit är oense avgör en oberoende beräkning ur scenariots
sanna parametrar (t.ex. simulerad sann styrka) — aldrig granskningens egen
skattning, och aldrig en språkmodells bedömning.

## 3b. En utforskande blick förbrukar sina dagar

`utforskande_samband` (regression, METODPLAN) får titta på historisk data för att
*föreslå* frågor — men de dagar den rangordnat på är därmed förbrukade för
bekräftelse. **En fråga därifrån får bara prövas på data insamlad EFTER att
studien låsts.** Låsflödet (`study.lock`) läser de analyserade fönstren
(`data/samband_fonster.json`) och vägrar en studie vars datafönster överlappar.
Utan den regeln blir skannern ett sätt att kika på svaret innan regeln låses, och
domstolsprincipen faller — det är den viktigaste spärren kring det utforskande
lagret.

## 4. Dolda uppsättningar förbrukas och roteras

- En dold uppsättning är ett ärligt mått **en** gång. Rättas granskningen efter
  att uppsättningens resultat setts är den förbrukad för de kategorier
  rättningen rör, och det bokförs.
- Nästa dolda uppsättning skrivs av en författare som inte sett rättningen —
  aldrig av den som skrev den. Författaren får läsa: fallformatet,
  skältabellen, README och RESULTAT:s missanalyser. Aldrig `granska.py`.
- Varje batch av metodändringar avslutas med en ny dold uppsättning innan
  nästa batch påbörjas.

## 5. Verkliga missar blir fall

Varje miss i verklig drift — en studie som visade sig felkonstruerad trots
godkänd granskning, ett stopp som visade sig omotiverat — blir ett fryst fall
innan något annat görs åt saken. Produktionen är benchmarkens viktigaste källa.

## 6. Måtten redovisas alltid i par

Stoppfrekvens utan godkännandefrekvens är meningslös (stoppa allt ger 100 %).
Falska godkännanden och falska stopp redovisas alltid tillsammans, med antal
fall i nämnaren.

## 7. Chaos monkey

Inför varje större släpp: en ny session utan kontext (`claude -p`, neutral, utan
minne av projektet) instrueras att attackera tesen och motorn — hitta sätt att
få igenom trasiga studier, lura domslutet eller knäcka antagandena. Varje äkta
fynd blir ett fryst fall eller en gate innan nästa släpp. Idé: F. Aiboud Nygren.

## 8. Hela kedjan testas mot skapad sanning

Granskningsbenchmarken testar designgranskningen; motortestet
(`make motortest`) testar själva domslutet på riktig data där sanningen är
skapad: omblandade exponeringar (rätt svar: inget definitivt besked) och
planterade effekter (rätt svar: hitta dem). Falsk-fynd-frekvens och
detektionsgrad redovisas alltid tillsammans, per exponeringsantal. Körs om
efter varje ändring i statistik- eller beslutslagret.
