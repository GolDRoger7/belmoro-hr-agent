/**
 * Connessione Redis condivisa, con degradazione silenziosa.
 *
 * Redis è OPZIONALE: senza `REDIS_URL` il backend continua a funzionare con lo
 * stato in memoria, che per una singola istanza va benissimo. Serve quando le
 * istanze sono più di una — cache e sessioni devono essere viste da tutte — e
 * quando non si vuole perdere lo stato a ogni riavvio.
 *
 * La regola che guida questo modulo: un problema della cache non deve mai
 * diventare un problema dell'utente. Se Redis non risponde, si registra una
 * volta sola e si torna alla memoria locale; l'agente risponde comunque.
 */
import { createClient } from "redis";

let client = null;
let connessione = null;
let stato = "non configurato";
let erroreSegnalato = false;

export function redisConfigurato() {
  return Boolean(process.env.REDIS_URL);
}

export async function getRedis() {
  if (!redisConfigurato()) return null;
  if (client?.isReady) return client;
  if (connessione) return connessione;

  connessione = (async () => {
    try {
      client = createClient({
        url: process.env.REDIS_URL,
        // Senza questo, i comandi vengono ACCODATI mentre la connessione è giù e
        // la promise non si risolve mai: una richiesta dell'utente resterebbe
        // appesa per sempre. Meglio che falliscano subito e si usi la memoria.
        disableOfflineQueue: true,
        socket: {
          connectTimeout: 2000,
          // Si riprova per un po', poi si rinuncia: un Redis spento non deve
          // tenere il backend in attesa all'infinito.
          reconnectStrategy: (tentativi) => (tentativi > 10 ? false : Math.min(tentativi * 300, 3000)),
        },
      });
      // Senza questo listener un errore di rete diventerebbe un'eccezione non
      // gestita che abbatte il processo.
      client.on("error", (errore) => {
        stato = `errore: ${errore.message}`;
        if (!erroreSegnalato) {
          console.warn(`⚠️  Redis non disponibile (${errore.message}): si continua con lo stato in memoria.`);
          erroreSegnalato = true;
        }
      });
      await client.connect();
      stato = "connesso";
      erroreSegnalato = false;
      console.log(`   redis           ${process.env.REDIS_URL} (cache e sessioni condivise)`);
      return client;
    } catch (errore) {
      stato = `errore: ${errore.message}`;
      if (!erroreSegnalato) {
        console.warn(`⚠️  Redis non raggiungibile (${errore.message}): stato in memoria.`);
        erroreSegnalato = true;
      }
      client = null;
      return null;
    } finally {
      connessione = null;
    }
  })();

  return connessione;
}

/**
 * Esegue un'operazione su Redis con un tetto di tempo, restituendo null se
 * qualcosa va storto.
 *
 * È il punto in cui si decide che la cache non può far male: qualunque problema
 * — connessione caduta, comando lento, client in riconnessione — si traduce in
 * un "non disponibile" entro pochi centesimi di secondo, e il chiamante
 * prosegue con la memoria locale.
 */
export async function conRedis(operazione, { timeoutMs = 300 } = {}) {
  if (!redisConfigurato()) return null;
  try {
    const redis = await Promise.race([
      getRedis(),
      new Promise((risolvi) => setTimeout(() => risolvi(null), timeoutMs)),
    ]);
    if (!redis?.isReady) return null;

    return await Promise.race([
      operazione(redis),
      new Promise((_, rifiuta) => setTimeout(() => rifiuta(new Error("timeout redis")), timeoutMs)),
    ]);
  } catch {
    return null;
  }
}

export function statoRedis() {
  if (!redisConfigurato()) return { configurato: false, stato: "non configurato" };
  return { configurato: true, stato, pronto: Boolean(client?.isReady) };
}

export async function chiudiRedis() {
  if (client?.isOpen) await client.quit().catch(() => {});
  client = null;
}
