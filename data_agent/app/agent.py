"""
Agente pandas: riceve una domanda in linguaggio naturale, scrive ed esegue
codice Python sul dataset HR già normalizzato, produce un grafico e restituisce
una sintesi narrativa in italiano.

L'agente è costruito con LangChain (create_pandas_dataframe_agent, paradigma
ReAct con tool calling): l'LLM ragiona, scrive codice, ne osserva l'output e
itera fino alla risposta finale.
"""

from __future__ import annotations

import logging
import re
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # backend headless: nessuna finestra, salvataggio su file

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from . import config  # noqa: E402
from .data_cleaning import clean_dataframe, riassunto_testuale  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = logging.getLogger("data_agent")

sns.set_theme(style="whitegrid", palette="deep")
plt.rcParams.update({
    "figure.figsize": (10, 6),
    "figure.dpi": 110,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.labelsize": 11,
    "font.size": 10,
})

# --- Cache del dataframe pulito (il cleaning gira una volta sola) -----------
_CACHE: dict[str, Any] = {"df": None, "report": None, "mtime": None}


def get_dataframe(force_reload: bool = False) -> tuple[pd.DataFrame, dict]:
    """Carica il CSV, applica il cleaning deterministico e mette in cache."""
    mtime = config.CSV_PATH.stat().st_mtime
    if force_reload or _CACHE["df"] is None or _CACHE["mtime"] != mtime:
        logger.info("Carico e pulisco il dataset da %s", config.CSV_PATH)
        raw = pd.read_csv(config.CSV_PATH, dtype=str, keep_default_na=False)
        df, report = clean_dataframe(raw)
        _CACHE.update({"df": df, "report": report, "mtime": mtime})
    return _CACHE["df"], _CACHE["report"]


def _descrizione_schema(df: pd.DataFrame) -> str:
    righe = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        n_na = int(df[col].isna().sum())
        if pd.api.types.is_numeric_dtype(df[col]) and col not in ("is_cessato",):
            extra = f"min={df[col].min():.1f}, max={df[col].max():.1f}, media={df[col].mean():.1f}"
        elif pd.api.types.is_string_dtype(df[col]):
            valori = [v for v in df[col].dropna().unique()[:8]]
            extra = "valori: " + ", ".join(map(str, valori)) + ("..." if df[col].nunique() > 8 else "")
        else:
            extra = ""
        righe.append(f"- {col} ({dtype}, {n_na} mancanti) {extra}")
    return "\n".join(righe)


PREFISSO_TEMPLATE = """Sei il Data Analyst della funzione People & Culture del Caffè Belmoro.
Lavori sul dataframe pandas `df`, che contiene l'anagrafica e le metriche dei dipendenti
del perimetro Italia (dati fittizi a scopo dimostrativo).

## Dataset già normalizzato
Sul dataframe è stato applicato un layer di pulizia deterministico:
{report_pulizia}

## Schema delle colonne
{schema}

## Regole di analisi che devi rispettare
1. Rispondi SEMPRE in italiano, con un tono da report per la direzione HR.
2. Prima di calcolare, gestisci i valori mancanti in modo esplicito e coerente con la
   domanda (di norma `.dropna()` sulle colonne coinvolte); dichiara nella risposta
   finale quante righe hai escluso e perché.
3. Usa `is_cessato` (1 = cessato) per il turnover e `stato == 'Attivo'` per l'organico
   in forza. Le percentuali di turnover si calcolano come media di `is_cessato`.
4. Non inventare MAI numeri: ogni cifra citata deve derivare dal codice eseguito.
5. Se un gruppo ha meno di 5 osservazioni, segnalane la scarsa significatività.

## Regole per il grafico (obbligatorie)
- Nel namespace hai già disponibili: `plt`, `sns`, `pd`, `np` e la variabile stringa
  `CHART_PATH` con il percorso in cui salvare l'immagine.
- Genera UN SOLO grafico, quello più utile a rispondere alla domanda, e salvalo così:
      plt.tight_layout()
      plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
      plt.close()
- Titolo, etichette degli assi e unità di misura sempre in italiano.
- Non usare `plt.show()`.
- Salta il grafico solo se la domanda richiede un singolo numero puntuale senza
  alcuna dimensione di confronto.

## Formato della risposta finale
Testo in markdown, senza codice, strutturato così:
**Risposta sintetica** (1-2 frasi con il numero chiave)
**Dettaglio** (elenco puntato con i valori rilevanti)
**Insight per People & Culture** (1-3 frasi di lettura manageriale e implicazione operativa)
**Nota metodologica** (righe escluse, assunzioni fatte)
"""


def _costruisci_agente(df: pd.DataFrame, report: dict, chart_path: Path):
    if not config.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY non configurata: valorizzala nel file .env alla root del progetto."
        )

    llm = ChatOpenAI(
        model=config.OPENAI_CHAT_MODEL,
        temperature=0,
        api_key=config.OPENAI_API_KEY,
    )

    prefisso = PREFISSO_TEMPLATE.format(
        report_pulizia=riassunto_testuale(report),
        schema=_descrizione_schema(df),
    )

    agente = create_pandas_dataframe_agent(
        llm,
        df,
        agent_type="tool-calling",
        prefix=prefisso,
        verbose=True,
        allow_dangerous_code=True,          # l'esecuzione di codice è il cuore del tool
        return_intermediate_steps=True,
        max_iterations=12,
        max_execution_time=180,
        include_df_in_prompt=True,
        number_of_head_rows=5,
        handle_parsing_errors=True,
    )

    # Iniettiamo nel REPL le librerie di plotting e il percorso del grafico,
    # così l'LLM non deve indovinare né import né path di salvataggio.
    for tool in agente.tools:
        if isinstance(getattr(tool, "locals", None), dict):
            tool.locals.update({
                "plt": plt, "sns": sns, "np": np, "pd": pd,
                "CHART_PATH": str(chart_path),
            })
    return agente


def _estrai_codice(intermediate_steps) -> list[str]:
    """Recupera il codice Python realmente eseguito dall'agente (audit trail)."""
    codice = []
    for azione, _osservazione in intermediate_steps or []:
        payload = getattr(azione, "tool_input", None)
        if isinstance(payload, dict):
            frammento = payload.get("query") or payload.get("__arg1")
        else:
            frammento = payload
        if frammento:
            codice.append(str(frammento))
    return codice


def esegui_analisi(domanda: str) -> dict:
    """Punto d'ingresso usato dall'endpoint FastAPI."""
    df, report = get_dataframe()

    slug = re.sub(r"[^a-z0-9]+", "-", domanda.lower())[:40].strip("-") or "analisi"
    nome_file = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}-{uuid.uuid4().hex[:6]}.png"
    chart_path = config.CHARTS_DIR / nome_file

    agente = _costruisci_agente(df, report, chart_path)

    plt.close("all")
    esito = agente.invoke({"input": domanda})

    sintesi = esito.get("output") or "L'agente non ha prodotto una risposta finale."
    if isinstance(sintesi, list):  # alcuni modelli restituiscono blocchi strutturati
        sintesi = "\n".join(b.get("text", "") for b in sintesi if isinstance(b, dict))

    grafico = nome_file if chart_path.exists() else None
    if grafico:
        logger.info("Grafico salvato: %s", chart_path)

    return {
        "summary": sintesi,
        "chart_file": grafico,
        "code_steps": _estrai_codice(esito.get("intermediate_steps")),
        "cleaning_report": riassunto_testuale(report),
        "rows_analyzed": int(len(df)),
    }
