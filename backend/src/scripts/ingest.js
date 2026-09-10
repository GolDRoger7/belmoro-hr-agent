#!/usr/bin/env node
/**
 * Indicizzazione della knowledge base HR su ChromaDB.
 *
 * Uso:  npm run ingest            (dalla cartella backend/)
 * Prerequisito: server Chroma in ascolto su CHROMA_HOST:CHROMA_PORT.
 */
import fs from "node:fs";
import path from "node:path";
import { config, assertConfig } from "../config.js";
import { chunkKnowledgeBase } from "../rag/chunker.js";
import { embedTexts } from "../rag/openaiClient.js";
import { getChromaClient, resetCollectionCache } from "../rag/chromaStore.js";

const BATCH = 64;

async function main() {
  assertConfig();

  const fonte = path.basename(config.paths.knowledgeBase);
  console.log(`\n📄 Knowledge base: ${config.paths.knowledgeBase}`);
  const raw = fs.readFileSync(config.paths.knowledgeBase, "utf-8");

  const chunks = chunkKnowledgeBase(raw, fonte);
  console.log(`✂️  Chunk generati: ${chunks.length}`);
  const perTipo = chunks.reduce((acc, c) => {
    acc[c.metadata.tipo] = (acc[c.metadata.tipo] || 0) + 1;
    return acc;
  }, {});
  console.log(`   ripartizione: ${JSON.stringify(perTipo)}`);

  const client = getChromaClient();
  console.log(`\n🔌 Connessione a Chroma su ${config.chroma.host}:${config.chroma.port}...`);
  await client.heartbeat();

  // Reindicizzazione idempotente: la collection viene ricreata da zero.
  try {
    await client.deleteCollection({ name: config.chroma.collection });
    console.log(`🗑️  Collection "${config.chroma.collection}" preesistente rimossa`);
  } catch {
    /* la collection non esisteva: va bene così */
  }
  resetCollectionCache();

  const collection = await client.getOrCreateCollection({
    name: config.chroma.collection,
    metadata: { descrizione: "Policy HR Caffè Belmoro - knowledge base RAG" },
    embeddingFunction: null,
  });

  console.log(`\n🧠 Calcolo embedding con ${config.openai.embeddingModel}...`);
  for (let i = 0; i < chunks.length; i += BATCH) {
    const lotto = chunks.slice(i, i + BATCH);
    const embeddings = await embedTexts(lotto.map((c) => c.text));
    await collection.add({
      ids: lotto.map((c) => c.id),
      embeddings,
      documents: lotto.map((c) => c.text),
      metadatas: lotto.map((c) => c.metadata),
    });
    console.log(`   indicizzati ${Math.min(i + BATCH, chunks.length)}/${chunks.length}`);
  }

  const totale = await collection.count();
  console.log(`\n✅ Indicizzazione completata: ${totale} chunk nella collection "${config.chroma.collection}"\n`);
}

main().catch((error) => {
  console.error("\n❌ Ingestion fallita:", error.message);
  process.exit(1);
});
