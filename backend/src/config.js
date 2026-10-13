/**
 * Configurazione centralizzata del backend.
 * Tutti i valori arrivano dal file .env alla root del progetto: nessun segreto
 * è mai hardcodato nel codice sorgente.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import dotenv from "dotenv";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT_DIR = path.resolve(__dirname, "..", "..");

dotenv.config({ path: path.join(ROOT_DIR, ".env"), quiet: true });

/** Risolve un percorso del .env rispetto alla root di progetto. */
const resolveFromRoot = (value, fallback) => {
  const raw = value || fallback;
  return path.isAbsolute(raw) ? raw : path.resolve(ROOT_DIR, raw);
};

export const config = {
  openai: {
    apiKey: process.env.OPENAI_API_KEY || "",
    chatModel: process.env.OPENAI_CHAT_MODEL || "gpt-4o-mini",
    embeddingModel: process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small",
  },
  server: {
    port: Number(process.env.BACKEND_PORT || 3001),
    frontendOrigin: process.env.FRONTEND_ORIGIN || "http://localhost:5173",
  },
  chroma: {
    host: process.env.CHROMA_HOST || "localhost",
    port: Number(process.env.CHROMA_PORT || 8001),
    collection: process.env.CHROMA_COLLECTION || "belmoro_hr_policies",
  },
  dataAgent: {
    url: process.env.DATA_AGENT_URL || "http://localhost:8000",
    // Deve restare MAGGIORE del budget massimo del data agent (analisi +
    // eventuale secondo passaggio per il grafico), altrimenti Node chiude la
    // connessione mentre Python sta ancora lavorando e l'utente vede un
    // timeout su un'analisi che sarebbe arrivata. All'avvio il server
    // confronta questo valore con il budget dichiarato da /health.
    timeoutMs: Number(process.env.DATA_AGENT_TIMEOUT_MS || 260000),
  },
  charts: {
    ttlOre: Number(process.env.CHARTS_TTL_ORE || 24),
    intervalloPuliziaMinuti: Number(process.env.CHARTS_PULIZIA_MINUTI || 60),
  },
  cache: {
    attiva: process.env.CACHE_RISPOSTE !== "off",
    ttlRagMs: Number(process.env.CACHE_TTL_RAG_MINUTI || 60) * 60 * 1000,
    ttlDatiMs: Number(process.env.CACHE_TTL_DATI_MINUTI || 30) * 60 * 1000,
  },
  paths: {
    csv: resolveFromRoot(process.env.CSV_PATH, "./data/hr_dipendenti_belmoro.csv"),
    knowledgeBase: resolveFromRoot(process.env.KB_PATH, "./data/hr_policy_belmoro.txt"),
    charts: resolveFromRoot(process.env.CHARTS_DIR, "./shared/charts"),
  },
};

/** Fallisce subito e con un messaggio chiaro se manca la chiave API. */
export function assertConfig() {
  if (!config.openai.apiKey) {
    throw new Error(
      "OPENAI_API_KEY mancante. Copia .env.example in .env alla root del progetto e inserisci la tua chiave."
    );
  }
  if (!fs.existsSync(config.paths.knowledgeBase)) {
    throw new Error(`Knowledge base non trovata in ${config.paths.knowledgeBase}`);
  }
}

fs.mkdirSync(config.paths.charts, { recursive: true });
