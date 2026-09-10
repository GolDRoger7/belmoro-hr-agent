/**
 * Indicatore di elaborazione: non è un semplice "sta scrivendo", ma racconta
 * la fase reale del ciclo ReAct comunicata dal backend via SSE.
 */
const FASI = {
  reasoning: "Sto ragionando sulla richiesta e scegliendo lo strumento…",
  cerca_nelle_policy_hr: "Sto consultando il manuale delle policy HR (ChromaDB)…",
  analizza_dati_dipendenti: "L'agente Python sta pulendo i dati ed eseguendo l'analisi…",
  writing: "Sto componendo la risposta…",
};

export default function TypingIndicator({ fase = "reasoning" }) {
  return (
    <div className="messaggio messaggio--assistente">
      <div className="avatar avatar--bot" aria-hidden="true">☕</div>
      <div className="bolla bolla--assistente bolla--typing">
        <span className="puntini" aria-hidden="true">
          <i /><i /><i />
        </span>
        <span className="typing-testo">{FASI[fase] ?? FASI.reasoning}</span>
      </div>
    </div>
  );
}
