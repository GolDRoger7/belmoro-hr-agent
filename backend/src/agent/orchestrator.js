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

const MAX_GIRI = 5;

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
- Rispondi senza strumenti solo per saluti, ringraziamenti, richieste di chiarimento sulle tue
  capacità o riformulazioni di quanto hai già detto in questa conversazione.

## Regole di risposta
- Non inventare MAI numeri, soglie o regole: ogni dato deve provenire da un tool.
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
export async function eseguiTurno(storico, messaggio, onStep = () => {}) {
  const messaggi = [
    { role: "system", content: SYSTEM_PROMPT },
    ...storico.map(({ role, content }) => ({ role, content })),
    { role: "user", content: messaggio },
  ];

  const traccia = [];
  const charts = [];
  let sources = [];
  let ultimoToolUsato = null;

  for (let giro = 0; giro < MAX_GIRI; giro += 1) {
    const risposta = await chatCompletion(
      {
        model: config.openai.chatModel,
        temperature: 0.2,
        messages: messaggi,
        tools: TOOLS,
        tool_choice: "auto",
      },
      "orchestratore"
    );

    const scelta = risposta.choices[0].message;
    messaggi.push(scelta);

    // Nessun tool richiesto: è la risposta finale.
    if (!scelta.tool_calls?.length) {
      return {
        reply: ripulisciRisposta(scelta.content),
        charts,
        sources,
        trace: traccia,
        toolUsed: ultimoToolUsato,
        usage: risposta.usage,
      };
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
        passo.detail =
          nome === "cerca_nelle_policy_hr"
            ? `${esito.sources?.length ?? 0} passaggi recuperati da ChromaDB`
            : `${esito.rows_analyzed ?? "?"} righe analizzate${esito.chart_url ? ", grafico generato" : ""}`;
        if (esito.code_steps?.length) passo.code = esito.code_steps;

        messaggi.push({
          role: "tool",
          tool_call_id: chiamata.id,
          content: JSON.stringify(esito).slice(0, 12000),
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
