/** Esempi che mostrano subito la natura ibrida dell'agente. */
const ESEMPI = [
  {
    gruppo: "📚 Knowledge base (RAG)",
    domande: [
      "Quanti giorni di smart working al mese posso fare se lavoro in IT?",
      "Come funziona la revisione salariale annuale e quali incrementi sono previsti?",
      "Che preavviso deve dare un quadro che si dimette?",
    ],
  },
  {
    gruppo: "📊 Analisi dati (agente Python)",
    domande: [
      "Qual è la RAL media per dipartimento? Mostrami un grafico.",
      "Quale reparto ha il tasso di turnover più alto?",
      "Analizza la distribuzione dei performance rating nell'organico.",
    ],
  },
  {
    gruppo: "🔀 Domanda ibrida (entrambi gli strumenti)",
    domande: [
      "Il nostro gender pay gap rispetta l'obiettivo fissato dalla policy?",
      "I giorni di smart working effettivi sono in linea con i plafond di policy?",
    ],
  },
];

export default function SuggestedPrompts({ onScegli }) {
  return (
    <div className="benvenuto">
      <div className="benvenuto__intro">
        <h2>Ciao, sono Chicco ☕</h2>
        <p>
          L'assistente della funzione <strong>People &amp; Culture</strong>. Interrogo il manuale
          delle policy HR e analizzo i dati dell'organico: decido io quale dei due strumenti
          serve alla tua domanda.
        </p>
      </div>

      {ESEMPI.map((blocco) => (
        <div key={blocco.gruppo} className="suggerimenti">
          <h3>{blocco.gruppo}</h3>
          <div className="suggerimenti__lista">
            {blocco.domande.map((domanda) => (
              <button key={domanda} onClick={() => onScegli(domanda)}>
                {domanda}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
