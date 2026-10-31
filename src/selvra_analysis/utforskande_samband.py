"""Utforskande samband: förvalda faktorer (dag t) mot ett utfall (natten t→t+1).

En regression, inte en faktoranalys. Den rangordnar associationer med intervall
för att FÖRESLÅ frågor — den dömer aldrig (METODPLAN: regression bara i skannern
och här). Fyra regler bär den:

1. **Utforskande, märkt observerat.** Varje tal ärver observationens startbetyg
   (GRADE: låg) och presenteras aldrig som en effekt eller en dom.
2. **Datan skiljs åt.** Rapporten skriver ut exakt vilket datumintervall som
   användes, och fönstret loggas (spara_fonster) så låsflödet kan vägra en
   bekräftande studie vars datafönster överlappar — annars prövar studien det
   skannern redan tittat på, och domstolsprincipen faller.
3. **Tidsordning inbyggd.** Faktorer från dag t mot utfallet natten t→t+1, aldrig
   samma dygn åt båda håll. Inga faktorer som är del av utfallet. Förbjudna
   kolumner (insulin, kolhydratkvoter, hypobehandling …) avvisas.
4. **För lite data ger null.** Under min_dagar säger rapporten "inget underlag"
   och rangordnar ingenting. Saknade dagar imputeras aldrig som noll.

Metod: OLS (numpy) för skattningar, cirkulär block-bootstrap (samma som motorn,
stats.circular_block_indices) för intervall — hanterar beroendet mellan dagar
utan nytt beroende. Firmwarebyte redovisas före/efter separat, inte som kovariat.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from selvra_analysis.stats import circular_block_indices

MODULVERSION = "1"
CONFIG = Path("faktorer.yml")
DB = Path("data/selvra.duckdb")
STUDIER = Path("studies")
RAPPORT = Path("data/rapporter/samband.md")   # får bo i gitignorerade data/ — kan återskapas
# Fönsterloggen måste överleva att data/ rensas: den bär BARA datum + modulversion
# (inga hälsovärden), ligger i repo-roten och versionshanteras, och är append-only.
FONSTER = Path("samband_fonster.jsonl")


def las_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text())


def _kontrollera_forbjudet(cfg: dict, outcome: str) -> None:
    """Vägrar om en förbjuden kolumn är faktor/utfall, eller om en faktor är del
    av utfallet, eller om utfallet självt står bland faktorerna."""
    forbjudet = set(cfg.get("forbjudet") or [])
    faktorer = list(cfg.get("faktorer") or [])
    trasig = forbjudet & (set(faktorer) | {outcome})
    if trasig:
        raise ValueError(f"förbjudna kolumner får aldrig prövas: {sorted(trasig)}")
    if outcome in faktorer:
        raise ValueError(f"utfallet {outcome!r} får inte också vara en faktor")
    delar = set((cfg.get("del_av") or {}).get(outcome) or [])
    overlapp = delar & set(faktorer)
    if overlapp:
        raise ValueError(f"faktorer som är del av utfallet {outcome!r}: {sorted(overlapp)}")


def _para_ihop(df: pd.DataFrame, faktorer: list[str], outcome: str) -> pd.DataFrame:
    """Faktorer dag t, utfall natten t→t+1. Utfallet för dag t hämtas från t+1
    via kalenderdatum (aldrig radskift — en lucka får inte para fel dagar)."""
    df = df.sort_values("reading_date").reset_index(drop=True)
    idx = pd.to_datetime(df["reading_date"])
    utfall_per_dag = pd.Series(df[outcome].to_numpy(), index=idx)
    nasta = utfall_per_dag.reindex(idx + pd.Timedelta(days=1)).to_numpy()
    finns = [f for f in faktorer if f in df.columns]
    ut = df[["reading_date", *finns]].copy()
    ut["_utfall"] = nasta
    return ut


def _tackning(parad: pd.DataFrame, faktorer: list[str]) -> dict[str, float]:
    """Andel dagar (av de med utfall t+1) som har ett värde per faktor. Saknad =
    saknad, aldrig noll."""
    med_utfall = parad[parad["_utfall"].notna()]
    n = len(med_utfall)
    ut = {}
    for f in faktorer:
        ut[f] = (float(med_utfall[f].notna().mean()) if (f in med_utfall and n) else 0.0)
    return ut


def _designmatris(d: pd.DataFrame, faktorer: list[str],
                  kovariater: list[str]) -> tuple[np.ndarray, list[str], dict[str, str]]:
    """EN gemensam modell: intercept + alla faktorer + kovariater som varierar.
    Alla skattas samtidigt så en faktor inte tar åt sig en annans effekt.
    Kontinuerliga z-standardiseras (skattning per SD), binära lämnas 0/1 (ja vs
    nej). Kovariater (t.ex. apparat) som varierar läggs till som drop-first-
    dummies; firmware är konstant inom segmentet och faller därför bort här."""
    kolumner, namn, enhet = [np.ones(len(d))], ["intercept"], {}
    for f in faktorer:
        v = pd.to_numeric(d[f], errors="coerce").to_numpy(dtype=float)
        unika = np.unique(v[~np.isnan(v)])
        if set(unika.tolist()) <= {0.0, 1.0}:
            kolumner.append(v)
            enhet[f] = "ja vs nej"
        else:
            sd = np.nanstd(v)
            kolumner.append((v - np.nanmean(v)) / sd if sd > 0 else v * 0.0)
            enhet[f] = "per SD"
        namn.append(f)
    for k in kovariater:
        if k not in d.columns:
            continue
        kategorier = sorted(str(c) for c in d[k].dropna().unique())
        for c in kategorier[1:]:  # drop-first; en enda kategori ger ingen kolumn
            kolumner.append((d[k].astype(str) == c).to_numpy(dtype=float))
            namn.append(f"{k}={c}")
            enhet[f"{k}={c}"] = "kovariat"
    return np.column_stack(kolumner), namn, enhet


def _ols_bootstrap(X: np.ndarray, y: np.ndarray, *, block_length: int, n_boot: int,
                   seed: int, level: float = 0.95) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OLS-skattning + intervall via cirkulär block-bootstrap (dag-block)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    rng = np.random.default_rng(seed)
    bl = min(block_length, len(y))
    idx = circular_block_indices(len(y), bl, n_boot, rng)
    boot = np.empty((n_boot, X.shape[1]))
    for i, rad in enumerate(idx):
        b, *_ = np.linalg.lstsq(X[rad], y[rad], rcond=None)
        boot[i] = b
    a = (1 - level) / 2
    return beta, np.quantile(boot, a, axis=0), np.quantile(boot, 1 - a, axis=0)


def _firmware_segment(df: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    """(firmware-etikett, apparat, delmängd) per firmware. Ett firmwarebyte ger
    separata segment — redovisas före/efter, aldrig hopblandat i en kovariat."""
    if "firmware" not in df.columns or df["firmware"].nunique(dropna=True) <= 1:
        fw = str(df["firmware"].dropna().iloc[0]) if "firmware" in df.columns and df["firmware"].notna().any() else "okänd"
        app = str(df["apparat"].dropna().iloc[0]) if "apparat" in df.columns and df["apparat"].notna().any() else "okänd"
        return [(fw, app, df)]
    ut = []
    for fw, sub in df.groupby("firmware", sort=True):
        app = str(sub["apparat"].dropna().iloc[0]) if "apparat" in sub.columns and sub["apparat"].notna().any() else "okänd"
        ut.append((str(fw), app, sub))
    return ut


def kor(df: pd.DataFrame, cfg: dict, outcome: str, *, seed: int = 0,
        studies_dir: Path = STUDIER) -> list[dict]:
    """Ett resultat per firmware-segment. Under min_dagar: underlag=False.

    Omvänd spärr: dagar i en LÅST (eller pågående) studies datafönster exkluderas
    och redovisas — annars kikar en utforskande körning på bekräftande data mitt
    i en studie, vilket domstolsprincipen förbjuder."""
    _kontrollera_forbjudet(cfg, outcome)
    if outcome not in df.columns:
        return [{"outcome": outcome, "underlag": False, "skal": f"utfallet {outcome} saknas i data"}]
    faktorer = list(cfg.get("faktorer") or [])
    kovariater = list(cfg.get("kovariater") or [])
    min_dagar = int(cfg.get("min_dagar", 60))
    uppskattning = set(cfg.get("uppskattning") or [])

    studiefonster = lasta_studiefonster(studies_dir)
    exkluderade: list[str] = []
    if studiefonster and len(df):
        datum = pd.to_datetime(df["reading_date"])
        mask = pd.Series(False, index=df.index)
        for w in studiefonster:
            mask |= (datum >= pd.Timestamp(w["fran"])) & (datum <= pd.Timestamp(w["till"]))
        exkluderade = sorted(df.loc[mask, "reading_date"].astype(str).str[:10].tolist())
        df = df.loc[~mask]

    resultat = []
    for fw, app, seg in _firmware_segment(df):
        parad = _para_ihop(seg, faktorer, outcome)
        tackning = _tackning(parad, faktorer)
        bas = {"outcome": outcome, "firmware": fw, "apparat": app,
               "fran": str(seg["reading_date"].min())[:10], "till": str(seg["reading_date"].max())[:10],
               "tackning": tackning, "exkluderade_dagar": exkluderade,
               "lasta_studiefonster": studiefonster}
        tillgangliga = [f for f in faktorer if f in parad.columns and tackning.get(f, 0) > 0]
        komplett = parad.dropna(subset=["_utfall", *tillgangliga])
        n = len(komplett)
        if n < min_dagar:
            resultat.append({**bas, "underlag": False, "n_dagar": n,
                             "skal": f"{n} kompletta dagar < min_dagar {min_dagar}"})
            continue
        X, namn, enhet = _designmatris(komplett, tillgangliga, kovariater)
        y = pd.to_numeric(komplett["_utfall"], errors="coerce").to_numpy(dtype=float)
        beta, lo, hi = _ols_bootstrap(X, y, block_length=int(cfg.get("blocklangd", 7)),
                                      n_boot=int(cfg.get("n_boot", 2000)), seed=seed)
        rader, kov = [], []
        for j in range(1, len(namn)):  # hoppa intercept
            post = {"faktor": namn[j], "skattning": float(beta[j]), "ci_low": float(lo[j]),
                    "ci_high": float(hi[j]), "enhet": enhet.get(namn[j], ""),
                    "tackning": tackning.get(namn[j], 0.0), "uppskattning": namn[j] in uppskattning}
            (kov if enhet.get(namn[j]) == "kovariat" else rader).append(post)
        rader.sort(key=lambda r: abs(r["skattning"]), reverse=True)
        resultat.append({**bas, "underlag": True, "n_dagar": n, "n_tester": len(rader),
                         "faktorer": rader, "kovariater": kov})
    return resultat


def fragor(resultat: list[dict]) -> list[dict]:
    """Studiefrågor (text, INGEN effektstorlek) för de faktorer vars intervall
    utesluter noll. Fråga om riktning/existens, aldrig om storlek — och den får
    bara prövas på data efter låsning (PROTOKOLL)."""
    ut = []
    for r in resultat:
        if not r.get("underlag"):
            continue
        for f in r["faktorer"]:
            if f["ci_low"] > 0 or f["ci_high"] < 0:  # intervallet utesluter noll
                ut.append({"outcome": r["outcome"], "faktor": f["faktor"],
                           "fraga": f"Påverkar {f['faktor']} dagen före {r['outcome']} natten efter?"})
    return ut


def spara_fonster(outcome: str, fran: str, till: str, path: Path = FONSTER) -> None:
    """Append-only: logga ett analyserat datafönster (bara datum + modulversion,
    inga hälsovärden). Låsflödet läser detta och vägrar en bekräftande studie vars
    fönster överlappar. Append, aldrig skriv-om — raderna är ett bestående spår."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rad = {"outcome": outcome, "fran": fran, "till": till, "modulversion": MODULVERSION,
           "vid": datetime.now(UTC).isoformat(timespec="seconds")}
    with path.open("a") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")


def overlappande_fonster(fran: str, till: str, path: Path = FONSTER) -> list[dict]:
    """Loggade samband-fönster (append-only jsonl) som överlappar [fran, till]
    (ISO-datum). Låsflödet vägrar om listan inte är tom."""
    if not path.exists():
        return []
    ut = []
    for rad in path.read_text().splitlines():
        if not rad.strip():
            continue
        w = json.loads(rad)
        if not (till < w["fran"] or fran > w["till"]):
            ut.append(w)
    return ut


def lasta_studiefonster(studies_dir: Path = STUDIER) -> list[dict]:
    """Datafönstren för LÅSTA studier (las.json finns): n1 = start→schemaslut,
    observation = design.period. Utforskande körningar exkluderar dessa dagar så
    de aldrig kikar på bekräftande data."""
    ut = []
    if not studies_dir.exists():
        return ut
    for mapp in sorted(studies_dir.glob("[0-9][0-9][0-9]-*")):
        las, spec_p = mapp / "las.json", mapp / "studie.yml"
        if "exempel" in mapp.name or not (las.exists() and spec_p.exists()):
            continue
        d = (yaml.safe_load(spec_p.read_text()) or {}).get("design") or {}
        rec = json.loads(las.read_text())
        if d.get("typ") == "n1":
            fran, till = str(d.get("start")), str(rec.get("schedule_end", d.get("start")))
        else:
            period = d.get("period")
            if not period:
                continue
            fran, till = str(period[0]), str(period[1])
        ut.append({"studie": mapp.name, "fran": fran, "till": till})
    return ut


def rapport(resultat: list[dict]) -> str:
    ingress = ("*Förvalda faktorer (dag t) mot utfall natten t→t+1. Associationer, inte "
               "effekter; rangordnade efter skattning med intervall, aldrig p-värde. En "
               "fråga härifrån får bara prövas på data insamlad EFTER att studien låsts "
               "(PROTOKOLL). Firmwarebyte redovisas före/efter separat.*")
    rader = ["# Utforskande samband (regression — observerat, GRADE: låg)", "", ingress, ""]
    for r in resultat:
        rader += [f"## {r['outcome']} · firmware {r.get('firmware', '?')} · {r.get('apparat', '?')}",
                  f"datumintervall: {r.get('fran', '?')} – {r.get('till', '?')}", ""]
        exk = r.get("exkluderade_dagar") or []
        if exk:
            studier = ", ".join(w["studie"] for w in (r.get("lasta_studiefonster") or []))
            rad_exk = (f"*{len(exk)} dagar exkluderade (ligger i en låst studies fönster: "
                       f"{studier}): {exk[0]}–{exk[-1]}*")
            rader += [rad_exk, ""]
        if not r.get("underlag"):
            rader += [f"**inget underlag** — {r.get('skal', '')}", ""]
            continue
        rader += [f"{r['n_dagar']} kompletta dagar · {r['n_tester']} tester", "",
                  "| faktor | skattning | 95 % intervall | täckning | enhet |",
                  "|---|---|---|---|---|"]
        for f in r["faktorer"]:
            namn = f["faktor"] + (" (uppskattning)" if f["uppskattning"] else "")
            rader.append(f"| {namn} | {f['skattning']:+.3f} | "
                         f"[{f['ci_low']:+.3f}, {f['ci_high']:+.3f}] | "
                         f"{f['tackning']:.0%} | {f['enhet']} |")
        kov = r.get("kovariater") or []
        if kov:
            rader += ["", "Kovariater i modellen (kontrollerade för, inte rangordnade): "
                      + ", ".join(f"{k['faktor']} {k['skattning']:+.3f}" for k in kov)]
        rader.append("")
    return "\n".join(rader) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=DB)
    args = p.parse_args(argv)
    cfg = las_config()
    with duckdb.connect(str(args.db), read_only=True) as con:
        df = con.execute("select * from marts.mart_analysis_days order by reading_date").df()
    alla = []
    for outcome in (cfg.get("utfall") or []):
        res = kor(df, cfg, outcome)
        alla += res
        for r in res:  # logga BARA fönster vi faktiskt rangordnat (det är peeken)
            if r.get("underlag"):
                spara_fonster(r["outcome"], r["fran"], r["till"])
    RAPPORT.parent.mkdir(parents=True, exist_ok=True)
    RAPPORT.write_text(rapport(alla))

    # Studiefrågor (text, ingen effektstorlek) in i skannerns Pattern-pipeline —
    # samma väg till Dreamers öppna hypoteser som skannerns egna mönster.
    fr = fragor(alla)
    if fr:
        # Lat import: scanner drar in dreamer-kedjan — hålls ur modulnivån så
        # inget importcykel-beroende uppstår mot lager som kan nå hit.
        from selvra_analysis.scanner import Pattern, spara_hypoteser  # noqa: PLC0415
        per_outcome: dict[str, list[str]] = {}
        for f in fr:
            per_outcome.setdefault(f["outcome"], []).append(f["fraga"])
        spara_hypoteser([
            Pattern(typ="samband",
                    beskrivning=f"Utforskande samband för {oc} — observerat, prövas bara på data efter låsning",
                    fragor=qs, vikt=2)
            for oc, qs in per_outcome.items()])
    print(f"skrev {RAPPORT} ({len(alla)} segment, {len(fr)} frågor till skannern)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
