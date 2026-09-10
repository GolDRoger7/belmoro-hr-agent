import { useCallback, useEffect, useRef, useState } from "react";
import MessageBubble from "./components/MessageBubble.jsx";
import TypingIndicator from "./components/TypingIndicator.jsx";
import Composer from "./components/Composer.jsx";
import SuggestedPrompts from "./components/SuggestedPrompts.jsx";
import StatusBar from "./components/StatusBar.jsx";
import { inviaMessaggioStreaming, leggiStatoSistema, resetSessione } from "./api/chatClient.js";

const CHIAVE_SESSIONE = "belmoro-hr-agent-session";

export default function App() {
  const [messaggi, setMessaggi] = useState([]);
  const [bozza, setBozza] = useState("");
  const [inCorso, setInCorso] = useState(false);
  const [fase, setFase] = useState("reasoning");
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(CHIAVE_SESSIONE) || null);
  const [stato, setStato] = useState(null);

  const fondoRef = useRef(null);

  // --- semaforo dei servizi, aggiornato periodicamente ---------------------
  useEffect(() => {
    let attivo = true;
    const aggiorna = async () => {
      const risultato = await leggiStatoSistema();
      if (attivo) setStato(risultato);
    };
    aggiorna();
    const timer = setInterval(aggiorna, 20000);
    return () => {
      attivo = false;
      clearInterval(timer);
    };
  }, []);

  // --- autoscroll sull'ultimo messaggio -----------------------------------
  useEffect(() => {
    fondoRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messaggi, inCorso, fase]);

  const invia = useCallback(
    async (testo) => {
      const contenuto = (testo ?? bozza).trim();
      if (!contenuto || inCorso) return;

      setBozza("");
      setInCorso(true);
      setFase("reasoning");
      setMessaggi((precedenti) => [
        ...precedenti,
        { id: crypto.randomUUID(), role: "user", content: contenuto, timestamp: Date.now() },
      ]);

      try {
        const esito = await inviaMessaggioStreaming({
          message: contenuto,
          sessionId,
          onEvent: (evento) => {
            // la memoria conversazionale vive sul backend: qui teniamo solo l'id
            if (evento.type === "start" && evento.sessionId) {
              setSessionId(evento.sessionId);
              localStorage.setItem(CHIAVE_SESSIONE, evento.sessionId);
            }
            if (evento.type === "tool_start") setFase(evento.tool);
            if (evento.type === "tool_end") setFase("writing");
          },
        });

        setSessionId(esito.sessionId);
        localStorage.setItem(CHIAVE_SESSIONE, esito.sessionId);
        setMessaggi((precedenti) => [
          ...precedenti,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: esito.reply,
            charts: esito.charts,
            sources: esito.sources,
            trace: esito.trace,
            toolUsed: esito.toolUsed,
            elapsedMs: esito.elapsedMs,
            timestamp: Date.now(),
          },
        ]);
      } catch (errore) {
        setMessaggi((precedenti) => [
          ...precedenti,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            error: true,
            content: `⚠️ **Si è verificato un problema.**\n\n${errore.message}\n\nVerifica dal semaforo in alto che ChromaDB e il data agent Python siano attivi.`,
            timestamp: Date.now(),
          },
        ]);
      } finally {
        setInCorso(false);
      }
    },
    [bozza, inCorso, sessionId]
  );

  const nuovaConversazione = async () => {
    await resetSessione(sessionId);
    localStorage.removeItem(CHIAVE_SESSIONE);
    setSessionId(null);
    setMessaggi([]);
  };

  return (
    <div className="app">
      <header className="intestazione">
        <div className="intestazione__brand">
          <span className="logo" aria-hidden="true">☕</span>
          <div>
            <h1>Chicco · Assistente People &amp; Culture</h1>
            <p>Agente AI ibrido · knowledge base documentale + analisi dati dell'organico</p>
          </div>
        </div>
        <div className="intestazione__azioni">
          <StatusBar stato={stato} />
          <button className="bottone-secondario" onClick={nuovaConversazione} disabled={inCorso}>
            Nuova conversazione
          </button>
        </div>
      </header>

      <main className="conversazione">
        {messaggi.length === 0 && !inCorso ? (
          <SuggestedPrompts onScegli={invia} />
        ) : (
          messaggi.map((messaggio) => <MessageBubble key={messaggio.id} messaggio={messaggio} />)
        )}
        {inCorso && <TypingIndicator fase={fase} />}
        <div ref={fondoRef} />
      </main>

      <footer className="piede">
        <Composer valore={bozza} onChange={setBozza} onInvia={() => invia()} disabilitato={inCorso} />
        <p className="disclaimer">
          Dati e policy sono fittizi, creati a scopo dimostrativo per un progetto universitario.
          Le informazioni individuali vanno trattate in forma aggregata secondo la policy privacy HR.
        </p>
      </footer>
    </div>
  );
}
