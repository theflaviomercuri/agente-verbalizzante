#!/usr/bin/env python3
"""
Rileva i label degli speaker in una trascrizione Teams/Zoom e confronta
con il thesaurus del progetto per distinguere partecipanti noti da nuovi.

Il formato atteso per i label speaker è:
    Nome Cognome   HH:MM:SS
(il nome è seguito da 2+ spazi e poi da un timestamp HH:MM:SS)

Uso:
    python scripts\\detect_speakers.py <transcript.docx|transcript.txt> [--project-slug <slug>]

    Se --project-slug non è fornito, lo script prova a rilevarlo
    automaticamente dall'header della trascrizione.

Uscita (JSON su stdout):
    {
      "total_unique_speakers": N,
      "known": [{"name": "...", "role": "...", "organization": "..."}],
      "new": ["Nome1", "Nome2"],
      "project_slug": "...",
      "thesaurus_loaded": true|false
    }

Uscita:
    0  rilevamento completato
    1  errore bloccante
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex: speaker label  →  "Nome Cognome   HH:MM:SS"
# Supporta nomi con 2+ parole, lettere accentate, apostrofi.
# ---------------------------------------------------------------------------
_SPEAKER_RE = re.compile(
    r"^((?:[A-ZÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜ][a-zA-ZàáâäèéêëìíîïòóôöùúûüÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜ'-]+"
    r"(?:\s+[A-ZÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜ][a-zA-ZàáâäèéêëìíîïòóôöùúûüÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜ'-]+)+))"
    r"\s{2,}\d{1,2}:\d{2}:\d{2}"
)

_HEADER_PROJECT_RE = re.compile(r"^\[(.+?)\]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def get_paragraphs(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError:
            print("ERRORE: python-docx non installata.", file=sys.stderr)
            sys.exit(1)
        doc = Document(str(path))
        return [p.text for p in doc.paragraphs]
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


# ---------------------------------------------------------------------------
# Speaker detection
# ---------------------------------------------------------------------------

def detect_speakers(paragraphs: list[str]) -> list[str]:
    """Restituisce lista ordinata di nomi speaker unici trovati nella trascrizione."""
    names: set[str] = set()
    for line in paragraphs:
        m = _SPEAKER_RE.match(line.strip())
        if m:
            names.add(m.group(1).strip())
    return sorted(names)


# ---------------------------------------------------------------------------
# Project slug resolution
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _slug_from_header(paragraphs: list[str]) -> str:
    """Estrae project_slug dall'header della trascrizione."""
    non_empty = [p.strip() for p in paragraphs if p.strip()]
    if not non_empty:
        return ""
    m = _HEADER_PROJECT_RE.match(non_empty[0])
    if not m:
        return ""
    project_name = m.group(1).strip().lower()

    projects_path = Path("knowledge/projects.json")
    if projects_path.exists():
        try:
            with open(projects_path, encoding="utf-8") as f:
                projects = json.load(f)
            for slug, meta in projects.items():
                display = str(meta.get("display_name", "")).lower().strip()
                if display == project_name:
                    return slug
                aliases = [str(a).lower().strip() for a in meta.get("aliases", [])]
                if project_name in aliases:
                    return slug
        except Exception:
            pass

    return _slugify(project_name)


# ---------------------------------------------------------------------------
# Thesaurus lookup
# ---------------------------------------------------------------------------

def load_thesaurus_participants(slug: str) -> list[dict]:
    """Carica la lista partecipanti dal thesaurus del progetto."""
    for kb_path in (
        Path(f"knowledge/{slug}/thesaurus.json"),
        Path("knowledge/thesaurus.json"),
    ):
        if kb_path.exists():
            try:
                with open(kb_path, encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("participants", [])
            except Exception:
                pass
    return []


def _normalize(s: str) -> str:
    return s.lower().strip()


def _build_known_index(participants: list[dict]) -> dict[str, dict]:
    """Costruisce un indice nome_normalizzato → partecipante."""
    index: dict[str, dict] = {}
    for p in participants:
        name = p.get("name", "").strip()
        if name:
            index[_normalize(name)] = p
        for alias in p.get("aliases", []):
            if alias:
                index[_normalize(alias)] = p
    return index


def _match_speaker(speaker: str, known_index: dict[str, dict]) -> dict | None:
    """Cerca corrispondenza esatta, poi per cognome (≥4 char)."""
    norm = _normalize(speaker)
    exact = known_index.get(norm)
    if exact:
        return exact
    parts = norm.split()
    for part in parts:
        if len(part) >= 4:
            for key, participant in known_index.items():
                if part in key.split():
                    return participant
    return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Rileva speaker nella trascrizione e confronta con il thesaurus."
    )
    ap.add_argument("transcript", help="Percorso al file di trascrizione (.docx o .txt)")
    ap.add_argument(
        "--project-slug",
        default=None,
        help="Slug del progetto (auto-detect se non fornito)",
    )
    args = ap.parse_args()

    path = Path(args.transcript)
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    paragraphs = get_paragraphs(path)
    detected = detect_speakers(paragraphs)

    slug = args.project_slug or _slug_from_header(paragraphs) or ""
    participants = load_thesaurus_participants(slug)
    thesaurus_loaded = bool(participants)

    known_index = _build_known_index(participants)

    known_results: list[dict] = []
    new_results: list[str] = []

    for speaker in detected:
        match = _match_speaker(speaker, known_index)
        if match:
            known_results.append({
                "name": match.get("name", speaker),
                "role": match.get("role", "-"),
                "organization": match.get("organization", "-"),
            })
        else:
            new_results.append(speaker)

    result = {
        "total_unique_speakers": len(detected),
        "known": known_results,
        "new": new_results,
        "project_slug": slug,
        "thesaurus_loaded": thesaurus_loaded,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
