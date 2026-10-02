/** Client OpenAI condiviso da orchestratore e RAG. */
import OpenAI from "openai";
import { config } from "../config.js";

export const openai = new OpenAI({ apiKey: config.openai.apiKey });

const TENTATIVI = 4;
const ATTESA_BASE_MS = 800;

/**
 * Errori che vale la pena ritentare: rate limit, indisponibilità temporanee,
 * problemi di rete e la finestra di propagazione dei permessi di progetto
 * (subito dopo aver abilitato un modello, l'API può rispondere 403 a
 * intermittenza per qualche minuto).
 */
function ritentabile(errore) {
  const stato = errore?.status;
  if (stato === 429 || (stato >= 500 && stato < 600)) return true;
  if (stato === 403 && /does not have access to model/i.test(errore?.message ?? "")) return true;
  return ["ECONNRESET", "ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN"].includes(errore?.cause?.code);
}

/** Esegue la chiamata con backoff esponenziale sugli errori transitori. */
export async function conRiprova(operazione, etichetta = "chiamata OpenAI") {
  let ultimoErrore;
  for (let tentativo = 1; tentativo <= TENTATIVI; tentativo += 1) {
    try {
      return await operazione();
    } catch (errore) {
      ultimoErrore = errore;
      if (!ritentabile(errore) || tentativo === TENTATIVI) break;
      const attesa = ATTESA_BASE_MS * 2 ** (tentativo - 1);
      console.warn(
        `⚠️  ${etichetta}: tentativo ${tentativo}/${TENTATIVI} fallito (${errore.status ?? errore.message}). Riprovo fra ${attesa}ms.`
      );
      await new Promise((risolvi) => setTimeout(risolvi, attesa));
    }
  }
  throw ultimoErrore;
}

/** Calcola gli embedding di una lista di testi (batch unico). */
export async function embedTexts(texts) {
  const response = await conRiprova(
    () => openai.embeddings.create({ model: config.openai.embeddingModel, input: texts }),
    "embedding"
  );
  return response.data.map((item) => item.embedding);
}

export async function embedQuery(text) {
  const [embedding] = await embedTexts([text]);
  return embedding;
}

/** Completion di chat con la stessa politica di riprova. */
export async function chatCompletion(parametri, etichetta = "chat") {
  return conRiprova(() => openai.chat.completions.create(parametri), etichetta);
}
