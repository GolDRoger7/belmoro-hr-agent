"""Configurazione del microservizio data_agent: tutto arriva dal .env di progetto."""

import os
from pathlib import Path

from dotenv import load_dotenv

# La root del progetto è due livelli sopra questo file (data_agent/app/config.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Il .env è unico e condiviso da backend, data_agent e script di ingestion.
load_dotenv(ROOT_DIR / ".env")


def _path_from_env(var: str, default: str) -> Path:
    """Risolve un percorso letto dal .env rispetto alla root di progetto."""
    raw = os.getenv(var, default)
    p = Path(raw)
    return p if p.is_absolute() else (ROOT_DIR / p).resolve()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

DATA_AGENT_PORT = int(os.getenv("DATA_AGENT_PORT", "8000"))

CSV_PATH = _path_from_env("CSV_PATH", "./data/hr_dipendenti_belmoro.csv")
CHARTS_DIR = _path_from_env("CHARTS_DIR", "./shared/charts")

# Il dataset normalizzato viene materializzato qui una volta sola (vedi store.py).
DUCKDB_PATH = _path_from_env("DUCKDB_PATH", "./shared/hr_dataset.duckdb")

# Oltre questa soglia il dataset non viene più caricato per intero in memoria:
# l'agente riceve un campione e interroga DuckDB con SQL per i conti complessivi.
MAX_RIGHE_IN_MEMORIA = int(os.getenv("MAX_RIGHE_IN_MEMORIA", "200000"))

# --- Budget di tempo -------------------------------------------------------
# Il chiamante (il backend Node) deve attendere PIÙ della somma di questi due.
# Il valore complessivo è dichiarato in /health, così il disallineamento si
# vede all'avvio invece che sotto carico.
BUDGET_ANALISI_S = int(os.getenv("BUDGET_ANALISI_S", "150"))
BUDGET_GRAFICO_S = int(os.getenv("BUDGET_GRAFICO_S", "45"))
BUDGET_TOTALE_S = BUDGET_ANALISI_S + BUDGET_GRAFICO_S

CHARTS_DIR.mkdir(parents=True, exist_ok=True)
