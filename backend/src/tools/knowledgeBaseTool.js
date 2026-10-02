/**
 * TOOL 1 - "cerca_nelle_policy_hr"
 * Retrieval-Augmented Generation sulla knowledge base documentale.
 *
 * Flusso: domanda -> embedding -> ricerca semantica su ChromaDB -> i passaggi
 * recuperati diventano l'UNICO contesto ammesso per la risposta finale.
 * Il modello è vincolato a non usare conoscenza generica: se il contesto non
 * contiene la risposta, deve dichiararlo.
 */
import { config } from "../config.js";
import { chatCompletion } from "../rag/openaiClient.js";
import { searchKnowledgeBase } from "../rag/chromaStore.js";

const PROMPT_RAG = `Sei l'assistente documentale della funzione People & Culture del Caffè Belmoro.
Rispondi ESCLUSIVAMENTE sulla base degli estratti del manuale delle policy HR riportati sotto.

Regole vincolanti:
- Non usare conoscenze esterne o generiche sul diritto del lavoro: solo il contesto fornito.
- Se il contesto non contiene l'informazione, dichiara esplicitamente che la policy non
  copre il punto e suggerisci di contattare People & Culture. Non inventare nulla.
- Riporta i numeri esatti (giorni, importi, soglie, percentuali) così come sono scritti.
- Rispondi in italiano, in modo diretto e operativo, in massimo 8 righe.
- Chiudi SEMPRE con una riga "Fonte: <titoli delle sezioni usate>".

--- ESTRATTI DAL MANUALE HR ---
{contesto}
--- FINE ESTRATTI ---`;

export async function cercaNellePolicyHr({ query, n_results = 5 }) {
  const passaggi = await searchKnowledgeBase(query, n_results);

  const contesto = passaggi
    .map((p, i) => `[${i + 1}] (sezione: ${p.section} | rilevanza: ${p.score})\n${p.text}`)
    .join("\n\n");

  const risposta = await chatCompletion(
    {
      model: config.openai.chatModel,
      temperature: 0,
      messages: [
        { role: "system", content: PROMPT_RAG.replace("{contesto}", contesto) },
        { role: "user", content: query },
      ],
    },
    "sintesi RAG"
  );

  return {
    answer: risposta.choices[0].message.content,
    sources: passaggi.map((p) => ({
      section: p.section,
      score: p.score,
      source: p.source,
      preview: p.text.slice(0, 220).replace(/\s+/g, " ") + "...",
    })),
  };
}

/** Descrizione del tool esposta all'LLM orchestratore (function calling). */
export const knowledgeBaseToolSchema = {
  type: "function",
  function: {
    name: "cerca_nelle_policy_hr",
    description:
      "Cerca nel manuale delle policy HR di Caffè Belmoro (regolamenti, procedure, FAQ interne). " +
      "Usalo per domande QUALITATIVE su regole e procedure: smart working, ferie e permessi, " +
      "welfare e benefit, congedi, revisione salariale e bonus, performance management e PIP, " +
      "formazione, selezione e onboarding, preavviso e dimissioni, trasferte e rimborsi, " +
      "diversity & inclusion, privacy dei dati HR. " +
      "NON usarlo per calcoli, medie, conteggi o confronti numerici sui dipendenti.",
    parameters: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description:
            "La domanda riformulata in modo autonomo e completo (senza pronomi che rimandano " +
            "ai messaggi precedenti), ottimizzata per la ricerca semantica.",
        },
        n_results: {
          type: "integer",
          description: "Numero di passaggi da recuperare (default 5).",
        },
      },
      required: ["query"],
      additionalProperties: false,
    },
  },
};
