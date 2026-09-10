/** Client OpenAI condiviso da orchestratore e RAG. */
import OpenAI from "openai";
import { config } from "../config.js";

export const openai = new OpenAI({ apiKey: config.openai.apiKey });

/** Calcola gli embedding di una lista di testi (batch unico). */
export async function embedTexts(texts) {
  const response = await openai.embeddings.create({
    model: config.openai.embeddingModel,
    input: texts,
  });
  return response.data.map((item) => item.embedding);
}

export async function embedQuery(text) {
  const [embedding] = await embedTexts([text]);
  return embedding;
}
