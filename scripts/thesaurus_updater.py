#!/usr/bin/env python3
"""
Aggiorna knowledge/thesaurus.json con i dati di un nuovo verbale JSON.

Merge rules:
  - participants : aggiorna role/org se vuoti; flagga conflitto se divergenti
  - technical_terms : aggiunge se nuovo; flagga conflitto se ridefinito
  - decisions_log   : appende senza merge (ogni decisione è unica per data)
  - open_issues     : aggiunge nuove; non chiude automaticamente quelle esistenti

Uso:
    python scripts\\thesaurus_updater.py sources\\meeting_minutes_YYYYMMDD.json

    Il percorso del thesaurus viene risolto automaticamente dal campo
    document.project_slug del JSON. Se assente, fallback a knowledge/.

Uscita:
    0  aggiornamento completato (con o senza avvisi di conflitto)
    1  errore bloccante (file non trovato, JSON malformato, ecc.)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# KB path resolution
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Normalizza un display_name in uno slug sicuro per filesystem."""
    text = text.lower().strip()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def resolve_kb_dir(verbale_data: dict) -> Path:
    """
    Ritorna la directory della knowledge base per il progetto del verbale.
    Legge document.project_slug; se assente, usa knowledge/ come fallback.
    Crea la directory se non esiste.
    """
    slug = verbale_data.get("document", {}).get("project_slug", "").strip()
    if slug:
        kb = Path(f"knowledge/{slug}")
    else:
        kb = Path("knowledge")
    kb.mkdir(parents=True, exist_ok=True)
    return kb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    return str(s).strip().lower() if s else ""


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_thesaurus(path: Path) -> dict:
    if path.exists():
        return load_json(path)
    return {
        "_meta": {
            "version": "1.0",
            "last_updated": "",
            "last_verbale": "",
            "total_meetings": 0,
        },
        "participants": [],
        "technical_terms": [],
        "decisions_log": [],
        "open_issues": [],
    }


def find_participant(thesaurus: dict, name: str) -> dict | None:
    norm = normalize(name)
    for p in thesaurus["participants"]:
        if normalize(p["name"]) == norm:
            return p
        if norm in [normalize(a) for a in p.get("aliases", [])]:
            return p
    return None


def find_term(thesaurus: dict, term: str) -> dict | None:
    norm = normalize(term)
    for t in thesaurus["technical_terms"]:
        if normalize(t["term"]) == norm:
            return t
    return None


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def merge_participants(
    thesaurus: dict, verbale: dict, date: str, report: list
) -> tuple[int, int]:
    """Returns (new_count, conflict_count)."""
    participants = verbale.get("meeting", {}).get("participants", [])
    new_count = conflict_count = 0

    for p in participants:
        name = p.get("name", "").strip()
        if not name or name == "-":
            continue

        existing = find_participant(thesaurus, name)
        if existing is None:
            thesaurus["participants"].append({
                "name": name,
                "normalized": normalize(name),
                "organization": p.get("organization", "-"),
                "role": p.get("role", "-"),
                "aliases": [],
                "active_in": [date],
                "confirmed_in": 0,
                "status": "pending_review",
            })
            report.append(f"  + NUOVO partecipante: {name}")
            new_count += 1
        else:
            if date not in existing.get("active_in", []):
                existing.setdefault("active_in", []).append(date)

            new_role = p.get("role", "").strip()
            new_org  = p.get("organization", "").strip()

            cur_role = existing.get("role", "-")
            cur_org  = existing.get("organization", "-")

            if new_role and new_role != "-":
                if cur_role in ("", "-"):
                    existing["role"] = new_role
                elif normalize(new_role) != normalize(cur_role):
                    existing["_pending_role"] = new_role
                    existing["status"] = "pending_review"
                    report.append(
                        f"  ⚑ CONFLITTO ruolo '{name}': "
                        f"'{cur_role}' vs '{new_role}' → richiede conferma"
                    )
                    conflict_count += 1

            if new_org and new_org != "-":
                if cur_org in ("", "-"):
                    existing["organization"] = new_org
                elif normalize(new_org) != normalize(cur_org):
                    existing["_pending_organization"] = new_org
                    existing["status"] = "pending_review"
                    report.append(
                        f"  ⚑ CONFLITTO organizzazione '{name}': "
                        f"'{cur_org}' vs '{new_org}' → richiede conferma"
                    )
                    conflict_count += 1

    return new_count, conflict_count


def merge_terms(
    thesaurus: dict, verbale: dict, date: str, report: list
) -> tuple[int, int]:
    """Returns (new_count, conflict_count)."""
    glossary = verbale.get("glossary", [])
    new_count = conflict_count = 0

    for entry in glossary:
        term = entry.get("term", "").strip()
        desc = entry.get("description", "").strip()
        if not term or not desc:
            continue

        existing = find_term(thesaurus, term)
        if existing is None:
            thesaurus["technical_terms"].append({
                "term": term,
                "normalized": normalize(term),
                "description": desc,
                "first_seen": date,
                "last_seen": date,
                "confirmed_in": 0,
                "status": "pending_review",
            })
            report.append(f"  + NUOVO termine: '{term}'")
            new_count += 1
        else:
            existing["last_seen"] = date
            cur_desc = existing.get("description", "")
            if normalize(desc) != normalize(cur_desc):
                existing["_pending_description"] = desc
                existing["status"] = "pending_review"
                report.append(f"  ⚑ CONFLITTO definizione '{term}' → richiede conferma")
                report.append(f"    attuale:  {cur_desc[:90]}")
                report.append(f"    proposta: {desc[:90]}")
                conflict_count += 1

    return new_count, conflict_count


def append_decisions(thesaurus: dict, verbale: dict, date: str, report: list) -> int:
    """Appende le decisioni del verbale al log. Non de-duplica: ogni verbale è unico."""
    meeting_date = verbale.get("meeting", {}).get("date", date)
    verbale_name = verbale.get("document", {}).get("document_name", "")
    count = 0

    for section in verbale.get("sections", []):
        num = section.get("number", "")
        for action in verbale.get("actions", []):
            # Only top-level decisions (from sections, not individual actions)
            pass

    # Store high-level decisions from notes as a block reference
    thesaurus.setdefault("decisions_log", [])
    entry = {
        "date": meeting_date,
        "verbale": verbale_name or Path(sys.argv[1]).name,
        "actions_count": len(verbale.get("actions", [])),
        "sections_count": len(
            [s for s in verbale.get("sections", []) if s.get("number") not in ("1", "2")]
        ),
    }
    thesaurus["decisions_log"].append(entry)
    count = 1
    report.append(f"  + Verbale registrato nel log decisioni ({entry['actions_count']} azioni, {entry['sections_count']} sezioni)")
    return count


def merge_open_issues(thesaurus: dict, verbale: dict, report: list) -> int:
    """Aggiunge nuove issues; non chiude automaticamente quelle esistenti."""
    existing_codes = {
        iss.get("code", "") for iss in thesaurus.get("open_issues", [])
    }
    new_count = 0

    for iss in verbale.get("issues", []):
        code = iss.get("code", "")
        if code and code not in existing_codes:
            thesaurus.setdefault("open_issues", []).append({
                "code": code,
                "description": iss.get("description", ""),
                "severity": iss.get("severity", ""),
                "first_seen": verbale.get("meeting", {}).get("date", ""),
                "status": "open",
            })
            existing_codes.add(code)
            report.append(f"  + NUOVA issue: {code} ({iss.get('severity', '')})")
            new_count += 1

    return new_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python scripts\\thesaurus_updater.py sources\\meeting_minutes_YYYYMMDD.json")
        sys.exit(1)

    verbale_path = Path(sys.argv[1])
    if not verbale_path.exists():
        print(f"ERRORE: file non trovato: {verbale_path}")
        sys.exit(1)

    try:
        verbale = load_json(verbale_path)
    except json.JSONDecodeError as e:
        print(f"ERRORE: JSON malformato in {verbale_path}: {e}")
        sys.exit(1)

    # Resolve knowledge base directory from project_slug
    kb_dir = resolve_kb_dir(verbale)
    thesaurus_path = kb_dir / "thesaurus.json"

    # Derive YYYYMMDD from filename
    stem = verbale_path.stem
    parts = stem.split("_")
    verbale_date = (
        parts[-1]
        if parts and parts[-1].isdigit() and len(parts[-1]) == 8
        else datetime.now().strftime("%Y%m%d")
    )

    thesaurus = load_thesaurus(thesaurus_path)
    report: list[str] = []

    sep = "=" * 55
    print(f"\n{sep}")
    print("AGGIORNAMENTO THESAURUS")
    print(f"Verbale: {verbale_path.name}  |  data: {verbale_date}")
    print(f"KB:      {thesaurus_path}")
    print(sep)

    report.append("\nPARTECIPANTI:")
    p_new, p_conf = merge_participants(thesaurus, verbale, verbale_date, report)
    if p_new == 0 and p_conf == 0:
        report.append("  Nessuna modifica")

    report.append("\nTERMINI TECNICI:")
    t_new, t_conf = merge_terms(thesaurus, verbale, verbale_date, report)
    if t_new == 0 and t_conf == 0:
        report.append("  Nessuna modifica")

    report.append("\nDECISIONI:")
    append_decisions(thesaurus, verbale, verbale_date, report)

    report.append("\nISSUES:")
    i_new = merge_open_issues(thesaurus, verbale, report)
    if i_new == 0:
        report.append("  Nessuna nuova issue")

    # Update meta
    thesaurus["_meta"]["last_updated"]   = datetime.now().strftime("%d/%m/%Y")
    thesaurus["_meta"]["last_verbale"]   = verbale_path.name
    thesaurus["_meta"]["total_meetings"] = thesaurus["_meta"].get("total_meetings", 0) + 1
    thesaurus["_meta"]["project_slug"]   = verbale.get("document", {}).get("project_slug", "")

    save_json(thesaurus_path, thesaurus)

    for line in report:
        print(line)

    total_conf = p_conf + t_conf
    print(f"\n{sep}")
    if total_conf > 0:
        print(f"ATTENZIONE: {total_conf} conflitti → verificare {thesaurus_path}")
    print(
        f"Thesaurus aggiornato: +{p_new} partecipanti, +{t_new} termini, +{i_new} issues"
    )
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
