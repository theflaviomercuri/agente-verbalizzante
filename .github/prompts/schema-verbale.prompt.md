---
description: "Regole complete per la generazione del JSON strutturato del verbale: schema obbligatorio, livelli di sintesi, normalizzazione, regole obbligatorie. Letta dal sub-agent Generatore JSON."
---

# Regole di generazione JSON — Verbale di riunione

## Utilizzo del knowledge base

Prima di generare il JSON, considera il contesto caricato:

- **Partecipanti noti**: pre-popola `name`, `role`, `organization` dai dati del thesaurus per i partecipanti già riconosciuti. Non sovrascrivere con valori meno precisi estratti dalla trascrizione.
- **Termini tecnici noti**: includi nel `glossary` i termini già presenti nel thesaurus con le loro definizioni confermate (`status: confirmed`). Aggiungi eventuali nuovi termini emersi dalla trascrizione.
- **Pattern di correzione**: se `correction_log.json` contiene pattern attivi, leggine la `description` e usala come anti-pattern. Es.: se un pattern dice "In sezioni filtri/navigazione preferire forma collettiva", applica quella regola nel livello `attributed`.

## Istruzioni per livello di sintesi

Applica le seguenti istruzioni in base al `synthesis_level` ricevuto nel brief:

**`verbatim` — Verbale esteso**

- Includi citazioni dirette tra virgolette attribuite al parlante, o parafrasi molto strette
- Riporta le posizioni intermedie e i contro-argomenti rilevanti
- Attribuisci ogni affermazione significativa al suo parlante
- Ogni sezione ha 3-6 paragrafi ricchi di attribuzioni

**`attributed` — Verbale standard** _(default)_

- Riassumi la discussione con attribuzione ai contributori principali
- Includi topic, argomenti chiave e soluzione/decisione con attribuzione
- Ometti interventi brevi, ripetizioni, intercalari
- Ogni sezione ha 2-4 paragrafi con attribuzioni selettive

**`resolved` — Verbale sintetico**

- Riporta solo la decisione finale o l'esito concordato per ogni argomento
- Includi la motivazione solo se spiega direttamente la decisione
- Nessun dibattito, nessuna posizione intermedia
- Ogni sezione ha 1-2 paragrafi brevi e diretti

**`executive` — Sintesi esecutiva**

- Una sola frase per argomento: cosa è stato deciso + impatto operativo
- Nessuna attribuzione, nessun dibattito, nessuna motivazione
- Ogni sezione ha 1 paragrafo di 1-2 righe massimo

## Analisi

Dalla trascrizione estrai:

- Partecipanti (dagli speaker label; integra con dati thesaurus)
- Contesto della riunione
- Punti di discussione rilevanti
- Decisioni prese
- Azioni operative (task concreti, responsabili, scadenze solo se esplicite)

## Normalizzazione

- Da parlato → scritto formale
- Rimuovi intercalari, ripetizioni, digressioni
- Non essere generico: specifica chi ha chiesto cosa e quali sono le osservazioni conclusive
- Mantieni solo contenuti verificabili e operativamente rilevanti

## Gestione trascrizioni di qualità variabile

- **Orari mancanti**: se l'orario assoluto non è ricavabile, usa `"-"` e aggiungi un issue con severity `"bassa"`
- **Organizzazioni non esplicitate**: usa `"-"`; aggiungi issue se rilevante
- **Frasi incomplete o interruzioni**: ricostruisci dal contesto se chiaro; se ambiguo, ometti e aggiungi nota
- **Nomi incerti**: segnala in `issues`
- **Discussioni senza esito**: documenta come paragrafo osservativo senza azione associata

## Struttura delle sezioni

- Produci tra **5 e 10 sezioni tematiche** (numerate da `"3"` in poi)
- Raggruppa argomenti correlati; non creare sezioni con un singolo paragrafo breve
- Le sezioni `"1"` e `"2"` sono obbligatorie:
  - `"1"` → `"Scopo del documento"` — scopo sintetico
  - `"2"` → `"Introduzione"` — contesto allargato, precedenti, obiettivi

## Glossario

Includi in `glossary`:

- Tutti i termini già confermati nel thesaurus che compaiono nella trascrizione
- Nuovi acronimi non autoesplicanti, nomi di sistemi, termini di dominio

## Partecipanti vs Distribuzione

- `meeting.participants`: tutte le persone presenti
- `document.distribution`: se non specificato, usa gli stessi partecipanti

## Informazioni Documento

Per i campi dell'area "Informazioni Documento":

- `document.client_references`: **non usare array vuoto**. Deriva automaticamente i nomi (stringa separata da virgola) dei partecipanti la cui `organization` contiene `"INPS"` dalla lista `meeting.participants`. Es: `["Michele Friscia, Paolo Capobianco"]`.
- `document.contract_reference`: usa il valore `contract_reference` ricevuto nel brief. Se non presente, usa `"-"`.
- `document.management_area`: usa il valore `management_area` ricevuto nel brief (nome del direttore d'area, non l'area tematica). Se non presente, usa `"-"`.

**Importante**: questi tre campi devono sempre essere valorizzati correttamente; `"-"` è accettabile solo se il valore non è disponibile nel knowledge base.

## Schema JSON obbligatorio

Produci un JSON conforme ESATTAMENTE a questo schema:

```json
{
  "document": {
    "title": "",
    "document_name": "",
    "document_type": "Verbale di riunione",
    "ssu_code": "-",
    "client_references": [],
    "management_area": "",
    "application_code": "-",
    "contract_reference": "",
    "supplier": "",
    "version": "1.0",
    "author": { "name": "", "organization": "" },
    "history": [
      {
        "version": "1.0",
        "date": "",
        "description": "Versione iniziale",
        "sections": ""
      }
    ],
    "distribution": [],
    "approvals": [
      {
        "version": "1.0",
        "approval_date": "-",
        "name": "-",
        "organization": "-"
      }
    ]
  },
  "meeting": {
    "date": "",
    "start_time": "",
    "end_time": "",
    "location": "",
    "subject": "",
    "participants": [{ "name": "", "role": "", "organization": "" }]
  },
  "references": [],
  "glossary": [],
  "sections": [],
  "actions": [],
  "notes": [],
  "issues": [],
  "generation_options": {
    "include_summary": true,
    "include_references_section": true,
    "include_glossary_section": true,
    "include_issues_section": true,
    "date_format": "dd/MM/yyyy",
    "empty_value_placeholder": "-",
    "language": "it",
    "synthesis_level": ""
  }
}
```

## Regole obbligatorie

- NON aggiungere campi fuori schema
- NON omettere campi; tutti gli array presenti anche se vuoti
- Dati mancanti: `""` per campi testuali attesi, `"-"` per campi non applicabili; NON inventare
- `number` nelle sezioni è una **STRINGA**; `paragraphs` è **SEMPRE** un array di stringhe
- `actions[].due_date` e `meeting.date` nel formato `dd/MM/yyyy`
- `generation_options.synthesis_level` → imposta il valore interno ricevuto nel brief
- Note: solo follow-up, date future, problemi aperti irrisolti
- Issues: `{ "code": "", "description": "", "severity": "alta|media|bassa" }`
- **Sezioni**: numera le sezioni tematiche a partire da `"3"`. Le sezioni `"1"` (Scopo) e `"2"` (Introduzione) sono riservate. La sezione `"1"` va sempre inclusa nel JSON ma il suo corpo non viene renderizzato nel DOCX (il template ha testo fisso); includi comunque un testo descrittivo sintetico.
- **Azioni — owner**: usa sempre la denominazione organizzativa (`Almaviva S.p.A.` o `INPS`), mai il nominativo individuale, salvo che la responsabilità sia esplicitamente e nominalmente attribuita nella trascrizione.
