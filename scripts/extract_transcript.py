#!/usr/bin/env python3
"""
Estrae il testo da un file di trascrizione DOCX o TXT e lo scrive su file o stdout.

Uso:
    python scripts\\extract_transcript.py <transcript.docx|transcript.txt> [--output <out.txt>]

    Se --output non è specificato, scrive su stdout.
    Il file di output viene salvato in UTF-8 senza BOM.

Uscita:
    0  estrazione completata
    1  errore bloccante (file non trovato, formato non supportato)
"""

import argparse
import sys
from pathlib import Path


def _read_docx(path: Path) -> list[str]:
    try:
        from docx import Document
    except ImportError:
        print(
            "ERRORE: libreria 'python-docx' non installata. Esegui: pip install python-docx",
            file=sys.stderr,
        )
        sys.exit(1)
    doc = Document(str(path))
    return [p.text for p in doc.paragraphs]


def _read_txt(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def extract_lines(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in (".txt", ".text", ""):
        return _read_txt(path)
    print(
        f"ERRORE: formato non supportato '{suffix}'. Usa .docx o .txt.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Estrae il testo da una trascrizione DOCX o TXT."
    )
    ap.add_argument("transcript", help="Percorso al file di trascrizione (.docx o .txt)")
    ap.add_argument(
        "--output",
        default=None,
        help="File di output .txt (default: stdout)",
    )
    args = ap.parse_args()

    path = Path(args.transcript)
    if not path.exists():
        print(f"ERRORE: file non trovato: {path}", file=sys.stderr)
        sys.exit(1)

    lines = extract_lines(path)
    content = "\n".join(lines)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        physical_lines = content.count("\n") + 1
        print(
            f"Estratto: {out} ({len(lines)} paragrafi, {physical_lines} righe fisiche)",
            file=sys.stderr,
        )
    else:
        print(content)


if __name__ == "__main__":
    main()
