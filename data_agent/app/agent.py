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
from langchain_experimental.tools.python.tool import PythonAstREPLTool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from . import config  # noqa: E402
from .data_cleaning import riassunto_testuale  # noqa: E402
from .sandbox import CodiceNonConsentito, spazio_globale_sicuro, valida_codice  # noqa: E402
from . import store  # noqa: E402
from langchain_core.tools import Tool  # noqa: E402

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


# Errori il cui messaggio, da solo, non dice all'agente come uscirne: senza un
# suggerimento il modello ritenta lo stesso blocco finché il budget non scade.
SUGGERIMENTI_ERRORE: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"does not support operation|agg function failed|could not convert string to float", re.I),
        "SUGGERIMENTO: stai applicando un'aggregazione a TUTTE le colonne, comprese quelle "
        "testuali, che pandas non sa mediare. Seleziona prima la colonna numerica — "
        "df.groupby('colonna_di_gruppo')['colonna_numerica'].mean() — oppure passa "
        "numeric_only=True all'aggregazione. Non rieseguire lo stesso blocco senza cambiarlo.",
    ),
    (
        re.compile(r"Length of values \(\d+\) does not match length of index|"
                   r"array length \d+ does not match index length|"
                   r"All arrays must be of the same length", re.I),
        "SUGGERIMENTO: stai mettendo insieme serie di lunghezze diverse — tipicamente un "
        "valore complessivo accanto a uno per ciascun gruppo. Nel grafico usa UNA sola serie "
        "coerente (il valore per ogni gruppo); se vuoi mostrare anche il dato complessivo, "
        "disegnalo come linea di riferimento con plt.axvline() o plt.axhline(), non come "
        "elemento della serie. Non rieseguire lo stesso blocco senza cambiarlo.",
    ),
    (
        re.compile(r"SettingWithCopyWarning|A value is trying to be set on a copy", re.I),
        "SUGGERIMENTO: stai scrivendo su una vista del dataframe. Usa .copy() dopo il filtro.",
    ),
]


class PythonReplConEco(PythonAstREPLTool):
    """
    REPL Python contenuto, che non restituisce mai un'osservazione vuota.

    Due comportamenti si aggiungono a quello di base.

    CONTENIMENTO. Prima di eseguire, il codice passa dall'analisi statica di
    `sandbox.valida_codice`: import fuori whitelist, `open`/`eval`/`exec` e
    accesso agli attributi dunder vengono rifiutati con un messaggio che l'agente
    legge come output del proprio codice e che gli spiega come riformulare.
    Nello spazio di esecuzione, inoltre, vivono solo i builtins ammessi.

    Un blocco che termina con un'assegnazione (`media = df.groupby(...).mean()`)
    non produce output: l'agente non vede alcun numero e, dovendo poi scrivere la
    risposta finale, rischia di inventarlo. Qui l'osservazione vuota viene
    sostituita da un'istruzione esplicita su come ottenere il valore, così il
    modello è costretto a guardare i dati veri prima di parlarne.
    """

    def _run(self, *args, **kwargs):
        codice = args[0] if args else kwargs.get("query", "")
        try:
            valida_codice(str(codice))
        except CodiceNonConsentito as blocco:
            logger.warning("Codice rifiutato dal sandbox: %s", blocco)
            return f"CODICE RIFIUTATO: {blocco}"

        risultato = super()._run(*args, **kwargs)

        # Un errore che non suggerisce la via d'uscita manda l'agente in loop:
        # qui gli si dice cosa cambiare, nello stesso punto in cui legge l'errore.
        testo = str(risultato)
        for schema, suggerimento in SUGGERIMENTI_ERRORE:
            if schema.search(testo):
                logger.info("Errore ricorrente intercettato, aggiungo un suggerimento")
                return f"{testo}\n\n{suggerimento}"

        if risultato is None or str(risultato).strip() == "":
            return (
                "(nessun output: l'ultima riga del blocco è un'assegnazione o un comando "
                "che non restituisce valore. Se ti serve il risultato per rispondere, "
                "riesegui il blocco terminandolo con l'espressione da osservare — per "
                "esempio il nome della variabile appena assegnata — oppure con un print(). "
                "Non scrivere MAI cifre che non hai letto in un'osservazione.)"
            )
        return risultato


class PyplotConGuardia:
    """
    Proxy su matplotlib.pyplot che fa da GUARDRAIL DETERMINISTICO sul salvataggio.

    Il prompt chiede all'agente di non produrre grafici con una sola barra, ma un
    modello piccolo non rispetta l'istruzione in modo affidabile. Qui il vincolo
    non è più una richiesta: `savefig` rifiuta di salvare una figura con una sola
    categoria e solleva un errore che l'agente legge come output del suo codice,
    con l'indicazione di come correggere. L'agente rifà il grafico da solo nel
    giro successivo del ciclo ReAct.
    """

    def __init__(self, pyplot):
        self._plt = pyplot

    def __getattr__(self, nome):
        return getattr(self._plt, nome)

    @staticmethod
    def _categorie_rappresentate(ax) -> int | None:
        """Numero di barre/fette; None se il grafico non è categoriale."""
        patch = [p for p in ax.patches if getattr(p, "get_width", None)]
        if not patch:
            return None  # linee, scatter, heatmap: nessun vincolo
        return len(patch)

    def savefig(self, *args, **kwargs):
        try:
            categorie = self._categorie_rappresentate(self._plt.gca())
        except Exception:
            categorie = None

        if categorie == 1:
            raise ValueError(
                "GRAFICO RIFIUTATO: contiene una sola barra e non comunica nulla. "
                "Ricalcola la metrica per TUTTI i gruppi della stessa dimensione "
                "(tutti i dipartimenti, tutte le sedi, tutti i livelli...) e ridisegna "
                "il confronto completo, colorando di '#c8801f' solo la barra del gruppo "
                "chiesto dall'utente e di '#1d4e89' le altre. Poi salva di nuovo."
            )
        return self._plt.savefig(*args, **kwargs)


# Colonne valorizzate solo per chi ha lasciato l'azienda: un valore vuoto qui è
# un'informazione ("è ancora in forza"), non un dato mancante da scartare.
COLONNE_VUOTE_SUGLI_ATTIVI = {
    "data_cessazione", "anno_cessazione", "mese_cessazione",
    "motivo_cessazione", "durata_rapporto_anni",
}

# --- Cache del dataframe pulito (il cleaning gira una volta sola) -----------
_CACHE: dict[str, Any] = {"df": None, "report": None, "mtime": None, "modalita": None}


def get_dataframe(force_reload: bool = False) -> tuple[pd.DataFrame, dict]:
    """
    Restituisce il dataframe su cui lavora l'agente, insieme al report di pulizia.

    La pulizia non viene più rifatta a ogni avvio: il dataset normalizzato vive in
    una tabella DuckDB, ricostruita solo quando il CSV cambia. Sopra la soglia di
    `MAX_RIGHE_IN_MEMORIA` qui arriva un CAMPIONE, e i conti sull'intera
    popolazione passano dallo strumento SQL (vedi `_costruisci_agente`).
    """
    # Nanosecondi, non secondi: due scritture ravvicinate devono risultare diverse.
    mtime = config.CSV_PATH.stat().st_mtime_ns
    if force_reload or _CACHE["df"] is None or _CACHE["mtime"] != mtime:
        esito = store.prepara_store(forza=force_reload)
        modo = store.modalita()
        limite = None if modo["modalita"] == "dataframe_completo" else 50_000
        if limite:
            logger.warning(
                "Dataset di %s righe oltre la soglia di %s: l'agente lavorerà su un campione "
                "di %s righe e su SQL per i totali.", modo["righe"], modo["soglia_memoria"], limite
            )
        _CACHE.update({
            "df": store.carica_dataframe(limite=limite),
            "report": esito["report"],
            "mtime": mtime,
            "modalita": modo,
        })
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
   Non scrivere MAI posizionamenti nella forma "sesto su dieci": il totale lo sbaglieresti a
   memoria. Scrivi "il sesto valore più alto" oppure, se ti serve davvero il totale,
   calcolalo prima con `len(serie)` e osservane l'output.
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
- MAI un grafico con una sola barra o una sola fetta: non comunica nulla. Se la domanda
  riguarda un singolo gruppo (un dipartimento, una sede, un livello), calcola comunque il
  valore per TUTTI i gruppi e disegna il confronto completo evidenziando quello richiesto,
  con questo schema esatto:

      serie = df.groupby('<colonna>')['<metrica>'].mean().sort_values()
      colori = ["#c8801f" if g == "<gruppo richiesto>" else "#1d4e89" for g in serie.index]
      sns.barplot(x=serie.values, y=serie.index, hue=serie.index, palette=colori, legend=False)

  Nel testo rispondi puntualmente sul gruppo chiesto, citando il suo posizionamento
  rispetto agli altri (es. "il terzo valore più alto").
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


def _strumento_sql() -> Tool:
    """
    Espone DuckDB all'agente quando il dataset non sta in memoria.

    Il DataFrame che l'agente ha davanti è in quel caso un campione: per i totali
    sull'intera popolazione deve passare da qui, dove l'aggregazione viene spinta
    nel motore e non richiede di materializzare la tabella.
    """

    def interroga(query: str) -> str:
        try:
            risultato = store.esegui_sql(query)
        except Exception as errore:  # il messaggio torna all'agente, che corregge
            return f"QUERY RIFIUTATA: {errore}"
        return risultato.head(100).to_markdown(index=False)

    return Tool(
        name="interroga_sql",
        description=(
            "Esegue una query SQL di sola lettura sulla tabella `dipendenti` di DuckDB, "
            "che contiene TUTTE le righe del dataset già normalizzate (il dataframe `df` "
            "che hai davanti è solo un campione). Usalo per conteggi, medie e "
            "raggruppamenti sull'intera popolazione. Accetta solo SELECT o WITH."
        ),
        func=interroga,
    )


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

    modo = (_CACHE.get("modalita") or {}).get("modalita", "dataframe_completo")
    strumenti_extra = [] if modo == "dataframe_completo" else [_strumento_sql()]
    if strumenti_extra:
        prefisso += (
            "\n\n## ATTENZIONE: `df` è un CAMPIONE\n"
            "Il dataset completo non sta in memoria. Usa `df` solo per esplorare la forma dei "
            "dati; ogni cifra che citi nella risposta deve venire da `interroga_sql`, che "
            "interroga la tabella `dipendenti` con tutte le righe."
        )

    agente = create_pandas_dataframe_agent(
        llm,
        df,
        agent_type="tool-calling",
        prefix=prefisso,
        verbose=True,
        # L'esecuzione di codice è il cuore dello strumento. Il contenimento non
        # sta in questo flag ma nel REPL sostituito più sotto: analisi statica
        # del codice e builtins ridotti (vedi sandbox.py).
        allow_dangerous_code=True,
        return_intermediate_steps=True,
        extra_tools=strumenti_extra,
        max_iterations=12,
        max_execution_time=config.BUDGET_ANALISI_S,
        include_df_in_prompt=True,
        number_of_head_rows=5,
        handle_parsing_errors=True,
    )

    # Iniettiamo nel REPL le librerie di plotting e il percorso del grafico, così
    # l'LLM non deve indovinare né import né path di salvataggio, e sostituiamo il
    # tool con la versione che non restituisce mai osservazioni vuote.
    for indice, tool in enumerate(agente.tools):
        if isinstance(getattr(tool, "locals", None), dict):
            spazio = dict(tool.locals)
            spazio.update({
                "plt": PyplotConGuardia(plt), "sns": sns, "np": np, "pd": pd,
                "CHART_PATH": str(chart_path),
            })
            # UN SOLO spazio dei nomi per globals e locals. Con due dizionari
            # distinti, `exec` mette le assegnazioni nei locals mentre una list
            # comprehension — che apre un proprio scope — cerca i nomi nei
            # globals: codice legittimo come
            #     serie = df.groupby(...).mean()
            #     colori = [... if g == serie.idxmax() else ... for g in serie.index]
            # falliva con NameError, e l'agente restava a ritentare fino a
            # esaurire il budget. Pydantic copia i dizionari passati al
            # costruttore, quindi l'allineamento va rifatto dopo.
            spazio_unico = spazio_globale_sicuro(spazio)
            strumento = PythonReplConEco(
                name=tool.name,
                description=tool.description,
                locals=spazio_unico,
                globals=spazio_unico,
            )
            strumento.locals = strumento.globals
            agente.tools[indice] = strumento
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
            # Il secondo giro ha un budget proprio e più stretto: la somma dei due
            # resta sotto BUDGET_TOTALE_S, che il backend Node conosce da /health.
            agente.max_execution_time = config.BUDGET_GRAFICO_S
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
