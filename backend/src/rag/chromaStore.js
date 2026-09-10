/**
 * Accesso a ChromaDB (istanza locale in esecuzione su http://CHROMA_HOST:CHROMA_PORT).
 *
 * Gli embedding sono calcolati lato Node con l'API OpenAI e passati a Chroma già
 * pronti (embeddingFunction: null): il vector store resta così un puro indice
 * vettoriale e la scelta del modello di embedding vive in un solo punto.
 */
import { ChromaClient } from "chromadb";
import { config } from "../config.js";
import { embedQuery } from "./openaiClient.js";

let client = null;
let collectionCache = null;

export function getChromaClient() {
  if (!client) {
    client = new ChromaClient({
      host: config.chroma.host,
      port: config.chroma.port,
      ssl: false,
    });
  }
  return client;
}

export async function getCollection() {
  if (collectionCache) return collectionCache;
  collectionCache = await getChromaClient().getOrCreateCollection({
    name: config.chroma.collection,
    metadata: { descrizione: "Policy HR Caffè Belmoro - knowledge base RAG" },
    embeddingFunction: null,
  });
  return collectionCache;
}

export function resetCollectionCache() {
  collectionCache = null;
}

/**
 * Ricerca semantica: restituisce i chunk più vicini alla domanda.
 * @returns {Promise<Array<{id:string, text:string, section:string, score:number}>>}
 */
export async function searchKnowledgeBase(question, nResults = 5) {
  const collection = await getCollection();
  const total = await collection.count();
  if (total === 0) {
    throw new Error(
      "La collection Chroma è vuota: esegui prima l'indicizzazione con `npm run ingest`."
    );
  }

  const queryEmbedding = await embedQuery(question);
  const result = await collection.query({
    queryEmbeddings: [queryEmbedding],
    nResults: Math.min(nResults, total),
    include: ["documents", "metadatas", "distances"],
  });

  const documents = result.documents?.[0] ?? [];
  const metadatas = result.metadatas?.[0] ?? [];
  const distances = result.distances?.[0] ?? [];
  const ids = result.ids?.[0] ?? [];

  return documents.map((text, i) => ({
    id: ids[i] ?? `chunk-${i}`,
    text,
    section: metadatas[i]?.sezione ?? "Documento HR",
    source: metadatas[i]?.fonte ?? "hr_policy_belmoro.txt",
    // Chroma restituisce una distanza: la convertiamo in un punteggio leggibile.
    score: distances[i] != null ? Number((1 / (1 + distances[i])).toFixed(3)) : null,
  }));
}

/** Diagnostica usata da /api/health. */
export async function chromaStatus() {
  try {
    const collection = await getCollection();
    return { reachable: true, collection: config.chroma.collection, chunks: await collection.count() };
  } catch (error) {
    return { reachable: false, collection: config.chroma.collection, error: error.message };
  }
}
