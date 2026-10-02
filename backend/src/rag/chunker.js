/**
 * Chunking "structure-aware" della knowledge base HR.
 *
 * Il documento è strutturato in sezioni numerate e in una sezione finale di FAQ.
 * Invece di tagliare il testo ogni N caratteri (che spezzerebbe le regole a metà),
 * segmentiamo per unità semantiche:
 *   - una sezione numerata -> uno o più chunk, con il titolo ripetuto in testa;
 *   - una FAQ (coppia domanda/risposta) -> un chunk autonomo.
 * Questo migliora nettamente la precisione del retrieval su domande operative.
 */

const MAX_CHARS = 1200;
const OVERLAP_CHARS = 150;

/**
 * Ripulisce il testo di un chunk dalle righe puramente decorative del documento
 * (cornici di "=" e "-"): non portano significato, inquinano l'embedding e
 * rendono illeggibile l'anteprima della fonte mostrata all'utente.
 */
function pulisciTesto(testo) {
  return testo
    .split("\n")
    .filter((riga) => !/^\s*[=\-_*]{6,}\s*$/.test(riga))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Ritaglia la coda di sovrapposizione a partire da un confine di parola. */
function codaPulita(testo) {
  const coda = testo.slice(-OVERLAP_CHARS);
  const daFrase = coda.search(/(?<=[.:;!?])\s+/);
  if (daFrase !== -1 && daFrase < OVERLAP_CHARS - 40) return coda.slice(daFrase).trim();
  const daParola = coda.search(/\s/);
  return daParola !== -1 ? coda.slice(daParola + 1) : coda;
}

/** Divide un blocco troppo lungo in sotto-blocchi con sovrapposizione. */
function splitLungo(testo) {
  if (testo.length <= MAX_CHARS) return [testo];

  const paragrafi = testo.split(/\n\s*\n/);
  const blocchi = [];
  let corrente = "";

  for (const paragrafo of paragrafi) {
    if ((corrente + "\n\n" + paragrafo).length > MAX_CHARS && corrente) {
      blocchi.push(corrente.trim());
      corrente = `(...continua) ${codaPulita(corrente)}\n\n${paragrafo}`;
    } else {
      corrente = corrente ? `${corrente}\n\n${paragrafo}` : paragrafo;
    }
  }
  if (corrente.trim()) blocchi.push(corrente.trim());
  return blocchi;
}

/**
 * @param {string} raw contenuto del file di knowledge base
 * @param {string} fonte nome del file, salvato nei metadati per la citazione
 */
export function chunkKnowledgeBase(raw, fonte) {
  const testo = raw.replace(/\r\n/g, "\n");
  const chunks = [];

  // 1) Le sezioni sono delimitate da righe di trattini seguite dal titolo.
  const regexSezione = /^-{20,}\n(.+?)\n-{20,}$/gm;
  const titoli = [];
  let match;
  while ((match = regexSezione.exec(testo)) !== null) {
    titoli.push({ titolo: match[1].trim(), inizio: match.index, fineHeader: regexSezione.lastIndex });
  }

  if (titoli.length === 0) {
    // fallback: documento senza struttura riconoscibile
    return splitLungo(testo).map((text, i) => ({
      id: `chunk-${i}`,
      text: pulisciTesto(text),
      metadata: { sezione: "Documento", fonte, tipo: "testo" },
    }));
  }

  // Preambolo (intestazione + avvertenza) come chunk a sé.
  const preambolo = testo.slice(0, titoli[0].inizio).trim();
  if (preambolo.length > 80) {
    chunks.push({
      id: "sezione-0-0",
      text: pulisciTesto(preambolo),
      metadata: { sezione: "Intestazione del manuale", fonte, tipo: "preambolo" },
    });
  }

  titoli.forEach((sezione, indice) => {
    const fine = indice + 1 < titoli.length ? titoli[indice + 1].inizio : testo.length;
    const corpo = testo.slice(sezione.fineHeader, fine).trim();
    if (!corpo) return;

    const isFaq = /FAQ/i.test(sezione.titolo);

    if (isFaq) {
      // 2) Ogni coppia D:/R: diventa un chunk indipendente.
      const coppie = corpo.split(/\n(?=D:\s)/).map((c) => c.trim()).filter(Boolean);
      coppie.forEach((coppia, i) => {
        const pulita = coppia.replace(/={20,}[\s\S]*$/, "").trim();
        if (pulita.length < 25) return;
        chunks.push({
          id: `faq-${i}`,
          text: pulisciTesto(`FAQ People & Culture\n${pulita}`),
          metadata: { sezione: sezione.titolo, fonte, tipo: "faq" },
        });
      });
      return;
    }

    splitLungo(corpo).forEach((blocco, i) => {
      chunks.push({
        id: `sezione-${indice + 1}-${i}`,
        text: pulisciTesto(`${sezione.titolo}\n\n${blocco}`),
        metadata: { sezione: sezione.titolo, fonte, tipo: "policy" },
      });
    });
  });

  return chunks;
}
