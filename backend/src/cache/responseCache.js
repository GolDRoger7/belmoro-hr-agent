/**
 * Cache delle risposte dei tool.
 *
 * Due persone che chiedono "qual è la RAL media per dipartimento?" e "Qual è la
 * RAL media per dipartimento" devono pagare una sola volta il costo dell'analisi.
 * La chiave è la domanda normalizzata (minuscole, senza accenti né punteggiatura)
 * combinata con una FIRMA DELLA FONTE: se il CSV o il manuale cambiano, le voci
 * che li riguardano smettono automaticamente di essere valide, senza bisogno di
 * svuotare la cache a mano.
 *
 * Implementazione in memoria con TTL e tetto di dimensione: sufficiente per una
 * istanza singola. In produzione, con più repliche del backend, la stessa
 * interfaccia si appoggerebbe a Redis.
 */
import crypto from "node:crypto";

const voci = new Map();

const TTL_PREDEFINITO_MS = 1000 * 60 * 30;
const MAX_VOCI = 200;

let colpi = 0;
let mancati = 0;

/** Minuscole, senza accenti, senza punteggiatura, spazi normalizzati. */
export function normalizzaTesto(testo) {
  return (testo ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9%€\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * @param {string} tool nome del tool
 * @param {string} domanda testo della richiesta
 * @param {string} firmaFonte impronta della fonte dati (es. mtime del file)
 */
export function chiaveCache(tool, domanda, firmaFonte) {
  const grezza = `${tool}::${firmaFonte}::${normalizzaTesto(domanda)}`;
  return crypto.createHash("sha256").update(grezza).digest("hex").slice(0, 32);
}

export function leggiDallaCache(chiave) {
  const voce = voci.get(chiave);
  if (!voce) {
    mancati += 1;
    return null;
  }
  if (Date.now() > voce.scadenza) {
    voci.delete(chiave);
    mancati += 1;
    return null;
  }
  // rinfresca la posizione: la voce più usata resta in coda e sopravvive al taglio
  voci.delete(chiave);
  voci.set(chiave, voce);
  colpi += 1;
  return voce.valore;
}

export function scriviInCache(chiave, valore, ttlMs = TTL_PREDEFINITO_MS) {
  if (voci.size >= MAX_VOCI) {
    const piuVecchia = voci.keys().next().value;
    voci.delete(piuVecchia);
  }
  voci.set(chiave, { valore, scadenza: Date.now() + ttlMs });
}

/** Rimuove una voce diventata inservibile (es. il grafico non esiste più). */
export function invalidaVoce(chiave) {
  voci.delete(chiave);
}

export function statisticheCache() {
  const totale = colpi + mancati;
  return {
    voci: voci.size,
    colpi,
    mancati,
    tasso_di_riuso: totale ? Number((colpi / totale).toFixed(2)) : 0,
  };
}
