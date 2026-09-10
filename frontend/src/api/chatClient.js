/**
 * Client HTTP verso il backend orchestratore.
 * Usa l'endpoint in streaming (SSE su POST) per ricevere in tempo reale gli
 * eventi di ragionamento dell'agente; se lo streaming non è disponibile,
 * ricade automaticamente sull'endpoint sincrono.
 */

const decodificatore = new TextDecoder();

export async function inviaMessaggioStreaming({ message, sessionId, onEvent, signal }) {
  const risposta = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId }),
    signal,
  });

  if (!risposta.ok || !risposta.body) {
    return inviaMessaggio({ message, sessionId, signal });
  }

  const reader = risposta.body.getReader();
  let buffer = "";
  let finale = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decodificatore.decode(value, { stream: true });
    const blocchi = buffer.split("\n\n");
    buffer = blocchi.pop() ?? "";

    for (const blocco of blocchi) {
      const riga = blocco.split("\n").find((r) => r.startsWith("data: "));
      if (!riga) continue;
      let evento;
      try {
        evento = JSON.parse(riga.slice(6));
      } catch {
        continue;
      }
      if (evento.type === "final") finale = evento;
      if (evento.type === "error") throw new Error(evento.error);
      onEvent?.(evento);
    }
  }

  if (!finale) throw new Error("Risposta incompleta dal backend.");
  return finale;
}

export async function inviaMessaggio({ message, sessionId, signal }) {
  const risposta = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId }),
    signal,
  });
  const dati = await risposta.json();
  if (!risposta.ok) throw new Error(dati.detail || dati.error || "Errore del backend");
  return dati;
}

export async function leggiStatoSistema() {
  try {
    const risposta = await fetch("/api/health");
    return await risposta.json();
  } catch (errore) {
    return { status: "offline", error: errore.message };
  }
}

export async function resetSessione(sessionId) {
  if (!sessionId) return;
  await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }).catch(() => {});
}
