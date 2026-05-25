#!/usr/bin/env python3
"""
Validazione semantica del JSON verbale.

Controlla la coerenza interna tra campi che validate_json.py non verifica:
  - action.owner riconducibile a un partecipante noto
  - action.due_date >= meeting.date
  - numerazione sezioni sequenziale e senza duplicati
  - codici issue univoci
  - termini del glossario referenziati nel testo delle sezioni
  - synthesis_level riconosciuto (se presente)

Uso:
    python scripts\\validate_semantic.py sources\\meeting_minutes_YYYYMMDD.json

Uscita:
    0  validazione OK (0 errori, N avvisi accettabili)
    1  validazione FALLITA (almeno 1 errore bloccante)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATE_RE         = re.compile(r"^\d{2}/\d{2}/\d{4}$")
VALID_LEVELS    = {"verbatim", "attributed", "resolved", "executive"}
MIN_PART_LENGTH = 4   # ignore owner fragments shorter than this


_errors:   list[str] = []
_warnings: list[str] = []


def err(msg: str) -> None:
    _errors.append(msg)


def warn(msg: str) -> None:
    _warnings.append(msg)


def parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def build_known_names(participants: list) -> set[str]:
    """Raccoglie tutti i frammenti di nomi noti (>= MIN_PART_LENGTH caratteri)."""
    known: set[str] = set()
    for p in participants:
        name = str(p.get("name", "")).strip().lower()
        if not name or name == "-":
            continue
        known.add(name)
        for part in name.split():
            if len(part) >= MIN_PART_LENGTH:
                known.add(part)
    return known


def check_actions(actions: list, known_names: set, meeting_date: datetime | None) -> None:
    for i, a in enumerate(actions):
        owner     = str(a.get("owner",    "")).strip()
        due_str   = str(a.get("due_date", "")).strip()

        # --- owner traceable to a participant ---
        if owner and owner not in ("", "-"):
            owner_lower = owner.lower()
            matched = any(part in owner_lower for part in known_names)
            if not matched:
                warn(
                    f"actions[{i}].owner '{owner}' "
                    "non riconducibile a nessun partecipante noto"
                )

        # --- due_date format and after meeting date ---
        if due_str and due_str not in ("", "-"):
            if not DATE_RE.match(due_str):
                warn(f"actions[{i}].due_date '{due_str}' non nel formato dd/MM/yyyy")
            else:
                due_dt = parse_date(due_str)
                if meeting_date and due_dt and due_dt < meeting_date:
                    err(
                        f"actions[{i}].due_date '{due_str}' è precedente "
                        f"alla data della riunione"
                    )


def check_sections(sections: list) -> None:
    numbers: list[int] = []
    str_numbers: list[str] = []

    for s in sections:
        raw = s.get("number")
        if raw is not None:
            str_numbers.append(str(raw))
            try:
                numbers.append(int(raw))
            except (ValueError, TypeError):
                err(f"sections[].number '{raw}' non convertibile a intero")

    # Duplicate numbers
    if len(str_numbers) != len(set(str_numbers)):
        err("Numeri di sezione duplicati")
        return

    if not numbers:
        return

    numbers_sorted = sorted(numbers)

    # Must start from 1
    if numbers_sorted[0] != 1:
        err(f"La prima sezione deve essere '1', trovato '{numbers_sorted[0]}'")

    # Must be consecutive
    for idx in range(len(numbers_sorted) - 1):
        if numbers_sorted[idx + 1] != numbers_sorted[idx] + 1:
            warn(
                f"Numerazione sezioni non consecutiva: "
                f"{numbers_sorted[idx]} → {numbers_sorted[idx + 1]}"
            )


def check_glossary_coverage(glossary: list, sections: list) -> None:
    """Avvisa se un termine del glossario non compare nel testo delle sezioni."""
    section_text = " ".join(
        " ".join(p for p in s.get("paragraphs", []))
        for s in sections
    ).lower()

    for g in glossary:
        term = str(g.get("term", "")).strip()
        if not term:
            continue
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if not re.search(pattern, section_text):
            warn(f"Termine glossario '{term}' non trovato nel testo delle sezioni")


def check_issues(issues: list) -> None:
    codes = [str(iss.get("code", "")) for iss in issues if iss.get("code")]
    if len(codes) != len(set(codes)):
        err("Codici issue duplicati")


def check_synthesis_level(gen_opts: dict) -> None:
    level = str(gen_opts.get("synthesis_level", "")).strip()
    if level and level not in VALID_LEVELS:
        warn(
            f"generation_options.synthesis_level '{level}' non riconosciuto "
            f"(valori attesi: {', '.join(sorted(VALID_LEVELS))})"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def validate(data: dict) -> None:
    meeting      = data.get("meeting", {})
    meeting_date = parse_date(str(meeting.get("date", "")))
    participants = meeting.get("participants", [])

    known_names = build_known_names(participants)

    check_actions(data.get("actions", []), known_names, meeting_date)
    check_sections(data.get("sections", []))
    check_glossary_coverage(data.get("glossary", []), data.get("sections", []))
    check_issues(data.get("issues", []))
    check_synthesis_level(data.get("generation_options", {}))


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python scripts\\validate_semantic.py sources\\meeting_minutes_YYYYMMDD.json")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}")
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERRORE: JSON malformato: {e}")
        sys.exit(1)

    validate(data)

    sep = "=" * 55
    print(f"\n{sep}")
    print(f"VALIDAZIONE SEMANTICA: {path.name}")
    print(sep)

    if _errors:
        print(f"\nERRORI ({len(_errors)}):")
        for e in _errors:
            print(f"  [ERRORE] {e}")

    if _warnings:
        print(f"\nAVVISI ({len(_warnings)}):")
        for w in _warnings:
            print(f"  [AVVISO] {w}")

    print(f"\n{sep}")
    if _errors:
        print(f"Validazione FALLITA  --  {len(_warnings)} avvisi, {len(_errors)} errori.")
        print(sep)
        sys.exit(1)
    else:
        print(f"Validazione OK  --  {len(_warnings)} avvisi, 0 errori.")
        print(f"{sep}\n")


if __name__ == "__main__":
    main()
