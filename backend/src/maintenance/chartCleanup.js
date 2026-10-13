/**
 * Pulizia periodica dei grafici.
 *
 * Ogni analisi produce un PNG nella cartella condivisa: senza manutenzione la
 * cartella cresce senza limite. Qui un task in background elimina le immagini
 * più vecchie della soglia configurata, all'avvio e poi a intervalli regolari.
 *
 * È un timer interno al processo invece di un cron di sistema perché il backend
 * conosce già il percorso dei grafici e vive quanto il servizio: nessun file di
 * configurazione esterno da tenere allineato. Chi preferisce il cron trova il
 * comando equivalente nel README.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { config } from "../config.js";

export async function puliziaGrafici({ silenzioso = false } = {}) {
  const sogliaMs = config.charts.ttlOre * 60 * 60 * 1000;
  const limite = Date.now() - sogliaMs;

  let rimossi = 0;
  let liberatiByte = 0;

  try {
    const file = await fs.readdir(config.paths.charts);
    for (const nome of file) {
      if (!nome.toLowerCase().endsWith(".png")) continue;
      const percorso = path.join(config.paths.charts, nome);
      try {
        const info = await fs.stat(percorso);
        if (info.mtimeMs < limite) {
          await fs.unlink(percorso);
          rimossi += 1;
          liberatiByte += info.size;
        }
      } catch {
        /* il file può essere sparito nel frattempo: non è un problema */
      }
    }
  } catch (errore) {
    console.warn(`⚠️  Pulizia grafici non riuscita: ${errore.message}`);
    return { rimossi: 0, liberatiByte: 0 };
  }

  if (rimossi && !silenzioso) {
    console.log(
      `🧹 Pulizia grafici: rimossi ${rimossi} file più vecchi di ${config.charts.ttlOre}h ` +
        `(${(liberatiByte / 1024 / 1024).toFixed(1)} MB liberati)`
    );
  }
  return { rimossi, liberatiByte };
}

/** Avvia la pulizia all'accensione e poi a intervalli regolari. */
export function avviaPuliziaPeriodica() {
  puliziaGrafici({ silenzioso: true });
  const timer = setInterval(puliziaGrafici, config.charts.intervalloPuliziaMinuti * 60 * 1000);
  timer.unref(); // non tiene vivo il processo in chiusura
  return timer;
}
