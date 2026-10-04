"""
Microservizio FastAPI che espone l'agente pandas al backend Node.js.

Endpoint
--------
GET  /health   -> stato del servizio e del dataset
GET  /schema   -> schema del dataset e report di pulizia
POST /analyze  -> {"question": "..."} -> analisi + grafico + sintesi
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import esegui_analisi, get_dataframe
from .data_cleaning import riassunto_testuale

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | data_agent | %(levelname)s | %(message)s",
)
logger = logging.getLogger("data_agent")

app = FastAPI(
    title="Belmoro People Analytics - Data Agent",
    description="Agente pandas per l'analisi del dataset HR",
    version="1.0.0",
)

# I grafici sono scritti nella cartella condivisa; il backend Node li serve al
# front end, ma li esponiamo anche qui per debug diretto del microservizio.
app.mount("/charts", StaticFiles(directory=str(config.CHARTS_DIR)), name="charts")


class RichiestaAnalisi(BaseModel):
    question: str = Field(..., min_length=3, description="Domanda in linguaggio naturale")


@app.get("/health")
def health():
    try:
        df, _ = get_dataframe()
        return {
            "status": "ok",
            "dataset": str(config.CSV_PATH),
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
            "model": config.OPENAI_CHAT_MODEL,
            "openai_key_configured": bool(config.OPENAI_API_KEY),
        }
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=f"Dataset non disponibile: {exc}")


@app.get("/schema")
def schema():
    df, report = get_dataframe()
    return {
        "columns": [
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
            }
            for col in df.columns
        ],
        "rows": int(len(df)),
        "cleaning_report": report,
        "cleaning_summary": riassunto_testuale(report),
    }


@app.post("/analyze")
def analyze(richiesta: RichiestaAnalisi):
    inizio = time.perf_counter()
    logger.info("Nuova analisi richiesta: %s", richiesta.question)
    try:
        risultato = esegui_analisi(richiesta.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Analisi fallita")
        raise HTTPException(status_code=500, detail=f"Analisi fallita: {exc}")

    risultato["elapsed_seconds"] = round(time.perf_counter() - inizio, 2)
    logger.info(
        "Analisi completata in %ss (grafico: %s)",
        risultato["elapsed_seconds"], risultato["chart_file"],
    )
    return risultato


if __name__ == "__main__":  # avvio diretto: python -m app.main
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=config.DATA_AGENT_PORT)
