# Agente Verbalizzante

Sistema di generazione automatica di verbali di riunione a partire da trascrizioni audio/testo. Converte una trascrizione grezza in un documento DOCX formattato, passando per un JSON strutturato come stadio intermedio verificabile.

---

## Struttura del progetto

```
├── .github/agents/
│   └── orchestratore.agent.md   # Definizione dell'agente Copilot
├── sources/
│   ├── <trascrizione>.docx       # File di input (trascrizione della riunione)
│   ├── verbale_template_placeholders_final.docx  # Template DOCX con placeholder
│   ├── logo inps.png             # Asset grafico usato nel documento
│   └── meeting_minutes_YYYYMMDD.json  # JSON strutturato prodotto dall'agente
├── results/
│   └── verbale_YYYYMMDD.docx    # Verbale finale generato
└── scripts/
    ├── validate_json.py          # Valida il JSON strutturato
    ├── template_placeholder_filler_v2.py  # Genera il DOCX dal JSON + template
    └── inspect_template.py       # Utility: ispeziona i placeholder nel template
```

---

## Come funziona

La pipeline si articola in **4 passi**, eseguiti dall'agente Copilot `Agente Verbalizzatore` o manualmente.

### Passo 1 — Lettura della trascrizione

L'agente cerca in `sources/` il file di trascrizione (qualsiasi file che non sia un JSON né il template DOCX) e ne legge il contenuto.

Il **primo paragrafo non vuoto** del file contiene un header strutturato con i metadati della riunione:

```
[INPS - ASI Reingegnerizzazione UIUX] - SAL-YYYYMMDD_HHmmss-Registrazione della riunione
DD mese YYYY, HH:MMAM/PM
MM m SS s
```

Da questo header vengono estratti: data, orario di inizio, durata (→ orario di fine), nome del documento.

### Passo 2 — Produzione del JSON strutturato

L'agente analizza la trascrizione e produce un JSON conforme allo schema del progetto, salvato in `sources/meeting_minutes_YYYYMMDD.json`.

Il JSON contiene:

| Chiave       | Contenuto                                                                |
| ------------ | ------------------------------------------------------------------------ |
| `document`   | Metadati del documento (titolo, versione, autore, storia, distribuzione) |
| `meeting`    | Data, orario, luogo, oggetto, partecipanti                               |
| `sections`   | Da 5 a 10 sezioni tematiche numerate, ognuna con titolo e paragrafi      |
| `actions`    | Azioni operative con responsabile, descrizione e scadenza                |
| `notes`      | Follow-up, link, date future, problemi aperti                            |
| `glossary`   | Acronimi, nomi di sistemi, termini tecnici di dominio                    |
| `references` | Documenti o fonti citate                                                 |
| `issues`     | Segnalazioni di dati mancanti o ambigui nella trascrizione               |

Le prime due sezioni sono sempre fisse:

- `"1"` → **Scopo del documento**
- `"2"` → **Introduzione**

### Passo 2.5 — Validazione del JSON

Prima di generare il DOCX, il JSON viene validato:

```powershell
python scripts\validate_json.py sources\meeting_minutes_YYYYMMDD.json
```

- In presenza di **errori**: il JSON viene corretto e rivalidato prima di procedere.
- In presenza di soli **avvisi**: la pipeline prosegue e gli avvisi vengono riportati all'utente.

### Passo 3 — Generazione del DOCX

Lo script `template_placeholder_filler_v2.py` sostituisce i placeholder nel template DOCX con i valori dal JSON:

```powershell
python scripts\template_placeholder_filler_v2.py \
  sources\meeting_minutes_YYYYMMDD.json \
  results\verbale_YYYYMMDD.docx \
  --template sources\verbale_template_placeholders_final.docx
```

I placeholder nel template hanno la forma `{{NOME_PLACEHOLDER}}`. Le sezioni tematiche, le azioni e le note vengono espanse dinamicamente.

### Passo 4 — Conferma

Al termine la pipeline comunica:

- Percorso del JSON generato
- Percorso del DOCX generato
- Eventuali avvisi di validazione
- Eventuali placeholder non riempiti
- Eventuali problemi segnalati in `issues`

---

## Utilizzo con l'agente Copilot

Aprire GitHub Copilot Chat in VS Code e selezionare l'agente **Agente Verbalizzatore** (definito in `.github/agents/orchestratore.agent.md`).

Esempi di invocazione:

```
genera verbale
```

```
crea verbale dalla trascrizione Reingegnerizzazione UI_UX ASI 17042026.docx
```

L'agente eseguirà in autonomia tutti e 4 i passi della pipeline e riporterà il risultato.

---

## Utilizzo manuale (senza agente)

1. Posizionarsi nella root del progetto.
2. Creare manualmente `sources/meeting_minutes_YYYYMMDD.json` seguendo lo schema.
3. Validare il JSON:
   ```powershell
   python scripts\validate_json.py sources\meeting_minutes_YYYYMMDD.json
   ```
4. Generare il DOCX:
   ```powershell
   python scripts\template_placeholder_filler_v2.py sources\meeting_minutes_YYYYMMDD.json results\verbale_YYYYMMDD.docx --template sources\verbale_template_placeholders_final.docx
   ```

---

## Requisiti

- Python 3.9+
- Pacchetto `python-docx`

```powershell
pip install python-docx
```
