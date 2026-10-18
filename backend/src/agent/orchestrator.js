/**
 * ORCHESTRATORE - il cervello decisionale del sistema.
 *
 * Implementa un ciclo ReAct (Reason + Act) con il function calling nativo di
 * OpenAI: ad ogni giro il modello osserva la conversazione e decide se
 *   a) rispondere direttamente (saluti, chiarimenti, meta-domande),
 *   b) invocare il tool RAG sulle policy documentali,
 *   c) delegare l'analisi numerica all'agente Python,
 *   d) invocare entrambi, quando la domanda è ibrida (regola + misura).
 *
 * Il backend non decide con if/else su parole chiave: la scelta del tool è
 * dell'LLM ed è tracciata passo passo per essere ispezionabile dal front end.
 */
import { config } from "../config.js";
import { chatCompletion } from "../rag/openaiClient.js";
import { cercaNellePolicyHr, knowledgeBaseToolSchema } from "../tools/knowledgeBaseTool.js";
import { analizzaDatiDipendenti, dataAnalysisToolSchema } from "../tools/dataAnalysisTool.js";
import { chiaveCache, leggiDallaCache, scriviInCache, normalizzaTesto } from "../cache/responseCache.js";
import { firmaFonti, graficiPresenti } from "../cache/firmeFonti.js";

const MAX_CARATTERI_CAMPO = 6000;
const MAX_CARATTERI_TOTALI = 12000;

/** Accorcia un testo dichiarando quanto è stato omesso. */
function accorcia(testo, massimo) {
  if (typeof testo !== "string" || testo.length <= massimo) return testo;
  return `${testo.slice(0, massimo)}\n[...troncato: ${testo.length - massimo} caratteri omessi]`;
}

/**
 * Prepara il risultato di un tool da rimandare al modello.
 *
 * Tagliare a lunghezza fissa la STRINGA già serializzata spezza la sintassi
 * JSON proprio sui risultati più grossi — cioè quelli che contano — e il
 * modello riceve una graffa o una virgoletta a metà. Qui si accorciano invece i
 * singoli campi PRIMA di serializzare: il JSON resta sempre strutturalmente
 * valido e dichiara apertamente che cosa è stato tagliato.
 */
function perIlModello(esito) {
  const compatto = { ...esito };

  compatto.summary = accorcia(compatto.summary, MAX_CARATTERI_CAMPO);
  compatto.answer = accorcia(compatto.answer, MAX_CARATTERI_CAMPO);
  compatto.cleaning_report = accorcia(compatto.cleaning_report, 1200);

  if (Array.isArray(compatto.code_steps)) {
    compatto.code_steps = compatto.code_steps.slice(0, 6).map((c) => accorcia(String(c), 1500));
  }
  if (Array.isArray(compatto.sources)) {
    compatto.sources = compatto.sources.map((fonte) => ({
      ...fonte,
      preview: accorcia(fonte.preview, 400),
    }));
  }

  const serializzato = JSON.stringify(compatto);
  if (serializzato.length <= MAX_CARATTERI_TOTALI) return serializzato;

  // Ultima riduzione: si tiene solo ciò che serve a comporre la risposta.
  return JSON.stringify({
    summary: accorcia(compatto.summary ?? compatto.answer ?? "", 4000),
    chart_url: compatto.chart_url ?? null,
    rows_analyzed: compatto.rows_analyzed ?? null,
    nota: "payload ridotto: i campi secondari sono stati omessi per limiti di contesto",
  });
}

const MAX_GIRI = 5;

/**
 * Riconosce una risposta che AFFERMA qualcosa di verificabile.
 *
 * Il system prompt vieta di rispondere con numeri o soglie senza aver
 * interrogato uno strumento, ma un divieto scritto non è una garanzia: ogni
 * tanto il modello risponde lo stesso, e una cifra inventata è indistinguibile
 * da una misurata per chi legge. Qui si controlla il testo: se contiene cifre o
 * percentuali e nessuno strumento è stato usato, la risposta non vale.
 */
function affermaDatiDaVerificare(testo) {
  return /\d/.test(testo ?? "");
}

const TOOLS = [knowledgeBaseToolSchema, dataAnalysisToolSchema];

const IMPLEMENTAZIONI = {
  cerca_nelle_policy_hr: cercaNellePolicyHr,
  analizza_dati_dipendenti: analizzaDatiDipendenti,
};

/**
 * Rete di sicurezza: anche con il prompt più chiaro, l'LLM può inserire un
 * markdown di immagine verso il PNG. Il grafico è già renderizzato dal front end
 * come allegato strutturato, quindi lo rimuoviamo dal testo.
 */
function ripulisciRisposta(testo) {
  return (testo ?? "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")                 // ![alt](url)
    .replace(/\[([^\]]*)\]\((?:sandbox:)?\/charts\/[^)]*\)/g, "$1") // [testo](/charts/x.png)
    .replace(/^\s*(?:Di seguito|Ecco)\b.*grafico.*$/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const SYSTEM_PROMPT = `Sei "Chicco", l'assistente AI della funzione People & Culture del Caffè Belmoro.
Supporti HR business partner e responsabili di funzione con due fonti di verità distinte,
accessibili solo tramite i tuoi strumenti.

## Come scegliere lo strumento
- Domande su REGOLE, PROCEDURE, DIRITTI, SOGLIE DI POLICY ("quanti giorni di smart working
  posso fare", "come funziona la revisione salariale", "che preavviso serve per dimettersi")
  -> usa "cerca_nelle_policy_hr".
- Domande su MISURE E FATTI del nostro organico ("qual è la RAL media", "quale reparto ha
  più turnover", "mostrami la distribuzione della performance", "com'è andato il turnover
  nel tempo") -> usa "analizza_dati_dipendenti".
- Domande IBRIDE che confrontano la regola con la realtà ("rispettiamo la policy sullo smart
  working?", "il nostro gender pay gap è in linea con l'obiettivo aziendale?") -> usa PRIMA
  "cerca_nelle_policy_hr" per la soglia di policy e POI "analizza_dati_dipendenti" per il dato
  misurato, quindi confronta i due nella risposta finale.
  In questo caso la richiesta che passi al data agent NON è la domanda dell'utente così com'è:
  è una richiesta che devi costruire tu a partire dalla definizione letta nella policy, perché
  misuri esattamente la stessa grandezza. Esempio: se la policy fissa l'obiettivo sul "gender
  pay gap corretto a parità di ruolo, livello e anzianità, sotto il 3%", chiedi al data agent
  "calcola il divario retributivo percentuale fra uomini e donne per ciascun livello di
  inquadramento, oltre al divario grezzo complessivo", non un generico "calcola il gender pay
  gap". Riporta sempre nell'unità della policy (di norma una percentuale).
  Se la soglia di policy è DIFFERENZIATA per gruppo (funzione, livello, sede, tipo di
  contratto), chiedi al data agent la misura DISAGGREGATA su quel gruppo e non la media
  complessiva: una media unica confrontata con soglie diverse non dice nulla. Esempio: i
  plafond di smart working valgono 10 giorni per gli impiegati, 12 per l'IT, 18 per i full
  remote e 4 per le mansioni di sito in Produzione, quindi la richiesta corretta è "calcola
  la media e il 90esimo percentile dei giorni di smart working mensili per dipartimento",
  così da confrontare ogni funzione con il proprio plafond.
- Se la domanda riguarda UN SOLO gruppo (un dipartimento, una sede, un livello, un tipo di
  contratto), non chiedere al data agent il valore isolato di quel gruppo: chiedi la metrica
  per TUTTI i gruppi di quella dimensione, specificando quale va evidenziato. Esempio: a
  "e per il Marketing?" corrisponde la richiesta "calcola la RAL media per tutti i
  dipartimenti, evidenziando il Marketing nel grafico". Nella risposta poi rispondi
  puntualmente sul gruppo chiesto, citando come si colloca rispetto agli altri.
- Rispondi senza strumenti solo per saluti, ringraziamenti, richieste di chiarimento sulle tue
  capacità, o quando l'utente ti chiede di ripetere o spiegare meglio qualcosa che hai già
  detto senza chiedere un taglio nuovo.
- NEL DUBBIO, USA UNO STRUMENTO. Non dichiarare mai di non poter rispondere, né rimandare
  l'utente al manuale o all'HR business partner, prima di aver effettivamente interrogato la
  knowledge base o i dati: sei tu ad avere accesso a quelle fonti. "Non lo so" è una risposta
  legittima solo dopo che uno strumento ha cercato e non ha trovato.
- Non ricavare MAI un numero dai tuoi messaggi precedenti. Se un follow-up chiede una metrica
  su un gruppo ("e per il Marketing?", "e a Milano?"), rilancia l'analisi con il data agent
  anche se quel valore era già comparso: i dati si rileggono dalla fonte, non si riciclano
  dal testo già scritto.

## Regole di risposta
- Non inventare MAI numeri, soglie o regole: ogni dato deve provenire da un tool. Questo vale
  anche per i conteggi (quanti dipartimenti, quante sedi, quante righe): se non te l'ha detto
  un tool, non scriverlo.
- OMOGENEITÀ DEL CONFRONTO: quando metti a confronto un dato misurato con una soglia di
  policy, verifica che le due grandezze siano davvero confrontabili (stessa unità di
  misura e stessa definizione). Se non lo sono — per esempio una soglia espressa in
  percentuale contro un valore misurato in euro, o un obiettivo definito "a parità di
  ruolo e livello" contro un dato grezzo — dichiaralo apertamente prima di trarre
  conclusioni, e preferisci la grandezza omogenea se il tool l'ha calcolata.
- Se un tool fallisce, spiega in modo semplice cosa non ha funzionato e cosa può fare l'utente.
- Rispondi sempre in italiano, in markdown, con un registro professionale e sintetico da
  business partner HR.
- Quando il tool "analizza_dati_dipendenti" risponde, RIPORTA la sua sintesi mantenendone la
  struttura (Risposta sintetica / Dettaglio / Insight per People & Culture / Nota metodologica).
  Puoi accorciarla, non riscriverla come elenco piatto: l'insight manageriale e la nota
  metodologica sono il valore per chi legge.
- Il grafico viene mostrato automaticamente sotto la risposta: NON descriverlo, NON scrivere
  "di seguito il grafico" e NON inserire mai markdown di immagini o link al file .png.
- Quando usi le policy, mantieni il riferimento alla sezione del manuale.
- Ricorda a chi legge, quando pertinente, che i dati individuali vanno trattati in forma
  aggregata secondo la policy privacy HR.`;

/**
 * Esegue un turno di conversazione.
 * @param {Array<{role:string, content:string}>} storico messaggi precedenti (memoria)
 * @param {string} messaggio nuovo messaggio dell'utente
 * @param {(evento:object)=>void} [onStep] callback opzionale di tracciamento
 */
/**
 * Chiave della cache di turno.
 *
 * Non basta la domanda: "e per il Marketing?" significa cose diverse a seconda
 * di che cosa è stato chiesto prima. Nella chiave entra quindi anche
 * un'impronta della conversazione, così due utenti che aprono la chat e fanno
 * la stessa domanda condividono la risposta, mentre un follow-up non eredita
 * mai quella di un'altra conversazione.
 *
 * La cache di turno sta QUI e non nei singoli tool perché è l'orchestratore a
 * riformulare la domanda prima di passarla: a parità di domanda dell'utente la
 * riformulazione cambia ("per dipartimento" / "per tutti i dipartimenti"), e una
 * cache più in basso non farebbe mai centro.
 */
function chiaveTurno(storico, messaggio) {
  const contesto = storico.map((m) => `${m.role}:${normalizzaTesto(m.content)}`).join("|");
  return chiaveCache("turno", `${contesto}>>${messaggio}`, firmaFonti());
}

export async function eseguiTurno(storico, messaggio, onStep = () => {}) {
  const chiave = config.cache.attiva ? chiaveTurno(storico, messaggio) : null;

  if (chiave) {
    const inCache = await leggiDallaCache(chiave);
    if (inCache && graficiPresenti(inCache.charts)) {
      const traccia = inCache.trace.map((passo) => ({
        ...passo,
        cached: true,
        detail: `${passo.detail} · risposta riusata dalla cache`,
      }));
      traccia.forEach((passo) => onStep({ type: "tool_end", ...passo }));
      return { ...inCache, trace: traccia, fromCache: true };
    }
  }

  const messaggi = [
    { role: "system", content: SYSTEM_PROMPT },
    ...storico.map(({ role, content }) => ({ role, content })),
    { role: "user", content: messaggio },
  ];

  const traccia = [];
  const charts = [];
  let sources = [];
  let ultimoToolUsato = null;

  // Vale per UN SOLO giro: imporre lo strumento a oltranza impedirebbe al
  // modello di chiudere, perché ogni risposta finale verrebbe rifiutata.
  let imponiStrumento = false;
  let recuperoGiaFatto = false;

  for (let giro = 0; giro < MAX_GIRI; giro += 1) {
    const risposta = await chatCompletion(
      {
        model: config.openai.chatModel,
        temperature: 0.2,
        messages: messaggi,
        tools: TOOLS,
        tool_choice: imponiStrumento ? "required" : "auto",
      },
      "orchestratore"
    );
    imponiStrumento = false;

    const scelta = risposta.choices[0].message;

    // Risposta con cifre dentro ma NESSUNO strumento usato in tutto il turno:
    // si rifà il giro obbligando un tool, invece di consegnare numeri non
    // verificati. La condizione sulla traccia vuota è essenziale: senza, il
    // controllo scatterebbe anche sulla risposta finale che riassume analisi
    // già svolte, e le farebbe rifare da capo.
    if (
      !scelta.tool_calls?.length &&
      traccia.length === 0 &&
      !recuperoGiaFatto &&
      affermaDatiDaVerificare(scelta.content)
    ) {
      console.warn("⚠️  Risposta con dati ma senza strumenti: ripeto il giro imponendo un tool.");
      recuperoGiaFatto = true;
      imponiStrumento = true;
      continue;
    }

    messaggi.push(scelta);

    // Nessun tool richiesto: è la risposta finale.
    if (!scelta.tool_calls?.length) {
      const esitoFinale = {
        reply: ripulisciRisposta(scelta.content),
        charts,
        sources,
        trace: traccia,
        toolUsed: ultimoToolUsato,
        usage: risposta.usage,
      };
      // Si memorizzano solo i turni andati a buon fine: un errore di un tool non
      // deve restare appiccicato alla domanda per la mezz'ora successiva.
      const tuttoRiuscito = traccia.every((passo) => passo.status === "ok");
      if (chiave && tuttoRiuscito) await scriviInCache(chiave, esitoFinale, config.cache.ttlDatiMs);
      return esitoFinale;
    }

    // L'LLM ha deciso di agire: eseguiamo i tool richiesti.
    for (const chiamata of scelta.tool_calls) {
      const nome = chiamata.function.name;
      let argomenti = {};
      try {
        argomenti = JSON.parse(chiamata.function.arguments || "{}");
      } catch {
        argomenti = {};
      }

      const passo = { step: traccia.length + 1, tool: nome, args: argomenti, status: "running" };
      traccia.push(passo);
      onStep({ type: "tool_start", ...passo });

      const inizio = Date.now();
      try {
        const esito = await IMPLEMENTAZIONI[nome](argomenti);
        ultimoToolUsato = nome;

        if (esito.chart_url) charts.push(esito.chart_url);
        if (esito.sources) sources = sources.concat(esito.sources);

        passo.status = "ok";
        passo.ms = Date.now() - inizio;
        const daCache = esito.from_cache ? " · risposta riusata dalla cache" : "";
        passo.detail =
          (nome === "cerca_nelle_policy_hr"
            ? `${esito.sources?.length ?? 0} passaggi recuperati da ChromaDB`
            : `${esito.rows_analyzed ?? "?"} righe analizzate${esito.chart_url ? ", grafico generato" : ""}`) + daCache;
        passo.cached = Boolean(esito.from_cache);
        if (esito.code_steps?.length) passo.code = esito.code_steps;

        messaggi.push({
          role: "tool",
          tool_call_id: chiamata.id,
          content: perIlModello(esito),
        });
      } catch (errore) {
        passo.status = "error";
        passo.ms = Date.now() - inizio;
        passo.detail = errore.message;
        messaggi.push({
          role: "tool",
          tool_call_id: chiamata.id,
          content: JSON.stringify({ errore: errore.message }),
        });
      }
      onStep({ type: "tool_end", ...passo });
    }
  }

  return {
    reply:
      "Non sono riuscito a completare l'analisi entro il numero massimo di passaggi. " +
      "Prova a formulare la domanda in modo più circoscritto.",
    charts,
    sources,
    trace: traccia,
    toolUsed: ultimoToolUsato,
  };
}
