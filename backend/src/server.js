/**
 * Backend orchestratore - Agente HR ibrido Caffè Belmoro.
 *
 * Espone al front end React un unico endpoint conversazionale (POST /api/chat) e
 * serve staticamente i grafici prodotti dal microservizio Python.
 */
import express from "express";
import cors from "cors";
import { randomUUID } from "node:crypto";
import { config, assertConfig } from "./config.js";
import { eseguiTurno } from "./agent/orchestrator.js";
import { chromaStatus } from "./rag/chromaStore.js";
import { dataAgentStatus } from "./tools/dataAnalysisTool.js";
import { getSession, appendMessages, clearSession, sessionStats } from "./session/sessionStore.js";

const app = express();

app.use(cors({ origin: config.server.frontendOrigin }));
app.use(express.json({ limit: "1mb" }));

// log minimale delle richieste
app.use((req, _res, next) => {
  if (req.path.startsWith("/api")) {
    console.log(`${new Date().toISOString()} | ${req.method} ${req.path}`);
  }
  next();
});

/**
 * I grafici sono scritti dal data agent Python nella cartella condivisa e
 * pubblicati qui: il front end li richiede al solo backend Node.
 */
app.use(
  "/charts",
  express.static(config.paths.charts, { maxAge: "1h", fallthrough: false })
);

// ---------------------------------------------------------------- health
app.get("/api/health", async (_req, res) => {
  const [chroma, dataAgent] = await Promise.all([chromaStatus(), dataAgentStatus()]);
  const ok = chroma.reachable && dataAgent.reachable && Boolean(config.openai.apiKey);
  res.status(ok ? 200 : 503).json({
    status: ok ? "ok" : "degraded",
    openai: { configured: Boolean(config.openai.apiKey), model: config.openai.chatModel },
    chroma,
    dataAgent,
    ...sessionStats(),
  });
});

// ------------------------------------------------------------------ chat
app.post("/api/chat", async (req, res) => {
  const { message, sessionId } = req.body ?? {};

  if (typeof message !== "string" || message.trim().length === 0) {
    return res.status(400).json({ error: "Il campo 'message' è obbligatorio." });
  }

  const idSessione = sessionId || randomUUID();
  const sessione = getSession(idSessione);

  try {
    const inizio = Date.now();
    const esito = await eseguiTurno(sessione.messages, message.trim());

    appendMessages(
      idSessione,
      { role: "user", content: message.trim() },
      { role: "assistant", content: esito.reply }
    );

    res.json({
      sessionId: idSessione,
      reply: esito.reply,
      charts: esito.charts,
      sources: esito.sources,
      trace: esito.trace,
      toolUsed: esito.toolUsed,
      elapsedMs: Date.now() - inizio,
    });
  } catch (errore) {
    console.error("Errore /api/chat:", errore);
    res.status(500).json({
      error: "L'orchestratore non è riuscito a completare la richiesta.",
      detail: errore.message,
    });
  }
});


// ----------------------------------------------------- chat in streaming (SSE)
/**
 * Variante streaming di /api/chat: emette in tempo reale gli eventi di
 * ragionamento (quale tool è stato scelto, quando parte e quando finisce) così
 * che il front end possa mostrare cosa sta facendo l'agente invece di un
 * generico "sto scrivendo".
 */
app.post("/api/chat/stream", async (req, res) => {
  const { message, sessionId } = req.body ?? {};

  if (typeof message !== "string" || message.trim().length === 0) {
    return res.status(400).json({ error: "Il campo 'message' è obbligatorio." });
  }

  const idSessione = sessionId || randomUUID();
  const sessione = getSession(idSessione);

  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });

  const invia = (evento) => res.write(`data: ${JSON.stringify(evento)}\n\n`);
  invia({ type: "start", sessionId: idSessione });

  try {
    const inizio = Date.now();
    const esito = await eseguiTurno(sessione.messages, message.trim(), invia);

    appendMessages(
      idSessione,
      { role: "user", content: message.trim() },
      { role: "assistant", content: esito.reply }
    );

    invia({
      type: "final",
      sessionId: idSessione,
      reply: esito.reply,
      charts: esito.charts,
      sources: esito.sources,
      trace: esito.trace,
      toolUsed: esito.toolUsed,
      elapsedMs: Date.now() - inizio,
    });
  } catch (errore) {
    console.error("Errore /api/chat/stream:", errore);
    invia({ type: "error", error: errore.message });
  } finally {
    res.end();
  }
});

// --------------------------------------------------------------- sessioni
app.delete("/api/sessions/:id", (req, res) => {
  clearSession(req.params.id);
  res.json({ status: "reset", sessionId: req.params.id });
});

// --------------------------------------------------------------- avvio
try {
  assertConfig();
} catch (errore) {
  console.error(`\n❌ Configurazione non valida: ${errore.message}\n`);
  process.exit(1);
}

app.listen(config.server.port, () => {
  console.log("\n☕  Agente HR ibrido Caffè Belmoro - backend orchestratore");
  console.log(`   in ascolto su   http://localhost:${config.server.port}`);
  console.log(`   modello LLM     ${config.openai.chatModel}`);
  console.log(`   ChromaDB        ${config.chroma.host}:${config.chroma.port} (${config.chroma.collection})`);
  console.log(`   data agent      ${config.dataAgent.url}`);
  console.log(`   grafici         ${config.paths.charts}\n`);
});
