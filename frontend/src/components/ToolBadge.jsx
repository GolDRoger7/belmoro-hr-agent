/** Etichetta che dichiara quale strumento ha usato l'agente per rispondere. */
const ETICHETTE = {
  cerca_nelle_policy_hr: {
    testo: "Knowledge base · RAG su ChromaDB",
    icona: "📚",
    classe: "badge badge--rag",
  },
  analizza_dati_dipendenti: {
    testo: "Data agent · pandas in Python",
    icona: "📊",
    classe: "badge badge--dati",
  },
};

export default function ToolBadge({ tool }) {
  const meta = ETICHETTE[tool];
  if (!meta) {
    return (
      <span className="badge badge--diretto">
        <span aria-hidden="true">💬</span> Risposta diretta dell'orchestratore
      </span>
    );
  }
  return (
    <span className={meta.classe}>
      <span aria-hidden="true">{meta.icona}</span> {meta.testo}
    </span>
  );
}
