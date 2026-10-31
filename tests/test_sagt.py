"""sagt: append-only bevisas, citatet är heligt, evidens är enda vägen uppåt."""

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
    for farligt in ("update", "uppdatera_post", "radera", "ta_bort", "delete", "skriv_over"):
        assert not any(farligt in n for n in publika if n != "uppgradera_status"), farligt


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


def test_status_kraver_evidens_aldrig_modellsakerhet(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pid = sagt.spara(POST)
    with pytest.raises(ValueError, match="evidens"):
        sagt.uppgradera_status(pid, "matt", {"typ": "modellen_ar_saker", "referens": "x"})
    with pytest.raises(ValueError, match="hoppar"):
        sagt.uppgradera_status(pid, "provat", {"typ": "matserie", "referens": "steg 14 d"})
    sagt.uppgradera_status(pid, "matt", {"typ": "matserie", "referens": "steg 14 d"})
    sagt.uppgradera_status(pid, "provat", {"typ": "last_studie", "referens": "003"})
    assert sagt._status(pid) == "provat"


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
    sagt.uppgradera_status(pid, "matt", {"typ": "matserie", "referens": "steg 14 d"})
    r = sagt.hamta("promenera")[0]
    assert r["status"] == "matt"
    assert r["evidens"]["referens"] == "steg 14 d"
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
    sagt.spara({**POST, "talare": "tredje_part",
                "citat": "mamma sa att jag sover oroligt", "citat_offset": 0,
                "modalitet": "annans_rost"})
    r = sagt.hamta("mamma")[0]
    assert r["talare"] == "tredje_part"       # VEM som sa det
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
