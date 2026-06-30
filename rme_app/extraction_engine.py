"""
extraction_engine.py — Generic disease-agnostic extraction engine.
===============================================================
Reads disease profile JSON → builds extractors dynamically.
No disease-specific hardcode — all logic lives in JSON profiles.

Architecture:
  1. Load profile JSON (disease_profiles/stroke_infark.json, etc.)
  2. For each category:
     - type "builtin"  → delegate to existing function from pipeline_core
     - type "regex"     → generic regex engine (patterns per field)
     - type "keyword"   → generic keyword search (keywords per field)
  3. Aggregate results → dict per patient

Builtin extractors are imported from pipeline_core (no code duplication).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# ── Import utility functions from pipeline_core (NO duplication) ──
# pipeline_core lives one level up in cp_stroke_app/
_CORE_DIR = Path(__file__).resolve().parent.parent / "cp_stroke_app"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

try:
    from pipeline_core import (
        # Utility
        normalize_text, get_doc_type, clean_snippet, first_by_priority,
        context, parse_indonesian_date,
        # File reading
        read_patient_files,
        # Builtin extractors
        extract_demographics,
        extract_diagnosis,
        extract_gcs,
        extract_vitals,
        extract_ct_scan,
        extract_thorax,
        extract_lab_dates,
        extract_lab_values,
        extract_demam,
        extract_medications,
        extract_risk_factors,
        extract_actions,
        extract_outcome,
        # Validation
        validate_extracted_data,
        # Drug loading
        get_drug_keywords,
    )
    _CORE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] pipeline_core not available: {e}")
    _CORE_AVAILABLE = False


# ================================================================
# PATHS
# ================================================================

APP_DIR = Path(__file__).resolve().parent
PROFILES_DIR = APP_DIR / "disease_profiles"
DRUG_PROFILES_DIR = APP_DIR / "drug_profiles"


# ================================================================
# BUILTIN EXTRACTOR REGISTRY
# ================================================================
# Maps "extractor" name in JSON → actual function.
# This is the ONLY place where builtin names are registered.

BUILTIN_EXTRACTORS: dict[str, Callable | None] = {}

def _register_builtins():
    """Register all builtin extractors. Called once at import."""
    if not _CORE_AVAILABLE:
        return
    BUILTIN_EXTRACTORS.update({
        "demographics": extract_demographics,
        "diagnosis": extract_diagnosis,
        "gcs": extract_gcs,  # special: returns str, not dict
        "vitals": extract_vitals,
        "ct_scan": extract_ct_scan,
        "thorax": extract_thorax,
        "lab_dates": extract_lab_dates,
        "lab_values": extract_lab_values,
        "demam": extract_demam,
        "medications": extract_medications,
        "risk_factors": extract_risk_factors,
        "actions": extract_actions,
        "outcome": extract_outcome,
    })

_register_builtins()


# ================================================================
# PROFILE LOADER
# ================================================================

def list_profiles() -> list[dict[str, str]]:
    """List all available disease profiles.
    
    Returns:
        list of {name, file, description} dicts
    """
    profiles = []
    if not PROFILES_DIR.exists():
        return profiles
    for fp in sorted(PROFILES_DIR.glob("*.json")):
        if fp.name.startswith("_"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            profiles.append({
                "name": data.get("name", fp.stem),
                "file": fp.name,
                "description": data.get("description", ""),
                "version": data.get("version", "1.0"),
                "drug_profile": data.get("drug_profile"),
                "category_count": len(data.get("categories", {})),
            })
        except Exception:
            pass
    return profiles


def load_profile(profile_name: str) -> dict:
    """Load a disease profile by name or filename.
    
    Args:
        profile_name: e.g. "Stroke Infark" or "stroke_infark.json"
    
    Returns:
        Profile dict with parsed categories.
    
    Raises:
        FileNotFoundError: if profile not found
        ValueError: if profile JSON is invalid
    """
    # Try direct filename first
    fp = PROFILES_DIR / profile_name
    if not fp.exists():
        # Try with .json extension
        fp = PROFILES_DIR / f"{profile_name}.json"
    if not fp.exists():
        # Search by "name" field
        for f in PROFILES_DIR.glob("*.json"):
            if f.name.startswith("_"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("name", "").lower() == profile_name.lower():
                    fp = f
                    break
            except Exception:
                continue
    
    if not fp.exists():
        raise FileNotFoundError(f"Profile not found: {profile_name}")
    
    data = json.loads(fp.read_text(encoding="utf-8"))
    if "categories" not in data:
        raise ValueError(f"Profile missing 'categories': {fp.name}")
    
    return data


def load_drug_profile(profile_name: str | None) -> dict[str, list[str]]:
    """Load drug keywords from a drug profile JSON.
    
    Args:
        profile_name: filename in drug_profiles/ (e.g. "stroke.json")
    
    Returns:
        dict of {drug_key: [keywords]}
    """
    if not profile_name:
        return {}
    fp = DRUG_PROFILES_DIR / profile_name
    if not fp.exists():
        return {}
    return json.loads(fp.read_text(encoding="utf-8"))


# ================================================================
# GENERIC EXTRACTORS
# ================================================================

def _extract_regex(files: list[dict], category: dict) -> dict[str, str]:
    """Generic regex extractor. Reads patterns from category JSON.
    
    For each field, applies its regex pattern to all files.
    Uses capture group 1 as the value. If no group, returns "ada"/"tidak".
    Doc type filtering via optional "doc_types" list.
    
    Priority: doc_types order (first match wins).
    
    Pattern format per field:
      - str  → plain regex, flags: re.I (default)
      - dict → {"pattern": "...", "dotall": true/false, "doc_types": [...]}
        dotall=true enables re.S (.* menelan newline), default false
    """
    patterns = category.get("patterns", {})
    doc_types = category.get("doc_types", [])  # optional filter
    
    result: dict[str, str] = {}
    
    for field_name, pat_spec in patterns.items():
        # Support both old string format and new dict format
        if isinstance(pat_spec, dict):
            pattern = pat_spec["pattern"]
            use_dotall = pat_spec.get("dotall", False)
            field_doc_types = pat_spec.get("doc_types", doc_types)
        else:
            pattern = pat_spec
            use_dotall = False
            field_doc_types = doc_types
        
        flags = re.I | (re.S if use_dotall else 0)
        compiled = re.compile(pattern, flags)
        best_match = None
        best_priority = 999
        
        for f in files:
            # Filter by doc_type if specified
            if field_doc_types and f["doc_type"] not in field_doc_types:
                continue
            
            priority = field_doc_types.index(f["doc_type"]) if field_doc_types and f["doc_type"] in field_doc_types else 99
            
            for m in compiled.finditer(f["text"]):
                if priority < best_priority or (priority == best_priority and best_match is None):
                    # Has capture group?
                    if m.lastindex and m.lastindex >= 1:
                        best_match = clean_snippet(m.group(1).strip(), 500)
                    else:
                        best_match = "ada"
                    best_priority = priority
                    break  # first match in this file is enough
        
        result[field_name] = best_match if best_match else None  # not found — missing
    
    return result


_NEGATION_WORDS = frozenset({
    "tidak", "tanpa", "negatif", "minus", "absen", "nihil", "kosong",
    "bukan", "belum", "non",
})
_POSITIVE_MARKERS = frozenset({"(+)", "positif", "ada", "terdapat", "ditemukan"})
_NEGATION_WINDOW = 5  # tokens before/after keyword to check for negation


def _check_negation(text_lower: str, keyword: str, window: int = _NEGATION_WINDOW) -> bool:
    """Check if keyword is negated within a context window.
    
    Returns True if ALL occurrences of keyword are negated.
    If ANY occurrence has a positive marker (e.g. "demam (+)"), returns False.
    
    Strategy:
      1. Find all keyword positions in text
      2. For each, extract N tokens before and after
      3. If ANY occurrence is unambiguously positive → not negated
      4. If ALL occurrences are negated → negated
    """
    tokens = text_lower.split()
    kw_lower = keyword.lower()
    
    found_positive = False
    found_negated = False
    
    for i, tok in enumerate(tokens):
        # Check if this token matches the keyword
        if tok == kw_lower or kw_lower in tok:
            # Look before keyword for negation
            start = max(0, i - window)
            before_tokens = tokens[start:i]
            after_tokens = tokens[i+1:i+1+window]
            
            # Check for positive markers that override (e.g. "demam (+)")
            has_positive = any(
                t in _POSITIVE_MARKERS or "(+)" in t
                for t in after_tokens[:3]  # close positive marker
            )
            
            if has_positive:
                found_positive = True
                continue  # this occurrence is positive, check others
            
            # Check for negation in "before" window
            has_negation_before = any(t in _NEGATION_WORDS for t in before_tokens)
            # Check for negation in "after" window (e.g. "demam tidak ada")
            has_negation_after = any(t in _NEGATION_WORDS for t in after_tokens)
            
            if has_negation_before or has_negation_after:
                found_negated = True
    
    # If any occurrence is positive, keyword is NOT negated overall
    if found_positive:
        return False
    return found_negated


def _extract_keyword(files: list[dict], category: dict) -> dict[str, str | None]:
    """Generic keyword extractor with word-boundary + negation detection.
    
    For each field:
      1. Check if any keyword exists with \\b word boundaries (no substring false positives)
      2. If found, check for negation within N-token window
      3. Returns:
         - "ada"   → keyword found + positive context
         - "tidak" → keyword found + negated context (e.g. "tidak ada demam")
         - None    → keyword not found in text at all (missing/undocumented)
    """
    keywords_map = category.get("keywords", {})
    
    # Combine all text (preserve per-file for context)
    all_text = " ".join(f["text"] for f in files)
    all_text_lower = all_text.lower()
    
    result: dict[str, str | None] = {}
    for field_name, keywords in keywords_map.items():
        found = False
        negated = False
        
        for kw in keywords:
            kw_escaped = re.escape(kw)
            # Word boundary match — prevents substring false positives
            # e.g. "stroke" won't match "antistroke" or "strokes" incorrectly
            pattern = r'\b' + kw_escaped + r'\b'
            if re.search(pattern, all_text_lower, re.IGNORECASE):
                found = True
                # Check negation context
                if _check_negation(all_text_lower, kw):
                    negated = True
                else:
                    negated = False  # positive override if multiple keywords
                    break  # confirmed positive, stop
        
        if found and not negated:
            result[field_name] = "ada"
        elif found and negated:
            result[field_name] = "tidak"
        else:
            result[field_name] = None  # not found at all — missing/undocumented
    
    return result


def _extract_builtin(files: list[dict], category: dict, 
                     drug_profile: dict[str, list[str]] | None = None,
                     selected_drug_keys: list[str] | None = None) -> dict[str, str | None]:
    """Delegate to a builtin extractor function from pipeline_core.
    
    Post-processes: converts "unknown" sentinel from pipeline_core → None (missing).
    """
    extractor_name = category.get("extractor", "")
    fn = BUILTIN_EXTRACTORS.get(extractor_name)
    
    if fn is None:
        # Fallback: all None (missing)
        return {f: None for f in category["fields"]}
    
    # Special case: GCS returns str, not dict
    if extractor_name == "gcs":
        val = fn(files)
        return {"gcs": val if val != "unknown" else None}
    
    # Special case: medications needs drug keys
    if extractor_name == "medications":
        data = fn(files, selected_drug_keys)
    else:
        # Standard: fn(files) → dict
        data = fn(files)
    
    # Convert "unknown" sentinel → None (missing/undocumented)
    return {k: (None if v == "unknown" else v) for k, v in data.items()}


# ================================================================
# TYPE COERCION — convert extracted values to proper types
# ================================================================

def coerce_extracted_types(
    result: dict[str, Any],
    profile: dict,
) -> dict[str, Any]:
    """Convert extracted string values to proper Python types based on field_types metadata.
    
    Field type spec in profile JSON (top-level "field_types" dict):
      - "numeric"  → int if whole number, float if decimal, None if not parseable
      - "boolean"  → kept as-is ("ada"/"tidak"/None)
      - "text"     → kept as-is (default if not specified)
    
    Rules:
      - None stays None (missing data)
      - "ada"/"tidak"/"tidak_ada"/"ada (+)" → kept as string (categorical)
      - "invalid" → kept as string (validation marker)
      - Numeric strings → converted to int/float
      - Empty string "" → None
    
    Args:
        result: dict from extract_one_patient (values are str | None)
        profile: loaded disease profile JSON (must contain "field_types")
    
    Returns:
        Same dict with values converted to proper types.
    """
    field_types = profile.get("field_types", {})
    
    for field, ftype in field_types.items():
        if field not in result:
            continue
        
        val = result[field]
        
        # Skip None (missing) — stays None
        if val is None:
            continue
        
        # Skip categorical markers
        if val in ("ada", "tidak", "tidak_ada", "invalid", "ada (+)"):
            continue
        # Also skip any "ada" variant or known categorical
        if isinstance(val, str) and val.startswith("ada"):
            continue
        
        if ftype == "numeric":
            result[field] = _coerce_numeric(val)
        # "boolean" and "text" → no conversion needed
    
    # Global cleanup: empty strings → None
    for field, val in list(result.items()):
        if val == "":
            result[field] = None
    
    return result


def _coerce_numeric(val: str) -> int | float | None:
    """Convert a string to int or float. Returns None if not parseable."""
    if not val or not isinstance(val, str):
        return None
    
    # Clean: remove commas in numbers, strip whitespace
    cleaned = val.strip().replace(",", ".")
    
    # Try int first (whole numbers)
    try:
        int_val = int(float(cleaned))
        if str(int_val) == cleaned or str(float(int_val)) == cleaned:
            return int_val
    except (ValueError, OverflowError):
        pass
    
    # Try float
    try:
        return float(cleaned)
    except (ValueError, OverflowError):
        return None


# ================================================================
# MAIN EXTRACTION ENGINE
# ================================================================

def extract_one_patient(
    patient_dir: Path,
    profile: dict,
    selected_categories: list[str] | None = None,
    selected_fields: dict[str, list[str]] | None = None,
    selected_drug_keys: list[str] | None = None,
) -> dict[str, str]:
    """Extract data from one patient's anonymized files using a disease profile.
    
    Args:
        patient_dir: path to patient's anonymized text folder
        profile: loaded disease profile dict
        selected_categories: categories to extract (None = all)
        selected_fields: {category: [field1, ...]} filter (None = all)
        selected_drug_keys: drug sub-categories to extract (None = all)
    
    Returns:
        dict of extracted field values
    """
    patient_id = patient_dir.name
    result: dict[str, str] = {"patient_id": patient_id}
    
    if not patient_dir.exists() or not patient_dir.is_dir():
        result["error"] = "folder_not_found"
        return result
    
    # Read patient files (reuse pipeline_core function)
    if _CORE_AVAILABLE:
        files = read_patient_files(patient_dir)
    else:
        files = _fallback_read_patient_files(patient_dir)
    
    if not files:
        result["error"] = "no_valid_files"
        return result
    
    categories = profile.get("categories", {})
    drug_profile_name = profile.get("drug_profile")
    drug_profile = load_drug_profile(drug_profile_name) if drug_profile_name else {}
    
    # Filter categories if specified
    if selected_categories is not None:
        categories = {k: v for k, v in categories.items() if k in selected_categories}
    
    for cat_name, cat_def in categories.items():
        cat_type = cat_def.get("type", "unknown")
        fields = cat_def.get("fields", [])
        
        # Filter fields if specified
        if selected_fields and cat_name in selected_fields:
            fields = [f for f in fields if f in selected_fields[cat_name]]
            if not fields:
                continue
        
        # Extract based on type
        if cat_type == "builtin":
            data = _extract_builtin(files, cat_def, drug_profile, selected_drug_keys)
        elif cat_type == "regex":
            data = _extract_regex(files, cat_def)
        elif cat_type == "keyword":
            data = _extract_keyword(files, cat_def)
        else:
            data = {f: None for f in fields}
        
        # Map fields to result
        field_map = {
            "demo_age": "age",
            "demo_gender": "gender",
            "jenis_kelamin": "gender",
        }
        
        for f in fields:
            if f in data:
                result[f] = data[f]
            elif f in field_map and field_map[f] in data:
                result[f] = data[field_map[f]]
            elif f not in result:
                result[f] = None  # missing — not documented
        
        # Merge extra dynamic fields (e.g. drug categories from drug_profile)
        for k, v in data.items():
            if k not in result:
                result[k] = v
    
    # Coerce types based on field_types metadata (string → numeric, etc.)
    result = coerce_extracted_types(result, profile)
    
    # Validate numeric fields (range check)
    if _CORE_AVAILABLE:
        result, _warnings = validate_extracted_data(result)
    
    return result


def extract_all_patients(
    anon_dir: Path | str,
    profile: dict,
    selected_categories: list[str] | None = None,
    selected_fields: dict[str, list[str]] | None = None,
    selected_drug_keys: list[str] | None = None,
) -> list[dict[str, str]]:
    """Extract data from ALL patients in an anonymized directory.
    
    Supports 2 folder structures:
      - NESTED: subfolder per patient (STROKE_001/, STROKE_002/, etc.)
      - FLAT:   all .anon.txt files in root (single virtual patient)
    
    Args:
        anon_dir: path to anonymized text directory
        profile: loaded disease profile dict
    
    Returns:
        list of dicts, one per patient
    """
    anon_dir = Path(anon_dir)
    if not anon_dir.exists():
        return []
    
    patient_dirs = sorted([d.name for d in anon_dir.iterdir() if d.is_dir()])
    flat_files = sorted([f for f in anon_dir.glob("*.anon.txt") if f.is_file()])
    
    results = []
    
    if patient_dirs:
        # NESTED structure
        for pid in patient_dirs:
            r = extract_one_patient(
                anon_dir / pid, profile,
                selected_categories, selected_fields, selected_drug_keys,
            )
            results.append(r)
    elif flat_files:
        # FLAT structure — single virtual patient
        files = []
        for fp in flat_files:
            text = fp.read_text(encoding="utf-8", errors="ignore")
            if len(text.strip()) < 20:
                continue
            files.append({
                "source_file": fp.name,
                "doc_type": get_doc_type(fp.name) if _CORE_AVAILABLE else "other",
                "text": normalize_text(text) if _CORE_AVAILABLE else text,
                "char_count": len(text),
            })
        if files:
            r = _extract_from_files(files, anon_dir.name, profile,
                                   selected_categories, selected_fields, selected_drug_keys)
            results.append(r)
    
    return results


def _extract_from_files(
    files: list[dict],
    patient_id: str,
    profile: dict,
    selected_categories: list[str] | None = None,
    selected_fields: dict[str, list[str]] | None = None,
    selected_drug_keys: list[str] | None = None,
) -> dict[str, str]:
    """Extract from pre-loaded file dicts (for flat structure)."""
    result: dict[str, str] = {"patient_id": patient_id}
    categories = profile.get("categories", {})
    drug_profile_name = profile.get("drug_profile")
    drug_profile = load_drug_profile(drug_profile_name) if drug_profile_name else {}
    
    if selected_categories is not None:
        categories = {k: v for k, v in categories.items() if k in selected_categories}
    
    for cat_name, cat_def in categories.items():
        cat_type = cat_def.get("type", "unknown")
        fields = cat_def.get("fields", [])
        
        if selected_fields and cat_name in selected_fields:
            fields = [f for f in fields if f in selected_fields[cat_name]]
            if not fields:
                continue
        
        if cat_type == "builtin":
            data = _extract_builtin(files, cat_def, drug_profile, selected_drug_keys)
        elif cat_type == "regex":
            data = _extract_regex(files, cat_def)
        elif cat_type == "keyword":
            data = _extract_keyword(files, cat_def)
        else:
            data = {f: None for f in fields}
        
        for f in fields:
            if f in data:
                result[f] = data[f]
            elif f not in result:
                result[f] = None  # missing — not documented
        
        for k, v in data.items():
            if k not in result:
                result[k] = v
    
    # Coerce types based on field_types metadata
    result = coerce_extracted_types(result, profile)
    
    if _CORE_AVAILABLE:
        result, _warnings = validate_extracted_data(result)
    
    return result


def _fallback_read_patient_files(patient_dir: Path) -> list[dict]:
    """Minimal file reader if pipeline_core is not available."""
    files = []
    for fp in sorted(patient_dir.glob("*.anon.txt")):
        text = fp.read_text(encoding="utf-8", errors="ignore")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text.strip()) < 20:
            continue
        name = fp.name.lower()
        doc_type = "other"
        if "resume" in name: doc_type = "resume"
        elif "rad" in name: doc_type = "radiology"
        elif "lab" in name: doc_type = "lab"
        elif "cppt_igd" in name: doc_type = "cppt_igd"
        elif "cppt_ranap" in name or "ranap" in name: doc_type = "cppt_ranap"
        files.append({
            "source_file": fp.name,
            "doc_type": doc_type,
            "text": text,
            "char_count": len(text),
        })
    return files


# ================================================================
# CLI TEST
# ================================================================

if __name__ == "__main__":
    import sys
    
    print("=== Disease Profile System ===\n")
    
    # List profiles
    profiles = list_profiles()
    print(f"Available profiles ({len(profiles)}):")
    for p in profiles:
        print(f"  • {p['name']} ({p['file']}) — {p['category_count']} categories")
        if p['description']:
            print(f"    {p['description']}")
    print()
    
    # If profile name given, load and show details
    if len(sys.argv) > 1:
        profile_name = sys.argv[1]
        try:
            profile = load_profile(profile_name)
            print(f"Profile: {profile['name']} v{profile.get('version', '?')}")
            print(f"Description: {profile.get('description', '-')}")
            print(f"Drug profile: {profile.get('drug_profile', 'none')}")
            print(f"\nCategories ({len(profile['categories'])}):")
            for cat_name, cat_def in profile['categories'].items():
                cat_type = cat_def.get('type', '?')
                fields = cat_def.get('fields', [])
                desc = cat_def.get('desc', '-')
                print(f"  [{cat_type}] {cat_name}: {len(fields)} fields")
                print(f"    Fields: {', '.join(fields)}")
                print(f"    {desc}")
        except Exception as e:
            print(f"Error: {e}")
