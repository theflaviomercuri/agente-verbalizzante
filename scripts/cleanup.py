#!/usr/bin/env python3
"""
Pulizia file intermedi al termine del processo di verbalizzazione.

Identifica i file temporanei generati durante il processo (bozze JSON e DOCX
pre-revisione) e chiede conferma all'utente prima di eliminarli.

Uso:
    python scripts\\cleanup.py [DATA]

    DATA  (opzionale) data della riunione nel formato YYYYMMDD
          Se omessa, lo script la rileva automaticamente dai file presenti.

Logica di identificazione file eliminabili:
  - sources/<slug>/meeting_minutes_{data}.json      eliminabile se esiste _rev.json
  - results/<slug>/verbale_{data}_v*.docx           eliminabile se esiste *_rev.docx
  - sources/_transcript_tmp.txt                     eliminabile sempre (file temp)

Uscita:
    0  operazione completata (eliminazione effettuata o rifiutata)
    1  errore bloccante
"""

import re
import sys
from pathlib import Path


SOURCES_DIR = Path("sources")
RESULTS_DIR = Path("results")


# ---------------------------------------------------------------------------
# Rilevamento automatico della data
# ---------------------------------------------------------------------------

def _detect_dates() -> list[str]:
    """Rileva le date disponibili in base ai file _rev.json presenti
    nelle sottocartelle per-progetto di sources/."""
    dates = []
    for p in SOURCES_DIR.glob("*/meeting_minutes_*_rev.json"):
        m = re.search(r"meeting_minutes_(\d{8})_rev\.json", p.name)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


# ---------------------------------------------------------------------------
# Costruzione lista candidati
# ---------------------------------------------------------------------------

def _find_candidates(date: str) -> list[tuple[Path, str]]:
    """
    Restituisce lista di (Path, motivo) per i file eliminabili relativi a `date`.
    Cerca nelle sottocartelle per-progetto di sources/ e results/.
    """
    candidates: list[tuple[Path, str]] = []

    # 1) JSON bozza — cerca in sources/<slug>/
    for draft_json in SOURCES_DIR.glob(f"*/meeting_minutes_{date}.json"):
        rev_json = draft_json.parent / f"meeting_minutes_{date}_rev.json"
        if rev_json.exists():
            candidates.append((draft_json, "bozza JSON pre-revisione (superata da _rev.json)"))

    # 2) DOCX bozza — cerca in results/<slug>/
    for p in RESULTS_DIR.glob(f"*/verbale_{date}_v*.docx"):
        if "_rev" not in p.name:
            rev_docx_pattern = f"verbale_{date}_v*_rev.docx"
            if list(p.parent.glob(rev_docx_pattern)):
                candidates.append((p, "bozza DOCX pre-revisione (superata da _rev.docx)"))

    # 3) File temp trascrizione (radice sources/)
    tmp_txt = SOURCES_DIR / "_transcript_tmp.txt"
    if tmp_txt.exists():
        candidates.append((tmp_txt, "trascrizione temporanea estratta"))

    return candidates


# ---------------------------------------------------------------------------
# Presentazione e conferma
# ---------------------------------------------------------------------------

def _human_size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / 1024 ** 2:.1f} MB"


def _ask_permission(candidates: list[tuple[Path, str]]) -> bool:
    """Mostra i candidati e chiede conferma [s/n]."""
    print()
    print("=" * 55)
    print("PULIZIA FILE INTERMEDI")
    print("=" * 55)
    print(f"  Trovati {len(candidates)} file eliminabili:\n")
    for p, reason in candidates:
        size = _human_size(p) if p.exists() else "n/d"
        print(f"  • {p}  [{size}]")
        print(f"    {reason}")
    print()
    while True:
        answer = input("  Procedere con l'eliminazione? [s/n]: ").strip().lower()
        if answer in ("s", "si", "sì", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Risposta non riconosciuta. Inserire 's' oppure 'n'.")


# ---------------------------------------------------------------------------
# Eliminazione
# ---------------------------------------------------------------------------

def _delete(candidates: list[tuple[Path, str]]) -> None:
    deleted = 0
    errors  = 0
    for p, _ in candidates:
        try:
            p.unlink()
            print(f"  ✓ eliminato: {p}")
            deleted += 1
        except Exception as exc:
            print(f"  ✗ errore su {p}: {exc}")
            errors += 1
    print()
    print(f"  Eliminati {deleted} file" + (f", {errors} errori." if errors else "."))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    # Determina la data
    if len(sys.argv) >= 2:
        date = sys.argv[1].strip()
        if not re.fullmatch(r"\d{8}", date):
            print(f"ERRORE: il parametro DATA deve essere in formato YYYYMMDD (es. 20260519), ricevuto: '{date}'")
            return 1
        dates = [date]
    else:
        dates = _detect_dates()
        if not dates:
            print("Nessun verbale completato trovato (nessun *_rev.json in sources/<slug>/).")
            print("Assicurarsi che il processo sia stato completato prima di eseguire la pulizia.")
            return 0

    # Raccoglie tutti i candidati per tutte le date rilevate
    all_candidates: list[tuple[Path, str]] = []
    for d in dates:
        all_candidates.extend(_find_candidates(d))

    if not all_candidates:
        print()
        print("=" * 55)
        print("PULIZIA FILE INTERMEDI")
        print("=" * 55)
        print("  Nessun file intermedio da eliminare. Workspace già pulito.")
        return 0

    # Chiede permesso ed eventualmente elimina
    if _ask_permission(all_candidates):
        _delete(all_candidates)
    else:
        print()
        print("  Operazione annullata. Nessun file eliminato.")

    print("=" * 55)
    return 0


if __name__ == "__main__":
    sys.exit(main())
