"""Vakt: ett test får aldrig röra riktiga filer.

Fäller testet som skriver till den riktiga studies/minne.yml eller skapar filer
under data/ — båda ska gå till tmp_path (monkeypatch.chdir eller en sökväg).
Hälsodata och skannerns riktiga hypoteslista får aldrig bero på en testkörning.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MINNE = REPO / "studies" / "minne.yml"
DATA = REPO / "data"


def _data_filer() -> set[pathlib.Path]:
    return {p for p in DATA.rglob("*") if p.is_file()} if DATA.exists() else set()


@pytest.fixture(autouse=True)
def _inga_riktiga_skrivningar():
    minne_fore = MINNE.read_bytes() if MINNE.exists() else None
    data_fore = _data_filer()
    yield
    fel = []
    if MINNE.exists() and MINNE.read_bytes() != minne_fore:
        fel.append(f"skrev till riktiga {MINNE.relative_to(REPO)}")
    nya = sorted(str(p.relative_to(REPO)) for p in (_data_filer() - data_fore))
    if nya:
        fel.append(f"skapade filer under data/: {nya}")
    if fel:
        pytest.fail("testet rörde riktiga filer (isolera med tmp_path / "
                    "monkeypatch.chdir): " + "; ".join(fel))
