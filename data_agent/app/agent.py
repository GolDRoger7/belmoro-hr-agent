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

# Colonne valorizzate solo per chi ha lasciato l'azienda: un valore vuoto qui è
# un'informazione ("è ancora in forza"), non un dato mancante da scartare.
COLONNE_VUOTE_SUGLI_ATTIVI = {
    "data_cessazione", "anno_cessazione", "mese_cessazione",
    "motivo_cessazione", "durata_rapporto_anni",
}

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
        if col in COLONNE_VUOTE_SUGLI_ATTIVI:
            nota = f"({dtype}, {n_na} vuoti = dipendenti ancora in forza, NON dati mancanti)"
        else:
            nota = f"({dtype}, {n_na} mancanti)"
        righe.append(f"- {col} {nota} {extra}")
    return "\n".join(righe)


PREFISSO_TEMPLATE = """Sei il Data Analyst della funzione People & Culture del Caffè Belmoro.
Lavori sul dataframe pandas `df`, che contiene l'anagrafica e le metriche dei dipendenti
del perimetro Italia (dati fittizi a scopo dimostrativo).

## Dataset già normalizzato
Sul dataframe è stato applicato un layer di pulizia deterministico:
{report_pulizia}

## Schema delle colonne
{schema}

## ATTENZIONE: valori vuoti che NON sono dati mancanti
Le colonne `data_cessazione`, `anno_cessazione`, `mese_cessazione`, `motivo_cessazione` e
`durata_rapporto_anni` sono vuote per TUTTI i dipendenti ancora in forza: è il
comportamento atteso, non un difetto dei dati. NON applicare mai `dropna()` su queste
colonne quando analizzi l'intero organico: escluderesti in un colpo solo tutti gli attivi
e falseresti qualunque percentuale. Usale solo quando l'analisi riguarda esplicitamente i
soli cessati (es. motivi di uscita, stagionalità delle uscite).

## Regole di analisi che devi rispettare
1. Rispondi SEMPRE in italiano, con un tono da report per la direzione HR.
2. Gestisci i valori mancanti in modo mirato: `.dropna(subset=[...])` SOLO sulle colonne
   effettivamente usate nel calcolo, mai `.dropna()` sull'intero dataframe. Dichiara nella
   risposta finale quante righe hai escluso e perché.
3. Turnover: usa `is_cessato` (1 = cessato, 0 = attivo, nessun valore mancante) su TUTTE le
   righe. Il tasso per dipartimento è `df.groupby('dipartimento')['is_cessato'].mean() * 100`.
   L'organico in forza è `df[df['stato'] == 'Attivo']`.
4. FILTRI ESPLICITI: rileggi la domanda e applica TUTTI i vincoli che nomina prima di
   calcolare — stato ("attivi"/"in forza" -> `df['stato'] == 'Attivo'`; "cessati"/"usciti"
   -> `df['stato'] == 'Cessato'`), dipartimento, sede, livello di inquadramento, tipo di
   contratto, genere, periodo temporale. Dichiara nella nota metodologica quali filtri hai
   applicato e su quante righe hai lavorato. Se la domanda non nomina alcun filtro, usa
   l'intero dataset e scrivilo esplicitamente.
5. Prima di dare la risposta finale, fai un controllo di plausibilità in due punti:
   (a) ho applicato tutti i filtri citati nella domanda?
   (b) quante righe ho davvero usato? Se ne ho escluse più del 20%, o se un tasso risulta
   0% su quasi tutti i gruppi, ho quasi certamente filtrato troppo: rivedo e rifaccio il
   calcolo.
6. Non inventare MAI numeri: ogni cifra citata deve derivare dal codice eseguito. Vale però
   anche il contrario: una risposta che spiega il metodo senza riportare NESSUNA cifra non è
   accettabile. Devi sempre trascrivere nella risposta finale i valori che hai calcolato,
   letti dall'output del codice.
7. Se un gruppo ha meno di 5 osservazioni, segnalane la scarsa significatività.
8. UNITÀ DI MISURA: esprimi ogni differenza fra gruppi sia in valore assoluto sia in
   percentuale, perché gli obiettivi aziendali sono quasi sempre fissati in percentuale.
9. DIVARIO RETRIBUTIVO: il "gender pay gap" ha due definizioni diverse e non
   intercambiabili. Quello GREZZO confronta le RAL medie di tutta la popolazione ed è
   influenzato dalla diversa distribuzione per livello e anzianità; quello CORRETTO
   confronta uomini e donne a parità di livello di inquadramento (e, dove possibile, di
   anzianità). Quando ti viene chiesto il gender pay gap calcola ENTRAMBI — il grezzo e
   quello per livello di inquadramento — e dichiara esplicitamente quale stai riportando:
   confrontare il gap grezzo con un obiettivo definito sul gap corretto è un errore
   metodologico. Usa SEMPRE la formula convenzionale (Eurostat/ILO), che mette al
   denominatore la retribuzione del gruppo di riferimento maschile:
       gap_% = (media_uomini - media_donne) / media_uomini * 100
   Usare la media femminile al denominatore gonfia il risultato e non è confrontabile con
   gli obiettivi aziendali o con i benchmark di mercato.

## Regole per il grafico (obbligatorie)
- Nel namespace hai già disponibili: `plt`, `sns`, `pd`, `np` e la variabile stringa
  `CHART_PATH` con il percorso in cui salvare l'immagine.
- Genera UN SOLO grafico, quello più utile a rispondere alla domanda, e salvalo così:
      plt.tight_layout()
      plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
      plt.close()
- Titolo, etichette degli assi e unità di misura sempre in italiano.
- Nei barplot seaborn usa un colore unico (`color="#1d4e89"`) oppure, se vuoi colorare per
  categoria, passa `hue=<colonna>` con `legend=False`: NON usare `palette=` da solo.
- Non usare `plt.show()`.
- Genera SEMPRE il grafico quando c'è una dimensione di confronto, un raggruppamento,
  una distribuzione o una serie temporale. Anche un confronto fra due soli gruppi
  (es. uomini e donne) va rappresentato. L'unico caso in cui puoi ometterlo è una
  domanda la cui risposta è un singolo numero senza alcun termine di paragone
  (es. "quanti dipendenti abbiamo in totale?").

## Formato della risposta finale
Testo in markdown, senza codice, strutturato così:
**Risposta sintetica** (1-2 frasi che contengono il numero chiave, esplicito)
**Dettaglio** (elenco puntato con i valori calcolati: per un raggruppamento riporta tutti i
gruppi, per una serie storica almeno gli ultimi 5-8 periodi più il minimo e il massimo)
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


# Domande la cui risposta è un singolo numero senza termini di paragone: qui il
# grafico non aggiunge nulla e non vale la pena richiederlo.
_SENZA_GRAFICO = re.compile(
    r"\b(quanti|quante|quanto)\b.*\b(in totale|complessivamente|in tutto)\b", re.IGNORECASE
)


def _merita_grafico(domanda: str) -> bool:
    return not _SENZA_GRAFICO.search(domanda)


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

    passi = list(esito.get("intermediate_steps") or [])

    # Fallback deterministico: con modelli piccoli capita che l'agente concluda
    # senza salvare l'immagine. Invece di restituire una risposta monca, gli
    # chiediamo una volta sola di produrre il grafico sui risultati già ottenuti.
    if not chart_path.exists() and _merita_grafico(domanda):
        logger.info("Nessun grafico prodotto: secondo passaggio dedicato alla visualizzazione.")
        try:
            recupero = agente.invoke({
                "input": (
                    f"Non hai salvato nessun grafico per la richiesta: «{domanda}». "
                    "Riprendi i risultati che hai appena calcolato e genera ORA il grafico "
                    "più utile a rappresentarli (confronto fra gruppi, distribuzione o serie "
                    "temporale, secondo il caso). Salvalo con "
                    "plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight') seguito da plt.close(). "
                    "Rispondi solo con una riga che descrive il grafico prodotto."
                )
            })
            passi += list(recupero.get("intermediate_steps") or [])
        except Exception:  # il grafico è un di più: non deve far fallire l'analisi
            logger.exception("Anche il secondo passaggio sul grafico è fallito")

    grafico = nome_file if chart_path.exists() else None
    if grafico:
        logger.info("Grafico salvato: %s", chart_path)

    return {
        "summary": sintesi,
        "chart_file": grafico,
        "code_steps": _estrai_codice(passi),
        "cleaning_report": riassunto_testuale(report),
        "rows_analyzed": int(len(df)),
    }
