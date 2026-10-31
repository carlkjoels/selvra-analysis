"""sagt: append-only bevisas, citatet är heligt, evidens är enda vägen uppåt."""

import unicodedata

import duckdb
import pytest

from selvra_analysis import sagt, sprakgrind

POST = {"typ": "intention", "kalla": "morgonsvar", "kallmeddelande_id": "m1",
        "citat": "jag vill börja promenera efter lunch", "citat_offset": 12,
        "polaritet": "bekraftad", "modalitet": "avsedd", "talare": "anvandare",
        "said_at": "2026-10-29", "tidsuttryck_ratt": "efter lunch",
        "modell": "test", "promptversion": "p0"}


def test_api_saknar_mutationsvagar() -> None:
    """Inget LLM-steg kan uppdatera eller radera: funktionerna finns inte."""
    publika = [n for n in dir(sagt) if not n.startswith("_")]
    for farligt in ("update", "uppdatera", "radera", "ta_bort", "delete", "skriv_over"):
        assert not any(farligt in n for n in publika), farligt


def test_post_utan_citat_avvisas(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="citat"):
        sagt.spara({**POST, "citat": "  "})


def test_journalen_vaxer_bara_och_dubbletter_ar_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    n1 = len(sagt._journal_rader())
    assert sagt.spara(POST) == pid          # exakt samma citat/källa → samma id
    assert len(sagt._journal_rader()) == n1  # ingen ny rad


def test_status_harleds_ur_evidens_aldrig_modellsakerhet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    assert sagt._status(pid) == "sagt"                 # ingen evidens → sagt
    with pytest.raises(ValueError, match="evidens"):   # modellsäkerhet är inte evidens
        sagt.koppla_evidens(pid, {"typ": "modellen_ar_saker", "referens": "x"})
    sagt.koppla_evidens(pid, {"typ": "matserie", "referens": "steg 14 d"})
    assert sagt._status(pid) == "matt"                 # mätserie → mätt
    sagt.koppla_evidens(pid, {"typ": "last_studie", "referens": "003"})
    assert sagt._status(pid) == "provat"               # låst studie → prövat


def test_indragen_evidens_sanker_status_utan_omskrivning(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    sagt.koppla_evidens(pid, {"typ": "matserie", "referens": "steg 14 d"})
    sagt.koppla_evidens(pid, {"typ": "last_studie", "referens": "003"})
    assert sagt._status(pid) == "provat"
    fore = sagt.JOURNAL.read_text().splitlines()
    sagt.dra_tillbaka_evidens(pid, "003")              # studien dras tillbaka
    assert sagt._status(pid) == "matt"                 # faller ett steg (TMS)
    sagt.dra_tillbaka_evidens(pid, "steg 14 d")        # mätserien dras tillbaka
    assert sagt._status(pid) == "sagt"                 # faller tillbaka helt
    efter = sagt.JOURNAL.read_text().splitlines()
    assert efter[:len(fore)] == fore                   # inget skrevs om, bara tillägg


def test_aterspelningen_bar_bekraftelse_och_status(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    sagt.bekrafta(pid, "2026-10-30T07:02:00Z")
    db = tmp_path / "t.duckdb"
    sagt.spela_upp(db)
    with duckdb.connect(str(db), read_only=True) as con:
        rad = con.execute("select status, bekraftad_av_anvandaren_vid, citat "
                          "from sagt.post").fetchone()
    assert rad == ("sagt", "2026-10-30T07:02:00Z", POST["citat"])


# --- Reflektionsgrinden -----------------------------------------------------

def test_reflektionsgrinden_faller_coach_och_betyg() -> None:
    for text in ("Kanske kan du ta en promenad?", "Har du funderat på mindre socker?",
                 "Sömnbetyg: 7/10.", "Du borde logga mer.", "Bra jobbat med stegen!"):
        ok, _ = sprakgrind.granska_reflektion(text, text)
        assert not ok, text


def test_hypo_blir_aldrig_en_fraga() -> None:
    ok, skal = sprakgrind.granska_reflektion(
        "Du hade en hypo i natt — vad tror du orsakade den?", "hypo i natt")
    assert not ok
    assert "hypo" in skal
    ok, _ = sprakgrind.granska_reflektion("Natten hade en period under 4 mmol/L kl 01:26.",
                                          "under 4 mmol/L 01:26")
    assert ok


def test_glukos_ar_monster_i_tid_aldrig_andel_utanfor_mal() -> None:
    ok, _ = sprakgrind.granska_reflektion("Du låg 34 % utanför målet i går.",
                                          "34 % utanför målet")
    assert not ok
    ok, _ = sprakgrind.granska_reflektion("Glukosen steg efter 21 varje kväll denna vecka.",
                                          "steg efter 21 varje kväll")
    assert ok


def test_hamta_ger_tillbaka_orden_byte_for_byte(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.spara(POST)
    träff = sagt.hamta("promenera")
    assert len(träff) == 1
    r = träff[0]
    assert r["citat"] == POST["citat"]          # ordagrant, aldrig omskrivet
    assert r["citat_offset"] == POST["citat_offset"]
    assert r["modalitet"] == POST["modalitet"]
    assert r["kalla"] == POST["kalla"]
    assert r["status"] == "sagt"                 # ingen evidens → sagt
    assert sagt.hamta("segelbåt") == []          # ingen matchning


def test_hamta_negerad_bar_alltid_falt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    neg = {**POST, "citat": "jag tar inte kaffe efter 15", "citat_offset": 0,
           "polaritet": "negerad", "typ": "handelse", "modalitet": "faktisk"}
    sagt.spara(neg)
    r = sagt.hamta("kaffe")
    assert len(r) == 1
    assert r[0]["polaritet"] == "negerad"        # aldrig utan fältet
    assert "inte" in r[0]["citat"]


def test_hamta_bar_evidens_och_bekraftelse(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    sagt.bekrafta(pid, "2026-11-01T07:00:00Z")
    sagt.koppla_evidens(pid, {"typ": "matserie", "referens": "steg 14 d"})
    r = sagt.hamta("promenera")[0]
    assert r["status"] == "matt"
    assert r["evidens"][0]["referens"] == "steg 14 d"   # evidens är nu en lista
    assert r["bekraftad_av_anvandaren_vid"] == "2026-11-01T07:00:00Z"


def test_hamta_bara_carl_i_v0(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.spara(POST)
    assert sagt.hamta("promenera", person="testare-1") == []


# --- Punkt 4: talare (anvandare | assistent | tredje_part) ------------------

def test_talare_kravs_och_valideras(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="talare"):
        sagt.spara({k: v for k, v in POST.items() if k != "talare"})  # saknas
    with pytest.raises(ValueError, match="talare"):
        sagt.spara({**POST, "talare": "roboten"})                      # ogiltig


def test_hamta_bar_talare(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Användaren rapporterar någon annans ord: talare=anvandare (vem som SA det
    # till Selvra), modalitet=annans_rost (OM vem det handlar). Ortogonalt — och
    # en sagt-post är ALLTID anvandare (rollvitlistan).
    sagt.spara({**POST, "talare": "anvandare",
                "citat": "mamma sa att jag sover oroligt", "citat_offset": 0,
                "modalitet": "annans_rost"})
    r = sagt.hamta("mamma")[0]
    assert r["talare"] == "anvandare"         # VEM som sa det till Selvra
    assert r["modalitet"] == "annans_rost"    # OM någon annan — ortogonalt


def test_migrera_talare_backfyller_gamla_poster(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # skriv en post UTAN talare direkt till journalen (som en post från före fältet)
    sagt._skriv({"op": "post", "id": "abc", "status": "sagt",
                 "citat": "gammalt ord", "kalla": "import"})
    assert sagt.migrera_talare() == 1
    rad = next(r for r in sagt._journal_rader() if r.get("id") == "abc")
    assert rad["talare"] == "anvandare"
    # citat och status orörda
    assert rad["citat"] == "gammalt ord"
    assert rad["status"] == "sagt"


def test_migrera_talare_ar_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.spara(POST)                 # har redan talare
    assert sagt.migrera_talare() == 0
    assert sagt.migrera_talare() == 0


def test_aterspelning_bar_talare_aven_for_omigrerad(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt._skriv({"op": "post", "id": "x1", "status": "sagt",
                 "citat": "utan talare", "kalla": "import"})
    db = tmp_path / "t.duckdb"
    sagt.spela_upp(db)               # ska defaulta talare, inte krascha
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("select talare from sagt.post").fetchone()[0] == "anvandare"


# --- Steg 1+2: rollvitlista, NFC, meddelandelogg, länkar, aktiv/ersatt_av ---

def test_bara_user_kan_bli_sagt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for t in ("assistent", "tredje_part"):
        with pytest.raises(ValueError, match="anvandare"):
            sagt.spara({**POST, "talare": t})
    assert sagt.far_bli_sagt("user") is True
    for roll in ("assistant", "third", "system", "verktyg", "nonsens"):
        assert sagt.far_bli_sagt(roll) is False


def test_observe_sparar_ratext_men_ger_inget_sagt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    mid = sagt.observe_message("assistant", "Du borde sova mer.")
    assert mid is not None                              # råtexten loggas ändå
    assert sagt.hamta("sova") == []                     # men blir aldrig sagt
    rader = sagt._journal_rader()
    assert any(r["op"] == "meddelande" and r["far_bli_sagt"] is False for r in rader)


def test_tom_inmatning_ger_uttryckligt_utfall(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert sagt.observe_message("user", "   ") is None
    assert sagt.observe_message("user", "") is None
    assert sagt._journal_rader() == []                  # inget loggas


def test_nfd_matchar_nfc(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    nfd = unicodedata.normalize("NFD", "jag fastar på måndagar")   # å i NFD
    sagt.spara({**POST, "citat": nfd, "citat_offset": 0, "typ": "handelse"})
    r = sagt.hamta("måndagar")                          # NFC-sökord
    assert len(r) == 1
    assert r[0]["citat"] == unicodedata.normalize("NFC", nfd)      # lagrat som NFC


def test_korrigering_gammalt_varde_blir_inaktivt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    gammalt = sagt.spara({**POST, "citat": "jag tar tabletten två gånger",
                          "citat_offset": 0, "typ": "handelse", "modalitet": "faktisk"})
    nytt = sagt.spara({**POST, "citat": "nej förresten, tre gånger", "citat_offset": 0,
                       "typ": "handelse", "modalitet": "faktisk", "kallmeddelande_id": "m2"})
    sagt.lanka(nytt, gammalt, "corrects")
    poster = {p["version_id"]: p for p in sagt.hamta("gånger")}
    assert poster[gammalt]["aktiv"] is False
    assert poster[gammalt]["ersatt_av"] == nytt
    assert poster[nytt]["aktiv"] is True
    assert poster[gammalt]["linje_id"] == poster[nytt]["linje_id"] == gammalt  # roten


def test_lank_mot_okand_post_vagras(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    a = sagt.spara(POST)
    with pytest.raises(ValueError, match="okänd post"):
        sagt.lanka(a, "finns_inte", "supersedes")


def test_lank_och_meddelande_muterar_aldrig_befintliga_rader(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    a = sagt.spara(POST)
    b = sagt.spara({**POST, "citat": "en helt annan sak", "citat_offset": 0})
    fore = sagt.JOURNAL.read_text().splitlines()
    sagt.lanka(b, a, "supersedes")
    sagt.observe_message("user", "hej Selvra")
    efter = sagt.JOURNAL.read_text().splitlines()
    assert efter[:len(fore)] == fore                    # bara tillägg, inga ändrade rader
    assert len(efter) == len(fore) + 2


def test_ombyggd_vy_lika_med_levande(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    gammalt = sagt.spara({**POST, "citat": "två gånger", "citat_offset": 0, "typ": "handelse"})
    nytt = sagt.spara({**POST, "citat": "tre gånger", "citat_offset": 0, "typ": "handelse",
                       "kallmeddelande_id": "m2"})
    sagt.lanka(nytt, gammalt, "corrects")
    db = tmp_path / "t.duckdb"
    sagt.spela_upp(db)
    with duckdb.connect(str(db), read_only=True) as con:
        rows = con.execute("select version_id, aktiv, ersatt_av, linje_id from sagt.post").fetchall()
        lankar = con.execute("select fran, till, rel from sagt.lank").fetchall()
    live = {p["version_id"]: p for p in sagt._aktuella().values()}
    for vid, aktiv, ersatt, linje in rows:
        assert live[vid]["aktiv"] == aktiv
        assert live[vid]["ersatt_av"] == ersatt
        assert live[vid]["linje_id"] == linje
    assert (nytt, gammalt, "corrects") in lankar


# --- Maskning av citerade Selvra-brev (återkopplingsspärren) ---

def test_citerat_selvra_brev_blir_aldrig_sagt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    brev = "Du sov 7 timmar och 12 minuter i natt."
    sagt.observe_message("assistant", brev)         # Selvras eget brev i dialogen
    with pytest.raises(ValueError, match="återkopplingsslingan"):
        sagt.spara({**POST, "citat": brev, "citat_offset": 0,
                    "typ": "handelse", "modalitet": "faktisk"})


def test_anvandarens_egna_ord_sparas_trots_brev(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.observe_message("assistant", "Du sov 7 timmar och 12 minuter i natt.")
    pid = sagt.spara({**POST, "citat": "jag sover alltid dåligt på söndagar",
                      "citat_offset": 0, "typ": "sjalvbild", "modalitet": "faktisk"})
    assert pid
    assert sagt.hamta("söndagar")[0]["citat"] == "jag sover alltid dåligt på söndagar"


def test_mask_selvra_quotes_maskar_bara_brevet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.observe_message("assistant", "Du sov 7 timmar i natt.")
    text = "Du sov 7 timmar i natt. Men jag kände mig ändå pigg."
    maskad = sagt.mask_selvra_quotes(text)
    assert sagt.MASK in maskad
    assert "7 timmar" not in maskad                 # Selvras mening maskad
    assert "jag kände mig ändå pigg" in maskad      # användarens mening kvar


def test_kort_overlapp_med_brev_maskas_inte(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sagt.observe_message("assistant", "Du sov 7 timmar i natt.")
    pid = sagt.spara({**POST, "citat": "7 timmar", "citat_offset": 0,   # < MIN_MASK
                      "typ": "handelse", "modalitet": "faktisk"})
    assert pid                                        # kort överlapp spärras inte
