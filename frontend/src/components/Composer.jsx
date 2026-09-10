import { useEffect, useRef } from "react";

/** Area di composizione: invio con Invio, a capo con Shift+Invio. */
export default function Composer({ valore, onChange, onInvia, disabilitato }) {
  const areaRef = useRef(null);

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 160)}px`;
  }, [valore]);

  const gestisciTasto = (evento) => {
    if (evento.key === "Enter" && !evento.shiftKey) {
      evento.preventDefault();
      onInvia();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onInvia();
      }}
    >
      <textarea
        ref={areaRef}
        rows={1}
        value={valore}
        placeholder="Chiedi una policy HR o un'analisi sui dati dell'organico…"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={gestisciTasto}
        disabled={disabilitato}
      />
      <button type="submit" disabled={disabilitato || !valore.trim()} aria-label="Invia messaggio">
        {disabilitato ? <span className="spinner" /> : "Invia"}
      </button>
    </form>
  );
}
