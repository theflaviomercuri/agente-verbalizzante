#!/usr/bin/env python3
"""
Analizza l'header strutturato della trascrizione ed estrae i metadati della riunione.

Formato header (primo paragrafo non vuoto del file di trascrizione):
    [NomeProgetto] - SAL-YYYYMMDD_HHmmss-Registrazione della riunione
    DD mese YYYY, HH:MMam/pm
    [Xh ]Ym Zs

Uso:
    python scripts\\parse_header.py <transcript.docx|transcript.txt>

Uscita (JSON su stdout):
    {
      "meeting_date":   "DD/MM/YYYY",
      "start_time":     "HH:MM",
      "end_time":       "HH:MM",
      "document_name":  "VRB_SAL_YYYYMMDD",
      "project_name":   "INPS - ASI Reingegnerizzazione UIUX",
      "project_slug":   "inps_asi_uiux",
      "raw_header":     "<righe originali>"
    }

Uscita:
    0  parsing completato
    1  header non trovato o non parsabile
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

_IT_MONTHS: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

_HEADER_LINE1_RE = re.compile(
    r"^\[(.+?)\]\s*-\s*SAL-(\d{8})_\d{6}-",
    re.IGNORECASE,
)
_DATETIME_LINE_RE = re.compile(
    r"(\d{1,2})\s+(\w+)\s+(\d{4}),\s*(\d{1,2}):(\d{2})\s*(am|pm)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s\b)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _resolve_project_slug(project_name: str) -> str:
    """Cerca il project_slug in knowledge/projects.json; fallback a slugify."""
    projects_path = Path("knowledge/projects.json")
    if projects_path.exists():
        try:
            with open(projects_path, encoding="utf-8") as f:
                projects = json.load(f)
            name_lower = project_name.lower().strip()
            for slug, meta in projects.items():
                display = str(meta.get("display_name", "")).lower().strip()
                if display == name_lower:
                    return slug
                aliases = [str(a).lower().strip() for a in meta.get("aliases", [])]
                if name_lower in aliases:
                    return slug
        except Exception:
            pass
    return _slugify(project_name)


def _parse_time_12h(hour: int, minute: int, ampm: str) -> tuple[int, int]:
    ampm = ampm.lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def _add_duration(
    start_h: int, start_m: int, hours: int, minutes: int, seconds: int
) -> tuple[int, int]:
    total_min = start_h * 60 + start_m + hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return (total_min // 60) % 24, total_min % 60


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


def find_header_lines(paragraphs: list[str]) -> list[str]:
    """Restituisce le prime 3 righe non vuote (header della trascrizione)."""
    non_empty = [p.strip() for p in paragraphs if p.strip()]
    return non_empty[:3] if len(non_empty) >= 3 else non_empty


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_header(lines: list[str]) -> dict:
    if len(lines) < 2:
        raise ValueError("Header incompleto: attese almeno 2 righe non vuote")

    # Riga 1: [ProjectName] - SAL-YYYYMMDD_HHmmss-...
    m1 = _HEADER_LINE1_RE.match(lines[0])
    if not m1:
        raise ValueError(f"Riga 1 non riconosciuta come header SAL: {lines[0]!r}")

    project_name = m1.group(1).strip()
    date_token = m1.group(2)  # YYYYMMDD

    # Riga 2: DD mese YYYY, HH:MMam/pm
    m2 = _DATETIME_LINE_RE.search(lines[1])
    if not m2:
        raise ValueError(f"Riga 2 non riconosciuta come data/ora: {lines[1]!r}")

    day = int(m2.group(1))
    month_str = m2.group(2).lower()
    year = int(m2.group(3))
    hour = int(m2.group(4))
    minute = int(m2.group(5))
    ampm = m2.group(6)

    month = _IT_MONTHS.get(month_str)
    if month is None:
        raise ValueError(f"Mese italiano non riconosciuto: {month_str!r}")

    meeting_date = f"{day:02d}/{month:02d}/{year}"
    start_h, start_m = _parse_time_12h(hour, minute, ampm)
    start_time = f"{start_h:02d}:{start_m:02d}"

    # Riga 3 (opzionale): durata  →  end_time
    end_time = "-"
    if len(lines) >= 3:
        m3 = _DURATION_RE.search(lines[2])
        if m3 and any(m3.groups()):
            h_dur = int(m3.group(1) or 0)
            m_dur = int(m3.group(2) or 0)
            s_dur = int(m3.group(3) or 0)
            end_h, end_m = _add_duration(start_h, start_m, h_dur, m_dur, s_dur)
            end_time = f"{end_h:02d}:{end_m:02d}"

    return {
        "meeting_date": meeting_date,
        "start_time": start_time,
        "end_time": end_time,
        "document_name": f"VRB_SAL_{date_token}",
        "project_name": project_name,
        "project_slug": _resolve_project_slug(project_name),
        "raw_header": "\n".join(lines[:3]),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Estrae i metadati dall'header strutturato della trascrizione."
    )
    ap.add_argument("transcript", help="Percorso al file di trascrizione (.docx o .txt)")
    args = ap.parse_args()

    path = Path(args.transcript)
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    paragraphs = get_paragraphs(path)
    lines = find_header_lines(paragraphs)

    try:
        result = parse_header(lines)
    except ValueError as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
