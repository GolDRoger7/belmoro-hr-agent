"""
Test di parità fra la pulizia in SQL e l'implementazione pandas di riferimento.

La normalizzazione è stata riscritta in SQL per non caricare più il CSV in
memoria. Riscrivere regole di dominio in un altro linguaggio è il momento in cui
si introducono differenze silenziose: una data interpretata diversamente, un
separatore decimale, un duplicato tenuto invece che scartato. Nessuna di queste
fa fallire il programma, ma tutte cambiano i numeri che finiscono in una
risposta.

Qui le due implementazioni vengono confrontate CELLA PER CELLA sul dataset
reale. `data_cleaning.py` resta nel progetto come oracolo di questo test: non è
più sul percorso di produzione.

Uso:
    data_agent/venv/bin/python data_agent/tests/test_parita_pulizia.py
    (oppure `pytest data_agent/tests/` se pytest è installato)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RADICE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RADICE / "data_agent"))

from app import config, store  # noqa: E402
from app.data_cleaning import clean_dataframe  # noqa: E402

TOLLERANZA = 1e-9


def _riferimento_pandas() -> pd.DataFrame:
    grezzo = pd.read_csv(config.CSV_PATH, dtype=str, keep_default_na=False)
    pulito, _ = clean_dataframe(grezzo)
    return pulito


def _allinea(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("id_dipendente").reset_index(drop=True)


def confronta() -> list[str]:
    """Restituisce l'elenco delle differenze trovate (vuoto se le due coincidono)."""
    store.prepara_store(forza=True)
    sql = _allinea(store.carica_dataframe())
    atteso = _allinea(_riferimento_pandas())

    differenze: list[str] = []

    if len(sql) != len(atteso):
        differenze.append(f"numero di righe diverso: SQL {len(sql)}, pandas {len(atteso)}")
        return differenze

    mancanti = set(atteso.columns) - set(sql.columns)
    in_piu = set(sql.columns) - set(atteso.columns)
    if mancanti:
        differenze.append(f"colonne assenti in SQL: {sorted(mancanti)}")
    if in_piu:
        differenze.append(f"colonne in più in SQL: {sorted(in_piu)}")

    for colonna in atteso.columns:
        if colonna not in sql.columns:
            continue
        a, b = atteso[colonna], sql[colonna]

        # i valori mancanti devono mancare negli stessi punti
        disallineati_na = (a.isna() != b.isna()).sum()
        if disallineati_na:
            differenze.append(f"{colonna}: {disallineati_na} valori mancanti in posizioni diverse")
            continue

        presenti = a.notna()
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            scarto = (a[presenti].astype(float) - b[presenti].astype(float)).abs()
            fuori = (scarto > TOLLERANZA).sum()
            if fuori:
                differenze.append(f"{colonna}: {fuori} valori numerici diversi (max {scarto.max()})")
        elif pd.api.types.is_datetime64_any_dtype(a):
            diversi = (pd.to_datetime(a[presenti]) != pd.to_datetime(b[presenti])).sum()
            if diversi:
                differenze.append(f"{colonna}: {diversi} date diverse")
        else:
            diversi = (a[presenti].astype(str) != b[presenti].astype(str)).sum()
            if diversi:
                esempio = atteso.loc[presenti & (a.astype(str) != b.astype(str)), colonna].head(3).tolist()
                differenze.append(f"{colonna}: {diversi} valori testuali diversi, es. {esempio}")

    return differenze


def test_parita_pulizia_sql_e_pandas():
    differenze = confronta()
    assert not differenze, "La pulizia SQL diverge dal riferimento pandas:\n- " + "\n- ".join(differenze)


if __name__ == "__main__":
    trovate = confronta()
    if trovate:
        print("DIFFERENZE TROVATE:")
        for d in trovate:
            print("  -", d)
        raise SystemExit(1)
    print("Parità verificata: la pulizia in SQL e quella pandas producono lo stesso dataset.")
