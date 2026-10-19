/**
 * Impronte delle fonti dati, condivise da tutti i livelli di cache.
 *
 * Una voce in cache resta valida finché la fonte da cui deriva non cambia: qui
 * la fonte è un file, e la sua impronta è data e dimensione. Se il manuale o il
 * CSV vengono sostituiti, le chiavi cambiano e le risposte vecchie smettono di
 * essere raggiungibili, senza dover svuotare nulla a mano.
 */
import fs from "node:fs";
import path from "node:path";
import { config } from "../config.js";

function firmaFile(percorso) {
  try {
    // `bigint: true` dà mtimeNs: la risoluzione al millisecondo di mtimeMs non
    // distingue due scritture ravvicinate, e una voce in cache resterebbe
    // valida su una fonte che nel frattempo è cambiata.
    const info = fs.statSync(percorso, { bigint: true });
    return `${info.mtimeNs}:${info.size}`;
  } catch {
    return "assente";
  }
}

export const firmaKnowledgeBase = () => firmaFile(config.paths.knowledgeBase);
export const firmaDataset = () => firmaFile(config.paths.csv);
export const firmaFonti = () => `${firmaKnowledgeBase()}|${firmaDataset()}`;

/**
 * Un'analisi in cache resta utile solo se il suo grafico esiste ancora:
 * la pulizia periodica può averlo rimosso.
 */
export function graficiPresenti(grafici = []) {
  return grafici.every((url) =>
    fs.existsSync(path.join(config.paths.charts, path.basename(url)))
  );
}
