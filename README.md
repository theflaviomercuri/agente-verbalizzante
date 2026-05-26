# Agente Verbalizzante

Sistema di generazione automatica di verbali di riunione a partire da trascrizioni audio/testo. Converte una trascrizione grezza in un documento DOCX formattato, passando per un JSON strutturato come stadio intermedio verificabile. Include un knowledge base persistente che apprende dai feedback e un ciclo di revisione che aggiorna automaticamente il thesaurus.

La pipeline è progettata per **minimizzare l'uso del modello LLM**: tutte le operazioni strutturali (parsing, validazione, generazione DOCX, diff, reverse-mapping) sono eseguite da script Python deterministici. Il modello interviene esclusivamente dove è indispensabile la comprensione del linguaggio naturale.

---

## Struttura del progetto

```
├── .github/agents/
│   └── orchestratore.agent.md              # Definizione agente Copilot "Agente Verbalizzatore"
├── knowledge/
│   └── <project_slug>/
│       ├── thesaurus.json                  # Partecipanti noti, termini tecnici, decisioni, issue aperte
│       └── correction_log.json             # Pattern di correzione appresi dai feedback (CRR-XXX)
│   └── projects.json                       # Registro progetti: slug → display_name + aliases
├── sources/
│   └── <project_slug>/
│       ├── <trascrizione>.docx             # Input: trascrizione della riunione (Teams/Zoom)
│       ├── meeting_minutes_YYYYMMDD.json   # JSON bozza generato dall'agente
│       └── meeting_minutes_YYYYMMDD_rev.json # JSON definitivo dopo revisione utente
│   └── _transcript_tmp.txt                 # Testo estratto temporaneamente dalla trascrizione
├── results/
│   └── <project_slug>/
│       ├── verbale_YYYYMMDD_v1.docx        # DOCX bozza (pre-revisione)
│       └── verbale_YYYYMMDD_v1_rev.docx    # DOCX definitivo (post-revisione utente)
├── templates/
│   └── template_verbale_<cliente>.docx     # Un template DOCX per cliente (es. template_verbale_INPS.docx)
└── scripts/
    ├── extract_transcript.py               # Estrae testo pulito da DOCX/TXT → _transcript_tmp.txt
    ├── parse_header.py                     # Parsea header strutturato → JSON (data, ore, slug)
    ├── detect_speakers.py                  # Rileva speaker della trascrizione, confronta con thesaurus
    ├── validate_json.py                    # Valida schema del JSON strutturato
    ├── validate_semantic.py                # Valida coerenza semantica interna del JSON
    ├── template_placeholder_filler_v2.py   # Genera il DOCX dal JSON + template
    ├── thesaurus_updater.py                # Aggiorna knowledge/thesaurus.json dal JSON verbale
    ├── diff_and_learn.py                   # Confronta JSON bozza vs rev, aggiorna thesaurus e correction_log
    ├── docx_reverse_map.py                 # Ricostruisce _rev.json dal DOCX revisionato (senza LLM)
    ├── cleanup.py                          # Elimina file intermedi a fine processo (con conferma)
    └── inspect_template.py                 # Utility: ispeziona i placeholder nel template
```

---

## Dove interviene il modello LLM e dove no

Questa distinzione è centrale per capire il costo operativo del sistema e cosa può essere verificato/controllato deterministicamente.

### Operazioni **deterministiche** (script Python, nessun LLM)

| Fase | Script                              | Cosa fa                                                                                                                         |
| ---- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 0a   | `extract_transcript.py`             | Legge il file DOCX/TXT e produce testo pulito in `_transcript_tmp.txt`                                                          |
| 0b   | `parse_header.py`                   | Parsea l'header strutturato della trascrizione con regex: estrae data, orari, durata, document_name, project_slug               |
| 0d   | `detect_speakers.py`                | Trova i label speaker (`Nome   HH:MM:SS`) nella trascrizione e li confronta con il thesaurus                                    |
| 2.5  | `validate_json.py`                  | Verifica la conformità del JSON allo schema obbligatorio                                                                        |
| 2.6  | `validate_semantic.py`              | Verifica coerenza interna: owner nelle azioni, date valide, sezioni consecutive                                                 |
| 3    | `template_placeholder_filler_v2.py` | Sostituisce i placeholder `{{…}}` nel template DOCX con i valori del JSON                                                       |
| 4    | `thesaurus_updater.py`              | Merge dei nuovi dati dal JSON verso il thesaurus del progetto                                                                   |
| 6b   | `docx_reverse_map.py`               | Legge il DOCX revisionato, estrae partecipanti/sezioni/azioni/glossario dalle tabelle e dai paragrafi, ricostruisce `_rev.json` |
| 6c   | `diff_and_learn.py`                 | Confronta JSON generato vs revisionato, scrive pattern nel correction_log                                                       |
| 7    | `cleanup.py`                        | Rimuove file intermedi (con conferma)                                                                                           |

### Operazioni che **richiedono il modello LLM**

| Fase | Operazione                                  | Perché serve il modello                                                                                                                  |
| ---- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Domande interattive (`vscode_askQuestions`) | Interpretazione della risposta utente su nuovi partecipanti in formato libero                                                            |
| 2    | Analisi trascrizione → JSON strutturato     | Comprensione del parlato, sintesi, raggruppamento tematico, disambiguazione degli interventi, applicazione del livello di sintesi scelto |
| 0c   | Lettura e contestualizzazione del thesaurus | Il modello usa thesaurus e correction_log come contesto per la generazione                                                               |

La **FASE 2** è l'unica operazione cognitivamente complessa e irriducibile al solo codice: trasformare decine di minuti di parlato non strutturato in un documento formale richiede comprensione semantica. Tutto il resto è eseguito da script.

---

## Pipeline completa

La pipeline si articola in **10 fasi**, eseguite dall'agente Copilot **Agente Verbalizzatore**.

### FASE 0 — Preparazione `[deterministico]`

L'agente localizza la trascrizione (tramite finestra di dialogo nativa o argomento passato direttamente), poi delega a tre script:

**0a — Estrazione testo:**

```powershell
python scripts\extract_transcript.py "<percorso_trascrizione>" --output sources\_transcript_tmp.txt
```

Legge il file DOCX o TXT e produce `sources/_transcript_tmp.txt` con testo pulito, eliminando metadati Word. Questo file è l'unico input del modello: il DOCX binario non viene mai letto dal modello direttamente.

**0b — Parsing header:**

```powershell
python scripts\parse_header.py sources\_transcript_tmp.txt
```

Il primo paragrafo non vuoto di ogni trascrizione ha questo formato fisso:

```
[INPS - ASI Reingegnerizzazione UIUX] - SAL-YYYYMMDD_HHmmss-Registrazione della riunione
DD mese YYYY, HH:MMam/pm
Xh Ym Zs
```

Lo script estrae con regex: `meeting_date`, `start_time`, `end_time`, `document_name`, `project_slug`. L'output è un JSON stampato su stdout, pronto per essere iniettato nel contesto del modello per FASE 2.

**0c — Caricamento knowledge base:** Il modello legge `knowledge/<slug>/thesaurus.json` e `correction_log.json` per pre-popolare partecipanti, termini tecnici e anti-pattern da evitare.

**0d — Rilevamento speaker:**

```powershell
python scripts\detect_speakers.py sources\_transcript_tmp.txt
```

Scansiona la trascrizione con regex (`Nome Cognome   HH:MM:SS`), confronta con il thesaurus e produce l'elenco di speaker noti e nuovi. Usato sia per la domanda interattiva in FASE 1 sia per la pre-popolazione di FASE 2.

---

### FASE 1 — Parametri di generazione `[LLM — interazione utente]`

Il modello pone due domande tramite `vscode_askQuestions`:

**Domanda 1 — Livello di sintesi** (sempre obbligatoria):

| Livello      | Descrizione                                                  |
| ------------ | ------------------------------------------------------------ |
| `verbatim`   | Citazioni e parafrasi attribuite ai singoli partecipanti     |
| `attributed` | Argomenti principali con attribuzione ai contributori chiave |
| `resolved`   | Solo topic e decisione finale concordata                     |
| `executive`  | Una riga per argomento, nessuna attribuzione                 |

**Domanda 2 — Nuovi partecipanti** (solo se `detect_speakers.py` ha trovato speaker non nel thesaurus): l'utente può fornire ruolo e organizzazione in formato libero.

---

### FASE 2 — Produzione del JSON strutturato `[LLM — operazione principale]`

Il modello analizza `sources/_transcript_tmp.txt` tenendo conto del thesaurus, del livello di sintesi e dei metadata estratti in FASE 0b. Produce `sources/<slug>/meeting_minutes_YYYYMMDD.json`.

Il JSON contiene:

| Chiave               | Contenuto                                                  |
| -------------------- | ---------------------------------------------------------- |
| `document`           | Metadati (titolo, versione, autore, storia, distribuzione) |
| `meeting`            | Data, orario, luogo, oggetto, partecipanti                 |
| `sections`           | Sezioni tematiche numerate (titolo + array di paragrafi)   |
| `actions`            | Azioni con `owner`, `action`, `due_date`, `status`         |
| `notes`              | Follow-up, date future, problemi aperti                    |
| `glossary`           | Termini con `term` e `description`                         |
| `references`         | Documenti o fonti citate                                   |
| `issues`             | Anomalie o ambiguità rilevate nella trascrizione           |
| `generation_options` | `synthesis_level`, lingua, formato date                    |

Le sezioni `"1"` (Scopo del documento) e `"2"` (Introduzione) sono sempre presenti. Le sezioni tematiche partono da `"3"`.

---

### FASE 2.5 — Validazione schema `[deterministico]`

```powershell
python scripts\validate_json.py sources\<slug>\meeting_minutes_YYYYMMDD.json
```

Verifica campi obbligatori, formati data, struttura array. Errori bloccanti → il modello corregge il JSON prima di procedere.

---

### FASE 2.6 — Validazione semantica `[deterministico]`

```powershell
python scripts\validate_semantic.py sources\<slug>\meeting_minutes_YYYYMMDD.json
```

Verifica coerenza interna: owner delle azioni ricavabile dai partecipanti, `due_date >= meeting.date`, numerazione sezioni sequenziale, codici issue univoci.

---

### FASE 3 — Generazione DOCX `[deterministico]`

```powershell
python scripts\template_placeholder_filler_v2.py `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    results\<slug>\verbale_YYYYMMDD_v1.docx `
    --template <da projects.json: projects[slug].template>
```

Il template DOCX viene risolto automaticamente dall'agente leggendo il campo `template` del progetto in `knowledge/projects.json`. I placeholder `{{NOME}}` nel template vengono sostituiti con i valori del JSON. Sezioni, azioni, note e righe delle tabelle (partecipanti, glossario, ecc.) sono espanse dinamicamente. Il nome del DOCX include sempre il suffisso `_v1`.

---

### FASE 4 — Aggiornamento thesaurus `[deterministico]`

```powershell
python scripts\thesaurus_updater.py sources\<slug>\meeting_minutes_YYYYMMDD.json
```

Merge JSON → `knowledge/<slug>/thesaurus.json`: aggiunge nuovi partecipanti e termini, segnala conflitti se un termine viene ridefinito con una descrizione divergente.

---

### FASE 5 — Report e attesa revisione `[LLM — comunicazione]`

Il modello presenta il riepilogo (file prodotti, avvisi di validazione, issue aperte, modifiche al thesaurus) e rimane in attesa che l'utente depositi il verbale revisionato come `results/<slug>/verbale_YYYYMMDD_v1_rev.docx`.

---

### FASE 6 — Feedback loop `[deterministico]`

Quando l'utente conferma di aver salvato il DOCX revisionato:

**6b — Reverse-mapping DOCX → JSON:**

```powershell
python scripts\docx_reverse_map.py `
    results\<slug>\verbale_YYYYMMDD_v1_rev.docx `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    --template <da projects.json: projects[slug].template>
```

Lo script usa il template come riferimento strutturale per identificare ogni tabella nel DOCX (partecipanti, glossario, distribuzione, storico, riferimenti) ed estrae i valori corretti. Le sezioni tematiche, le azioni e le note vengono re-parsate dai paragrafi numerati del documento. I metadati scalari (titolo, date, codici) vengono copiati dal JSON originale.

Il file `sources/<slug>/meeting_minutes_YYYYMMDD_rev.json` viene prodotto **senza alcuna chiamata al modello**.

**6c — Diff e apprendimento:**

```powershell
python scripts\diff_and_learn.py `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    sources\<slug>\meeting_minutes_YYYYMMDD_rev.json
```

Confronta campo per campo i due JSON, scrive le correzioni in `knowledge/<slug>/correction_log.json` come pattern (`CRR-XXX`) applicati automaticamente alle generazioni future.

---

### FASE 7 — Pulizia `[deterministico]`

```powershell
python scripts\cleanup.py YYYYMMDD
```

Dopo conferma dell'utente, rimuove i file intermedi (bozza JSON e bozza DOCX pre-revisione). I file definitivi (`_rev.json`, `_rev.docx`) e il knowledge base non vengono mai toccati.

---

## Knowledge base

Il sistema mantiene memoria persistente tra le riunioni, organizzata per progetto:

- **`knowledge/projects.json`** — Registro dei progetti attivi: slug, display_name, aliases. Permette il riconoscimento automatico del progetto dall'header della trascrizione.
- **`knowledge/<slug>/thesaurus.json`** — Partecipanti con ruoli e organizzazione, termini tecnici con descrizione, log delle decisioni, issue aperte. Aggiornato in FASE 4 (da JSON generato) e FASE 6 (da diff con revisione).
- **`knowledge/<slug>/correction_log.json`** — Pattern di correzione appresi (es. "preferire forma collettiva nelle sezioni filtri"). Applicati come anti-pattern in FASE 2 per migliorare la qualità del testo generato.

---

## Utilizzo con l'agente Copilot

Aprire GitHub Copilot Chat in VS Code e selezionare l'agente **Agente Verbalizzatore** (definito in `.github/agents/orchestratore.agent.md`).

```
genera verbale
```

```
vai
```

L'agente apre automaticamente la finestra di selezione file e conduce l'intera pipeline in autonomia.

---

## Utilizzo manuale degli script

```powershell
# Preparazione (FASE 0)
python scripts\extract_transcript.py <trascrizione.docx> --output sources\_transcript_tmp.txt
python scripts\parse_header.py sources\_transcript_tmp.txt
python scripts\detect_speakers.py sources\_transcript_tmp.txt

# Validazione (FASE 2.5 e 2.6)
python scripts\validate_json.py sources\<slug>\meeting_minutes_YYYYMMDD.json
python scripts\validate_semantic.py sources\<slug>\meeting_minutes_YYYYMMDD.json

# Generazione DOCX (FASE 3)
# Il template è registrato in knowledge/projects.json → projects[slug].template
python scripts\template_placeholder_filler_v2.py `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    results\<slug>\verbale_YYYYMMDD_v1.docx `
    --template templates\template_verbale_<cliente>.docx

# Aggiornamento thesaurus (FASE 4)
python scripts\thesaurus_updater.py sources\<slug>\meeting_minutes_YYYYMMDD.json

# Feedback loop (FASE 6)
python scripts\docx_reverse_map.py `
    results\<slug>\verbale_YYYYMMDD_v1_rev.docx `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    --template templates\template_verbale_<cliente>.docx

python scripts\diff_and_learn.py `
    sources\<slug>\meeting_minutes_YYYYMMDD.json `
    sources\<slug>\meeting_minutes_YYYYMMDD_rev.json

# Pulizia (FASE 7)
python scripts\cleanup.py YYYYMMDD

# Utilità
python scripts\inspect_template.py templates\template_verbale_INPS.docx
```

---

## Requisiti

- Python 3.10+
- Pacchetto `python-docx`

```powershell
pip install python-docx
```
