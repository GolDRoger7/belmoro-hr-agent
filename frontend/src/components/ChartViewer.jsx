/** Mostra i grafici prodotti dall'agente Python e serviti dal backend Node. */
export default function ChartViewer({ charts = [] }) {
  if (!charts.length) return null;

  return (
    <div className="grafici">
      {charts.map((url) => (
        <figure key={url} className="grafico">
          <img src={url} alt="Grafico generato dall'agente di analisi dati" loading="lazy" />
          <figcaption>
            Grafico generato da matplotlib/seaborn ·{" "}
            <a href={url} target="_blank" rel="noreferrer">apri a dimensione piena</a>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
