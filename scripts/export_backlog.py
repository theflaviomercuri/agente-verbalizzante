#!/usr/bin/env python3
"""
Genera un file CSV compatibile con Azure Boards (Queries > Import Work Items)
a partire dal JSON del verbale.

Struttura CSV:
  - 1 PBI "Attività dalla riunione SAL del gg/mm/yyyy" con le azioni Almaviva come Task figli
    La description del PBI è una lista numerata sintetica di tutte le azioni Almaviva.
  - 1 PBI separato (senza figli) per ogni azione il cui owner è diverso da Almaviva.

Sorgente preferita:
  Se viene passato il file generato (senza _rev), lo script cerca automaticamente
  la versione _rev.json nella stessa directory; se esiste, la usa come input.

Uso:
    python scripts\\export_backlog.py <json_path>

Output:
    results/<project_slug>/backlog-SAL-DDMMYYYY.csv
    Encoding: utf-8-sig (UTF-8 con BOM — richiesto da Azure DevOps via browser
              per la corretta gestione dei caratteri accentati italiani)

Uscita:
    0  file generato con successo
    1  errore bloccante
"""

import csv
import json
import sys
from pathlib import Path


ALMAVIVA_OWNER = "Almaviva S.p.A."


def load_json(json_path: Path) -> dict:
    """Carica il JSON; se non è già _rev, preferisce la versione _rev se esiste."""
    if not json_path.name.endswith("_rev.json"):
        rev_path = json_path.with_name(json_path.stem + "_rev.json")
        if rev_path.exists():
            json_path = rev_path
    with json_path.open(encoding="utf-8") as f:
        return json.load(f)


def build_pbi_description(almaviva_actions: list) -> str:
    """Lista numerata sintetica delle azioni Almaviva, separata da punto e virgola."""
    parts = [f"({i + 1}) {a['action']}" for i, a in enumerate(almaviva_actions)]
    return "; ".join(parts)


def date_to_tag(date_str: str) -> str:
    """Converte 'dd/mm/yyyy' nel tag filename 'ddmmyyyy'."""
    d, m, y = date_str.split("/")
    return f"{d}{m}{y}"


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts\\export_backlog.py <json_path>", file=sys.stderr)
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Errore: file non trovato: {json_path}", file=sys.stderr)
        sys.exit(1)

    data = load_json(json_path)

    meeting_date = data["meeting"]["date"]          # es. "07/07/2026"
    project_slug = data["document"]["project_slug"]  # es. "asi"
    actions = data.get("actions", [])

    almaviva_actions = [a for a in actions if a.get("owner") == ALMAVIVA_OWNER]
    other_actions   = [a for a in actions if a.get("owner") != ALMAVIVA_OWNER]

    # Percorso di output
    date_tag = date_to_tag(meeting_date)
    output_dir = Path("results") / project_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"backlog-SAL-{date_tag}.csv"

    rows = []

    # --- PBI principale (azioni Almaviva, ID=1) ---
    rows.append({
        "ID":             "1",
        "Work Item Type": "Product Backlog Item",
        "Title":          f"Attività dalla riunione SAL del {meeting_date}",
        "Parent":         "",
        "Description":    build_pbi_description(almaviva_actions),
    })

    # Task figli: una riga per ogni azione Almaviva
    for action in almaviva_actions:
        rows.append({
            "ID":             "",
            "Work Item Type": "Task",
            "Title":          action["action"],
            "Parent":         "1",
            "Description":    action.get("owner", ""),
        })

    # --- PBI separati per ogni owner diverso da Almaviva (ID progressivi da 2) ---
    for i, action in enumerate(other_actions, start=2):
        rows.append({
            "ID":             str(i),
            "Work Item Type": "Product Backlog Item",
            "Title":          action["action"],
            "Parent":         "",
            "Description":    action.get("owner", ""),
        })

    # Scrittura CSV
    fieldnames = ["ID", "Work Item Type", "Title", "Parent", "Description"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV generato: {output_path}")
    print(f"  PBI Almaviva (ID=1): {len(almaviva_actions)} task figli")
    if other_actions:
        owners = ", ".join(sorted({a.get("owner", "?") for a in other_actions}))
        print(f"  PBI separati: {len(other_actions)} ({owners})")


if __name__ == "__main__":
    main()
