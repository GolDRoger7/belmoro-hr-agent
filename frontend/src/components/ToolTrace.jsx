import { useState } from "react";

const NOMI = {
  cerca_nelle_policy_hr: "RAG sulle policy HR",
  analizza_dati_dipendenti: "Agente dati Python",
};

/** Pannello ispezionabile con i passi decisionali e il codice eseguito. */
export default function ToolTrace({ trace = [], sources = [] }) {
  const [aperto, setAperto] = useState(false);
  if (!trace.length && !sources.length) return null;

  return (
    <div className="trace">
      <button className="trace__toggle" onClick={() => setAperto((v) => !v)}>
        {aperto ? "▾" : "▸"} Come sono arrivato a questa risposta
        <span className="trace__conteggio">{trace.length} passaggi</span>
      </button>

      {aperto && (
        <div className="trace__corpo">
          <ol className="trace__lista">
            {trace.map((passo) => (
              <li key={passo.step} className={`trace__passo trace__passo--${passo.status}`}>
                <div className="trace__titolo">
                  <strong>{NOMI[passo.tool] ?? passo.tool}</strong>
                  {passo.ms != null && <span className="trace__tempo">{(passo.ms / 1000).toFixed(1)}s</span>}
                </div>
                {passo.args?.query && <p className="trace__query">Query: «{passo.args.query}»</p>}
                {passo.args?.question && <p className="trace__query">Richiesta: «{passo.args.question}»</p>}
                {passo.detail && <p className="trace__dettaglio">{passo.detail}</p>}
                {passo.code?.length > 0 && (
                  <details className="trace__codice">
                    <summary>Codice Python eseguito ({passo.code.length} blocchi)</summary>
                    {passo.code.map((frammento, i) => (
                      <pre key={i}>{frammento}</pre>
                    ))}
                  </details>
                )}
              </li>
            ))}
          </ol>

          {sources.length > 0 && (
            <div className="fonti">
              <h4>Fonti documentali recuperate</h4>
              <ul>
                {sources.map((fonte, i) => (
                  <li key={i}>
                    <span className="fonti__sezione">{fonte.section}</span>
                    {fonte.score != null && <span className="fonti__score">rilevanza {fonte.score}</span>}
                    <p>{fonte.preview}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
