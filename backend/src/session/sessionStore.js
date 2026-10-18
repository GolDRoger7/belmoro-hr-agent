/**
 * Memoria conversazionale lato server.
 *
 * Il front end invia solo un sessionId: lo storico vive qui, così l'orchestratore
 * può ricostruire il contesto (riferimenti impliciti, follow-up del tipo
 * "e per il Marketing?") senza fidarsi del client.
 *
 * Come la cache, la memoria ha due depositi dietro la stessa interfaccia. Senza
 * `REDIS_URL` le sessioni stanno in una Map del processo, e questo basta per una
 * istanza sola. Con più repliche dietro un bilanciatore il problema sarebbe
 * concreto e non teorico: la seconda domanda di un utente può finire su
 * un'istanza diversa dalla prima, che non ricorderebbe nulla e tratterebbe
 * "e per il Marketing?" come una domanda isolata. Con Redis lo storico è
 * condiviso e sopravvive anche al riavvio.
 */
import { conRedis, redisConfigurato } from "../cache/redisClient.js";

const sessioni = new Map();

const MAX_MESSAGGI = 20;      // finestra di contesto passata all'LLM
const TTL_MS = 1000 * 60 * 60 * 3;
const PREFISSO = "chicco:sessione:";

function sessioneVuota() {
  const adesso = Date.now();
  return { messages: [], createdAt: adesso, updatedAt: adesso };
}

function getSessionLocale(sessionId) {
  const adesso = Date.now();
  let sessione = sessioni.get(sessionId);
  if (!sessione || adesso - sessione.updatedAt > TTL_MS) {
    sessione = sessioneVuota();
    sessioni.set(sessionId, sessione);
  }
  return sessione;
}

export async function getSession(sessionId) {
  if (redisConfigurato()) {
    const grezzo = await conRedis((redis) => redis.get(PREFISSO + sessionId));
    if (grezzo) {
      try {
        return JSON.parse(grezzo);
      } catch {
        /* sessione illeggibile: si riparte da vuota */
      }
    }
  }
  return getSessionLocale(sessionId);
}

export async function appendMessages(sessionId, ...messaggi) {
  const sessione = await getSession(sessionId);
  sessione.messages.push(...messaggi);
  if (sessione.messages.length > MAX_MESSAGGI) {
    sessione.messages = sessione.messages.slice(-MAX_MESSAGGI);
  }
  sessione.updatedAt = Date.now();

  const scritta = await conRedis((redis) =>
    redis.set(PREFISSO + sessionId, JSON.stringify(sessione), { PX: TTL_MS })
  );
  // Anche quando Redis risponde, si tiene una copia locale: è la rete di
  // sicurezza se Redis cade fra una domanda e la successiva.
  sessioni.set(sessionId, sessione);
  if (!scritta && redisConfigurato()) { /* degradato: resta la copia locale */ }
  return sessione;
}

export async function clearSession(sessionId) {
  sessioni.delete(sessionId);
  await conRedis((redis) => redis.del(PREFISSO + sessionId));
}

export function sessionStats() {
  return {
    sessioni_locali: sessioni.size,
    deposito_sessioni: redisConfigurato() ? "redis" : "memoria",
  };
}
