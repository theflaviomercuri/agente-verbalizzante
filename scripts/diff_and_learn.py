#!/usr/bin/env python3
"""
Confronta il JSON generato con il JSON revisionato dall'utente.
Aggiorna knowledge/thesaurus.json e knowledge/correction_log.json con le
correzioni confermate e i pattern di errore rilevati.

FORMATO CORRECTION LOG v2 (regole canoniche deduplicate):
  Il log usa "rules" invece di "patterns". Ogni rule accumula occurrences e
  verbali invece di duplicarsi. Le rule con deterministic=true sono applicabili
  via script senza LLM; quelle generation_policy sono passate come contesto
  all'agente in FASE 2.

  Struttura rule:
  {
    "rule_id":       "RULE-001",
    "type":          "field_value_override|field_default|content_override|
                      artifact_filter|vocabulary_substitution|
                      generation_policy|ownership_policy",
    "deterministic": true|false,
    "applies_to":    "actions[*].owner",   // campo template, non istanza
    "condition":     "...",                // opzionale
    "corrected_to":  "...",               // per rule deterministiche
    "occurrences":   3,
    "verbali":       ["20260112", ...],
    "first_seen":    "20260112",
    "last_seen":     "20260707",
    "description":   "...",
    "status":        "active|conflicted|superseded",
    "_fingerprint":  "actions[*].owner:person_to_org"
  }

  Compatibilità legacy: se il file ha "patterns" (v1), viene migrato
  automaticamente a "rules" (v2) al momento del caricamento.

Uso:
    python scripts\\diff_and_learn.py <generated_json> <revised_json>

    Il percorso della knowledge base viene risolto automaticamente dal campo
    document.project_slug del JSON generato.

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
# Helpers base
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
    """
    Carica il correction log. Se il file è in formato v1 (patterns),
    lo migra automaticamente a v2 (rules).
    """
    if not path.exists():
        return {
            "_meta": {
                "version": "2.0",
                "total_rules": 0,
                "last_updated": "",
                "project_slug": "",
            },
            "rules": [],
        }
    data = load_json(path)
    if "patterns" in data and "rules" not in data:
        data = _migrate_v1_to_v2(data)
    return data


def _migrate_v1_to_v2(old: dict) -> dict:
    """
    Migrazione automatica dal formato v1 (patterns) al formato v2 (rules).
    I vecchi pattern vengono convertiti in generation_policy rule generiche,
    preservando description e occurrences. Non deduplica automaticamente:
    la deduplicazione avviene sui verbali futuri.
    """
    print(
        "⚠  Formato correction_log v1 rilevato. Migrazione automatica a v2...\n"
        "   Per una migrazione completa con deduplicazione, aggiorna il file\n"
        "   manualmente seguendo lo schema v2.\n"
    )
    rules = []
    for p in old.get("patterns", []):
        category = p.get("category", "unknown")
        pid = p.get("pattern_id", f"CRR-{len(rules)+1:03d}")
        new_id = re.sub(r"CRR-", "RULE-", pid)
        rule = {
            "rule_id":        new_id,
            "type":           "generation_policy",
            "deterministic":  False,
            "applies_to":     category,
            "occurrences":    p.get("occurrences", 1),
            "verbali":        [p["verbale"]] if p.get("verbale") else [],
            "first_seen":     p.get("first_seen", ""),
            "last_seen":      p.get("last_seen", ""),
            "description":    p.get("description", ""),
            "status":         "active",
            "_fingerprint":   f"migrated:{pid}",
            "_migrated_from": pid,
        }
        rules.append(rule)
    meta = old.get("_meta", {})
    meta["version"] = "2.0"
    meta["total_rules"] = len(rules)
    meta.pop("total_patterns", None)
    return {"_meta": meta, "rules": rules}


def next_rule_id(log: dict) -> str:
    nums = [
        int(r["rule_id"].split("-")[1])
        for r in log.get("rules", [])
        if re.match(r"RULE-\d+", r.get("rule_id", ""))
    ]
    return f"RULE-{(max(nums, default=0) + 1):03d}"


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
# Rule fingerprinting & merging
# ---------------------------------------------------------------------------

_ALMAVIVA_ORGS = {"almaviva", "almaviva s.p.a.", "almaviva spa"}
_INPS_ORGS     = {"inps"}
_ORG_NAMES     = _ALMAVIVA_ORGS | _INPS_ORGS

# Artefatti noti del reverse mapper: delta costanti su "Scopo del documento"
# prodotti dal prefisso fisso del template INPS, non da modifiche dell'utente.
_REVERSE_MAPPER_ARTIFACTS = {
    ("scopo del documento", 162),
    ("scopo del documento", -156),
}


def _field_template(field: str) -> str:
    """Normalizza un field path rimuovendo gli indici: actions[3].owner → actions[*].owner"""
    return re.sub(r'\[\d+\]', '[*]', field)


def _normalize_org(value: str) -> str:
    """Normalizza i nomi organizzazione alla forma canonica."""
    norm = normalize(value)
    if norm in _ALMAVIVA_ORGS:
        return "Almaviva"
    if norm in _INPS_ORGS:
        return "INPS"
    return value


def _classify_owner(value: str, thesaurus: dict) -> str:
    """
    Classifica il valore di un campo owner in una categoria semantica.
    Gestisce anche nomi multipli separati da '/'.
    """
    norm = normalize(value)
    if norm in _ORG_NAMES:
        return "org_name"
    if not norm or norm == "-":
        return "empty"

    # Gestione "Nome A / Nome B"
    parts_slash = [n.strip() for n in value.split("/") if n.strip()]
    if len(parts_slash) > 1:
        classes = [_classify_owner(n, thesaurus) for n in parts_slash]
        if all(c == "person_almaviva" for c in classes):
            return "person_almaviva"
        if all(c == "person_inps" for c in classes):
            return "person_inps"
        if all(c.startswith("person_") for c in classes):
            return "person_name"
        return "mixed"

    # Cerca nel thesaurus
    p = find_thesaurus_participant(thesaurus, value)
    if p:
        org = normalize(p.get("organization", ""))
        if org in _ALMAVIVA_ORGS:
            return "person_almaviva"
        if org in _INPS_ORGS:
            return "person_inps"
        return "person_unknown"

    # Euristica: 2+ parole iniziali maiuscole → probabilmente nome persona
    words = value.strip().split()
    if len(words) >= 2 and all(w[0].isupper() for w in words if w):
        return "person_name"
    return "other"


def _is_reverse_mapper_artifact(change: dict) -> bool:
    """
    Ritorna True se il change è un artefatto noto del docx_reverse_map.py
    (prefisso fisso del template INPS sulla sezione 'Scopo del documento').
    """
    title = normalize(change.get("title", ""))
    delta = change.get("char_delta", None)
    if delta is not None and (title, delta) in _REVERSE_MAPPER_ARTIFACTS:
        return True
    # Delta trascurabile (<= 5 char) su scopo del documento → rumore
    if "scopo del documento" in title and delta is not None and abs(delta) <= 5:
        return True
    return False


def _fingerprint_action_change(change: dict, thesaurus: dict) -> str | None:
    """
    Calcola il fingerprint semantico di un change su actions.
    Ritorna None se non classificabile deterministicamente.
    """
    field     = _field_template(change.get("field", ""))
    original  = change.get("original", "")
    corrected = change.get("corrected", "")

    if field == "actions[*].owner":
        orig_cls = _classify_owner(original, thesaurus)
        corr_cls = _classify_owner(corrected, thesaurus)
        # Persona → Organizzazione: normalizzazione standard
        if orig_cls in ("person_almaviva", "person_inps", "person_name", "mixed") \
                and corr_cls == "org_name":
            return "actions[*].owner:person_to_org"
        # Organizzazione → Organizzazione diversa: riassegnazione semantica
        if orig_cls == "org_name" and corr_cls == "org_name":
            return "actions[*].owner:org_reassignment"

    if field == "actions[*].status":
        if (not original or original == "-") and normalize(corrected) == "open":
            return "actions[*].status:default_open"

    if field == "actions[*].action":
        orig_n = normalize(original)
        corr_n = normalize(corrected)
        destructive    = re.search(r'\b(rimuov|elimin|cancel)\w*', orig_n)
        transformative = re.search(r'\b(dinamizz|aggiorn|modific|trasform)\w*', corr_n)
        if destructive and transformative:
            return "actions[*].action:verb_destructive_to_transformative"

    return None


def _fingerprint_section_change(change: dict) -> str | None:
    """Fingerprint semantico per un change su sections."""
    if _is_reverse_mapper_artifact(change):
        return "artifact:reverse_mapper:scopo_doc_delta"

    title = normalize(change.get("title", ""))
    delta = change.get("char_delta", 0)

    if "scopo del documento" in title:
        return "sections[1]:scopo_doc_content"

    # Riduzione significativa del contenuto → verbosity policy
    if delta is not None and delta < -80:
        return "sections[*]:verbosity_reduction"

    return None


def find_matching_rule(log: dict, fingerprint: str) -> dict | None:
    """Cerca la prima rule attiva con il dato fingerprint."""
    for r in log.get("rules", []):
        if r.get("_fingerprint") == fingerprint and r.get("status") == "active":
            return r
    return None


def merge_into_rule(rule: dict, verbale: str) -> None:
    """Aggiorna una rule esistente: occurrences++, last_seen, verbali."""
    rule["occurrences"] = rule.get("occurrences", 1) + 1
    rule["last_seen"]   = verbale
    verbali = rule.setdefault("verbali", [])
    if verbale not in verbali:
        verbali.append(verbale)


# ---------------------------------------------------------------------------
# Rule templates (descrizioni auto-generate per fingerprint noti)
# ---------------------------------------------------------------------------

_RULE_TEMPLATES: dict[str, dict] = {
    "actions[*].owner:person_to_org": {
        "type":          "field_value_override",
        "deterministic": True,
        "applies_to":    "actions[*].owner",
        "description": (
            "Usare la denominazione organizzativa per il campo owner delle azioni "
            "('Almaviva' per i membri del team di sviluppo, 'INPS' per i referenti "
            "cliente), non il nominativo individuale del partecipante, salvo che la "
            "responsabilità sia esplicitamente e nominalmente attribuita nella trascrizione."
        ),
    },
    "actions[*].owner:org_reassignment": {
        "type":          "ownership_policy",
        "deterministic": False,
        "applies_to":    "actions[*].owner",
        "description": (
            "Assegnare a INPS le azioni che richiedono chiarimento o decisione su "
            "requisiti funzionali; assegnare ad Almaviva le attività di sviluppo tecnico. "
            "La sola appartenenza organizzativa del partecipante non è sufficiente: "
            "valutare il tipo di azione."
        ),
    },
    "actions[*].status:default_open": {
        "type":          "field_default",
        "deterministic": True,
        "applies_to":    "actions[*].status",
        "corrected_to":  "open",
        "description": (
            "Inizializzare sempre il campo status di ogni azione al valore 'open' "
            "per i verbali nuovi; non lasciarlo vuoto o '-'."
        ),
    },
    "actions[*].action:verb_destructive_to_transformative": {
        "type":          "generation_policy",
        "deterministic": False,
        "applies_to":    "actions[*].action",
        "description": (
            "Quando un'azione riguarda la modifica comportamentale di un elemento UI "
            "(es. testo che cambia stato, contenuto che si aggiorna dinamicamente), "
            "usare verbi trasformativi ('dinamizzare', 'aggiornare', 'modificare') "
            "anziché distruttivi ('rimuovere', 'eliminare'), salvo che la rimozione "
            "sia esplicitamente confermata nella trascrizione."
        ),
    },
    "artifact:reverse_mapper:scopo_doc_delta": {
        "type":          "artifact_filter",
        "deterministic": True,
        "applies_to":    "sections[1].content",
        "description": (
            "Il delta di caratteri sulla sezione 'Scopo del documento' prodotto da "
            "docx_reverse_map.py è un artefatto del prefisso fisso del template INPS, "
            "non una modifica dell'utente. Ignorare questo delta nell'analisi."
        ),
    },
    "sections[1]:scopo_doc_content": {
        "type":          "content_override",
        "deterministic": True,
        "applies_to":    "sections[1].content",
        "corrected_to": (
            "Il presente documento riporta la trascrizione di quanto è stato discusso "
            "e stabilito durante lo svolgimento della riunione."
        ),
        "description": (
            "La sezione 'Scopo del documento' deve contenere esclusivamente la frase "
            "boilerplate standard del template INPS, senza riassumere il contenuto "
            "del verbale."
        ),
    },
    "sections[*]:verbosity_reduction": {
        "type":          "generation_policy",
        "deterministic": False,
        "applies_to":    "sections[*].content",
        "description": (
            "Per il livello di sintesi 'resolved', ogni paragrafo deve contenere "
            "unicamente la decisione finale e il suo impatto operativo; omettere "
            "le motivazioni tecniche di dettaglio, i ragionamenti intermedi, le "
            "ipotesi non confermate, le date marcate come indicative e le osservazioni "
            "interne non pertinenti al verbale formale."
        ),
    },
    "sections.first_thematic_number": {
        "type":          "generation_policy",
        "deterministic": True,
        "applies_to":    "sections[*].number",
        "description": (
            "Numerare le sezioni tematiche in sequenza consecutiva senza salti "
            "(1, 2, 3, 4, …). Non saltare posizioni né iniziare da un numero errato."
        ),
    },
    "vocabulary:term_substitutions": {
        "type":          "vocabulary_substitution",
        "deterministic": True,
        "applies_to":    "sections[*].content,actions[*].action",
        "description":   "Sostituzioni lessicali confermate dalle revisioni.",
    },
    "actions.inclusion_policy": {
        "type":          "generation_policy",
        "deterministic": False,
        "applies_to":    "actions",
        "description": (
            "Includere un'azione nel verbale solo se nella trascrizione è presente "
            "un'assegnazione esplicita o un accordo confermato tra i partecipanti. "
            "Non trasformare in azione segnalazioni informali o verifiche tentative."
        ),
    },
    "actions.formatting_exception": {
        "type":          "generation_policy",
        "deterministic": False,
        "applies_to":    "actions[*].action",
        "description": (
            "Quando si descrivono azioni di uniformazione della formattazione "
            "numerica o valutaria, specificare esplicitamente l'eccezione per i "
            "form e i campi di input numerico."
        ),
    },
}


def _build_rule(fingerprint: str, verbale: str, corrected_to: str = "") -> dict:
    """Crea una nuova rule da un fingerprint noto usando il template corrispondente."""
    template = _RULE_TEMPLATES.get(fingerprint, {})
    rule: dict = {
        "rule_id":       "",   # assegnato dal chiamante
        "type":          template.get("type", "generation_policy"),
        "deterministic": template.get("deterministic", False),
        "applies_to":    template.get("applies_to", "unknown"),
        "occurrences":   1,
        "verbali":       [verbale],
        "first_seen":    verbale,
        "last_seen":     verbale,
        "description":   template.get("description", ""),
        "status":        "active",
        "_fingerprint":  fingerprint,
    }
    effective_corrected = template.get("corrected_to", corrected_to)
    if effective_corrected:
        rule["corrected_to"] = effective_corrected
    if template.get("condition"):
        rule["condition"] = template["condition"]
    return rule


def _upsert_rule(log: dict, fingerprint: str, verbale: str,
                 corrected_to: str = "", report: list | None = None) -> None:
    """
    Cerca una rule con lo stesso fingerprint:
    - Se trovata e senza conflitto → merge (occurrences++, last_seen, verbali)
    - Se trovata con corrected_to diverso → marca 'conflicted' e avvisa
    - Se non trovata → crea nuova rule
    """
    if report is None:
        report = []

    existing = find_matching_rule(log, fingerprint)
    if existing:
        if corrected_to:
            ex_corr = normalize(existing.get("corrected_to", ""))
            if ex_corr and ex_corr != normalize(corrected_to):
                msg = (
                    f"  ⚠ CONFLITTO {existing['rule_id']}: "
                    f"valore atteso '{existing['corrected_to']}' vs "
                    f"nuova osservazione '{corrected_to}' (verbale {verbale}). "
                    f"Rule marcata 'conflicted' — revisione manuale necessaria."
                )
                report.append(msg)
                existing["status"] = "conflicted"
                return
        merge_into_rule(existing, verbale)
        report.append(
            f"  ↑ {existing['rule_id']} aggiornata "
            f"(occurrences={existing['occurrences']})"
        )
    else:
        rule           = _build_rule(fingerprint, verbale, corrected_to)
        rule["rule_id"] = next_rule_id(log)
        log["rules"].append(rule)
        report.append(f"  + {rule['rule_id']} creata: {fingerprint}")


# ---------------------------------------------------------------------------
# Diff sections
# ---------------------------------------------------------------------------

def diff_participants(gen: dict, rev: dict, thesaurus: dict, log: dict,
                      report: list, date: str) -> int:
    """
    Confronta i partecipanti. Le correzioni confermane aggiornano direttamente
    il thesaurus (non generano rule: il thesaurus è la fonte di verità sui
    partecipanti).
    """
    gen_map = {normalize(p["name"]): p for p in gen.get("meeting", {}).get("participants", [])}
    rev_map = {normalize(p["name"]): p for p in rev.get("meeting", {}).get("participants", [])}
    changes = 0

    for norm_name, rev_p in rev_map.items():
        if norm_name not in gen_map:
            continue
        gen_p = gen_map[norm_name]
        name  = rev_p.get("name", "")

        for field in ("role", "organization"):
            gen_val = gen_p.get(field, "")
            rev_val = rev_p.get(field, "")
            if normalize(gen_val) != normalize(rev_val) and rev_val not in ("", "-"):
                changes += 1
                report.append(f"  ~ {field.upper()} '{name}': '{gen_val}' → '{rev_val}'")
                tp = find_thesaurus_participant(thesaurus, name)
                if tp is not None:
                    tp[field] = rev_val
                    tp["status"] = "confirmed"
                    tp.pop(f"_pending_{field}", None)

    return changes


def diff_glossary(gen: dict, rev: dict, thesaurus: dict, log: dict,
                  report: list, date: str) -> int:
    """
    Confronta il glossario. Le correzioni aggiornano il thesaurus direttamente.
    """
    gen_map = {normalize(g["term"]): g for g in gen.get("glossary", [])}
    rev_map = {normalize(g["term"]): g for g in rev.get("glossary", [])}
    changes = 0

    for norm_term, rev_g in rev_map.items():
        term = rev_g.get("term", "")
        if norm_term not in gen_map:
            report.append(f"  + NUOVO termine (aggiunto nella revisione): '{term}'")
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
            changes += 1
            report.append(f"  ~ DEFINIZIONE '{term}' modificata")
            tt = find_thesaurus_term(thesaurus, term)
            if tt is not None:
                tt["description"] = rev_val
                tt["status"]      = "confirmed"
                tt.pop("_pending_description", None)

    for norm_term, gen_g in gen_map.items():
        if norm_term not in rev_map:
            report.append(f"  - TERMINE rimosso nella revisione: '{gen_g.get('term', '')}'")

    return changes


def diff_actions(gen: dict, rev: dict, thesaurus: dict, log: dict,
                 report: list, date: str) -> int:
    """
    Confronta le azioni. Ogni change viene fingerprinted: se corrisponde a una
    rule esistente → merge; se nuovo pattern riconoscibile → nuova rule;
    se non classificabile → solo report (nessuna rule creata).
    """
    gen_actions = gen.get("actions", [])
    rev_actions = rev.get("actions", [])
    total = 0

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
                total += 1
                change = {
                    "field":     f"actions[{i}].{field}",
                    "original":  gen_val,
                    "corrected": rev_val,
                }
                label = f"#{i+1} '{gen_a.get('action', '')[:40]}...'"
                report.append(
                    f"  ~ {field.upper()} azione {label}: '{gen_val}' → '{rev_val}'"
                )
                fp = _fingerprint_action_change(change, thesaurus)
                if fp:
                    corrected_to = _normalize_org(rev_val) if field == "owner" else (
                        rev_val if field == "status" else ""
                    )
                    _upsert_rule(log, fp, date, corrected_to=corrected_to, report=report)

    return total


def diff_sections(gen: dict, rev: dict, log: dict, report: list, date: str) -> int:
    """
    Confronta le sezioni. Filtra gli artefatti noti del reverse mapper prima di
    fingerprint e conteggio. Registra solo modifiche reali.
    """
    gen_map = {str(s["number"]): s for s in gen.get("sections", [])}
    rev_map = {str(s["number"]): s for s in rev.get("sections", [])}
    total = 0

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
            change = {
                "field":           f"sections[{num}]",
                "title":           rev_s.get("title", ""),
                "original_length": len(gen_text),
                "revised_length":  len(rev_text),
                "char_delta":      delta,
            }

            if _is_reverse_mapper_artifact(change):
                report.append(
                    f"  ◌ SEZIONE {num} '{rev_s.get('title', '')}': "
                    f"delta artefatto reverse mapper ({sign}{delta} car) — ignorato"
                )
                _upsert_rule(
                    log, "artifact:reverse_mapper:scopo_doc_delta",
                    date, report=report
                )
                continue

            total += 1
            report.append(
                f"  ~ SEZIONE {num} '{rev_s.get('title', '')}': "
                f"testo modificato ({sign}{delta} caratteri)"
            )
            fp = _fingerprint_section_change(change)
            if fp:
                _upsert_rule(log, fp, date, report=report)

    for num in gen_map:
        if num not in rev_map:
            report.append(f"  - SEZIONE {num} rimossa nella revisione")

    return total


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

    slug   = gen.get("document", {}).get("project_slug", "").strip()
    kb_dir = resolve_kb_dir(gen)
    thesaurus_filename      = f"thesaurus_{slug}.json"      if slug else "thesaurus_global.json"
    correction_log_filename = f"correction_log_{slug}.json" if slug else "correction_log_global.json"
    thesaurus_path      = kb_dir / thesaurus_filename
    correction_log_path = kb_dir / correction_log_filename

    thesaurus = load_thesaurus(thesaurus_path)
    log       = load_correction_log(correction_log_path)

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
    print(f"  generato    : {gen_path.name}")
    print(f"  revisionato : {rev_path.name}")
    print(f"  KB          : {kb_dir}")
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
    n_a = diff_actions(gen, rev, thesaurus, log, report, date)
    if n_a == 0:
        report.append("  Nessuna modifica")

    report.append("\nSEZIONI:")
    n_s = diff_sections(gen, rev, log, report, date)
    if n_s == 0:
        report.append("  Nessuna modifica")

    total = n_p + n_g + n_a + n_s

    # Aggiorna metadata
    log["_meta"]["version"]      = "2.0"
    log["_meta"]["total_rules"]  = len(log["rules"])
    log["_meta"]["last_updated"] = datetime.now().strftime("%d/%m/%Y")
    if slug and not log["_meta"].get("project_slug"):
        log["_meta"]["project_slug"] = slug

    save_json(thesaurus_path, thesaurus)
    save_json(correction_log_path, log)

    for line in report:
        print(line)

    conflicted   = [r for r in log["rules"] if r.get("status") == "conflicted"]
    new_rules    = [r for r in log["rules"] if date in r.get("verbali", [])
                    and r.get("first_seen") == date]
    merged_count = sum(
        1 for r in log["rules"]
        if date in r.get("verbali", []) and r.get("first_seen") != date
    )

    print(f"\n{sep}")
    print(f"Totale modifiche reali rilevate : {total}")
    print(f"Nuove rule create               : {len(new_rules)}")
    print(f"Rule aggiornate (merge)         : {merged_count}")
    print(f"Rule totali in KB               : {len(log['rules'])}")
    if conflicted:
        print(
            f"⚠  Rule in conflitto ({len(conflicted)}): "
            f"{', '.join(r['rule_id'] for r in conflicted)}"
        )
        print("   Revisione manuale necessaria.")
    if total > 0:
        print("Thesaurus e correction_log aggiornati.")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
