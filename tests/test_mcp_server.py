"""MCP-servern: exponerar bara det som finns, ingen mutation, allt grindat."""

from selvra_analysis import mcp_server as srv
from selvra_analysis import sagt


def test_servern_har_inga_mutationsverktyg() -> None:
    # bara läsa + spara_sagt; ingen uppdatering/radering/statusändring exponeras
    verktyg = {n for n in dir(srv) if not n.startswith("_") and callable(getattr(srv, n))}
    for farligt in ("uppdatera", "radera", "ta_bort", "satt_status", "delete", "andra"):
        assert not any(farligt in n for n in verktyg), farligt


def test_spara_sagt_ger_alltid_status_sagt(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    svar = srv.spara_sagt("Jag sover sämre efter kvällspass", "sjalvbild",
                          "bekraftad", "faktisk")
    assert "sagt" in svar.lower()
    r = sagt.hamta("kvällspass")
    assert len(r) == 1
    assert r[0]["status"] == "sagt"
    assert r[0]["citat"] == "Jag sover sämre efter kvällspass"
    # talare sätts i servern, inte av agenten: alltid anvandare, ingen parameter
    assert r[0]["talare"] == "anvandare"
    assert "talare" not in srv.spara_sagt.__doc__.lower()  # verktyget erbjuder inte valet


def test_negerad_kommer_tillbaka_negerad(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    srv.spara_sagt("jag tar inte kaffe efter 15", "handelse", "negerad", "faktisk")
    ut = srv.hamta_om("kaffe")
    assert "negerad" in ut
    assert "inte kaffe" in ut


def test_hamta_om_har_tre_grupper_var_for_sig(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    srv.spara_sagt("Jag tränar på morgonen", "handelse", "bekraftad", "faktisk")
    ut = srv.hamta_om("tränar")
    assert "SAGT" in ut
    assert "MÄTT" in ut
    assert "PRÖVAT" in ut


def test_dalig_input_sparas_inte(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert "sparades inte" in srv.spara_sagt("", "handelse", "bekraftad", "faktisk")
    assert "sparades inte" in srv.spara_sagt("x", "fel_typ", "bekraftad", "faktisk")
