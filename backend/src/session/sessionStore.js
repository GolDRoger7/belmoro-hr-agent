/**
 * Memoria conversazionale lato server.
 *
 * Il front end invia solo un sessionId: lo storico vive qui, così l'orchestratore
 * può ricostruire il contesto (riferimenti impliciti, follow-up del tipo
 * "e per il Marketing?") senza fidarsi del client.
 * Implementazione in memoria: sufficiente per una demo locale; in produzione si
 * sostituirebbe con Redis o un database, mantenendo la stessa interfaccia.
 */
const sessioni = new Map();

const MAX_MESSAGGI = 20;      // finestra di contesto passata all'LLM
const TTL_MS = 1000 * 60 * 60 * 3;

export function getSession(sessionId) {
  const adesso = Date.now();
  let sessione = sessioni.get(sessionId);
  if (!sessione || adesso - sessione.updatedAt > TTL_MS) {
    sessione = { messages: [], createdAt: adesso, updatedAt: adesso };
    sessioni.set(sessionId, sessione);
  }
  return sessione;
}

export function appendMessages(sessionId, ...messaggi) {
  const sessione = getSession(sessionId);
  sessione.messages.push(...messaggi);
  if (sessione.messages.length > MAX_MESSAGGI) {
    sessione.messages = sessione.messages.slice(-MAX_MESSAGGI);
  }
  sessione.updatedAt = Date.now();
  return sessione;
}

export function clearSession(sessionId) {
  sessioni.delete(sessionId);
}

export function sessionStats() {
  return { sessioni_attive: sessioni.size };
}
