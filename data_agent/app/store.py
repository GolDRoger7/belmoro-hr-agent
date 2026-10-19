"""
Persistenza del dataset su DuckDB.

Perché non leggere il CSV a ogni richiesta
-----------------------------------------
Il percorso originale era: leggi il CSV, pulisci, tieni tutto in un DataFrame.
Funziona bene con le 1.240 righe della demo, ma non regge quando il file passa a
centinaia di migliaia di righe: la pulizia viene rifatta a ogni avvio e l'intero
dataset deve stare in memoria anche per calcolare una media.

Qui il CSV viene normalizzato UNA VOLTA e materializzato in una tabella DuckDB,
rigenerata solo quando il file sorgente cambia (si confronta una firma di
dimensione e data di modifica). Da quel momento:

- le letture partono da un formato colonnare già tipizzato, senza riparsare testo;
- le aggregazioni possono essere spinte nel motore con `esegui_sql`, che legge
  dal disco e non richiede di materializzare l'intera tabella in memoria;
- sopra la soglia `MAX_RIGHE_IN_MEMORIA` l'agente riceve un campione
  rappresentativo come DataFrame e lo strumento SQL per i conti sull'intero
  dataset, invece di tentare un caricamento che non starebbe in RAM.

Sotto la soglia il comportamento è identico a prima: l'agente lavora sul
DataFrame completo, e le analisi restano quelle verificate.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

from . import config
from .cleaning_duckdb import (
    colonne_sorgente,
    definisci_macro,
    query_fuori_range,
    query_pulizia,
)

logger = logging.getLogger("data_agent")

TABELLA = "dipendenti"
TABELLA_META = "_meta"


def _firma_sorgente() -> str:
    """
    Impronta del CSV usata per decidere se ricostruire la tabella.

    Si usa `st_mtime_ns` e non `st_mtime`: il secondo è un float in secondi, e
    due scritture ravvicinate — una rigenerazione del dataset, un `cp` seguito
    da una correzione — possono risultare con lo stesso istante. In quel caso lo
    store si considererebbe aggiornato e continuerebbe a servire i dati vecchi,
    senza che nulla segnali l'errore. I nanosecondi tolgono l'ambiguità.
    """
    info = config.CSV_PATH.stat()
    return f"{info.st_mtime_ns}:{info.st_size}"


def _connessione(sola_lettura: bool = False) -> duckdb.DuckDBPyConnection:
    config.DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.DUCKDB_PATH), read_only=sola_lettura)


def _firma_registrata(con: duckdb.DuckDBPyConnection) -> str | None:
    try:
        riga = con.execute(
            f"SELECT valore FROM {TABELLA_META} WHERE chiave = 'firma_sorgente'"
        ).fetchone()
        return riga[0] if riga else None
    except duckdb.Error:
        return None


def prepara_store(forza: bool = False) -> dict:
    """
    Allinea la tabella DuckDB al CSV. Ricostruisce solo se la firma è cambiata.

    @return il report di pulizia e lo stato dello store
    """
    firma = _firma_sorgente()

    with _connessione() as con:
        if not forza and _firma_registrata(con) == firma:
            righe = con.execute(f"SELECT count(*) FROM {TABELLA}").fetchone()[0]
            report = json.loads(
                con.execute(
                    f"SELECT valore FROM {TABELLA_META} WHERE chiave = 'report_pulizia'"
                ).fetchone()[0]
            )
            return {"ricostruito": False, "righe": righe, "report": report}

        logger.info("Costruisco la tabella DuckDB da %s (pulizia in SQL)", config.CSV_PATH)
        report = _costruisci_tabella(con)

        con.execute(f"CREATE TABLE IF NOT EXISTS {TABELLA_META} (chiave VARCHAR PRIMARY KEY, valore VARCHAR)")
        for chiave, valore in (
            ("firma_sorgente", firma),
            ("report_pulizia", json.dumps(report, ensure_ascii=False)),
            ("sorgente", str(config.CSV_PATH)),
        ):
            con.execute(
                f"INSERT INTO {TABELLA_META} VALUES (?, ?) "
                "ON CONFLICT (chiave) DO UPDATE SET valore = excluded.valore",
                [chiave, valore],
            )

        righe = con.execute(f"SELECT count(*) FROM {TABELLA}").fetchone()[0]
        logger.info("Tabella DuckDB pronta: %s righe", righe)
        return {"ricostruito": True, "righe": righe, "report": report}


def _costruisci_tabella(con: duckdb.DuckDBPyConnection) -> dict:
    """
    Legge il CSV, lo normalizza e scrive la tabella: tutto dentro il motore.

    Il file non viene mai materializzato in memoria: `read_csv` lo attraversa in
    streaming e il risultato va direttamente in `CREATE TABLE AS SELECT`. Le
    uniche cose che tornano in Python sono i conteggi del report, che sono
    aggregati di poche righe.
    """
    percorso = str(config.CSV_PATH)
    definisci_macro(con)
    colonne = colonne_sorgente(con, percorso)

    righe_iniziali = con.execute(
        f"SELECT count(*) FROM read_csv('{percorso}', all_varchar = true, header = true)"
    ).fetchone()[0]

    con.execute(f"CREATE OR REPLACE TABLE {TABELLA} AS {query_pulizia(colonne, percorso)}")

    righe_finali = con.execute(f"SELECT count(*) FROM {TABELLA}").fetchone()[0]

    # Valori leggibili ma fuori dal dominio, azzerati dalla normalizzazione
    colonne_range = [c for c in colonne]
    intestazioni = [d[0] for d in con.execute(query_fuori_range(colonne_range, percorso)).description]
    valori = con.execute(query_fuori_range(colonne_range, percorso)).fetchone()
    fuori_range = {c: int(v) for c, v in zip(intestazioni, valori) if v}

    # Valori mancanti residui, letti dalla tabella già scritta
    colonne_finali = [d[0] for d in con.execute(f"SELECT * FROM {TABELLA} LIMIT 0").description]
    espressioni = ", ".join(f'count(*) - count("{c}") AS "{c}"' for c in colonne_finali)
    conteggi = con.execute(f"SELECT {espressioni} FROM {TABELLA}").fetchone()
    mancanti = {c: int(v) for c, v in zip(colonne_finali, conteggi) if v}

    operazioni = [
        f"Lettura in streaming del CSV e normalizzazione eseguite dentro DuckDB: "
        f"il file non viene mai caricato per intero in memoria.",
        "Rimossi spazi superflui e normalizzati i marcatori di valore nullo ('', 'NULL', 'n/d').",
        f"Rimosse {righe_iniziali - righe_finali} righe duplicate (identiche o con lo stesso id_dipendente).",
        "Uniformate le categorie di dipartimento, genere, stato, tipo di contratto e livello.",
        "Normalizzate le date scritte in 4 formati diversi (ISO, gg/mm/aaaa, gg-mm-aaaa, gg.mm.aaaa).",
        "Convertiti gli importi con valuta e separatori decimali misti in valori numerici.",
        "Aggiunte colonne derivate: anno_assunzione, anno_cessazione, mese_cessazione, is_cessato, durata_rapporto_anni.",
    ]
    if fuori_range:
        dettaglio = ", ".join(f"{k}: {v}" for k, v in fuori_range.items())
        operazioni.append(
            f"Portati a valore mancante i dati fuori dai range di dominio -> {dettaglio}."
        )

    return {
        "righe_iniziali": int(righe_iniziali),
        "colonne_iniziali": len(colonne),
        "righe_finali": int(righe_finali),
        "colonne_finali": len(colonne_finali),
        "duplicati_rimossi": int(righe_iniziali - righe_finali),
        "valori_fuori_range_azzerati": fuori_range,
        "valori_mancanti_residui": mancanti,
        "operazioni": operazioni,
        "motore": "duckdb",
    }


def conteggio_righe() -> int:
    with _connessione(sola_lettura=True) as con:
        return con.execute(f"SELECT count(*) FROM {TABELLA}").fetchone()[0]


def carica_dataframe(limite: int | None = None) -> pd.DataFrame:
    """Materializza la tabella (o un campione) in un DataFrame pandas."""
    query = f"SELECT * FROM {TABELLA}"
    if limite:
        query += f" USING SAMPLE {limite} ROWS"
    with _connessione(sola_lettura=True) as con:
        return con.execute(query).df()


def report_pulizia() -> dict:
    with _connessione(sola_lettura=True) as con:
        riga = con.execute(
            f"SELECT valore FROM {TABELLA_META} WHERE chiave = 'report_pulizia'"
        ).fetchone()
    return json.loads(riga[0]) if riga else {}


def esegui_sql(query: str) -> pd.DataFrame:
    """
    Esegue una SELECT sulla tabella, in sola lettura.

    La connessione è aperta in read_only, quindi il motore stesso rifiuta
    qualunque scrittura: il controllo sul testo della query è solo un filtro
    anticipato per restituire all'agente un messaggio comprensibile.
    """
    normalizzata = query.strip().rstrip(";").lstrip("(").lstrip()
    if not normalizzata.lower().startswith(("select", "with")):
        raise ValueError("sono ammesse solo query di lettura (SELECT o WITH)")
    with _connessione(sola_lettura=True) as con:
        return con.execute(query).df()


def modalita() -> dict:
    """Descrive come verrà servito il dataset, in funzione della sua dimensione."""
    righe = conteggio_righe()
    in_memoria = righe <= config.MAX_RIGHE_IN_MEMORIA
    return {
        "righe": righe,
        "soglia_memoria": config.MAX_RIGHE_IN_MEMORIA,
        "modalita": "dataframe_completo" if in_memoria else "campione_piu_sql",
        "file": str(config.DUCKDB_PATH),
    }
