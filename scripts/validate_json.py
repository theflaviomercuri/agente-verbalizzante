#!/usr/bin/env python3
"""
Valida il file meeting_minutes JSON prima della generazione del DOCX.
Uso: python scripts\validate_json.py <path_json>
Uscita: 0 se valido (also con avvisi), 1 se ci sono errori bloccanti.
"""
import json
import re
import sys
from pathlib import Path

DATE_RE = re.compile(r'^\d{2}/\d{2}/\d{4}$')

_errors: list[str] = []
_warnings: list[str] = []


def err(msg: str) -> None:
    _errors.append(msg)


def warn(msg: str) -> None:
    _warnings.append(msg)


def validate(data: dict) -> None:
    # --- document ---
    doc = data.get('document')
    if not isinstance(doc, dict):
        err("'document' mancante o non e' un oggetto")
    else:
        for field in ('title', 'document_name', 'version'):
            if not doc.get(field):
                err(f"document.{field} mancante o vuoto")
        author = doc.get('author')
        if not isinstance(author, dict):
            err("document.author mancante o non e' un oggetto")
        else:
            if not author.get('name'):
                warn("document.author.name vuoto")
        history = doc.get('history')
        if history is None:
            warn("document.history mancante: verra' usato il fallback 'Versione iniziale'")
        elif not isinstance(history, list) or len(history) == 0:
            err("document.history deve essere un array non vuoto")
        else:
            for i, h in enumerate(history):
                for f in ('version', 'date', 'description'):
                    if not h.get(f):
                        warn(f"document.history[{i}].{f} vuoto")
        dist = doc.get('distribution')
        if not isinstance(dist, list) or len(dist) == 0:
            warn("document.distribution vuoto o mancante")

    # --- meeting ---
    meeting = data.get('meeting')
    if not isinstance(meeting, dict):
        err("'meeting' mancante o non e' un oggetto")
    else:
        date_val = str(meeting.get('date') or '')
        if not date_val or date_val == '-':
            warn("meeting.date mancante")
        elif not DATE_RE.match(date_val):
            warn(f"meeting.date '{date_val}' non e' nel formato dd/MM/yyyy")
        participants = meeting.get('participants')
        if not isinstance(participants, list) or len(participants) == 0:
            err("meeting.participants mancante o vuoto")
        else:
            for i, p in enumerate(participants):
                if not p.get('name'):
                    err(f"meeting.participants[{i}].name vuoto")
                if not p.get('role'):
                    warn(f"meeting.participants[{i}].role vuoto")

    # --- sections ---
    sections = data.get('sections')
    if not isinstance(sections, list) or len(sections) == 0:
        err("'sections' mancante o vuoto")
    else:
        has_section_1 = False
        has_section_2 = False
        for i, s in enumerate(sections):
            num = s.get('number')
            if not isinstance(num, str):
                err(f"sections[{i}].number deve essere una stringa (trovato: {type(num).__name__})")
            else:
                if num == '1':
                    has_section_1 = True
                if num == '2':
                    has_section_2 = True
            if not s.get('title'):
                err(f"sections[{i}].title vuoto")
            paras = s.get('paragraphs')
            if not isinstance(paras, list):
                err(f"sections[{i}].paragraphs deve essere un array (trovato: {type(paras).__name__})")
            elif len(paras) == 0:
                warn(f"sections[{i}] ('{s.get('title', '')}') ha paragraphs vuoto")
            else:
                for j, p in enumerate(paras):
                    if not isinstance(p, str):
                        err(f"sections[{i}].paragraphs[{j}] deve essere una stringa")
        if not has_section_1:
            err("Sezione '1' (Scopo del documento) obbligatoria ma mancante")
        if not has_section_2:
            err("Sezione '2' (Introduzione) obbligatoria ma mancante")
        thematic_count = len([s for s in sections if s.get('number') not in ('1', '2')])
        if thematic_count < 2:
            warn(f"Solo {thematic_count} sezioni tematiche (dalla 3 in poi): potrebbe essere troppo sintetico")
        if thematic_count > 12:
            warn(f"{thematic_count} sezioni tematiche: valutare se accorpare argomenti correlati")
        numbers = [str(s.get('number')) for s in sections if s.get('number') is not None]
        if len(numbers) != len(set(numbers)):
            err("sections: numeri di sezione duplicati")

    # --- actions ---
    actions = data.get('actions')
    if not isinstance(actions, list):
        err("'actions' deve essere un array")
    else:
        for i, a in enumerate(actions):
            if not a.get('owner'):
                err(f"actions[{i}].owner vuoto")
            if not a.get('action'):
                err(f"actions[{i}].action vuoto")
            due = str(a.get('due_date') or '')
            if due and due != '-' and not DATE_RE.match(due):
                warn(f"actions[{i}].due_date '{due}' non e' nel formato dd/MM/yyyy")
            if not a.get('status'):
                warn(f"actions[{i}].status vuoto")

    # --- notes ---
    if not isinstance(data.get('notes'), list):
        err("'notes' deve essere un array")

    # --- references / glossary ---
    if not isinstance(data.get('references'), list):
        err("'references' deve essere un array")
    glossary = data.get('glossary')
    if not isinstance(glossary, list):
        err("'glossary' deve essere un array")
    else:
        for i, g in enumerate(glossary):
            if not g.get('term') and not g.get('acronym'):
                warn(f"glossary[{i}]: manca 'term' o 'acronym'")
            if not g.get('description'):
                warn(f"glossary[{i}].description vuoto")

    # --- issues ---
    issues = data.get('issues')
    if not isinstance(issues, list):
        warn("'issues' mancante o non e' un array")
    else:
        _valid_severities = {'alta', 'media', 'bassa'}
        for i, issue in enumerate(issues):
            if not issue.get('code'):
                warn(f"issues[{i}].code vuoto")
            if not issue.get('description'):
                warn(f"issues[{i}].description vuoto")
            sev = issue.get('severity', '')
            if sev not in _valid_severities:
                warn(f"issues[{i}].severity '{sev}' non valido (atteso: alta|media|bassa)")

    # --- generation_options ---
    opts = data.get('generation_options')
    if not isinstance(opts, dict):
        warn("'generation_options' mancante")


def main() -> None:
    global _errors, _warnings
    _errors.clear()
    _warnings.clear()
    if len(sys.argv) < 2:
        print("Uso: python scripts\\validate_json.py <path_json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"[ERRORE] File non trovato: {path}")
        sys.exit(1)

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERRORE] JSON malformato: {e}")
        sys.exit(1)

    validate(data)

    print(f"\n{'=' * 55}")
    print(f"VALIDAZIONE: {path.name}")
    print(f"{'=' * 55}")

    if _warnings:
        print(f"\nAVVISI ({len(_warnings)}):")
        for w in _warnings:
            print(f"  [AVVISO] {w}")

    if _errors:
        print(f"\nERRORI ({len(_errors)}):")
        for e in _errors:
            print(f"  [ERRORE] {e}")
        print(f"\n{'=' * 55}")
        print("Validazione FALLITA. Correggere gli errori prima di procedere.")
        print(f"{'=' * 55}\n")
        sys.exit(1)
    else:
        print(f"\n{'=' * 55}")
        print(f"Validazione OK  --  {len(_warnings)} avvisi, 0 errori.")
        print(f"{'=' * 55}\n")
        sys.exit(0)


if __name__ == '__main__':
    main()
