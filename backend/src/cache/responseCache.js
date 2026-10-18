/**
 * Cache delle risposte.
 *
 * Due persone che chiedono "qual è la RAL media per dipartimento?" e "Qual è la
 * RAL media per dipartimento" devono pagare una sola volta il costo dell'analisi.
 * La chiave è la domanda normalizzata (minuscole, senza accenti né punteggiatura)
 * combinata con una FIRMA DELLA FONTE: se il CSV o il manuale cambiano, le voci
 * che li riguardano smettono automaticamente di essere valide, senza bisogno di
 * svuotare la cache a mano.
 *
 * DUE DEPOSITI DIETRO LA STESSA INTERFACCIA. Senza `REDIS_URL` le voci stanno in
 * una Map del processo: semplice, ma non condivisa fra istanze e persa a ogni
 * riavvio. Con `REDIS_URL` le stesse voci vivono in Redis, quindi più repliche
 * del backend riusano le analisi l'una dell'altra e il riavvio non azzera nulla.
 *
 * La memoria locale resta come rete di sicurezza: se Redis smette di rispondere
 * la cache degrada invece di propagare l'errore all'utente.
 */
import crypto from "node:crypto";
import { conRedis, redisConfigurato, statoRedis } from "./redisClient.js";

const PREFISSO = "chicco:cache:";

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

// --- deposito locale, usato da solo o come rete di sicurezza ---------------
function leggiLocale(chiave) {
  const voce = voci.get(chiave);
  if (!voce) return null;
  if (Date.now() > voce.scadenza) {
    voci.delete(chiave);
    return null;
  }
  // rinfresca la posizione: la voce più usata resta in coda e sopravvive al taglio
  voci.delete(chiave);
  voci.set(chiave, voce);
  return voce.valore;
}

function scriviLocale(chiave, valore, ttlMs) {
  if (voci.size >= MAX_VOCI) {
    const piuVecchia = voci.keys().next().value;
    voci.delete(piuVecchia);
  }
  voci.set(chiave, { valore, scadenza: Date.now() + ttlMs });
}

export async function leggiDallaCache(chiave) {
  let valore = null;

  const grezzo = await conRedis((redis) => redis.get(PREFISSO + chiave));
  if (grezzo) {
    try {
      valore = JSON.parse(grezzo);
    } catch {
      /* voce illeggibile: vale come assente */
    }
  }
  if (valore === null) valore = leggiLocale(chiave);

  if (valore === null) mancati += 1;
  else colpi += 1;
  return valore;
}

export async function scriviInCache(chiave, valore, ttlMs = TTL_PREDEFINITO_MS) {
  scriviLocale(chiave, valore, ttlMs);

  await conRedis((redis) => redis.set(PREFISSO + chiave, JSON.stringify(valore), { PX: ttlMs }));
}

/** Rimuove una voce diventata inservibile (es. il grafico non esiste più). */
export async function invalidaVoce(chiave) {
  voci.delete(chiave);
  await conRedis((redis) => redis.del(PREFISSO + chiave));
}

export function statisticheCache() {
  const totale = colpi + mancati;
  return {
    deposito: redisConfigurato() ? "redis" : "memoria",
    redis: statoRedis(),
    voci_locali: voci.size,
    colpi,
    mancati,
    tasso_di_riuso: totale ? Number((colpi / totale).toFixed(2)) : 0,
  };
}
