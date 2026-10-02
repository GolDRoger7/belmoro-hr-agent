# ☕ Chicco — Agente AI ibrido e multi-tool per People & Culture

> Progetto realizzato per il Master in AI ed Agenti AI per il business.
> Caso aziendale: **Caffè Belmoro — Direzione People & Culture (perimetro Italia)**.
> Dataset e knowledge base sono **fittizi**, creati a scopo didattico: non rappresentano
> dati o policy reali di Caffè Belmoro S.p.A.

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
│       └── session/sessionStore.js   # memoria conversazionale lato server
│
├── data_agent/                       # MICROSERVIZIO PYTHON
│   ├── app/main.py                   # FastAPI: /analyze, /schema, /health
│   ├── app/agent.py                  # pandas agent (LangChain) + generazione grafici
│   ├── app/data_cleaning.py          # pulizia deterministica + report
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
./scripts/avvia_tutto.sh          # avvia i 4 servizi, log in logs/
./scripts/avvia_tutto.sh stop     # li ferma tutti
```

### Opzione B — quattro terminali (per vedere i log in diretta)

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

### 8.8 Valori vuoti che non sono dati mancanti
Alla domanda sul turnover per reparto l'agente rispondeva «Customer Care 20%, tutti gli
altri 0%». Causa: aveva applicato `dropna()` anche a `data_cessazione` e
`motivo_cessazione`, che sono vuote **per definizione** su chi è ancora in forza — così
spariva in un colpo solo l'81% della popolazione. La distinzione fra "dato mancante" e
"vuoto che significa qualcosa" è ora esplicita nel prompt e nella descrizione dello schema,
insieme a un controllo di plausibilità obbligatorio prima della risposta finale
(«ho escluso più del 20% delle righe? allora ho filtrato troppo»).

### 8.9 Confronti omogenei e disaggregati fra policy e dati
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

### 8.10 Il grafico come requisito, non come eventualità
Con un modello piccolo capita che l'agente concluda l'analisi senza salvare l'immagine. Il
microservizio verifica l'esistenza del file e, se manca e la domanda ha una dimensione di
confronto, esegue **un secondo passaggio dedicato** che riprende i risultati già calcolati e
produce solo il grafico. Stesso principio sul versante opposto: una risposta che spiega il
metodo senza riportare alcuna cifra viene esplicitamente vietata dal prompt.

### 8.11 Resilienza operativa
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

### 8.12 Sicurezza
Nessuna chiave nel codice: un unico `.env` alla root, letto da `dotenv` (Node) e
`python-dotenv` (Python), escluso dal versionamento. Il `PythonAstREPLTool` è confinato
nel microservizio Python, che non è esposto all'esterno e riceve solo la domanda in
linguaggio naturale, mai codice, dal front end.

---

## 9. API del backend

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/chat` | Turno di conversazione sincrono → `{reply, charts, sources, trace, toolUsed}` |
| `POST` | `/api/chat/stream` | Come sopra, in streaming SSE con gli eventi di ragionamento |
| `GET` | `/api/health` | Stato di OpenAI, ChromaDB e data agent |
| `DELETE` | `/api/sessions/:id` | Azzera la memoria di una conversazione |
| `GET` | `/charts/<file>.png` | Grafico generato dal data agent |

Microservizio Python: `POST /analyze`, `GET /schema`, `GET /health`.

---

## 10. Stack

| Livello | Tecnologia |
|---|---|
| Front end | React 19 · Vite · react-markdown |
| Orchestrazione | Node.js 20 · Express 5 · OpenAI SDK (function calling) |
| Knowledge retrieval | ChromaDB 1.5 (server locale) · `text-embedding-3-small` |
| Analisi dati | Python 3.11 · FastAPI · pandas · LangChain (pandas agent) · matplotlib/seaborn |
| LLM | `gpt-4o-mini` (configurabile da `.env`) |

---

*Progetto didattico. Dati e policy sono interamente inventati.*
