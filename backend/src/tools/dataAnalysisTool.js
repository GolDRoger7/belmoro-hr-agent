/**
 * TOOL 2 - "analizza_dati_dipendenti"
 * Delega l'analisi quantitativa al microservizio Python (FastAPI + pandas agent).
 *
 * Il backend Node non calcola nulla: passa la domanda, riceve la sintesi
 * narrativa, il codice eseguito e il nome del file del grafico prodotto.
 */
import { config } from "../config.js";

export async function analizzaDatiDipendenti({ question }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.dataAgent.timeoutMs);

  try {
    const risposta = await fetch(`${config.dataAgent.url}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });

    if (!risposta.ok) {
      const dettaglio = await risposta.text();
      throw new Error(`Data agent HTTP ${risposta.status}: ${dettaglio.slice(0, 300)}`);
    }

    const esito = await risposta.json();
    return {
      summary: esito.summary,
      // il grafico è servito dal backend Node come risorsa statica
      chart_url: esito.chart_file ? `/charts/${esito.chart_file}` : null,
      code_steps: esito.code_steps ?? [],
      cleaning_report: esito.cleaning_report,
      rows_analyzed: esito.rows_analyzed,
      elapsed_seconds: esito.elapsed_seconds,
    };
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(
        `Il data agent non ha risposto entro ${config.dataAgent.timeoutMs / 1000}s.`
      );
    }
    if (error.cause?.code === "ECONNREFUSED") {
      throw new Error(
        `Microservizio Python non raggiungibile su ${config.dataAgent.url}. ` +
          "Avvialo con: uvicorn app.main:app --port 8000 (dalla cartella data_agent)."
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

/** Diagnostica usata da /api/health. */
export async function dataAgentStatus() {
  try {
    const risposta = await fetch(`${config.dataAgent.url}/health`, {
      signal: AbortSignal.timeout(4000),
    });
    if (!risposta.ok) return { reachable: false, error: `HTTP ${risposta.status}` };
    return { reachable: true, ...(await risposta.json()) };
  } catch (error) {
    return { reachable: false, error: error.message };
  }
}

/** Descrizione del tool esposta all'LLM orchestratore (function calling). */
export const dataAnalysisToolSchema = {
  type: "function",
  function: {
    name: "analizza_dati_dipendenti",
    description:
      "Delega a un agente Python (pandas) l'analisi del dataset dei dipendenti di Caffè Belmoro " +
      "(1.240 righe: anagrafica, dipartimento, sede, livello, contratto, RAL, bonus, " +
      "performance rating 1-5, engagement score, ore di formazione, giorni di smart working, " +
      "ferie residue, assenze, data di assunzione e cessazione, motivo di uscita). " +
      "Usalo per QUALSIASI richiesta quantitativa: medie, mediane, conteggi, distribuzioni, " +
      "confronti fra dipartimenti o sedi, trend temporali, tassi di turnover, correlazioni, " +
      "gender pay gap misurato, individuazione di anomalie nei dati. " +
      "L'agente pulisce i dati, esegue il calcolo e produce un grafico.",
    parameters: {
      type: "object",
      properties: {
        question: {
          type: "string",
          description:
            "La richiesta di analisi in italiano, autonoma e completa (esplicita metriche, " +
            "dimensioni di raggruppamento e filtri; niente pronomi riferiti alla conversazione).",
        },
      },
      required: ["question"],
      additionalProperties: false,
    },
  },
};
