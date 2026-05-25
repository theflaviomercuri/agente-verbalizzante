# Agente Verbalizzante

Sistema di generazione automatica di verbali di riunione a partire da trascrizioni audio/testo. Converte una trascrizione grezza in un documento DOCX formattato, passando per un JSON strutturato come stadio intermedio verificabile. Include un knowledge base persistente che apprende dai feedback e un ciclo di revisione che aggiorna automaticamente il thesaurus.

---

## Struttura del progetto

```
├── .github/agents/
│   └── orchestratore.agent.md            # Definizione agente Copilot "Agente Verbalizzatore"
├── knowledge/
│   ├── thesaurus.json                     # Partecipanti noti, termini tecnici, decisioni, issue aperte
│   └── correction_log.json               # Pattern di correzione appresi dai feedback (CRR-XXX)
├── sources/
│   ├── <trascrizione>.docx               # Input: trascrizione della riunione
│   ├── verbale_template_placeholders_final.docx  # Template DOCX con placeholder {{…}}
│   ├── logo inps.png                     # Asset grafico del template
│   ├── meeting_minutes_YYYYMMDD.json     # JSON bozza generato dall'agente
│   └── meeting_minutes_YYYYMMDD_rev.json # JSON definitivo dopo revisione utente
├── results/
│   ├── verbale_YYYYMMDD_v1.docx          # DOCX bozza (pre-revisione)
│   └── verbale_YYYYMMDD_v1_rev.docx      # DOCX definitivo (post-revisione utente)
└── scripts/
    ├── validate_json.py                  # Valida schema del JSON strutturato
    ├── validate_semantic.py              # Valida coerenza semantica interna del JSON
    ├── template_placeholder_filler_v2.py # Genera il DOCX dal JSON + template
    ├── thesaurus_updater.py              # Aggiorna knowledge/thesaurus.json dal JSON verbale
    ├── diff_and_learn.py                 # Confronta JSON bozza vs rev, aggiorna thesaurus e correction_log
    ├── cleanup.py                        # Elimina i file intermedi a fine processo (con conferma)
    └── inspect_template.py               # Utility: ispeziona i placeholder nel template
```

---

## Pipeline completa

La pipeline si articola in **10 fasi**, eseguite dall'agente Copilot **Agente Verbalizzatore**.

### FASE 0 — Preparazione

L'agente apre la finestra di selezione file per scegliere la trascrizione (`.docx` o `.txt`), estrae i metadati dall'header e carica il knowledge base (`thesaurus.json`, `correction_log.json`).

Il **primo paragrafo non vuoto** del file di trascrizione contiene un header strutturato:

```
[INPS - ASI Reingegnerizzazione UIUX] - SAL-YYYYMMDD_HHmmss-Registrazione della riunione
DD mese YYYY, HH:MMAM/PM
Xh MM m SS s
```

Da questo header vengono estratti: data, orario di inizio, durata → orario di fine, nome del documento.

### FASE 1 — Parametri di generazione

L'agente chiede il **livello di sintesi** desiderato:

| Livello      | Descrizione                                                  |
| ------------ | ------------------------------------------------------------ |
| `verbatim`   | Parafrasi ravvicinate con attribuzioni nominali              |
| `attributed` | Argomenti principali con attribuzioni ai contributori chiave |
| `resolved`   | Solo topic e decisione finale concordata                     |
| `executive`  | Una riga per argomento, nessuna attribuzione                 |

Se sono presenti partecipanti non ancora in thesaurus, vengono chiesti ruolo e organizzazione.

### FASE 2 — Produzione JSON

L'agente analizza la trascrizione tenendo conto del thesaurus e del livello scelto, e produce `sources/meeting_minutes_YYYYMMDD.json`.

Il JSON contiene:

| Chiave               | Contenuto                                                  |
| -------------------- | ---------------------------------------------------------- |
| `document`           | Metadati (titolo, versione, autore, storia, distribuzione) |
| `meeting`            | Data, orario, luogo, oggetto, partecipanti                 |
| `sections`           | Sezioni tematiche numerate (titolo + paragrafi)            |
| `actions`            | Azioni con `id`, `action`, `owner`, `due_date`, `status`   |
| `notes`              | Follow-up, date future, segnalazioni                       |
| `glossary`           | Termini con `term` e `description`                         |
| `references`         | Documenti o fonti citate                                   |
| `issues`             | Anomalie o dati ambigui rilevati nella trascrizione        |
| `generation_options` | `synthesis_level`, lingua, formato date                    |

Le prime due sezioni sono sempre: `"1"` → **Scopo del documento**, `"2"` → **Introduzione**.

### FASE 2.5 — Validazione schema

```powershell
python scripts\validate_json.py sources\meeting_minutes_YYYYMMDD.json
```

Errori bloccanti vengono corretti prima di proseguire. Gli avvisi vengono riportati senza bloccare.

### FASE 2.6 — Validazione semantica

```powershell
python scripts\validate_semantic.py sources\meeting_minutes_YYYYMMDD.json
```

Controlla coerenza interna: owner delle azioni presenti nei partecipanti, date valide, sezioni consecutive, termini glossario usati nel testo.

### FASE 3 — Generazione DOCX

```powershell
python scripts\template_placeholder_filler_v2.py \
  sources\meeting_minutes_YYYYMMDD.json \
  results\verbale_YYYYMMDD_v1.docx \
  --template sources\verbale_template_placeholders_final.docx
```

I placeholder `{{NOME}}` nel template vengono sostituiti con i valori del JSON. Sezioni, azioni e note sono espanse dinamicamente.

### FASE 4 — Aggiornamento thesaurus

```powershell
python scripts\thesaurus_updater.py sources\meeting_minutes_YYYYMMDD.json
```

Aggiorna `knowledge/thesaurus.json` con nuovi partecipanti, termini tecnici, decisioni e issue emerse dalla riunione.

### FASE 5 — Report e attesa revisione

L'agente presenta il riepilogo (file prodotti, avvisi, issue aperte) e rimane in attesa che l'utente depositi il verbale revisionato.

### FASE 6 — Feedback loop (revisione utente)

Quando l'utente salva le proprie correzioni in `results/verbale_YYYYMMDD_v1_rev.docx`, l'agente:

1. Ri-estrae il testo dal DOCX revisionato
2. Produce `sources/meeting_minutes_YYYYMMDD_rev.json` con le correzioni applicate
3. Esegue il diff e aggiorna il knowledge base:

```powershell
python scripts\diff_and_learn.py \
  sources\meeting_minutes_YYYYMMDD.json \
  sources\meeting_minutes_YYYYMMDD_rev.json
```

Le correzioni vengono registrate in `knowledge/correction_log.json` come pattern riutilizzabili nelle riunioni successive.

### FASE 7 — Pulizia (automatica)

L'agente chiede conferma e rimuove i file intermedi non più necessari (bozza JSON e bozza DOCX pre-revisione):

```powershell
python scripts\cleanup.py YYYYMMDD
```

I file definitivi (`_rev.json` e `_rev.docx`) e il knowledge base non vengono mai toccati.

---

## Knowledge base

Il sistema mantiene memoria persistente tra le riunioni:

- **`knowledge/thesaurus.json`** — Partecipanti con ruoli e organizzazione, termini tecnici con descrizione, log delle decisioni, issue aperte. Aggiornato automaticamente in FASE 4 e FASE 6.
- **`knowledge/correction_log.json`** — Pattern di correzione appresi (es. sostituzione sistematica di termini errati). Applicati automaticamente nelle generazioni successive.

---

## Utilizzo con l'agente Copilot

Aprire GitHub Copilot Chat in VS Code e selezionare l'agente **Agente Verbalizzatore** (definito in `.github/agents/orchestratore.agent.md`).

```
vai
```

```
genera verbale
```

L'agente apre automaticamente la finestra di selezione file e conduce l'intera pipeline in autonomia.

---

## Utilizzo manuale degli script

```powershell
# 1. Validazione schema
python scripts\validate_json.py sources\meeting_minutes_YYYYMMDD.json

# 2. Validazione semantica
python scripts\validate_semantic.py sources\meeting_minutes_YYYYMMDD.json

# 3. Generazione DOCX
python scripts\template_placeholder_filler_v2.py sources\meeting_minutes_YYYYMMDD.json results\verbale_YYYYMMDD_v1.docx --template sources\verbale_template_placeholders_final.docx

# 4. Aggiornamento thesaurus
python scripts\thesaurus_updater.py sources\meeting_minutes_YYYYMMDD.json

# 5. Diff e apprendimento (dopo revisione)
python scripts\diff_and_learn.py sources\meeting_minutes_YYYYMMDD.json sources\meeting_minutes_YYYYMMDD_rev.json

# 6. Pulizia file intermedi (con conferma interattiva)
python scripts\cleanup.py YYYYMMDD
```

---

## Requisiti

- Python 3.10+
- Pacchetto `python-docx`

```powershell
pip install python-docx
```
