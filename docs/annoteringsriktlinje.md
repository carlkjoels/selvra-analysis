# Annoteringsriktlinje — Selvras golden set

Steg 0 i minneslager-planen ([[0001-minneslager-maalarkitektur]]): reglerna som två
människor märker efter, innan någon kod skrivs. Golden set har två delar:
`gs-extraktion` (enskilda påståenden ur ett meddelande) och `gs-länkar` (par av
påståenden som ska kopplas). Riktlinjen är den enda källan till vad ett rätt svar
*är*; när annotatörer är oense skrivs oenigheten in här, aldrig bort.

**Värdemängder är desamma som benchens `facit/SCHEMA.md`** (typ, polaritet,
modalitet, talare) så att export mot benchen blir en ren namnmappning. Riktlinjen
lägger bara till `osaker` och de fem länktyperna, som är Selvras egna.

**Inga riktiga data.** Varje exempel nedan är hittepå. Selvras verkliga golden set
(samtyckta, pseudonymiserade dogfood-yttranden) hålls **helt skild från benchens
repo** och från dessa exempel.

---

## Grundregler

- **Citatet är en sats, inte ett ord.** Märk alltid så att negation, modalitet och
  villkor ligger *inne i* citatet: "inte", "ska", "skulle", "om", "mamma säger att".
  Citatet ska vara en exakt delsträng av ett *användarmeddelande*.
- **Talare sätts av rollen, aldrig av tolkning.** Bara ett `user`-meddelande kan ge
  ett sparat påstående (`sagt`).
- **Vid osäkerhet: märk osäkert, spara inte en gissning.** En oklar referent ("hon
  sa, men jag minns inte vem") sparas inte alls.

---

## Typ — `intention | handelse | sjalvbild`

Vad slags sak påståendet är.

| typ | betydelse | exempel (sv / en) |
|---|---|---|
| `intention` | en avsikt, en plan framåt | "Jag ska börja promenera efter lunch" / "I'm going to cut my coffee" |
| `handelse` | något som hände eller görs | "Jag bytte sensor i tisdags" / "I switched to decaf" |
| `sjalvbild` | ett stående drag om personen | "Jag är morgonmänniska" / "I don't drink alcohol" |

Gränsfall: en vana ("jag tar tabletten varje kväll") är `handelse`, inte `sjalvbild`.

## Polaritet — `bekraftad | negerad`

Bevarar negationen. Vänd den aldrig.

- Svenska negationstecken att se efter: **inte, ej, aldrig, ingen/inget, utan, slutat**.
  Engelska: **not, no, never, without, stopped, don't/doesn't**.
- Varning: negationen saknar ibland ett lexikalt tecken ("Jag är fri från besvär" =
  negerad). Läs satsen, inte bara ordlistan.
- Exempel: "Jag tar inte kaffe efter 15" → `negerad`. "I'm not on any blood thinners"
  → `negerad`. "Jag dricker kaffe på morgonen" → `bekraftad`.

## Modalitet — `faktisk | avsedd | hypotetisk | annans_rost | osaker`

Det fält där mätningen kommer att visa flest fel. Märk strikt.

| modalitet | betydelse | exempel |
|---|---|---|
| `faktisk` | gäller nu, som fakta | "Jag tar 500 mg metformin" |
| `avsedd` | en avsikt, inte ännu gjort | "Jag ska börja ta dem på morgonen" |
| `hypotetisk` | under ett villkor som inte inträffat | "Om proverna är dåliga kanske jag börjar med insulin" |
| `annans_rost` | *om* någon annan sa/tycker (talaren är ändå användaren) | "Läkaren sa att proverna var normala" |
| `osaker` | körningarna är oeniga, eller satsen bär ingen tydlig modalitet | märks av k=3-oenighet, inte av handen i första hand |

Tre regler som annotatörer missar:

- **Villkorat = `hypotetisk` med villkoret kvar i citatet.** "Om biverkningarna
  fortsätter ska jag ringa läkaren" är `hypotetisk`; klipp aldrig bort "om…".
- **`annans_rost` är *om* någon annan, inte *vem som talar*.** Talaren är fortfarande
  `user`; det är modaliteten som bär att orden är någon annans. ("Mamma tycker att
  jag jobbar för mycket" → talare `user`, modalitet `annans_rost`.)
- **`osaker` är en utgång, inte en soptunna.** Använd den när meningen genuint är
  tvetydig, inte för att slippa välja.

## Talare — `user | assistant | third`

Sätts ur meddelandets roll, i kod. Riktlinjen säger bara vad som får bli `sagt`:

- `user` → kan bli ett sparat påstående.
- `assistant` → **aldrig** `sagt` (ett assistentförslag får inte bli användarens avsikt).
- `third` → **aldrig** `sagt`. En tredje part som talar i transkriptet ("Hon glömmer
  ofta sina tabletter") får aldrig lagras som användarens egen utsaga.

## Tid

Märk **det ordagranna uttrycket**, och, när det går, det upplösta datumet.

- Uttrycket ligger inne i citatet och klarar delsträngskontrollen: "på fredag",
  "sista augusti", "i julas", "om två veckor", "i förrgår".
- Upplös deterministiskt mot meddelandets tidsstämpel och användarens tidszon.
- **Tvetydigt → `olöst`, aldrig en gissning.** "På fredag" (denna eller nästa?) och
  veckonummer (Sverige använder ISO-veckor) märks `olöst`.

---

## De fem länktyperna (`gs-länkar`)

En länk kopplar **två bestämda poster**. Skillnaden mellan "ändrat sig", "hade fel"
och "båda stämmer" ligger i **giltighetstid och kontext** — fånga dem vid märkning,
annars går paret inte att klassa.

| länk | betydelse | exempel |
|---|---|---|
| `supersedes` | ändrat sig / uppdaterat tillstånd; samma ämne, senare giltighetstid | "Jag flyttade till Malmö förra månaden" ersätter "Jag bor i Göteborg" |
| `corrects` | självrättelse i samma yttrande/samtal; gamla gällde aldrig | "Två gånger. Nej förresten, tre gånger." |
| `contradicts` | två poster om *samma* giltighetstid kan inte båda stämma | "sover 8 h" mot sensorns median 6,1 h |
| `context_differs` | båda stämmer under olika villkor; kvalificeraren lagras på nya posten | "tränar på morgonen" (vardag) vs "på kvällen" (helg) |
| `evidences` | kopplar ett `sagt` till en mätserie eller en låst n-of-1-studie | "jag sover dåligt" ↔ sömnserien |

Regler:

- **Ett `sagt`-mot-`sagt`-par får aldrig märkas `corrects` ("hade fel") automatiskt.**
  Utan evidens har Selvra inget facit för vem som hade rätt — då är det `supersedes`
  (om tiden skiljer) eller `contradicts` (om samma tid).
- **`contradicts` löses aldrig automatiskt.** Det är kärnsignalen (typiskt sagt mot
  mätt); båda sidor visas, ingen vinner i kod.
- **`corrects` kräver en självrättelsemarkör** i samma meddelande/samtal: "nej
  förresten", "jag menade", "no wait", "sorry, I meant".

---

## Process

- **Två oberoende annotatörer** märker minst 50 items var. κ rapporteras **per fält**
  (typ, polaritet, modalitet, talare, tid) och per länkkategori.
- **Lågt κ på en kategori betyder att kategorin är fel definierad**, inte att en
  modell är dålig. Troligaste tvistfallet: `supersedes` ("ändrat sig") mot
  `context_differs` ("båda stämmer"). Oenigheten skrivs in här som en ny regel.
- Varje oenighet som löses blir ett tillägg i denna fil med ett daterat exempel.
- `gs-extraktion`: 300 items, ~60 % svenska / 40 % engelska, minst 100
  polaritetsbärande. `gs-länkar`: 150 par över de tio kategorierna i planen.
- Dev-delen itereras fritt; testdelen fryses med ett manifest (item-id,
  innehållshash, etikettversion) och rörs bara vid milstolpar.

*Golden set och annotering byggs när riktlinjen är låst; denna fil är förutsättningen,
inte bygget.*
