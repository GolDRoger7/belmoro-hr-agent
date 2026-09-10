/** Semaforo dei tre servizi dell'architettura a microservizi. */
export default function StatusBar({ stato }) {
  if (!stato) return null;

  const servizi = [
    { nome: "OpenAI", ok: stato.openai?.configured, dettaglio: stato.openai?.model },
    {
      nome: "ChromaDB",
      ok: stato.chroma?.reachable,
      dettaglio: stato.chroma?.reachable ? `${stato.chroma.chunks} chunk` : "non raggiungibile",
    },
    {
      nome: "Data agent",
      ok: stato.dataAgent?.reachable,
      dettaglio: stato.dataAgent?.reachable ? `${stato.dataAgent.rows} righe` : "non raggiungibile",
    },
  ];

  return (
    <div className="stato">
      {servizi.map((servizio) => (
        <span key={servizio.nome} className={`stato__voce ${servizio.ok ? "is-ok" : "is-ko"}`}>
          <i className="stato__pallino" /> {servizio.nome}
          <em>{servizio.dettaglio}</em>
        </span>
      ))}
    </div>
  );
}
