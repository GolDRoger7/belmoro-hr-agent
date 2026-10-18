# ☕ Chicco — Agente AI ibrido e multi-tool per People & Culture

> Progetto realizzato per il Master in AI ed Agenti AI per il business.
> Caso aziendale: **Caffè Belmoro — Direzione People & Culture (perimetro Italia)**.
> Dataset e knowledge base sono **fittizi**, creati a scopo didattico: non rappresentano
> dati o policy reali di Caffè Belmoro S.p.A.

📑 **[Presentazione del progetto (PDF, 16 slide)](Presentazione-Chicco-People-and-Culture.pdf)**

---

## 1. Il problema di business

La funzione People & Culture convive ogni giorno con **due domande di natura opposta**:

| | Domanda tipica | Fonte della risposta | Problema oggi |
|---|---|---|---|
| **Qualitativa** | «Quanti giorni di smart working spettano a chi lavora in IT?» | Manuale delle policy HR (60 pagine) | Si perde tempo a cercare nel PDF, si risponde a memoria, le risposte non sono uniformi |
| **Quantitativa** | «Quale reparto ha il turnover più alto?» | Dataset dell'organico (1.240 dipendenti) | Serve un analista, i dati sono "sporchi", il ciclo domanda→risposta dura giorni |

**Chicco** risponde a entrambe da un'unica chat, **decidendo da solo** quale strumento
usare: nessuna scelta manuale, nessun menu, nessun `if` su parole chiave.

---

## 2. Architettura

```
┌────────────────────────┐
│   FRONT END (React)    │   chat con memoria, typing indicator,
│      localhost:5173    │   rendering markdown + grafici, trace dei tool
└───────────┬────────────┘
            │ POST /api/chat/stream  (SSE)
            ▼
┌────────────────────────────────────────────────────────────┐
│        BACK END — ORCHESTRATORE (Node.js + Express)        │
│                     localhost:3001                         │
│                                                            │
│   ┌──────────────────────────────────────────────────┐     │
│   │  LLM (OpenAI function calling) — ciclo ReAct     │     │
│   │  «Questa domanda è una regola o una misura?»     │     │
│   └───────────┬──────────────────────────┬───────────┘     │
│               │ tool 1                   │ tool 2          │
│               ▼                          ▼                 │
│   cerca_nelle_policy_hr        analizza_dati_dipendenti     │
└───────────────┬──────────────────────────┬─────────────────┘
                │                          │ HTTP POST /analyze
                ▼                          ▼
   ┌────────────────────────┐   ┌──────────────────────────────┐
   │      ChromaDB          │   │  DATA AGENT (Python/FastAPI) │
   │    localhost:8001      │   │        localhost:8000        │
   │  47 chunk della KB HR  │   │  cleaning + pandas agent     │
   │  embedding OpenAI      │   │  matplotlib → PNG            │
   └────────────────────────┘   └──────────────┬───────────────┘
                                               │ salva il grafico
                                               ▼
                                    shared/charts/*.png
                                (serviti dal backend su /charts)
```

### Il cuore del progetto: la decisione autonoma

L'orchestratore ([`backend/src/agent/orchestrator.js`](backend/src/agent/orchestrator.js))
espone all'LLM due funzioni con descrizioni precise e lo lascia scegliere. Sono possibili
quattro esiti, tutti gestiti dallo stesso ciclo:

1. **risposta diretta** — saluti, meta-domande, riformulazioni;
2. **solo RAG** — la domanda riguarda una regola documentale;
3. **solo data agent** — la domanda riguarda una misura sull'organico;
4. **entrambi, in sequenza** — domanda ibrida del tipo *«il nostro gender pay gap rispetta
   l'obiettivo di policy?»*: prima recupera la soglia dal manuale, poi misura il dato reale
   e confronta i due nella risposta finale.

Ogni passo è tracciato e restituito al front end (`trace`), che lo mostra nel pannello
**«Come sono arrivato a questa risposta»** insieme al codice Python realmente eseguito.

---

## 3. Struttura del repository

```
.
├── data/
│   ├── hr_dipendenti_belmoro.csv     # dataset: 1.285 righe (1.240 dopo il cleaning), 25 colonne
│   ├── hr_policy_belmoro.txt         # knowledge base: manuale policy HR + 21 FAQ
│   └── genera_dataset.py             # generatore riproducibile del CSV (seed fisso)
│
├── backend/                          # ORCHESTRATORE (Node.js + Express)
│   └── src/
│       ├── server.js                 # API: /api/chat, /api/chat/stream, /api/health, /charts
│       ├── config.js                 # lettura del .env, nessun segreto nel codice
│       ├── agent/orchestrator.js     # ciclo ReAct + function calling  ← il "cervello"
│       ├── tools/knowledgeBaseTool.js# tool 1: RAG su ChromaDB
│       ├── tools/dataAnalysisTool.js # tool 2: delega HTTP al microservizio Python
│       ├── rag/chunker.js            # chunking structure-aware del manuale
│       ├── rag/chromaStore.js        # client ChromaDB + ricerca semantica
│       ├── rag/openaiClient.js       # client OpenAI + embedding
│       ├── scripts/ingest.js         # indicizzazione della KB  (npm run ingest)
│       ├── session/sessionStore.js   # memoria conversazionale lato server
│       ├── cache/responseCache.js    # cache delle risposte (TTL + firma delle fonti)
│       ├── cache/firmeFonti.js       # impronte di CSV e manuale, condivise
│       ├── cache/redisClient.js      # connessione Redis con degradazione
│       └── maintenance/chartCleanup.js # pulizia periodica dei grafici
│
├── data_agent/                       # MICROSERVIZIO PYTHON
│   ├── app/main.py                   # FastAPI: /analyze, /schema, /health
│   ├── app/agent.py                  # pandas agent (LangChain) + generazione grafici
│   ├── app/data_cleaning.py          # pulizia deterministica + report
│   ├── app/store.py                  # dataset normalizzato su DuckDB
│   ├── app/cleaning_duckdb.py        # pulizia in SQL, senza passare da pandas
│   └── tests/test_parita_pulizia.py  # confronto cella per cella SQL vs pandas
│   ├── app/sandbox.py                # contenimento del codice generato dall'LLM
│   ├── app/config.py                 # lettura del .env condiviso
│   └── requirements.txt
│
├── frontend/                         # INTERFACCIA REACT (Vite)
│   └── src/
│       ├── App.jsx                   # stato della chat, memoria, fasi di caricamento
│       ├── api/chatClient.js         # client SSE verso il backend
│       └── components/               # bolle, badge del tool, grafici, trace, semaforo
│
├── shared/charts/                    # grafici PNG generati a runtime
├── Presentazione-Chicco-People-and-Culture.pdf   # presentazione per la Direzione People & Culture
├── scripts/avvia_tutto.sh            # avvio/arresto dell'intera architettura
├── .env.example                      # template delle variabili d'ambiente
└── .gitignore                        # esclude .env, node_modules, venv, chroma_db, PNG
```

---

## 4. I dati

### 4.1 Dataset — `data/hr_dipendenti_belmoro.csv`

**1.285 righe × 25 colonne** (1.240 dipendenti dopo la rimozione dei duplicati), con
anagrafica, organizzazione (9 dipartimenti, 8 sedi, 4 livelli di inquadramento),
retribuzione (RAL, bonus), performance (rating 1–5, engagement 0–100), formazione,
smart working, ferie, assenze e cessazioni.

Il dataset è **volutamente "sporco"**, per mettere alla prova il data cleaning dell'agente:

| Anomalia | Esempio nel file |
|---|---|
| Righe duplicate | 45 righe replicate |
| Formati data misti | `2019-03-14`, `14/03/2019`, `14-03-2019`, `14.03.2019` |
| Separatori decimali e valuta | `45000`, `45.000,00`, `EUR 45000`, `€ 45000`, `45000.00` |
| Valori mancanti | RAL 4,5%, performance 3,8%, engagement 3%, e-mail 2% |
| Categorie incoerenti | `Vendite` / `vendite` / `  VENDITE ` , `M` / `m` / `Maschio` |
| Valori fuori range | performance `7`, età `-5` e `129`, RAL `9999999`, smart working `45` |
| Marcatori di nullo eterogenei | `""`, `NULL`, `n/d` |
| Incoerenze logiche | dipendenti `Attivo` con data di cessazione valorizzata |

Il file è rigenerabile in modo identico (seed fisso): `python3 data/genera_dataset.py`.

### 4.2 Knowledge base — `data/hr_policy_belmoro.txt`

Manuale delle policy HR in 15 sezioni (~4.000 parole): orario e flessibilità, smart
working, ferie e congedi, welfare, politica retributiva, performance management,
formazione, selezione e onboarding, cessazioni e retention, D&I, sicurezza, trasferte,
codice etico e privacy, più **21 FAQ interne**.

Indicizzazione **structure-aware** ([`chunker.js`](backend/src/rag/chunker.js)): ogni
sezione diventa uno o più chunk con il titolo in testa, **ogni FAQ diventa un chunk
autonomo**. Risultato: 47 chunk (25 policy + 21 FAQ + 1 preambolo), nessuna regola
spezzata a metà.

---

## 5. Installazione

### Prerequisiti

| Componente | Versione | Verifica |
|---|---|---|
| Node.js | ≥ 18.18 (testato su 20.11 e 20.19) | `node -v` |
| Python | ≥ 3.10 (testato su 3.11) | `python3 --version` |
| Chiave API OpenAI | — | [platform.openai.com](https://platform.openai.com/api-keys) |
| Redis | qualsiasi | `redis-cli ping` → `PONG` |

> Redis ospita cache e sessioni condivise. Se non è installato il sistema parte
> lo stesso — cache e memoria restano nel processo e lo script di avvio lo
> segnala — ma per riprodurre il comportamento previsto conviene installarlo:
> `brew install redis` su macOS, `apt install redis-server` su Debian/Ubuntu.

### Step 1 — Clonare e configurare i segreti

```bash
git clone <URL-DEL-REPO>
cd "Tesi - Paolo Savino"
cp .env.example .env
```

Apri `.env` e inserisci la tua chiave:

```dotenv
OPENAI_API_KEY=sk-...
```

> ⚠️ Il file `.env` è escluso dal version control (`.gitignore`) e **non è mai presente
> nel repository**: viene consegnato a parte. Nessuna credenziale è hardcodata nel codice:
> backend, data agent e script di ingestion leggono tutti da questo unico file.

### Step 2 — Backend Node.js

```bash
cd backend
npm install
cd ..
```

### Step 3 — Front end React

```bash
cd frontend
npm install
cd ..
```

### Step 4 — Microservizio Python

```bash
cd data_agent
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..
```

<details>
<summary>Se <code>python3 -m venv</code> fallisce (Python di sistema non adatto)</summary>

Su alcune installazioni macOS il Python disponibile è troppo vecchio o ha librerie di
sistema incompatibili. In quel caso si può usare [`uv`](https://docs.astral.sh/uv/), che
scarica un interprete autonomo:

```bash
brew install uv
uv venv --python 3.11 data_agent/venv
VIRTUAL_ENV=data_agent/venv uv pip install -r data_agent/requirements.txt
```
</details>

---

## 6. Avvio dell'architettura

### Opzione A — script unico (consigliata)

```bash
./scripts/avvia_tutto.sh          # avvia i servizi (Redis incluso), log in logs/
./scripts/avvia_tutto.sh stop     # li ferma tutti
```

Se Redis è già in esecuzione sulla macchina lo script lo riusa invece di
avviarne un altro.

### Opzione B — quattro terminali (per vedere i log in diretta)

**Terminale 0 — Redis**

```bash
redis-server --port 6379
```

**Terminale 1 — ChromaDB**

```bash
data_agent/venv/bin/chroma run --path ./chroma_db --host localhost --port 8001
```

**Terminale 2 — Data agent Python**

```bash
cd data_agent && source venv/bin/activate && uvicorn app.main:app --port 8000
```

**Terminale 3 — Backend orchestratore**

```bash
cd backend && npm start
```

**Terminale 4 — Front end**

```bash
cd frontend && npm run dev
```

### Step obbligatorio — indicizzare la knowledge base

**Una sola volta** (a Chroma già avviato), da un terminale qualsiasi:

```bash
cd backend && npm run ingest
```

Output atteso:

```
📄 Knowledge base: .../data/hr_policy_belmoro.txt
✂️  Chunk generati: 47
   ripartizione: {"preambolo":1,"policy":25,"faq":21}
🧠 Calcolo embedding con text-embedding-3-small...
✅ Indicizzazione completata: 47 chunk nella collection "belmoro_hr_policies"
```

### Verifica

```bash
curl http://localhost:3001/api/health
```

Tutti e tre i pallini in alto nell'interfaccia devono essere verdi. Poi apri
**http://localhost:5173**.

---

## 7. Come provarlo

| Domanda | Strumento atteso | Cosa dimostra |
|---|---|---|
| «Quanti giorni di smart working al mese posso fare se lavoro in IT?» | 📚 RAG | Risposta ancorata alla policy, con citazione della sezione |
| «Che preavviso deve dare un quadro che si dimette?» | 📚 RAG | Recupero preciso da una FAQ |
| «Qual è la RAL media per dipartimento? Mostrami un grafico.» | 📊 Data agent | Cleaning + `groupby` + grafico in chat |
| «Quale reparto ha il turnover più alto?» | 📊 Data agent | Insight manageriale, non solo numeri |
| «Il nostro gender pay gap rispetta l'obiettivo fissato dalla policy?» | 📚 **+** 📊 | Entrambi i tool nello stesso turno: soglia di policy vs dato misurato |
| «E per il Marketing?» (dopo una domanda sui dipartimenti) | 📊 Data agent | La memoria conversazionale risolve il riferimento implicito |

---

## 8. Scelte tecniche e sfide affrontate

### 8.1 Cleaning a due livelli
L'agente LLM da solo non è deterministico: a due esecuzioni della stessa domanda può
pulire i dati in modo diverso, e i numeri cambiano. La pulizia strutturale
(duplicati, date, valuta, categorie, range di dominio) è quindi **codice deterministico**
in [`data_cleaning.py`](data_agent/app/data_cleaning.py), che produce anche un **report
ispezionabile**; all'agente resta la decisione contestuale su come trattare i valori
mancanti residui, che dipende dalla domanda. Determinismo dove serve, autonomia dove
serve davvero.

### 8.2 Il percorso del grafico non lo sceglie l'LLM
Far generare all'LLM il path di salvataggio dell'immagine è fragile (path inventati,
`plt.show()`, grafici multipli). Il backend genera il nome del file, lo inietta nel REPL
Python come variabile `CHART_PATH` insieme a `plt`, `sns`, `pd`, `np`, e il prompt impone
`plt.savefig(CHART_PATH)`. Il servizio verifica poi l'esistenza del file: se manca,
la risposta resta testuale senza rompersi.

### 8.3 Chunking structure-aware invece del taglio a lunghezza fissa
Con uno split a caratteri fissi, la regola *«fino a 12 giorni al mese per IT»* finiva
spezzata fra due chunk e il retrieval restituiva contesti mutili. Segmentando per sezioni
del manuale e per singola FAQ, ogni chunk è un'unità di senso completa.

### 8.4 Descrizioni dei tool come vero "manuale operativo" dell'LLM
La qualità della decisione dipende quasi interamente dalle `description` delle funzioni.
Elencare esplicitamente i domini coperti (*«smart working, ferie, welfare, PIP…»*) e i
casi da escludere (*«NON usarlo per calcoli o medie»*), più regole di arbitraggio nel
system prompt per le domande ibride, ha portato il routing a essere stabile.

### 8.5 Memoria lato server, non lato client
Lo storico vive nel `sessionStore` del backend e il front end trasmette solo il
`sessionId`: il client non può alterare il contesto e il backend controlla la finestra
di memoria (ultimi 20 messaggi).

### 8.6 Streaming degli stati di ragionamento
Un'analisi pandas può richiedere 15–30 secondi. Invece di un generico spinner, il backend
emette via SSE gli eventi `tool_start` / `tool_end` e l'interfaccia mostra la fase reale
(*«L'agente Python sta pulendo i dati ed eseguendo l'analisi…»*).

### 8.7 Valori vuoti che non sono dati mancanti
Alla domanda sul turnover per reparto l'agente rispondeva «Customer Care 20%, tutti gli
altri 0%». Causa: aveva applicato `dropna()` anche a `data_cessazione` e
`motivo_cessazione`, che sono vuote **per definizione** su chi è ancora in forza — così
spariva in un colpo solo l'81% della popolazione. La distinzione fra "dato mancante" e
"vuoto che significa qualcosa" è ora esplicita nel prompt e nella descrizione dello schema,
insieme a un controllo di plausibilità obbligatorio prima della risposta finale
(«ho escluso più del 20% delle righe? allora ho filtrato troppo»).

### 8.8 Confronti omogenei e disaggregati fra policy e dati
Nella domanda ibrida sul gender pay gap il sistema confrontava il gap **grezzo** misurato in
euro con un obiettivo di policy definito sul gap **corretto** a parità di ruolo e livello,
espresso in percentuale: due grandezze diverse messe sullo stesso piano. Stesso difetto
sullo smart working, dove una media unica veniva confrontata con plafond differenziati per
funzione. La soluzione non è nel data agent ma nell'orchestratore: avendo già letto la
policy, è lui a dover formulare la richiesta di analisi **nei termini della soglia** —
stessa unità di misura, stessa definizione, stesso livello di disaggregazione. Sul divario
retributivo è stata inoltre fissata la convenzione Eurostat
(`(media_uomini − media_donne) / media_uomini`), perché usare il denominatore femminile
gonfiava il risultato dal 6,15% al 6,55%.

### 8.9 Il grafico come requisito, non come eventualità
Con un modello piccolo capita che l'agente concluda l'analisi senza salvare l'immagine. Il
microservizio verifica l'esistenza del file e, se manca e la domanda ha una dimensione di
confronto, esegue **un secondo passaggio dedicato** che riprende i risultati già calcolati e
produce solo il grafico. Stesso principio sul versante opposto: una risposta che spiega il
metodo senza riportare alcuna cifra viene esplicitamente vietata dal prompt.

### 8.10 Le istruzioni importanti non si chiedono, si impongono
La lezione più utile dei test: con `gpt-4o-mini` una regola scritta dentro un prompt lungo
viene rispettata *a volte*. Due casi reali, entrambi risolti spostando il vincolo dal prompt
al codice:

- **Grafici a una barra sola.** Alla domanda «e per il Marketing?» l'agente disegnava una
  singola barra isolata, che non comunica nulla. La regola nel prompt veniva seguita in
  modo intermittente. Ora `plt` iniettato nel REPL è un proxy
  (`PyplotConGuardia`) il cui `savefig` **rifiuta** una figura con una sola categoria e
  solleva un errore che spiega come correggere: l'agente legge l'errore come output del
  proprio codice e ridisegna il confronto completo evidenziando il gruppo richiesto.
- **Numeri inventati dopo un'osservazione vuota.** Un blocco che termina con
  un'assegnazione (`media = df.groupby(...).mean()`) non produce output: l'agente non vedeva
  i numeri e, dovendo scrivere la risposta, li inventava — in un caso riportando 36.000 €
  invece di 48.258 €, con cifre prese dalle righe di esempio mostrate nel prompt. Il REPL è
  stato sostituito da `PythonReplConEco`, che non restituisce mai un'osservazione vuota: al
  suo posto arriva l'istruzione a rieseguire il blocco terminandolo con l'espressione da
  osservare. Dopo la correzione il valore è stabile su esecuzioni ripetute.

Entrambi i guardrail sono deterministici e lasciano all'agente la libertà di *come*
correggersi: non irrigidiscono l'autonomia, ne delimitano gli esiti inaccettabili.

### 8.11 I numeri si rileggono dalla fonte
A un follow-up come «e per il Marketing?» l'orchestratore a volte rispondeva riusando la
cifra citata nel proprio messaggio precedente, senza richiamare il data agent. Non è
formalmente un errore, ma è una pessima abitudine per un assistente dati: gli errori si
propagano e il comportamento diventa imprevedibile. Ora una richiesta di metrica su un
gruppo rilancia sempre l'analisi.

### 8.12 Resilienza operativa
Tre problemi emersi avviando davvero l'architettura, non leggendo il codice:
- **Permessi OpenAI in propagazione**: dopo aver abilitato il modello di embedding, l'API ha
  risposto 403 a intermittenza (5 fallimenti su 10 chiamate) per alcuni minuti. Le chiamate
  OpenAI hanno ora riprove con backoff esponenziale su 429, 5xx, errori di rete e su questa
  specifica finestra di propagazione.
- **Riferimento a una collection ricreata**: rilanciando `npm run ingest` a backend acceso,
  la RAG restava rotta fino al riavvio, perché il backend teneva in cache l'id di una
  collection ormai cancellata. Il riferimento ora si rinfresca da solo al primo errore.
- **Processi figli sopravvissuti**: lo script di avvio registrava il PID della subshell e non
  quello del processo reale, lasciando i servizi in ascolto dopo lo stop. Ora usa `exec` sui
  binari diretti e libera comunque le porte.

### 8.13 Sicurezza
Nessuna chiave nel codice: un unico `.env` alla root, letto da `dotenv` (Node) e
`python-dotenv` (Python), escluso dal versionamento. Il `PythonAstREPLTool` è confinato
nel microservizio Python, che non è esposto all'esterno e riceve solo la domanda in
linguaggio naturale, mai codice, dal front end.

---

## 9. Interventi dopo la revisione tecnica

Sette segnalazioni raccolte in revisione, e come sono state chiuse.

### 9.1 I grafici non si accumulano più
Ogni analisi scrive un PNG nella cartella condivisa. Un task in background interno
al backend ([`chartCleanup.js`](backend/src/maintenance/chartCleanup.js)) elimina
le immagini più vecchie di `CHARTS_TTL_ORE` (24 di default), all'avvio e poi ogni
ora. È un timer nel processo anziché un cron di sistema perché il backend conosce
già il percorso dei grafici e vive quanto il servizio: nessuna configurazione
esterna da tenere allineata. La pulizia si può anche invocare a mano
(`POST /api/maintenance/charts`), oppure affidare al cron:

```bash
find ./shared/charts -name "*.png" -mmin +1440 -delete
```

### 9.2 Cache delle risposte
Domande identiche o quasi non pagano due volte il costo dell'analisi. La cache sta
a livello di **turno** e non dei singoli tool, per un motivo preciso: l'orchestratore
riformula la domanda prima di passarla, e a parità di domanda dell'utente la
riformulazione cambia («per dipartimento» / «per tutti i dipartimenti»), quindi una
cache più in basso non farebbe quasi mai centro. La chiave combina la domanda
normalizzata (minuscole, senza accenti né punteggiatura), un'impronta della
conversazione — così «e per il Marketing?» non eredita mai la risposta di un'altra
chat — e la firma delle fonti: se il CSV o il manuale cambiano, le voci che ne
derivano smettono da sole di essere raggiungibili. Misurato: **13,9 s al primo giro,
risposta immediata ai successivi**. Restano in cache solo i turni riusciti, e una
voce il cui grafico è stato nel frattempo ripulito viene scartata.

### 9.3 Il dataset vive su DuckDB
Leggere e ripulire il CSV a ogni avvio regge con 1.240 righe, non con qualche
centinaio di migliaia. Il dataset normalizzato viene ora materializzato una volta
sola in una tabella DuckDB ([`store.py`](data_agent/app/store.py)), ricostruita solo
quando cambia la firma del CSV. Sopra `MAX_RIGHE_IN_MEMORIA` il comportamento
degrada in modo esplicito: l'agente riceve un **campione** come dataframe e uno
strumento `interroga_sql` in sola lettura per i conti sull'intera popolazione, con
l'aggregazione spinta nel motore. Sotto la soglia nulla cambia e le analisi restano
quelle verificate.

### 9.4 Il troncamento del risultato non rompe più il JSON
`JSON.stringify(esito).slice(0, 12000)` tagliava la stringa già serializzata, e
spezzava la sintassi proprio sui risultati più grossi — quelli che contano — con il
modello che riceveva una graffa o una virgoletta a metà. Ora si accorciano i
**singoli campi prima** di serializzare, con una riduzione finale ai soli campi
indispensabili se il totale resta oltre il limite. Verificato su payload da 40.000
caratteri, con accenti e virgolette: il JSON resta sempre valido e dichiara quanto
ha omesso.

### 9.5 Contenimento del codice generato
L'agente traduce la domanda dell'utente in Python eseguito sull'host: è la
funzionalità centrale ed è anche la superficie d'attacco. Il contenimento
([`sandbox.py`](data_agent/app/sandbox.py)) è su due livelli indipendenti:

- **analisi statica** del codice prima dell'esecuzione: import fuori whitelist,
  `eval`/`exec`/`open`/`__import__`/`getattr` e accesso agli attributi dunder —
  la via classica per risalire da un oggetto qualsiasi fino a `os` — vengono
  rifiutati con un messaggio che l'agente legge come output del proprio codice e
  che gli spiega come riformulare;
- **builtins ridotti** nello spazio di esecuzione, con un `__import__` che conosce
  solo i moduli dell'analisi dati.

Provato dal vivo: a una richiesta costruita per farglielo fare, il modello ha
tentato `import os; os.listdir(".")` cinque volte e il sandbox lo ha bloccato ogni
volta, registrando il tentativo nel log. Restano fuori dal perimetro i consumi di
risorse, coperti dal tetto di iterazioni e dal budget di tempo; in produzione si
aggiungerebbe l'esecuzione in un sottoprocesso con `setrlimit`.

### 9.6 Timeout allineati e verificati all'avvio
Il rischio era reale e peggiore di quanto sembrasse: oltre all'analisi (180 s)
poteva scattare il secondo passaggio sul grafico, per un tetto effettivo di 360 s
contro i 240 s di attesa di Node. Ora il data agent dichiara il proprio budget
(`BUDGET_ANALISI_S` + `BUDGET_GRAFICO_S` = 195 s) in `/health`, e il backend lo
confronta con il proprio timeout all'accensione:

```
timeout        Node 260s > data agent 195s (margine 65s)
```

Se il margine scende sotto i 10 secondi, l'avvio stampa un avviso con il valore da
impostare.

### 9.7 Errori Chroma riconosciuti per classe
Il recupero dopo una reindicizzazione si appoggiava al testo del messaggio
d'errore: basta un cambio di versione o di lingua e la rete di sicurezza salta in
silenzio. Ora si parte dalle classi esportate dal client (`ChromaNotFoundError`,
`InvalidCollectionError`) e dallo stato HTTP, tenendo il confronto sul testo solo
come ultima rete.

### 9.8 Lo stato non era condiviso fra istanze
La cache del punto 9.2 viveva nella memoria del processo: due repliche del
backend non si sarebbero viste a vicenda e ogni riavvio azzerava tutto. Stesso
difetto, più insidioso, per la memoria conversazionale: dietro un bilanciatore
la seconda domanda di un utente può finire su un'istanza diversa dalla prima,
che tratterebbe «e per il Marketing?» come una domanda isolata.

Ora cache e sessioni hanno **due depositi dietro la stessa interfaccia**: senza
`REDIS_URL` restano in memoria, con `REDIS_URL` vivono in Redis e sono condivise.
Nella configurazione consegnata `REDIS_URL` è valorizzata, quindi il percorso
attivo è quello condiviso.
Il punto delicato è stato il comportamento in avaria. Alla prima prova, spegnendo
Redis a backend acceso, la richiesta è rimasta **appesa per sempre**: il client
accoda i comandi mentre la connessione è giù e la promise non si risolve mai. La
correzione è su tre livelli — coda offline disattivata, tentativi di riconnessione
limitati e soprattutto un **tetto di tempo su ogni operazione**, oltre il quale
si prosegue con la memoria locale.

Verificato: con Redis attivo e il backend riavviato da zero la risposta torna
dalla cache in **0,1 s**; con Redis spento l'agente risponde comunque in 7,4 s,
e `/health` dichiara `redis: pronto false`.

### 9.9 La pulizia non carica più il file in memoria
Lo store DuckDB del punto 9.3 risolveva la lettura ma non la costruzione: il CSV
veniva comunque materializzato in un DataFrame pandas per essere ripulito, e solo
dopo scritto nella tabella. Il picco di memoria restava proporzionale alla
dimensione del file, cioè il problema che lo store doveva risolvere.

La normalizzazione è ora **una query** ([`cleaning_duckdb.py`](data_agent/app/cleaning_duckdb.py)):
DuckDB legge il CSV in streaming con `read_csv`, applica trim, deduplica,
normalizzazione delle categorie, conversione degli importi con separatori misti,
parsing delle quattro forme di data, controlli di range e colonne derivate, e
scrive la tabella con un `CREATE TABLE AS SELECT`. In Python tornano solo i
conteggi del report. Misurato con `tracemalloc`: il picco di allocazioni Python
durante la costruzione passa da **1,2 MB a 0,0 MB** sul dataset della demo —
differenza che su mezzo milione di righe diventa centinaia di megabyte, con in
più la possibilità di DuckDB di riversare su disco quando la memoria non basta.

Riscrivere regole di dominio in un altro linguaggio è però il momento in cui si
introducono differenze silenziose: una data interpretata diversamente, un
separatore decimale, un duplicato tenuto invece che scartato. Nessuna fa fallire
il programma, tutte cambiano i numeri. Per questo
[`data_cleaning.py`](data_agent/app/data_cleaning.py) resta nel progetto con due
ruoli espliciti: è la fonte unica delle regole di dominio, che la versione SQL
importa invece di riscriverle, ed è l'**oracolo del test di parità**
([`tests/test_parita_pulizia.py`](data_agent/tests/test_parita_pulizia.py)), che
confronta le due implementazioni cella per cella sul dataset reale.

```bash
data_agent/venv/bin/python data_agent/tests/test_parita_pulizia.py
# Parità verificata: la pulizia in SQL e quella pandas producono lo stesso dataset.
```

### 9.10 Un difetto latente trovato verificando il resto
Collaudando le modifiche qui sopra, una domanda già vista — «quale reparto ha il
turnover più alto?» — ha smesso di produrre il grafico. Nel log del data agent
otto tentativi identici, tutti con lo stesso errore:

```
NameError: name 'turnover_per_dipartimento' is not defined
```

Il codice però era corretto: la variabile veniva assegnata due righe sopra e
usata dentro una list comprehension. La causa sta in come `exec` tratta due
spazi dei nomi distinti: le assegnazioni finiscono nei *locals*, ma una
comprehension apre un proprio scope e cerca i nomi nei *globals*, dove quella
variabile non c'era. Il difetto era presente da sempre e si vedeva solo quando
il modello scriveva una comprehension che riusa una variabile — cosa che faceva
ogni volta che doveva evidenziare una barra nel grafico.

L'agente non falliva in modo visibile: ritentava lo stesso blocco fino a
esaurire il budget, e l'utente riceveva una risposta corretta ma senza grafico.
La correzione è una riga — un solo spazio dei nomi condiviso fra `globals` e
`locals` — con l'avvertenza che Pydantic copia i dizionari passati al
costruttore, quindi l'allineamento va rifatto dopo. Dopo la modifica: grafico
presente e **zero `NameError`** nel log.

## 10. API del backend

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/chat` | Turno di conversazione sincrono → `{reply, charts, sources, trace, toolUsed}` |
| `POST` | `/api/chat/stream` | Come sopra, in streaming SSE con gli eventi di ragionamento |
| `GET` | `/api/health` | Stato di OpenAI, ChromaDB e data agent |
| `DELETE` | `/api/sessions/:id` | Azzera la memoria di una conversazione |
| `POST` | `/api/maintenance/charts` | Esegue subito la pulizia dei grafici scaduti |
| `GET` | `/charts/<file>.png` | Grafico generato dal data agent |

Microservizio Python: `POST /analyze`, `GET /schema`, `GET /health`.

---

## 11. Stack

| Livello | Tecnologia |
|---|---|
| Front end | React 19 · Vite · react-markdown |
| Orchestrazione | Node.js 20 · Express 5 · OpenAI SDK (function calling) |
| Knowledge retrieval | ChromaDB 1.5 (server locale) · `text-embedding-3-small` |
| Analisi dati | Python 3.11 · FastAPI · DuckDB (pulizia in SQL) · pandas · LangChain (pandas agent) · matplotlib/seaborn |
| Stato condiviso | Redis per cache e sessioni; memoria del processo come fallback automatico |
| LLM | `gpt-4o-mini` (configurabile da `.env`) |

---

*Progetto didattico. Dati e policy sono interamente inventati.*
