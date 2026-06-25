#!/usr/bin/env python3
"""
Confronta il JSON generato con il JSON revisionato dall'utente.
Aggiorna knowledge/thesaurus.json e knowledge/correction_log.json con le
correzioni confermate e i pattern di errore rilevati.

Il "JSON revisionato" (REV) viene prodotto dall'agente rileggendo il verbale
DOCX corretto dall'utente e salvandolo come meeting_minutes_YYYYMMDD_rev.json.

Uso:
    python scripts\\diff_and_learn.py <generated_json> <revised_json>

    Il percorso della knowledge base viene risolto automaticamente dal campo
    document.project_slug del JSON generato.

    es:  python scripts\\diff_and_learn.py \\
             sources\\meeting_minutes_20260519.json \\
             sources\\meeting_minutes_20260519_rev.json

Uscita:
    0  diff completato (con o senza modifiche)
    1  errore bloccante
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

def normalize(s) -> str:
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
    return {"participants": [], "technical_terms": [], "_meta": {}}


def load_correction_log(path: Path) -> dict:
    if path.exists():
        return load_json(path)
    return {"_meta": {"version": "1.0", "total_patterns": 0, "last_updated": ""}, "patterns": []}


def next_pattern_id(log: dict) -> str:
    nums = [
        int(p["pattern_id"].split("-")[1])
        for p in log.get("patterns", [])
        if p.get("pattern_id", "").startswith("CRR-")
    ]
    return f"CRR-{(max(nums, default=0) + 1):03d}"


def find_thesaurus_participant(thesaurus: dict, name: str) -> dict | None:
    norm = normalize(name)
    for p in thesaurus.get("participants", []):
        if normalize(p.get("name", "")) == norm:
            return p
        if norm in [normalize(a) for a in p.get("aliases", [])]:
            return p
    return None


def find_thesaurus_term(thesaurus: dict, term: str) -> dict | None:
    norm = normalize(term)
    for t in thesaurus.get("technical_terms", []):
        if normalize(t.get("term", "")) == norm:
            return t
    return None


# ---------------------------------------------------------------------------
# Diff sections
# ---------------------------------------------------------------------------

def diff_participants(gen: dict, rev: dict, thesaurus: dict, log: dict,
                      report: list, date: str) -> int:
    gen_map = {normalize(p["name"]): p for p in gen.get("meeting", {}).get("participants", [])}
    rev_map = {normalize(p["name"]): p for p in rev.get("meeting", {}).get("participants", [])}
    changes = []

    for norm_name, rev_p in rev_map.items():
        if norm_name not in gen_map:
            continue
        gen_p = gen_map[norm_name]
        name  = rev_p.get("name", "")

        for field in ("role", "organization"):
            gen_val = gen_p.get(field, "")
            rev_val = rev_p.get(field, "")
            if normalize(gen_val) != normalize(rev_val) and rev_val not in ("", "-"):
                changes.append({
                    "field":     f"participants.{field}[{name}]",
                    "original":  gen_val,
                    "corrected": rev_val,
                })
                report.append(f"  ~ {field.upper()} '{name}': '{gen_val}' → '{rev_val}'")
                # Apply confirmed correction to thesaurus
                tp = find_thesaurus_participant(thesaurus, name)
                if tp is not None:
                    tp[field] = rev_val
                    tp["status"] = "confirmed"
                    tp.pop(f"_pending_{field}", None)

    if changes:
        pid = next_pattern_id(log)
        log["patterns"].append({
            "pattern_id":  pid,
            "verbale":     date,
            "category":    "participants",
            "changes":     changes,
            "description": "",
            "occurrences": 1,
            "first_seen":  date,
            "last_seen":   date,
        })
    return len(changes)


def diff_glossary(gen: dict, rev: dict, thesaurus: dict, log: dict,
                  report: list, date: str) -> int:
    gen_map = {normalize(g["term"]): g for g in gen.get("glossary", [])}
    rev_map = {normalize(g["term"]): g for g in rev.get("glossary", [])}
    changes = []

    for norm_term, rev_g in rev_map.items():
        term = rev_g.get("term", "")
        if norm_term not in gen_map:
            report.append(f"  + NUOVO termine (aggiunto nella revisione): '{term}'")
            # Add to thesaurus if not already present
            if find_thesaurus_term(thesaurus, term) is None:
                thesaurus.setdefault("technical_terms", []).append({
                    "term":        term,
                    "normalized":  normalize(term),
                    "description": rev_g.get("description", ""),
                    "first_seen":  date,
                    "last_seen":   date,
                    "confirmed_in": 1,
                    "status":      "confirmed",
                })
            continue

        gen_g   = gen_map[norm_term]
        gen_val = gen_g.get("description", "")
        rev_val = rev_g.get("description", "")
        if normalize(gen_val) != normalize(rev_val) and rev_val:
            changes.append({
                "field":     f"glossary.description[{term}]",
                "original":  gen_val,
                "corrected": rev_val,
            })
            report.append(f"  ~ DEFINIZIONE '{term}' modificata")
            # Apply confirmed correction to thesaurus
            tt = find_thesaurus_term(thesaurus, term)
            if tt is not None:
                tt["description"] = rev_val
                tt["status"]      = "confirmed"
                tt.pop("_pending_description", None)

    # Check for removed terms (present in gen but not in rev)
    for norm_term, gen_g in gen_map.items():
        if norm_term not in rev_map:
            report.append(f"  - TERMINE rimosso nella revisione: '{gen_g.get('term', '')}'")

    if changes:
        pid = next_pattern_id(log)
        log["patterns"].append({
            "pattern_id":  pid,
            "verbale":     date,
            "category":    "glossary",
            "changes":     changes,
            "description": "",
            "occurrences": 1,
            "first_seen":  date,
            "last_seen":   date,
        })
    return len(changes)


def diff_actions(gen: dict, rev: dict, log: dict, report: list, date: str) -> int:
    gen_actions = gen.get("actions", [])
    rev_actions = rev.get("actions", [])
    changes = []

    # Match by position (same order assumption); flag count diff
    if len(gen_actions) != len(rev_actions):
        report.append(
            f"  ⚑ Numero azioni cambiato: {len(gen_actions)} → {len(rev_actions)}"
        )

    for i, rev_a in enumerate(rev_actions):
        if i >= len(gen_actions):
            report.append(f"  + NUOVA azione #{i+1}: '{rev_a.get('action', '')[:60]}...'")
            continue
        gen_a = gen_actions[i]
        for field in ("owner", "action", "due_date", "status"):
            gen_val = gen_a.get(field, "")
            rev_val = rev_a.get(field, "")
            if normalize(gen_val) != normalize(rev_val) and rev_val not in ("", "-"):
                changes.append({
                    "field":     f"actions[{i}].{field}",
                    "original":  gen_val,
                    "corrected": rev_val,
                })
                label = f"#{i+1} '{gen_a.get('action', '')[:40]}...'"
                report.append(f"  ~ {field.upper()} azione {label}: '{gen_val}' → '{rev_val}'")

    if changes:
        pid = next_pattern_id(log)
        log["patterns"].append({
            "pattern_id":  pid,
            "verbale":     date,
            "category":    "actions",
            "changes":     changes,
            "description": "",
            "occurrences": 1,
            "first_seen":  date,
            "last_seen":   date,
        })
    return len(changes)


def diff_sections(gen: dict, rev: dict, log: dict, report: list, date: str) -> int:
    gen_map = {str(s["number"]): s for s in gen.get("sections", [])}
    rev_map = {str(s["number"]): s for s in rev.get("sections", [])}
    changes = []

    for num, rev_s in rev_map.items():
        if num not in gen_map:
            report.append(f"  + NUOVA sezione {num}: '{rev_s.get('title', '')}'")
            continue
        gen_s    = gen_map[num]
        gen_text = " ".join(gen_s.get("paragraphs", []))
        rev_text = " ".join(rev_s.get("paragraphs", []))
        if normalize(gen_text) != normalize(rev_text):
            delta = len(rev_text) - len(gen_text)
            sign  = "+" if delta >= 0 else ""
            changes.append({
                "field":           f"sections[{num}]",
                "title":           rev_s.get("title", ""),
                "original_length": len(gen_text),
                "revised_length":  len(rev_text),
                "char_delta":      delta,
            })
            report.append(
                f"  ~ SEZIONE {num} '{rev_s.get('title', '')}': "
                f"testo modificato ({sign}{delta} caratteri)"
            )

    for num in gen_map:
        if num not in rev_map:
            report.append(f"  - SEZIONE {num} rimossa nella revisione")

    if changes:
        pid = next_pattern_id(log)
        log["patterns"].append({
            "pattern_id":  pid,
            "verbale":     date,
            "category":    "sections",
            "changes":     changes,
            "description": "",
            "occurrences": 1,
            "first_seen":  date,
            "last_seen":   date,
        })
    return len(changes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Uso: python scripts\\diff_and_learn.py <generated_json> <revised_json>\n"
            "  es: python scripts\\diff_and_learn.py "
            "sources\\meeting_minutes_20260519.json "
            "sources\\meeting_minutes_20260519_rev.json"
        )
        sys.exit(1)

    gen_path = Path(sys.argv[1])
    rev_path = Path(sys.argv[2])

    for p in (gen_path, rev_path):
        if not p.exists():
            print(f"ERRORE: file non trovato: {p}")
            sys.exit(1)

    try:
        gen = load_json(gen_path)
        rev = load_json(rev_path)
    except json.JSONDecodeError as e:
        print(f"ERRORE: JSON malformato: {e}")
        sys.exit(1)

    # Resolve knowledge base directory and filenames from project_slug (reads from gen)
    slug = gen.get("document", {}).get("project_slug", "").strip()
    kb_dir = resolve_kb_dir(gen)
    thesaurus_filename      = f"thesaurus_{slug}.json" if slug else "thesaurus_global.json"
    correction_log_filename = f"correction_log_{slug}.json" if slug else "correction_log_global.json"
    thesaurus_path      = kb_dir / thesaurus_filename
    correction_log_path = kb_dir / correction_log_filename

    thesaurus = load_thesaurus(thesaurus_path)
    log       = load_correction_log(correction_log_path)

    # Derive YYYYMMDD from generated filename
    stem  = gen_path.stem
    parts = stem.split("_")
    date  = (
        parts[-1]
        if parts and parts[-1].isdigit() and len(parts[-1]) == 8
        else datetime.now().strftime("%Y%m%d")
    )

    sep    = "=" * 55
    report: list[str] = []

    print(f"\n{sep}")
    print("DIFF & LEARN")
    print(f"  generato : {gen_path.name}")
    print(f"  revisionato: {rev_path.name}")
    print(f"  KB:          {kb_dir}")
    print(sep)

    report.append("\nPARTECIPANTI:")
    n_p = diff_participants(gen, rev, thesaurus, log, report, date)
    if n_p == 0:
        report.append("  Nessuna modifica")

    report.append("\nGLOSSARIO:")
    n_g = diff_glossary(gen, rev, thesaurus, log, report, date)
    if n_g == 0:
        report.append("  Nessuna modifica")

    report.append("\nAZIONI:")
    n_a = diff_actions(gen, rev, log, report, date)
    if n_a == 0:
        report.append("  Nessuna modifica")

    report.append("\nSEZIONI:")
    n_s = diff_sections(gen, rev, log, report, date)
    if n_s == 0:
        report.append("  Nessuna modifica")

    total = n_p + n_g + n_a + n_s

    # Update correction_log meta
    log["_meta"]["total_patterns"] = len(log["patterns"])
    log["_meta"]["last_updated"]   = datetime.now().strftime("%d/%m/%Y")

    save_json(thesaurus_path, thesaurus)
    save_json(correction_log_path, log)

    for line in report:
        print(line)

    new_patterns = len([p for p in log["patterns"] if p.get("verbale") == date])
    print(f"\n{sep}")
    print(f"Totale modifiche rilevate : {total}")
    print(f"Nuovi pattern (CRR)       : {new_patterns}")
    if total > 0:
        print("Thesaurus e correction_log aggiornati.")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
