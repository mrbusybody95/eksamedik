"""
pipeline_core.py — Inti pipeline anonimisasi + ekstraksi RME Stroke
===============================================================
Digunakan oleh app Streamlit (run_stroke_app.py).
Anonimisasi 100% LOKAL — tidak ada data dikirim ke API eksternal.

Arsitektur:
  1. Baca PDF/TXT → SourceText
  2. Anonimisasi 6 stage × 2 iterasi → teks anonim
  3. Deteksi sisa kebocoran (leftovers)
  4. Ekstraksi data terstruktur → dictionary
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# PDF libraries
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None
try:
    import fitz
except Exception:
    fitz = None
try:
    import pytesseract
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None


# ================================================================
# KONSTANTA
# ================================================================

LABEL = {
    "patient": "[PASIEN]", "family": "[KELUARGA]", "mrn": "[NO_RM]",
    "nik": "[NIK]", "phone": "[NO_HP]", "email": "[EMAIL]",
    "address": "[ALAMAT]", "birth": "[TANGGAL_LAHIR]",
    "sep": "[NO_SEP]", "visit": "[NO_KUNJUNGAN]",
    "lab": "[NO_LAB]", "rad": "[NO_RADIOLOGI]",
    "hospital": "[RUMAH_SAKIT]",
}

SPECIALIST_MAP = {
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI",
    "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",
    "sp.pd": "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.jp": "DOKTER_SPESIALIS_JANTUNG",
    "sp.an": "DOKTER_SPESIALIS_ANESTESI",
    "sp.b": "DOKTER_SPESIALIS_BEDAH",
    "sp.bs": "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot": "DOKTER_SPESIALIS_ORTOPEDI",
    "sp.u": "DOKTER_SPESIALIS_UROLOGI",
    "sp.a": "DOKTER_SPESIALIS_ANAK",
    "sp.og": "DOKTER_SPESIALIS_OBGYN",
    "sp.p": "DOKTER_SPESIALIS_PARU",
    "sp.kfr": "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj": "DOKTER_SPESIALIS_KEDOKTERAN_JIWA",
    "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m": "DOKTER_SPESIALIS_MATA",
    "sp.kk": "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv": "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",
}

CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning",
    "observasi", "pasien", "nyeri", "lemah", "sesak", "muntah",
    "demam", "stroke", "infark", "anamnesis", "pemeriksaan",
    "tekanan", "darah", "suhu", "spo2", "gcs", "ews", "hasil",
    "nilai", "rujukan", "satuan", "alamat", "umur", "tgl",
    "lahir", "hematologi", "hemoglobin", "leukosit", "foto",
    "thorax", "kesan", "cor", "pulmo", "ct", "scan", "kepala",
    "normal", "abnormal", "igd", "ranap",
}

TITLE_WORDS = {
    "dr", "drg", "prof", "sp", "spd", "spn", "sps", "sprad",
    "sppk", "sppa", "sppd", "spjp", "span", "spb", "spbs",
    "spot", "spu", "spa", "spog", "spp", "spkfr", "spkj",
    "sptht", "spm", "spkk", "spdv", "mkes", "mhkes", "mm",
    "mmrs", "msc", "phd", "finasim", "fiha", "kic", "fics",
    "cahm", "khom", "subsp", "h", "hj", "haji", "hajah",
    "kom", "pol",
}

LEFTOVER_PATTERNS = {
    "leftover_nik_16": r"\b\d{16}\b",
    "leftover_phone": r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b",
    "leftover_email": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    "leftover_rm": r"(?i)\b(?:no\.?\s*rm|rekam\s*medis|mrn)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{3,}",
    "leftover_sep": r"(?i)\b(?:no\.?\s*sep|sep)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{5,}",
    "leftover_dr_name": r"(?i)\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
    "leftover_name_comma_dr": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*(?:H\.?|Hj\.?)?\s*drg?\.?:?",
    "leftover_sp": r"(?i)\bSp\.\s*[A-Za-z]{2,}\b",
    "leftover_ners_apt": r"(?i)\b(?:Ners|Ns\.?|Apt\.?|Amd\.?\s*Kep\.?|Amd\.?\s*Rad\.?)\b",
}

# ================================================================
# DATA CLASSES
# ================================================================

@dataclass
class SourceText:
    """Hasil ekstraksi teks dari PDF/TXT."""
    path: Path
    relative_path: Path
    text: str
    extraction_status: str  # txt | pdf_pypdf | pdf_fitz_text | pdf_ocr | pdf_empty_or_failed
    ocr_used: bool = False


@dataclass
class AnonResult:
    """Hasil anonimisasi satu file."""
    source_file: str
    output_file: str
    patient_folder: str
    extraction_status: str
    ocr_used: bool
    chars_in: int
    chars_out: int
    processed_at: str
    needs_manual_review: bool
    counts: dict[str, int] = field(default_factory=dict)
    leftovers: dict[str, int] = field(default_factory=dict)
    leftover_examples: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ProgressState:
    """State progress untuk Streamlit."""
    total: int = 0
    current: int = 0
    current_file: str = ""
    status: str = "idle"  # idle | running | done | error
    start_time: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time if self.start_time else 0.0

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return min(100.0, self.current / self.total * 100.0)

    @property
    def eta(self) -> str:
        if self.current == 0 or self.elapsed < 1:
            return "--:--"
        remaining = (self.elapsed / self.current) * (self.total - self.current)
        m, s = divmod(int(remaining), 60)
        return f"{m:02d}:{s:02d}"


# ================================================================
# UTILITY FUNCTIONS
# ================================================================

def add_count(counts: dict[str, int], key: str, n: int) -> None:
    counts[key] = counts.get(key, 0) + int(n)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text)


def clean_snippet(text: str, max_len: int = 500) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len] + " ...[truncated]"
    return text


def infer_role(s: str) -> str:
    low = s.lower()
    compact = re.sub(r"[\s,\.\-]+", "", low)
    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.sub(r"[\.\s\-]+", "", degree.lower()) in compact:
            return role
    if re.search(r"\bsp\.?\s*[a-z]", low, re.I):
        return "DOKTER_SPESIALIS"
    if re.search(r"\bdrg\.?\b", low, re.I):
        return "DOKTER_GIGI"
    if re.search(r"\bdr\.?\b|\bdr\s*,", low, re.I):
        return "DOKTER_UMUM"
    return "DOKTER"


# ================================================================
# STAFF CSV MANAGEMENT
# ================================================================

def clean_staff_name(name: str) -> str:
    x = name.strip()
    x = re.sub(r"(?i)\b(?:prof\.?|kom\.?\s*pol\.?)\b", " ", x)
    x = re.sub(r"(?i)\bdrg?\.?\s*", " ", x)
    x = re.sub(r"(?i)\bSp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?", " ", x)
    x = re.sub(r"(?i)\bSubsp\.?\s*[A-Za-z\.\-\(\)]+", " ", x)
    x = re.sub(r"(?i)\b(?:M\.?Kes|MH\.?Kes|M\.?Sc|MM|MMRS|PhD|FINASIM|FIHA|KIC|FICS|SH|MH|CAHM|KHOM|CH)\b\.?,?", " ", x)
    x = re.sub(r"(?i)\b(?:H\.?|Hj\.?|Haji|Hajah)\b\.?,?", " ", x)
    x = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'` -]", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def tokens_from_name(name: str) -> list[str]:
    toks = []
    for t in clean_staff_name(name).split():
        t = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'`]", "", t).strip()
        if t and len(t) > 1 and t.lower().strip(".") not in TITLE_WORDS:
            toks.append(t)
    return toks


def build_variants(toks: list[str]) -> set[str]:
    variants = set()
    if len(toks) >= 2:
        variants |= {" ".join(toks), " ".join(toks[:2]), f"{toks[0]} {toks[-1]}"}
    if len(toks) >= 3:
        variants |= {" ".join([toks[0], toks[1], toks[-1]]), " ".join(toks[-2:])}
    if len(toks) >= 4:
        variants |= {" ".join(toks[:3]), " ".join(toks[-3:])}
    safe = set()
    for v in variants:
        low = v.lower().split()
        if len(low) >= 2 and len(v) >= 7 and not any(w in CLINICAL_STOPWORDS for w in low):
            safe.add(v)
    return safe


def load_staff_variants(staff_csv: Path | str | None) -> list[tuple[str, str]]:
    """
    Load staff CSV → list of (variant_name, role).
    CSV minimal columns: name, role (role optional, auto-inferred if empty).
    """
    if isinstance(staff_csv, str):
        staff_csv = Path(staff_csv)
    if not staff_csv or not staff_csv.exists():
        return []
    variants: list[tuple[str, str]] = []
    with staff_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or infer_role(name)
            for v in build_variants(tokens_from_name(name)):
                variants.append((v, role))
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for v, r in sorted(variants, key=lambda x: len(x[0]), reverse=True):
        key = (v.lower(), r)
        if key not in seen:
            seen.add(key)
            out.append((v, r))
    return out


def compile_role_patterns(variants: list[tuple[str, str]]) -> list[tuple[re.Pattern, str]]:
    """Group variants by role → one compiled regex per role. ~8-10x faster."""
    groups: dict[str, list[str]] = {}
    for v, role in variants:
        groups.setdefault(role, []).append(v)
    compiled: list[tuple[re.Pattern, str]] = []
    for role, names in groups.items():
        names.sort(key=len, reverse=True)
        alts = []
        for name in names:
            parts = [re.escape(p) for p in name.split() if p.strip()]
            if parts:
                alts.append(r"(?:\s|,|\.|\-|_)+".join(parts))
        if not alts:
            continue
        pattern_str = r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?![A-Za-z])"
        compiled.append((re.compile(pattern_str, re.I), role))
    return compiled


def load_staff_csv_data(staff_csv: Path | str | None) -> list[dict[str, str]]:
    """Load raw staff CSV data as list of dicts."""
    if isinstance(staff_csv, str):
        staff_csv = Path(staff_csv)
    if not staff_csv or not staff_csv.exists():
        return []
    data = []
    with staff_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            data.append({"name": (row.get("name") or "").strip(),
                          "role": (row.get("role") or "").strip() or infer_role(row.get("name") or "")})
    return data


def save_staff_csv_data(staff_csv: Path | str, data: list[dict[str, str]]) -> None:
    """Save staff data back to CSV."""
    if isinstance(staff_csv, str):
        staff_csv = Path(staff_csv)
    staff_csv.parent.mkdir(parents=True, exist_ok=True)
    with staff_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "role"])
        w.writeheader()
        w.writerows(data)


# ================================================================
# PDF / TEXT EXTRACTION
# ================================================================

def is_text_empty(text: str) -> bool:
    return len(re.sub(r"\s+", "", text or "")) < 50


def read_source(path: Path, root: Path, use_ocr: bool = True) -> SourceText:
    """Read text from PDF or TXT file. Fallback chain: pypdf → fitz → OCR."""
    rel = path.relative_to(root)
    
    # TXT file
    if path.suffix.lower() == ".txt":
        return SourceText(path, rel, path.read_text(encoding="utf-8", errors="ignore"), "txt", False)
    
    text = ""
    # 1. pypdf
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            parts = []
            for i, page in enumerate(reader.pages, 1):
                txt = page.extract_text() or ""
                parts.append(f"\n--- HALAMAN {i}: {path.name} ---\n{txt}")
            text = "\n".join(parts)
        except Exception:
            text = ""
    if not is_text_empty(text):
        return SourceText(path, rel, text, "pdf_pypdf", False)
    
    # 2. fitz (PyMuPDF)
    if fitz is not None:
        try:
            with fitz.open(str(path)) as doc:
                parts = [f"\n--- HALAMAN {i}: {path.name} ---\n{p.get_text('text') or ''}" for i, p in enumerate(doc, 1)]
            text = "\n".join(parts)
        except Exception:
            text = ""
        if not is_text_empty(text):
            return SourceText(path, rel, text, "pdf_fitz_text", False)
    
    # 3. OCR
    if use_ocr and fitz is not None and pytesseract is not None and Image is not None:
        try:
            lang = "ind+eng" if "ind" in pytesseract.get_languages(config="") else "eng"
            parts = []
            with fitz.open(str(path)) as doc:
                for i, page in enumerate(doc, 1):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    parts.append(f"\n--- OCR HALAMAN {i}: {path.name} ---\n{pytesseract.image_to_string(img, lang=lang, config='--psm 6')}")
            text = "\n".join(parts)
            if not is_text_empty(text):
                return SourceText(path, rel, text, "pdf_ocr", True)
        except Exception:
            pass
    
    return SourceText(path, rel, text, "pdf_empty_or_failed", False)


# ================================================================
# ANONIMISASI — 6 STAGES
# ================================================================

def apply_patterns(text: str, counts: dict[str, int], specs: list[tuple[str, str, str]], flags: int = re.I) -> str:
    for key, pat, repl in specs:
        text, n = re.subn(pat, repl, text, flags=flags)
        add_count(counts, key, n)
    return text


def anonymize_patient_docs(text: str, counts: dict[str, int]) -> str:
    """Stage 1: Hapus identitas pasien (nama, NIK, RM, SEP, alamat, dll)."""
    specs = [
        ("mrn", r"\b(?:No\.?\s*RM\b|Nomor\s*RM\b|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[: \-]?\s*[A-Za-z0-9\-/\.]+", LABEL["mrn"]),
        ("nik_labeled", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[: \-]?\s*\d{12,20}\b", LABEL["nik"]),
        ("nik_16", r"\b\d{16}\b", LABEL["nik"]),
        ("sep", r"\b(?:No\.?\s*SEP|SEP)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{5,}", LABEL["sep"]),
        ("visit", r"\b(?:No\.?\s*(?:Registrasi|Reg|Kunjungan|Visit)|Admission\s*No)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{3,}", LABEL["visit"]),
        ("lab_id", r"\b(?:No\.?\s*(?:Lab|Laboratorium)|ID\s*Lab|Order\s*Lab)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{3,}", LABEL["lab"]),
        ("rad_id", r"\b(?:No\.?\s*(?:Rad|Radiologi)|Accession\s*No|ID\s*Radiologi)\s*[: \-]?\s*[A-Za-z0-9\-/\.]{3,}", LABEL["rad"]),
        ("phone", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", LABEL["phone"]),
        ("email", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", LABEL["email"]),
        ("birthdate", r"\b(?:Tgl\.?\s*Lahir|Tanggal\s*Lahir|DOB)\s*[: \-]?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", "Tanggal Lahir: " + LABEL["birth"]),
        ("patient_name", r"(?is)(?:Nama\s*Pasien|Nama)[\s\n]*:[\s\n]*([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}(?:,\s*[A-Z]{1,3})?)", "Nama Pasien: " + LABEL["patient"]),
        ("family_name", r"(?is)(?:Penanggung\s*Jawab|Keluarga|Nama\s*Ayah|Nama\s*Ibu|Suami|Istri)[\s\n]*:[\s\n]*([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}(?:,\s*[A-Z]{1,3})?)", LABEL["family"]),
        ("address", r"(?im)^\s*(?:Alamat|Domisili)\s*[: \-]?\s*.{5,160}$", "Alamat: " + LABEL["address"]),
        ("hospital", r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", LABEL["hospital"]),
        ("cppt_field", r"(?im)^\s*(?:OA?|B|C|D|E|S)\s*:.*$", "[CPPT_FIELD]"),
        ("rs_address", r"\b(?:Jl\.|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-/]{5,120}", "[ALAMAT_RS]"),
        ("rs_phone", r"\b(?:Telp\.?|Telepon|Phone|Fax)\.?\s*[: \-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]
    return apply_patterns(text, counts, specs)


def anonymize_staff_csv(text: str, counts: dict[str, int], role_patterns: list[tuple[re.Pattern, str]]) -> str:
    """Stage 2: Hapus nama staf dari CSV."""
    for pat, role in role_patterns:
        text, n = pat.subn(f"[{role}]", text)
        add_count(counts, f"staff_csv_{role}", n)
    return text


def anonymize_doctor_regex(text: str, counts: dict[str, int]) -> str:
    """Stage 3: Hapus nama dokter via regex (dr. X, Sp. pattern)."""
    degree = r"(?:drg?\.?|Drg?\.?)"
    sp = r"(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)"
    honor = r"(?:Prof\.?|H\.?|Hj\.?)"
    suffix = r"(?:\s*,?\s*(?:H\.?|Hj\.?|KIC|FINASIM|FIHA|FICS|M\.?Kes|MH\.?Kes|M\.?Sc|MM|MMRS|SH|MH|PhD|CAHM|KHOM|CH))*"

    def repl(m: re.Match[str]) -> str:
        old = m.group(0)
        role = infer_role(old)
        add_count(counts, f"doctor_regex_{role}", 1)
        pref = re.match(
            r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim|Diverifikasi\s+oleh|Print\s+copy\s+(?:ke-\d+\s+)?by)\s*[: \-]?",
            old.strip()
        )
        return f"{pref.group(1)}: [{role}]" if pref else f"[{role}]"

    patterns = [
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,60}}(?:\n\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\.?" ,
        rf"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[: \-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\.?\)?" ,
        rf"\b{degree}\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}(?:,\s*)?{sp}?{suffix}\.?" ,
        rf"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?" ,
        rf"(?m)^[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?" ,
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])" ,
    ]
    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.I | re.S)
    return text


def anonymize_other_ppa(text: str, counts: dict[str, int]) -> str:
    """Stage 4: Hapus nama PPA lain (perawat, bidan, apoteker, dll)."""
    specs = [
        ("nurse", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[PERAWAT]"),
        ("nurse", r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b", "[PERAWAT]"),
        ("midwife", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[BIDAN]"),
        ("pharmacist", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[APOTEKER]"),
        ("pharmacist", r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b", "[APOTEKER]"),
        ("lab_staff", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[: \-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[ANALIS_LAB]"),
        ("radiographer", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[: \-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[RADIOGRAFER]"),
        ("nutrition", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[: \-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[NUTRISIONIS]"),
    ]
    return apply_patterns(text, counts, specs)


def anonymize_cppt_header(text: str, counts: dict[str, int]) -> str:
    """Stage 5: Hapus blok header CPPT (tanggal+jam+nama staf)."""
    def repl(m: re.Match[str]) -> str:
        header, block, soap = m.group("header"), m.group("block"), m.group("soap")
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        joined = " ".join(lines)
        low = joined.lower()
        if any(w in low for w in CLINICAL_STOPWORDS) or len(lines) > 5 or len(joined) > 160:
            return m.group(0)
        role = "PPA"
        if re.search(r"\[APOTEKER\]|\bapt\.?\b|apoteker", joined, re.I):
            role = "APOTEKER"
        elif re.search(r"\[PERAWAT\]|\bners\b|\bns\.?\b|\bamd\.?\s*kep\b|\bs\.?\s*kep\b", joined, re.I):
            role = "PERAWAT"
        elif re.search(r"\bdrg?\.?\b|\bdr\b|\bsp\.?|\[DOKTER", joined, re.I):
            role = infer_role(joined)
        elif re.search(r"\[RADIOGRAFER\]|amd\.?\s*rad", joined, re.I):
            role = "RADIOGRAFER"
        add_count(counts, f"cppt_header_{role}", 1)
        return f"{header}[{role}]\n{soap}"

    pat = r"(?m)(?P<header>^\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*\n\s*\d{1,2}:\d{2}(?::\d{2})?\s*\n)(?P<block>(?:[^\n]+\n){1,5})(?P<soap>^\s*[SOAP]\s*$)"
    return re.sub(pat, repl, text)


def cleanup(text: str, counts: dict[str, int]) -> str:
    """Stage 6: Bersihkan label ganda, gelar sisa setelah label."""
    specs = [
        ("cleanup_colon_name_label", r"(?m)^(\s*:\s*)[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80},?\s*(\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|NUTRISIONIS|ANALIS_LAB)(?:_[A-Z_]+)?\])", r"\1\2"),
        ("cleanup_label_degree", r"(\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER)(?:_[A-Z_]+)?\])\s*[\.\,]*\s*(?:drg?\.?|Sp\.?\s*[A-Za-z]+|Ners|Ns\.?|Apt\.?|Amd\.?\s*Kep\.?|Amd\.?\s*Rad\.?)\b\.?,?", r"\1"),
        ("cleanup_print_copy", r"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
        ("cleanup_missing_space", r"(\[[A-Z_]+?\])(\w)", r"\1 \2"),
        ("cleanup_dr_sp_leftover", r"\b(?:dr|Dr)\.?\s*,?\s*Sp\.\s*[A-Za-z]+\b\s*,?", ""),
        ("cleanup_hj_dr_leftover", r"\b(?:Hj?\.|H\.)\s*Dr\..*?Sp\.\s*[A-Za-z]+\b\s*,?", ""),
    ]
    text = apply_patterns(text, counts, specs)
    text, n = re.subn(r"(\[[A-Z_]+\])(?:\s*,?\s*\1)+", r"\1", text)
    add_count(counts, "cleanup_duplicate_labels", n)
    return re.sub(r"[ \t]+\n", "\n", text)


def detect_leftovers(text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Deteksi sisa PII yang belum teranoniimasi. Skip false positive Sp. setelah [DOKTER_]."""
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for key, pat in LEFTOVER_PATTERNS.items():
        if key == "leftover_sp":
            # Skip Sp. yang muncul setelah label dokter (bukan bocor — gelar sisa)
            hits = []
            for m in re.finditer(pat, text, re.I):
                before = text[max(0, m.start()-80):m.start()]
                if re.search(r"\[DOKTER(?:_[A-Z_]+)?\]", before):
                    continue  # false positive — Sp. setelah label dokter
                hits.append(m.group(0).strip().replace("\n", " "))
        else:
            hits = [m.group(0).strip().replace("\n", " ") for m in re.finditer(pat, text, re.I)]
        counts[key] = len(hits)
        if hits:
            examples[key] = [hashlib.sha256(h.encode("utf-8", "ignore")).hexdigest()[:16] for h in hits[:3]]
    return counts, examples


def anonymize_text(text: str, role_patterns: list[tuple[re.Pattern, str]]) -> tuple[str, dict[str, int], dict[str, int], dict[str, list[str]]]:
    """Anonimisasi lengkap: 6 stage × 2 iterasi + deteksi sisa."""
    counts: dict[str, int] = {}
    text = normalize_text(text)
    for _ in range(2):
        text = anonymize_patient_docs(text, counts)
        text = anonymize_staff_csv(text, counts, role_patterns)
        text = anonymize_doctor_regex(text, counts)
        text = anonymize_other_ppa(text, counts)
        text = anonymize_cppt_header(text, counts)
        text = cleanup(text, counts)
    leftovers, examples_dict = detect_leftovers(text)
    return text, counts, leftovers, examples_dict


# ================================================================
# BATCH ANONIMISASI
# ================================================================

def collect_source_files(input_dir: Path) -> list[Path]:
    """Kumpulkan semua file PDF/TXT dari input_dir."""
    return sorted(
        [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".pdf", ".txt"}],
        key=lambda p: str(p).lower()
    )


def anonymize_folder(
    input_dir: Path | str,
    output_dir: Path | str,
    staff_csv: Path | str | None = None,
    use_ocr: bool = True,
    progress: ProgressState | None = None,
) -> list[AnonResult]:
    """
    Anonimisasi batch semua file PDF/TXT dalam folder.
    Args:
        input_dir: Folder input (bisa nested per pasien)
        output_dir: Folder output untuk file .anon.txt
        staff_csv: Path ke staff_doctors.csv
        use_ocr: Gunakan OCR untuk PDF scan
        progress: Optional ProgressState untuk tracking Streamlit
    Returns:
        list[AnonResult] — hasil tiap file
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {input_dir}")

    variants = load_staff_variants(staff_csv)
    role_patterns = compile_role_patterns(variants)
    files = collect_source_files(input_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if progress:
        progress.total = len(files)
        progress.current = 0
        progress.status = "running"
        progress.start_time = time.time()
        progress.errors = []

    results: list[AnonResult] = []

    for i, fp in enumerate(files):
        if progress:
            progress.current = i
            progress.current_file = str(fp.relative_to(input_dir))

        try:
            src = read_source(fp, input_dir, use_ocr)
            anon, counts, leftovers, examples = anonymize_text(src.text, role_patterns)

            out_rel = src.relative_path.with_suffix(".anon.txt")
            out = output_dir / out_rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(anon, encoding="utf-8")

            result = AnonResult(
                source_file=str(src.relative_path),
                output_file=str(out_rel),
                patient_folder=src.relative_path.parts[0] if len(src.relative_path.parts) > 1 else "",
                extraction_status=src.extraction_status,
                ocr_used=src.ocr_used,
                chars_in=len(src.text),
                chars_out=len(anon),
                processed_at=datetime.now().isoformat(timespec="seconds"),
                needs_manual_review=any(v > 0 for v in leftovers.values()),
                counts=counts,
                leftovers=leftovers,
                leftover_examples=examples,
            )
            results.append(result)

        except Exception as e:
            err_msg = f"{fp.relative_to(input_dir)}: {e}"
            if progress:
                progress.errors.append(err_msg)
            results.append(AnonResult(
                source_file=str(fp.relative_to(input_dir)),
                output_file="",
                patient_folder="",
                extraction_status="error",
                ocr_used=False,
                chars_in=0,
                chars_out=0,
                processed_at=datetime.now().isoformat(timespec="seconds"),
                needs_manual_review=True,
            ))

    if progress:
        progress.current = len(files)
        progress.status = "done"

    return results


def save_audit_report(results: list[AnonResult], report_dir: Path | str) -> Path:
    """Simpan audit report CSV ke report_dir."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "anonymization_report.csv"

    if not results:
        report_path.write_text("", encoding="utf-8")
        return report_path

    # Collect all keys
    all_keys = set()
    for r in results:
        all_keys.add("source_file")
        all_keys.add("patient_folder")
        all_keys.add("chars_in")
        all_keys.add("chars_out")
        all_keys.add("needs_manual_review")
        all_keys.update(r.counts.keys())
        all_keys.update(r.leftovers.keys())

    extra_keys = [
        "source_file", "output_file", "patient_folder",
        "extraction_status", "ocr_used", "chars_in", "chars_out",
        "processed_at", "needs_manual_review", "leftover_examples_sha256_16",
    ]
    fieldnames = extra_keys + sorted(k for k in all_keys if k not in extra_keys)

    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            row = {
                "source_file": r.source_file,
                "output_file": r.output_file,
                "patient_folder": r.patient_folder,
                "extraction_status": r.extraction_status,
                "ocr_used": r.ocr_used,
                "chars_in": r.chars_in,
                "chars_out": r.chars_out,
                "processed_at": r.processed_at,
                "needs_manual_review": r.needs_manual_review,
                "leftover_examples_sha256_16": json.dumps(r.leftover_examples, ensure_ascii=False),
            }
            row.update(r.counts)
            row.update(r.leftovers)
            w.writerow(row)

    return report_path


# ================================================================
# EKSTRAKSI DATA TERSTRUKTUR (STROKE INFARK)
# ================================================================

def get_doc_type(filename: str) -> str:
    name = filename.lower()
    if "resume" in name:
        return "resume"
    if "rad" in name:
        return "radiology"
    if "lab" in name:
        return "lab"
    if "cppt_igd" in name:
        return "cppt_igd"
    if "cppt_ranap" in name or "ranap" in name:
        return "cppt_ranap"
    return "other"


def read_patient_files(patient_dir: Path) -> list[dict[str, Any]]:
    files = []
    for fp in sorted(patient_dir.glob("*.anon.txt")):
        text = normalize_text(fp.read_text(encoding="utf-8", errors="ignore"))
        if len(text.strip()) < 20:
            continue
        files.append({
            "source_file": fp.name,
            "doc_type": get_doc_type(fp.name),
            "text": text,
            "char_count": len(text),
        })
    return files


def first_by_priority(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x.get("priority", 9), x.get("pos", 10**9)))[0]


def context(text: str, start: int, end: int, radius: int = 100, max_len: int = 450) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return clean_snippet(text[a:b], max_len=max_len)


def number_str(x: Any) -> str:
    if x is None:
        return "unknown"
    x = str(x).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", x)
    return m.group(0) if m else "unknown"


def extract_demographics(files: list[dict]) -> dict[str, str]:
    result = {"age": "unknown", "gender": "unknown"}
    for f in files:
        text = f["text"]
        m = re.search(r"(?:Umur|Usia)\s*[:=]?\s*(\d+)\s*(?:Tahun|th|thn)?", text, re.I)
        if m:
            result["age"] = m.group(1)
        m = re.search(r"(?:JK|Jenis\s*Kelamin|Kelamin)\s*[:=]?\s*(L(?:aki[\s-]*laki)?|P(?:erempuan|ria)?)", text, re.I)
        if m:
            g = m.group(1).upper()
            result["gender"] = "Laki-laki" if g.startswith("L") else "Perempuan"
        if result["age"] != "unknown" and result["gender"] != "unknown":
            break
    return result


def extract_diagnosis(files: list[dict]) -> dict[str, str]:
    patterns = [
        (r".{0,80}(?:diagnosis|diagnosa|assessment|asesmen|kesimpulan).{0,200}(?:stroke|infark|iskemik|hemoragik|ICH|PIS).{0,200}", 1),
        (r".{0,80}(stroke\s+infark|infark\s+cerebri|stroke\s+iskemik|stroke\s+non\s+hemoragik|SNH|cerebral\s+infarct).{0,150}", 1),
        (r".{0,80}(stroke\s+lakunar|lakunar\s+infark|infark\s+lakuner|small\s+vessel).{0,150}", 2),
        (r".{0,80}(stroke\s+hemoragik|ICH|PIS|perdarahan\s+intraserebral|perdarahan\s+intracerebral).{0,150}", 3),
    ]
    pr = {"resume": 1, "radiology": 2, "cppt_igd": 3, "cppt_ranap": 4}
    candidates = []
    for f in files:
        for pat, _ in patterns:
            for m in re.finditer(pat, f["text"], re.I | re.S):
                candidates.append({
                    "source_file": f["source_file"], "doc_type": f["doc_type"],
                    "priority": pr.get(f["doc_type"], 9), "pos": m.start(),
                    "evidence": clean_snippet(m.group(0), 450)
                })
    best = first_by_priority(candidates)
    if not best:
        return {"stroke_type": "unknown", "diagnosis_text": "unknown", "evidence": ""}
    low = best["evidence"].lower()
    infark_terms = ["infark", "infarct", "iskemik", "ischemic", "lakunar", "lacunar", "snh", "non hemoragik"]
    hemoragik_terms = ["hemoragik", "hemorrhagic", "ich", "pis", "perdarahan intraserebral", "perdarahan intracerebral"]
    is_infark = any(t in low for t in infark_terms)
    is_hemo = any(t in low for t in hemoragik_terms)
    if is_infark and not is_hemo:
        stype = "INFARK"
    elif is_hemo and not is_infark:
        stype = "HEMORAGIK"
    elif is_infark and is_hemo:
        stype = "MIXED"
    else:
        stype = "UNCLEAR"
    return {"stroke_type": stype, "diagnosis_text": best["evidence"], "evidence": best["evidence"]}


def extract_gcs(files: list[dict]) -> str:
    candidates = []
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3}
    component_patterns = [
        r"\bGCS\s*[:=]?\s*E\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
        r"\bE\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
    ]
    total_patterns = [r"\bGCS\s*[:=]?\s*(1[0-5]|[3-9])\b"]
    for f in files:
        if f["doc_type"] not in pr:
            continue
        for pat in total_patterns:
            for m in re.finditer(pat, f["text"], re.I):
                candidates.append({"value": m.group(1), "source_file": f["source_file"],
                    "priority": pr[f["doc_type"]], "pos": m.start(),
                    "evidence": context(f["text"], m.start(), m.end())})
        for pat in component_patterns:
            for m in re.finditer(pat, f["text"], re.I):
                nums = [int(x) for x in m.groups()]
                candidates.append({"value": str(sum(nums)), "source_file": f["source_file"],
                    "priority": pr[f["doc_type"]], "pos": m.start(),
                    "evidence": context(f["text"], m.start(), m.end())})
    best = first_by_priority(candidates)
    return best["value"] if best else "unknown"


def extract_vitals(files: list[dict]) -> dict[str, str]:
    result = {"td_sistol": "unknown", "td_diastol": "unknown", "hr": "unknown",
              "rr": "unknown", "suhu": "unknown", "spo2": "unknown"}
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3}
    patterns = {
        "td": (r"\bTD\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b", lambda m: (m.group(1), m.group(2))),
        "hr": (r"\b(?:HR|Nadi|Heart\s*Rate)\s*[:=]?\s*(\d{2,3})\b", lambda m: m.group(1)),
        "rr": (r"\b(?:RR|Respiratory|Resp)\s*[:=]?\s*(\d{1,3})\b", lambda m: m.group(1)),
        "suhu": (r"\b[SST]\s*[:=]?\s*(\d{2,3}(?:[.,]\d)?)\s*(?:[°′]?C)?\b", lambda m: m.group(1).replace(",", ".")),
        "spo2": (r"\b(?:SPO2|SpO2|SaO2|O2\s*Sat)\s*[:=]?\s*(\d{2,3})\s*%?\b", lambda m: m.group(1)),
    }
    for f in files:
        if f["doc_type"] not in pr:
            continue
        text = f["text"]
        for key, (pat, extractor) in patterns.items():
            if key == "td":
                if result["td_sistol"] != "unknown":
                    continue
                for m in re.finditer(pat, text, re.I):
                    if 50 <= int(m.group(1)) <= 300 and 30 <= int(m.group(2)) <= 200:
                        result["td_sistol"], result["td_diastol"] = m.group(1), m.group(2)
                        break
            else:
                if result[key] != "unknown":
                    continue
                m = re.search(pat, text, re.I)
                if m:
                    result[key] = extractor(m)
    return result


# ================================================================
# CT SCAN
# ================================================================

def extract_ct_scan(files: list[dict]) -> dict[str, str]:
    """Ekstrak 9 field CT Scan kepala dari radiology & resume."""
    result = {
        "ct_documented": "tidak", "ct_result": "", "ct_infark_lokasi": "",
        "ct_aspects": "unknown", "ct_perdarahan": "unknown",
        "ct_midline_shift": "unknown", "ct_hidrosefalus": "unknown",
        "ct_atrofi": "unknown", "ct_tanggal": "unknown",
    }
    for f in files:
        if f["doc_type"] not in ["radiology", "resume"]:
            continue
        text = f["text"]; low = text.lower()
        if re.search(r"(?:ct\s*scan|msct|ct\s*kepala|ct\s*head|head\s*ct)", low):
            result["ct_documented"] = "ada"
        # Lokasi infark
        locs = set()
        for pat in ["thalamus", "talamus", "kapsula\s*interna", "capsula\s*interna",
                     "nukleus\s*lentiformis", "ganglia\s*basalis", "basal\s*ganglia",
                     "pons", "cerebellum", "serebelum", "centrum\s*semiovale",
                     "corona\s*radiata", "periventrikel", "frontal", "parietal",
                     "temporal", "occipital", "oksipital", "subcortical", "subkortikal",
                     "lacunar", "lakunar", "mca", "aca", "pca"]:
            m = re.search(r".{0,40}" + pat + r".{0,60}", low, re.I)
            if m and any(t in m.group() for t in ["infark", "infarct", "lakuner", "hipodens"]):
                locs.add(pat.replace(r"\s*", " "))
        if locs:
            result["ct_infark_lokasi"] = ", ".join(sorted(locs))
        # ASPECTS
        m = re.search(r"\bASPECTS\s*[:=]?\s*(\d{1,2})\b", text, re.I)
        if m: result["ct_aspects"] = m.group(1)
        # Perdarahan
        if re.search(r"(?:tidak\s+tampak\s+(?:tanda[- ]tanda\s+)?perdarahan|no\s+hemorrhage|no\s+bleeding)", low):
            result["ct_perdarahan"] = "tidak_ada"
        elif re.search(r"\b(?:perdarahan|hemorrhage|ICH|PIS|SAH|SAB|IVH|intraserebral|intracerebral|subarachnoid)", low):
            result["ct_perdarahan"] = "ada"
        # Midline shift
        if re.search(r"(?:midline\s*shift|pergeseran\s*garis\s*tengah)", low):
            result["ct_midline_shift"] = "ada" if not re.search(r"(?:tidak|no|tanpa).{0,30}midline", low) else "tidak_ada"
        # Hidrosefalus
        if re.search(r"(?:hidrosefalus|hydrocephalus)", low):
            result["ct_hidrosefalus"] = "ada"
        # Atrofi
        if re.search(r"(?:atrofi|atrophy)", low):
            result["ct_atrofi"] = "ada"
        # Kesan
        for pat in [r"(?:KESIMPULAN|Kesimpulan|kesimpulan)\s*[:=]?\s*(.{20,800})",
                     r"(?:IMPRESSION|Impression)\s*[:=]?\s*(.{20,800})"]:
            m = re.search(pat, text, re.I | re.S)
            if m: result["ct_result"] = clean_snippet(m.group(1), 600); break
        # Tanggal dari TANGGAL SELESAI
        m = re.search(r"TANGGAL\s*SELESAI\s*:\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
        if m:
            parsed = parse_indonesian_date(m.group(1))
            if parsed: result["ct_tanggal"] = parsed
    return result


# ================================================================
# THORAX
# ================================================================

def extract_thorax(files: list[dict]) -> dict[str, str]:
    """Ekstrak 3 field Thorax dari radiology."""
    result = {"thorax_documented": "tidak", "thorax_kesan": "", "thorax_tanggal": "unknown"}
    for f in files:
        if f["doc_type"] not in ["radiology", "resume"]:
            continue
        text = f["text"]; low = text.lower()
        # Deteksi thorax: keyword foto thorax/chest — TAPI bukan CT scan
        if re.search(r"(?:foto\s*thorax|chest\s*x[- ]?ray|thorax\s*ap|thorax\s*pa|x\s*ray\s*thorax)", low) and not re.search(r"(?:ct\s*scan|msct|ct\s*kepala)", low):
            result["thorax_documented"] = "ada"
        elif re.search(r"(?:foto\s*thorax|chest\s*x[- ]?ray)", low):
            result["thorax_documented"] = "ada"
        # KESAN thorax — hanya jika mengandung keyword thorax
        m = re.search(r"KESAN\s*:\s*(.{10,600})", text, re.I | re.S)
        if m:
            kesan = m.group(1).lower()
            if any(t in kesan for t in ["broncho", "pneumonia", "cardiomegali", "paru",
                                         "jantung", "aorta", "infiltrat", "efusi",
                                         "pulmo", "cor", "trachea", "bronkitis",
                                         "atelektasis", "nodul", "massa"]):
                result["thorax_documented"] = "ada"
                result["thorax_kesan"] = clean_snippet(m.group(1), 400)
        # Tanggal
        m = re.search(r"TANGGAL\s*SELESAI\s*:\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
        if m:
            parsed = parse_indonesian_date(m.group(1))
            if parsed: result["thorax_tanggal"] = parsed
        # Fallback: Tgl. Pmk
        if result["thorax_tanggal"] == "unknown":
            m = re.search(r"Tgl\.?\s*Pmk\s*:\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
            if m:
                parsed = parse_indonesian_date(m.group(1))
                if parsed: result["thorax_tanggal"] = parsed
    return result


# ================================================================
# LAB DATES
# ================================================================

def extract_lab_dates(files: list[dict]) -> dict[str, str]:
    """Ekstrak tanggal lab: IGD, Ranap, Pertama."""
    result = {"lab_tanggal_igd": "unknown", "lab_tanggal_ranap": "unknown", "lab_tanggal_pertama": "unknown"}
    lab_files = [f for f in files if f["doc_type"] == "lab"]
    for f in lab_files:
        text = f["text"]; name = f["source_file"].lower()
        cek_tgl = ""
        for pat in [r"Tgl\.?\s*Sampling\s*:\s*(\d{1,2}\s+\w+\s+\d{4})",
                     r"Tgl\.?\s*Selesai\s*:\s*(\d{1,2}\s+\w+\s+\d{4})",
                     r"TANGGAL\s*SELESAI\s*:\s*(\d{1,2}\s+\w+\s+\d{4})"]:
            m = re.search(pat, text, re.I)
            if m:
                parsed = parse_indonesian_date(m.group(1))
                if parsed: cek_tgl = parsed; break
        if not cek_tgl:
            continue
        # Deteksi IGD: nama file OR konten teks
        is_igd = "igd" in name or re.search(r"(?:IGD|Instalasi\s*Gawat\s*Darurat|Gawat\s*Darurat|UGD|I\s*G\s*D)", text, re.I)
        if is_igd:
            result["lab_tanggal_igd"] = cek_tgl
        else:
            # ranap lab
            if result["lab_tanggal_ranap"] == "unknown":
                result["lab_tanggal_ranap"] = cek_tgl
        # Pertama: ambil tanggal paling awal
        if result["lab_tanggal_pertama"] == "unknown" or (cek_tgl and cek_tgl < result["lab_tanggal_pertama"]):
            result["lab_tanggal_pertama"] = cek_tgl
    return result


# ================================================================
# DEMAM
# ================================================================

def extract_demam(files: list[dict]) -> dict[str, str]:
    """Ekstrak tracking demam dari CPPT."""
    result = {"demam_saat_masuk": "tidak", "demam_selama_rawat": "tidak", "suhu_tertinggi": "unknown"}
    suhu_values: list[float] = []
    for f in files:
        if f["doc_type"] not in ["cppt_igd", "cppt_ranap"]:
            continue
        text = f["text"]; low = text.lower()
        # Keyword demam
        if re.search(r"\bfebris\b|demam|panas\s*badan|pireksia|suhu\s*tinggi", low):
            result["demam_selama_rawat"] = "ada"
            if f["doc_type"] == "cppt_igd":
                result["demam_saat_masuk"] = "ada"
        # Suhu tertinggi dari vital sign
        for m in re.finditer(r"\b[SST]\s*[:=]?\s*(\d{2,3}(?:[.,]\d)?)\s*(?:[°′]?\s*C)?\b", text, re.I):
            try:
                s = float(m.group(1).replace(",", "."))
                if 35 <= s <= 42:
                    suhu_values.append(s)
            except ValueError:
                pass
    if suhu_values:
        result["suhu_tertinggi"] = f"{max(suhu_values):.1f}"
        if max(suhu_values) >= 38:
            result["demam_selama_rawat"] = "ada"
    return result


# ================================================================
# DEMOGRAFI
# ================================================================

def parse_indonesian_date(date_str: str) -> str | None:
    """Parse Indonesian date string → YYYY-MM-DD or None."""
    months = {
        "januari": "01", "februari": "02", "maret": "03", "april": "04",
        "mei": "05", "juni": "06", "juli": "07", "agustus": "08",
        "september": "09", "oktober": "10", "november": "11", "desember": "12",
    }
    date_str = date_str.strip()
    m = re.search(r"(\d{1,2})\s+(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember|Jan|Feb|Mar|Apr|Mei|Jun|Jul|Agu|Sep|Okt|Nov|Des)\s+(\d{4})", date_str, re.I)
    if m:
        day = m.group(1).zfill(2)
        month_name = m.group(2).lower()[:3]
        month_map_short = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "mei": "05",
                           "jun": "06", "jul": "07", "agu": "08", "sep": "09", "okt": "10",
                           "nov": "11", "des": "12"}
        month = month_map_short.get(month_name, "01")
        year = m.group(3)
        return f"{year}-{month}-{day}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


import json
import os

# ── Database Obat ──
DRUG_DB_PATH = Path(__file__).parent / "drug_database.json"

def get_drug_keywords() -> dict[str, list[str]]:
    """Load drug keywords: hardcoded defaults + user edits from JSON (override)."""
    # Default hardcoded
    keywords = {
        "med_antiplatelet": [
            # Aspirin & turunan
            "aspirin", "asetosal", "acetylsalicylic", "ascardia",
            "tromboaspilet", "thromboaspilet", "aspilet", "thrombo aspilet",
            "cardio aspirin", "cardi aspirina",
            # Clopidogrel
            "clopidogrel", "duoplavin", "grepid", "clopidogrel bisulfate",
            "clopidogrel hydrogen sulfate", "clopidogrel actavis",
            # Ticagrelor
            "ticagrelor", "brilinta", "ticagrelor actavis",
            # Cilostazol
            "cilostazol", "pletal", "cilostazol actavis",
            # Generic antiplatelet
            "antiplatelet", "anti platelet", "antiplatelet drug",
            "anti agregasi", "antiagregasi",
        ],
        "med_antikoagulan": ["warfarin", "notisil", "simarc", "coumadin", "warfarin na",
                            "rivaroxaban", "xarelto",
                            "apixaban", "eliquis",
                            "dabigatran", "pradaxa",
                            "edoxaban", "lixiana",
                            "antikoagulan", "anti koagulan",
                            "heparin", "heparin natrium", "heparin sodium",
                            "enoxaparin", "clexane", "fragmin", "fondaparinux",
                            "acenocoumarol", "sintrom", "phenprocoumon", "marcumar"],
        "med_statin": ["simvastatin", "atorvastatin", "rosuvastatin", "statin",
                      "pravastatin", "fluvastatin", "pitavastatin", "lovastatin"],
        "med_antihipertensi": ["amlodipine", "amlodipin", "nifedipine", "captopril", "lisinopril",
                              "enalapril", "ramipril", "candesartan", "valsartan",
                              "telmisartan", "irbesartan", "losartan", "bisoprolol",
                              "metoprolol", "propranolol", "atenolol",
                              "furosemide", "furosemid", "lasix",
                              "hydrochlorothiazid", "spironolactone", "antihipertensi",
                              "norvask", "tenormin", "coversyl", "diovan"],
        "med_mannitol": ["mannitol", "manitol"],
        "med_citicoline": ["citicoline", "citikolin", "citol", "neurotam",
                          "cerebroforte", "cerebrofort"],
        "med_ppi": ["omeprazole", "omeprazol", "pantoprazole", "lansoprazole", "esomeprazole",
                   "rabeprazole", "ppi", "protonix", "nexium",
                   "ranitidin", "ranitidine"],
        "med_antibiotik": [
            "ceftriaxone", "ceftriaxon", "seftriakson",
            "cefixime", "cefixim", "sefiksim",
            "cefotaxime", "cefotaxim", "cefotaksim", "sefotaksim",
            "cefoperazone", "cefoperazon", "sefoperazon",
            "cefepime", "cefepim", "sefepim",
            "ceftazidime", "ceftazidim", "seftazidim",
            "cefadroxil", "cefadroksil", "sefadroksil",
            "cefuroxime", "cefuroxim", "sefuroksim",
            "cefazolin", "sefazolin",
            "cefalexin", "cefaleksin", "sefaleksin",
            "cefradin", "cephradine", "sefradin",
            "amoxicillin", "amoksisilin", "amoxsan",
            "ampicillin", "ampisilin",
            "ampicillin sulbactam", "ampisilin sulbaktam",
            "ampisul", "sulbaktam", "sulperazon",
            "piperacillin tazobactam", "piperasilin tazobaktam",
            "piperacillin", "tazobactam",
            "penicillin g", "penisilin g", "prokain", "benzatin",
            "kloramfenikol", "chloramphenicol",
            "tetrasiklin", "tetracycline", "doxycycline", "doksisiklin",
            "ciprofloxacin", "siprofloksasin", "cipro",
            "levofloxacin", "levofloksasin",
            "moxifloxacin", "moksifloksasin",
            "ofloxacin", "ofloksasin",
            "metronidazole", "metronidazol", "flagyl",
            "gentamicin", "gentamisin",
            "amikacin", "amikasin",
            "streptomycin", "streptomisin",
            "kanamycin", "kanamisin",
            "meropenem", "imipenem",
            "azithromycin", "azitromisin",
            "erythromycin", "eritromisin",
            "clarithromycin", "klaritromisin",
            "clindamycin", "klindamisin",
            "vancomycin", "vankomisin",
            "linezolid",
            "cotrimoxazole", "kotrimoksazol",
            "trimethoprim", "trimetoprim",
            "sulfamethoxazole", "sulfametoksazol",
            "flukonazol", "fluconazole",
            "ketokonazol", "ketoconazole",
            "miconazole", "mikonazol",
            "asiklovir", "acyclovir",
            "antibiotik", "anti biotik",
            "fosfomycin", "fosfomisin",
            "nitrofurantoin",
            "methenamine"],
    }
    # Override dari JSON kalau ada
    if DRUG_DB_PATH.exists():
        try:
            user_data = json.loads(DRUG_DB_PATH.read_text(encoding="utf-8"))
            # 1) Override kategori yang sudah ada di hardcoded
            for key in keywords:
                if key in user_data and isinstance(user_data[key], list) and user_data[key]:
                    keywords[key] = user_data[key]
            # 2) Tambah kategori BARU dari JSON yang belum ada di hardcoded
            for key in user_data:
                if key.startswith("med_") and key not in keywords and isinstance(user_data[key], list):
                    keywords[key] = user_data[key]
        except Exception:
            pass
    return keywords


def extract_medications(files: list[dict], selected_drug_keys: list[str] | None = None) -> dict[str, str]:
    """
    Ekstrak medikasi dari file teks.
    Args:
        files: list dict dengan key 'text' dan 'doc_type'
        selected_drug_keys: list drug key yg ingin dicek (None = semua)
    Returns:
        dict: med_kategori → "ada"/"tidak", med_kategori_detail → nama obat,
              med_kategori_dosis → dosis, med_kategori_durasi → durasi
    """
    keywords = get_drug_keywords()
    # Filter jika sub-kategori dipilih
    # None = semua (default), [] = tidak ada, [...] = hanya yang dipilih
    if selected_drug_keys is not None:
        keywords = {k: v for k, v in keywords.items() if k in selected_drug_keys}

    # Dynamic result dict
    result = {}
    for key in keywords:
        if key.startswith("med_"):
            result[key] = "tidak"
            result[f"{key}_detail"] = ""
            result[f"{key}_dosis"] = ""
            result[f"{key}_durasi"] = ""

    all_text = "\n".join(f["text"] for f in files).lower()

    for key, terms in keywords.items():
        found = []
        dosages = []
        durations = []
        for t in terms:
            if t in all_text:
                found.append(t)
                # Ekstrak dosis di sekitar keyword
                dosis = _extract_dosis_around(all_text, t)
                if dosis:
                    dosages.append(dosis)
                # Ekstrak durasi di sekitar keyword
                durasi = _extract_durasi_around(all_text, t)
                if durasi:
                    durations.append(durasi)

        if found:
            result[key] = "ada"
            unique_found = []
            for t in terms:
                if t in all_text and t not in unique_found:
                    unique_found.append(t)
            result[f"{key}_detail"] = ", ".join(unique_found[:10])
            if dosages:
                result[f"{key}_dosis"] = "; ".join(dict.fromkeys(dosages))[:200]  # unik + max 200 char
            if durations:
                result[f"{key}_durasi"] = "; ".join(dict.fromkeys(durations))[:200]

    return result


def _extract_dosis_around(text: str, drug_term: str) -> str:
    """Cari dosis obat di sekitar nama obat. Contoh: 'ceftriaxone 1g/12jam'"""
    idx = text.find(drug_term)
    if idx == -1:
        return ""
    # Lihat ~80 karakter setelah nama obat
    start = idx
    end = min(len(text), idx + len(drug_term) + 80)
    context = text[start:end]

    # Pola dosis: angka + unit setelah nama obat
    # "ceftriaxone 1g", "metformin 500mg", "amlodipin 5mg", "3x500mg", "/12jam"
    patterns = [
        # dosis setelah nama obat: "obat 1g", "obat 500mg", "obat 1.5g"
        r'(?:' + re.escape(drug_term) + r')[\s:,]*(\d+[.,]?\d*\s*(?:g|mg|mcg|gr|gram|mili?gram|mcg|ml|cc|IU|unit|mili?liter|mEq))(?:\s*(?:/|per)\s*(\d+)\s*(?:jam|hour|hari))?',
        # format dosis: "3x500mg"
        r'(\d+\s*[x×]\s*\d+[.,]?\d*\s*(?:g|mg|mcg|gr|gram|ml))',
        # /8jam, /12jam, /24jam
        r'(?:' + re.escape(drug_term) + r')(?:.*?)(/\d+\s*(?:jam|hour))',
    ]
    for pat in patterns:
        m = re.search(pat, context, re.I)
        if m:
            found = m.group(0).strip()
            # Bersihkan: jangan panjang banget
            if len(found) < 60:
                return found
    return ""


def _extract_durasi_around(text: str, drug_term: str) -> str:
    """Cari durasi pemberian obat. Contoh: 'selama 7 hari', 'diberikan 5 hari'"""
    idx = text.find(drug_term)
    if idx == -1:
        return ""
    # Lihat ~150 karakter setelah nama obat
    start = idx
    end = min(len(text), idx + len(drug_term) + 150)
    context = text[start:end]

    patterns = [
        r'selama\s+(\d+\s*(?:hari|minggu|bulan|jam|dosis))',
        r'diberikan\s+(?:selama\s+)?(\d+\s*(?:hari|minggu|bulan))',
        r'(\d+\s*(?:hari|minggu|bulan))\s*(?:pemberian|terapi|diberikan|perawatan)?',
        r'lama\s*(?:terapi|pemberian|pengobatan)?\s*[:\s]+(\d+\s*(?:hari|minggu))',
    ]
    for pat in patterns:
        m = re.search(pat, context, re.I)
        if m:
            found = m.group(0).strip() if m.group(0) else m.group(1).strip()
            if len(found) < 50:
                return found
    return ""


def extract_risk_factors(files: list[dict]) -> dict[str, str]:
    result = {"rf_hipertensi": "tidak", "rf_diabetes": "tidak", "rf_dislipidemia": "tidak",
              "rf_jantung": "tidak", "rf_stroke_sebelumnya": "tidak", "rf_merokok": "tidak",
              "rf_atrial_fibrilasi": "tidak", "rf_obesitas": "tidak", "rpd_text": ""}
    all_text = "\n".join(f["text"] for f in files).lower()
    if re.search(r"(?:hipertensi|darah\s*tinggi|hypertension)", all_text):
        result["rf_hipertensi"] = "ada"
    if re.search(r"(?:diabetes|dm\b|kencing\s*manis|gula\s*darah|diabetic)", all_text):
        result["rf_diabetes"] = "ada"
    if re.search(r"(?:dislipidemia|kolesterol\s*tinggi|hiperlipidemia|trigliserida)", all_text):
        result["rf_dislipidemia"] = "ada"
    if re.search(r"(?:jantung|cardiovascular|penyakit\s*jantung|atherosclerosis|aterosklerosis|kardiovaskuler)", all_text):
        result["rf_jantung"] = "ada"
    if re.search(r"(?:stroke\s*sebelumnya|riwayat\s*stroke|CVA\s*sebelumnya|stroke\s*old)", all_text):
        result["rf_stroke_sebelumnya"] = "ada"
    if re.search(r"(?:merokok|rokok|perokok|smoker|smoking)", all_text):
        result["rf_merokok"] = "ada"
    if re.search(r"(?:atrial\s*fibrilasi|atrial\s*fibrillation|AF|fibrilasi\s*atrial)", all_text):
        result["rf_atrial_fibrilasi"] = "ada"
    if re.search(r"(?:obesitas|obesity|obes|BMI|IMT|gemuk|overweight)", all_text):
        result["rf_obesitas"] = "ada"
    # rpd_text: ambil Riwayat Penyakit Dahulu dari resume
    for f in files:
        if f["doc_type"] == "resume":
            m = re.search(r"(?:Riwayat\s*Penyakit\s*Dahulu|RPD)\s*[:=]?\s*(.{20,800})", f["text"], re.I | re.S)
            if m:
                result["rpd_text"] = clean_snippet(m.group(1), 400)
                break
    return result


def extract_lab_values(files: list[dict]) -> dict[str, str]:
    result = {"lab_hb": "unknown", "lab_leukosit": "unknown", "lab_trombosit": "unknown",
              "lab_gds": "unknown", "lab_ureum": "unknown", "lab_kreatinin": "unknown",
              "lab_ht": "unknown", "lab_eritrosit": "unknown", "lab_natrium": "unknown",
              "lab_kalium": "unknown", "lab_asam_urat": "unknown",
              "lab_inr": "unknown", "lab_ldl": "unknown", "lab_kolesterol_total": "unknown",
              "lab_trigliserida": "unknown", "lab_hba1c": "unknown"}
    test_map = {
        "lab_hb": [r"hemoglobin", r"hb\b"],
        "lab_leukosit": [r"leukosit", r"lekosit", r"wbc"],
        "lab_trombosit": [r"trombosit", r"platelet", r"plt\b"],
        "lab_gds": [r"glukosa\s*darah\s*sewaktu", r"gds\b", r"gula\s*darah", r"glucose"],
        "lab_ureum": [r"ureum", r"urea"],
        "lab_kreatinin": [r"kreatinin", r"creatinine", r"crea"],
        "lab_ht": [r"hematokrit", r"ht\b"],
        "lab_eritrosit": [r"eritrosit", r"rbc", r"red\s*blood"],
        "lab_natrium": [r"natrium", r"sodium"],
        "lab_kalium": [r"kalium", r"potassium"],
        "lab_asam_urat": [r"asam\s*urat", r"uric\s*acid"],
        "lab_inr": [r"\binr\b", r"inr\s*[\d]"],
        "lab_ldl": [r"ldl\b", r"ldl\s*kolesterol", r"low\s*density"],
        "lab_kolesterol_total": [r"kolesterol\s*total", r"total\s*kolesterol"],
        "lab_trigliserida": [r"trigliserida", r"trigliserid", r"triglyceride"],
        "lab_hba1c": [r"hba1c\b", r"hba1c", r"hb\s*a1c", r"hemoglobin\s*a1c", r"glycated\s*hemoglobin"],
    }
    for f in files:
        if f["doc_type"] != "lab":
            continue
        text = f["text"]
        for key, names in test_map.items():
            if result[key] != "unknown":
                continue
            for name_pat in names:
                m = re.search(r"(?im)^.*?" + name_pat + r"[\s\S]*?([\d.,]+)\s*.*$", text)
                if m:
                    result[key] = m.group(1).replace(",", ".")
                    break
    return result


# ================================================================
# TINDAKAN KLINIS
# ================================================================

def extract_actions(files: list[dict]) -> dict[str, str]:
    """Ekstrak tindakan klinis: konsul, fisioterapi, gizi, skrining menelan, edukasi."""
    result = {
        "act_konsul_neurologi": "tidak", "act_konsul_bedah_saraf": "tidak",
        "act_konsul_jantung": "tidak", "act_rawat_icu_hcu": "tidak",
        "act_fisioterapi": "tidak", "act_konsul_gizi": "tidak",
        "act_skrining_menelan": "tidak", "act_edukasi_keluarga": "tidak",
    }
    all_text = "\n".join(f["text"] for f in files).lower()
    if re.search(r"(?:konsul\s*(?:ke|neurologi|saraf|sp\.?\s*[ns])|neurologi|sp\.?\s*s)", all_text):
        result["act_konsul_neurologi"] = "ada"
    if re.search(r"(?:konsul\s*(?:bedah\s*saraf|neurosurgeri|sp\.?\s*bs))", all_text):
        result["act_konsul_bedah_saraf"] = "ada"
    if re.search(r"(?:konsul\s*(?:jantung|kardio|kardiologi|sp\.?\s*jp))", all_text):
        result["act_konsul_jantung"] = "ada"
    if re.search(r"(?:rawat\s*(?:icu|hcu|picu|nicu|intensive\s*care|high\s*care))", all_text):
        result["act_rawat_icu_hcu"] = "ada"
    if re.search(r"(?:fisioterapi|fisio\s*terapi|fisioterapis|ftr|physiotherapy)", all_text):
        result["act_fisioterapi"] = "ada"
    if re.search(r"(?:konsul\s*(?:gizi|nutrisi|nutrisionis|dietisien)|ahli\s*gizi)", all_text):
        result["act_konsul_gizi"] = "ada"
    if re.search(r"(?:skrining\s*menelan|skrining\s*telan|swallowing\s*screening|tes\s*menelan)", all_text):
        result["act_skrining_menelan"] = "ada"
    if re.search(r"(?:edukasi|penyuluhan|konseling|health\s*education|inform\s*consent|keluarga)", all_text):
        result["act_edukasi_keluarga"] = "ada"
    return result


# ================================================================
# OUTCOME / DISCHARGE
# ================================================================

def extract_outcome(files: list[dict]) -> dict[str, str]:
    result = {"cara_keluar": "unknown", "kondisi_pulang": "unknown",
              "rencana_kontrol": "unknown", "lama_rawat_hari": "unknown",
              "keterangan_pulang": "unknown"}
    kondisi_map = {
        "perbaikan": "perbaikan", "membaik": "perbaikan", "baik": "perbaikan",
        "stabil": "stabil", "stabilis": "stabil",
        "memburuk": "perburukan", "perburukan": "perburukan", "buruk": "perburukan",
        "meninggal": "meninggal_dunia", "meninggal dunia": "meninggal_dunia", "death": "meninggal_dunia", "deceased": "meninggal_dunia",
        "pulang": "pulang", "rawat jalan": "rawat_jalan",
    }
    for f in files:
        if f["doc_type"] != "resume":
            continue
        text = f["text"]
        # Cara Keluar / Keterangan pulang
        m = re.search(r"(?:Cara\s*Pasien\s*Keluar|Cara\s*Keluar)\s*[:=]?\s*([A-Za-z\s]{5,50})", text, re.I)
        if m:
            raw = m.group(1).strip()
            result["cara_keluar"] = raw
            # Klasifikasi keterangan_pulang
            low = raw.lower()
            if any(w in low for w in ["meninggal", "meninggal dunia", "death"]):
                result["keterangan_pulang"] = "meninggal_dunia"
            elif any(w in low for w in ["rujuk", "dirujuk", "rujukan"]):
                result["keterangan_pulang"] = "dirujuk"
            elif any(w in low for w in ["pulang", "ke rumah", "perbaikan", "baik", "stabil"]):
                result["keterangan_pulang"] = "pulang_ke_rumah"
            elif any(w in low for w in ["aps", "atas permintaan", "paksa"]):
                result["keterangan_pulang"] = "aps"
        # Kondisi Pulang — diklasifikasi
        m = re.search(r"(?:Kondisi\s*Pasien\s*(?:Pada\s*Saat)?\s*Pulang|Kondisi\s*Pulang)\s*[:=]?\s*([A-Za-z\s]{5,50})", text, re.I)
        if m:
            raw_kondisi = m.group(1).strip().lower()
            classified = "unknown"
            for key, val in kondisi_map.items():
                if key in raw_kondisi:
                    classified = val
                    break
            if classified != "unknown":
                result["kondisi_pulang"] = classified
            else:
                result["kondisi_pulang"] = raw_kondisi.capitalize()
        m = re.search(r"(?:Intruksi\s*Tindak\s*Lanjut\s*Kontrol|Rencana\s*Kontrol|Kontrol)\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text, re.I)
        if m:
            result["rencana_kontrol"] = m.group(1)
        # Lama rawat — coba langsung dulu
        m = re.search(r"(?:Lama\s*Rawat|Lama\s*Dirawat|LOS|Length\s*Of\s*Stay)\s*[:=]?\s*(\d+)\s*(?:hari|hr|h)?", text, re.I)
        if m:
            result["lama_rawat_hari"] = m.group(1)
        else:
            # Hitung dari tanggal masuk-keluar
            m_in = re.search(r"(?:Tanggal\s*Masuk|Tgl\s*Masuk|MRS|Admission)\s*[:=]?\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
            m_out = re.search(r"(?:Tanggal\s*Keluar|Tgl\s*Keluar|Keluar)\s*[:=]?\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.I)
            if m_in and m_out:
                d_in = parse_indonesian_date(m_in.group(1))
                d_out = parse_indonesian_date(m_out.group(1))
                if d_in and d_out:
                    try:
                        from datetime import datetime as dt
                        di = dt.strptime(d_in, "%Y-%m-%d")
                        do = dt.strptime(d_out, "%Y-%m-%d")
                        days = (do - di).days
                        if days >= 0:
                            result["lama_rawat_hari"] = str(days)
                    except Exception:
                        pass
        if f["doc_type"] == "resume":
            break
    return result


# ================================================================
# VALIDASI DATA
# ================================================================

VALIDATION_RULES = {
    "gcs": {"min": 3, "max": 15, "label": "GCS"},
    "td_sistol": {"min": 60, "max": 260, "label": "TD Sistol"},
    "td_diastol": {"min": 30, "max": 180, "label": "TD Diastol"},
    "hr": {"min": 30, "max": 250, "label": "HR/Nadi"},
    "rr": {"min": 5, "max": 60, "label": "RR"},
    "suhu": {"min": 35.0, "max": 42.0, "label": "Suhu"},
    "spo2": {"min": 50, "max": 100, "label": "SpO2"},
    "demo_age": {"min": 0, "max": 120, "label": "Usia"},
    "lab_hb": {"min": 2, "max": 25, "label": "HB"},
    "lab_leukosit": {"min": 0.1, "max": 500, "label": "Leukosit"},
    "lab_trombosit": {"min": 1, "max": 1500, "label": "Trombosit"},
    "lab_gds": {"min": 10, "max": 800, "label": "GDS"},
    "lab_ureum": {"min": 1, "max": 300, "label": "Ureum"},
    "lab_kreatinin": {"min": 0.1, "max": 30, "label": "Kreatinin"},
}


def validate_field(value: str, field: str) -> tuple[str, str | None]:
    """
    Validasi satu field. Return (cleaned_value, warning_message).
    Jika valid: value as-is, None.
    Jika invalid: "invalid", pesan error.
    """
    if field not in VALIDATION_RULES:
        return value, None
    rules = VALIDATION_RULES[field]
    try:
        v = float(value.replace(",", "."))
        if v < rules["min"] or v > rules["max"]:
            return "invalid", f"{rules['label']}={value} (range: {rules['min']}-{rules['max']})"
        return value, None
    except (ValueError, AttributeError):
        return value, None  # unknown/tidak terbaca → skip validasi


def validate_extracted_data(data: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Validasi semua field numerik dalam hasil ekstraksi. Return (data, warnings)."""
    warnings = []
    for field in list(data.keys()):
        val = data[field]
        cleaned, warn = validate_field(val, field)
        if cleaned == "invalid":
            data[field] = "invalid"
        if warn:
            warnings.append(warn)
    return data, warnings


# ================================================================
# CATEGORY-BASED EXTRACTION
# ================================================================

EXTRACTOR_CATEGORIES_EXTRA_PATH = Path(__file__).parent / "extractor_categories_extra.json"

# ================================================================
# GENERIC EXTRACTOR untuk kategori user-defined
# ================================================================

def extract_generic_fields(files: list[dict], fields: list[str], keywords: list[str] | None = None) -> dict[str, str]:
    """Ekstraktor generik untuk kategori user-defined.
    
    Cara kerja:
    - Jika keywords diberikan: cari setiap keyword di semua teks → "ada"/"tidak" per field
    - Jika keywords kosong: semua field = "unknown" (isi manual nanti)
    """
    all_text = " ".join(f["text"] for f in files).lower()
    result: dict[str, str] = {}
    
    if keywords:
        for f in fields:
            # Cari apakah ada keyword yang cocok dengan field ini
            found_keywords = [kw for kw in keywords if kw.lower() in all_text]
            if found_keywords:
                result[f] = "ada"
            else:
                result[f] = "tidak"
    else:
        for f in fields:
            result[f] = "unknown"
    
    return result


def load_extra_categories() -> dict:
    """Load user-defined categories from JSON, merge dengan hardcoded defaults."""
    extra_categories: dict[str, dict] = {}
    
    if EXTRACTOR_CATEGORIES_EXTRA_PATH.exists():
        try:
            raw = json.loads(EXTRACTOR_CATEGORIES_EXTRA_PATH.read_text(encoding="utf-8"))
            for cat_name, cat_data in raw.items():
                if cat_name.startswith("_"):
                    continue  # skip komentar
                if "fields" in cat_data and isinstance(cat_data["fields"], list):
                    fields = cat_data["fields"]
                    extractor_type = cat_data.get("extractor", "none")
                    keywords = cat_data.get("keywords", [])
                    
                    if extractor_type == "keyword" and keywords:
                        # Buat closure yang bind keywords
                        def make_keyword_extractor(kw_list, flds):
                            def extractor(files):
                                return extract_generic_fields(files, flds, kw_list)
                            return extractor
                        extractor_fn = make_keyword_extractor(keywords, fields)
                    else:
                        def make_unknown_extractor(flds):
                            def extractor(files):
                                return extract_generic_fields(files, flds, None)
                            return extractor
                        extractor_fn = make_unknown_extractor(fields)
                    
                    extra_categories[cat_name] = {
                        "fields": fields,
                        "extractor": extractor_fn,
                        "desc": cat_data.get("desc", f"Kategori user: {cat_name}"),
                    }
        except Exception as e:
            print(f"[WARNING] Gagal load extra categories: {e}")
    
    return extra_categories


# Build final EXTRACTOR_CATEGORIES = hardcoded + extra dari JSON
_EXTRA_CATS = load_extra_categories()

EXTRACTOR_CATEGORIES = {
    "Demografi": {
        "fields": ["demo_age", "demo_gender", "jenis_kelamin"],
        "extractor": extract_demographics,
        "desc": "Usia + Jenis Kelamin (Laki-laki/Perempuan) dari Resume",
    },
    "Diagnosis Stroke": {
        "fields": ["stroke_type", "diagnosis_text"],
        "extractor": extract_diagnosis,
        "desc": "Infark / Hemoragik + teks diagnosis",
    },
    "GCS": {
        "fields": ["gcs"],
        "extractor": None,
        "desc": "Glasgow Coma Scale dari CPPT IGD/Ranap",
    },
    "Vital Sign": {
        "fields": ["td_sistol", "td_diastol", "hr", "rr", "suhu", "spo2"],
        "extractor": extract_vitals,
        "desc": "TD, HR, RR, Suhu, SpO2 dari CPPT IGD",
    },
    "CT Scan": {
        "fields": ["ct_documented", "ct_result", "ct_infark_lokasi",
                    "ct_aspects", "ct_perdarahan", "ct_midline_shift",
                    "ct_hidrosefalus", "ct_atrofi", "ct_tanggal"],
        "extractor": extract_ct_scan,
        "desc": "Dokumentasi CT, lokasi infark, ASPECTS, perdarahan, midline shift, dll",
    },
    "Thorax": {
        "fields": ["thorax_documented", "thorax_kesan", "thorax_tanggal"],
        "extractor": extract_thorax,
        "desc": "Hasil foto thorax + kesan + tanggal",
    },
    "Laboratorium": {
        "fields": ["lab_hb", "lab_leukosit", "lab_trombosit", "lab_gds",
                    "lab_ureum", "lab_kreatinin", "lab_ht", "lab_eritrosit",
                    "lab_natrium", "lab_kalium", "lab_asam_urat",
                    "lab_inr", "lab_ldl", "lab_kolesterol_total",
                    "lab_trigliserida", "lab_hba1c"],
        "extractor": extract_lab_values,
        "desc": "16 parameter: HB, Leukosit, Trombosit, GDS, Ureum, Kreatinin, INR, LDL, Kolesterol, Trigliserida, HBA1c",
    },
    "Tanggal Laboratorium": {
        "fields": ["lab_tanggal_igd", "lab_tanggal_ranap", "lab_tanggal_pertama"],
        "extractor": extract_lab_dates,
        "desc": "Tanggal sampling lab IGD, Ranap, dan pertama",
    },
    "Demam": {
        "fields": ["demam_saat_masuk", "demam_selama_rawat", "suhu_tertinggi"],
        "extractor": extract_demam,
        "desc": "Tracking demam saat masuk & selama rawat + suhu tertinggi",
    },
    "Medikasi": {
        "fields": ["med_antiplatelet",
                    "med_antikoagulan", "med_statin",
                    "med_antihipertensi", "med_mannitol", "med_citicoline",
                    "med_ppi", "med_antibiotik",
                    "med_antiplatelet_detail",
                    "med_antikoagulan_detail", "med_statin_detail", "med_antihipertensi_detail",
                    "med_mannitol_detail", "med_citicoline_detail", "med_ppi_detail", "med_antibiotik_detail"],
        "extractor": extract_medications,
        "desc": "16 field dasar: antiplatelet, antikoagulan, statin, antihipertensi, mannitol, citicoline, PPI, antibiotik",
    },
    "Faktor Risiko": {
        "fields": ["rf_hipertensi", "rf_diabetes", "rf_dislipidemia",
                    "rf_jantung", "rf_stroke_sebelumnya", "rf_merokok",
                    "rf_atrial_fibrilasi", "rf_obesitas", "rpd_text"],
        "extractor": extract_risk_factors,
        "desc": "Hipertensi, DM, Dislipidemia, Jantung, Stroke prev, Merokok, AF, Obesitas, RPD",
    },
    "Tindakan Klinis": {
        "fields": ["act_konsul_neurologi", "act_konsul_bedah_saraf",
                    "act_konsul_jantung", "act_rawat_icu_hcu",
                    "act_fisioterapi", "act_konsul_gizi",
                    "act_skrining_menelan", "act_edukasi_keluarga"],
        "extractor": extract_actions,
        "desc": "Konsul neuro, bedah saraf, jantung, fisioterapi, gizi, skrining menelan, edukasi",
    },
    "Outcome": {
        "fields": ["cara_keluar", "kondisi_pulang", "rencana_kontrol", "lama_rawat_hari", "keterangan_pulang"],
        "extractor": extract_outcome,
        "desc": "Cara keluar, kondisi pulang (perbaikan/stabil/perburukan/meninggal), kontrol, LOS, keterangan",
    },
}

# Merge extra categories dari JSON (user-defined)
if _EXTRA_CATS:
    for cat_name, cat_data in _EXTRA_CATS.items():
        if cat_name not in EXTRACTOR_CATEGORIES:
            EXTRACTOR_CATEGORIES[cat_name] = cat_data
            print(f"[INFO] Loaded extra category: {cat_name} ({len(cat_data['fields'])} fields)")


def get_extractor_categories() -> dict:
    """Return EXTRACTOR_CATEGORIES + reload extra categories (untuk Streamlit hot-reload).
    
    Memeriksa file JSON extra categories setiap kali dipanggil.
    Jika ada perubahan, merge ulang tanpa restart.
    Juga mendukung OVERRIDE field list untuk kategori hardcoded.
    """
    result = dict(EXTRACTOR_CATEGORIES)
    if EXTRACTOR_CATEGORIES_EXTRA_PATH.exists():
        try:
            raw = json.loads(EXTRACTOR_CATEGORIES_EXTRA_PATH.read_text(encoding="utf-8"))
            for cat_name, cat_data in raw.items():
                if cat_name.startswith("_"):
                    continue
                if "fields" in cat_data and isinstance(cat_data["fields"], list):
                    fields = cat_data["fields"]
                    extractor_type = cat_data.get("extractor", "none")
                    keywords = cat_data.get("keywords", [])
                    
                    # Jika kategori SUDAH ada di hardcoded → override fields saja
                    if cat_name in EXTRACTOR_CATEGORIES:
                        # Override field list, pertahankan extractor asli
                        result[cat_name] = dict(EXTRACTOR_CATEGORIES[cat_name])
                        result[cat_name]["fields"] = fields
                        result[cat_name]["desc"] = cat_data.get("desc", result[cat_name].get("desc", cat_name))
                        continue
                    
                    # Kategori BARU (tidak ada di hardcoded)
                    if extractor_type == "keyword" and keywords:
                        def make_kw_ext(kw_list, flds):
                            def ext(files):
                                return extract_generic_fields(files, flds, kw_list)
                            return ext
                        extractor_fn = make_kw_ext(keywords, fields)
                    else:
                        def make_unk_ext(flds):
                            def ext(files):
                                return extract_generic_fields(files, flds, None)
                            return ext
                        extractor_fn = make_unk_ext(fields)
                    
                    result[cat_name] = {
                        "fields": fields,
                        "extractor": extractor_fn,
                        "desc": cat_data.get("desc", f"Kategori user: {cat_name}"),
                    }
        except Exception as e:
            print(f"[WARNING] Gagal reload extra categories: {e}")
    return result


def extract_one_patient(
    anon_dir: Path,
    patient_folder: str,
    selected_categories: list[str] | None = None,
    selected_drug_keys: list[str] | None = None,
    selected_fields: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """
    Ekstraksi sesuai kategori yang dipilih.
    Args:
        anon_dir: folder teks anonim
        patient_folder: nama folder pasien
        selected_categories: list kategori (None = semua)
        selected_drug_keys: sub-kategori obat (None = semua obat)
        selected_fields: dict {kategori: [field1, field2, ...]} — hanya field ini yang diekstrak (None = semua field)
    """
    patient_path = anon_dir / patient_folder
    if not patient_path.exists() or not patient_path.is_dir():
        return {"patient_id": patient_folder, "error": "folder_not_found"}

    files = read_patient_files(patient_path)
    if not files:
        return {"patient_id": patient_folder, "error": "no_valid_files"}

    result: dict[str, str] = {"patient_id": patient_folder}

    # Tentukan kategori yang akan diekstrak
    _cats_map = get_extractor_categories()
    if selected_categories is None:
        cats = list(_cats_map.keys())
    else:
        cats = [c for c in selected_categories if c in _cats_map]

    for cat in cats:
        info = _cats_map[cat]
        extractor = info["extractor"]
        fields = info["fields"]
        
        # Filter field sesuai selected_fields (kalau ada)
        if selected_fields and cat in selected_fields:
            fields = [f for f in fields if f in selected_fields[cat]]
            if not fields:
                continue  # skip kategori kalau semua field di-uncheck

        if extractor is not None:
            # Jika Medikasi, kirim selected_drug_keys
            if cat == "Medikasi" and selected_drug_keys is not None:
                data = extract_medications(files, selected_drug_keys)
                # Hanya include field yang ada di data (sub-kategori terpilih)
                for k, v in data.items():
                    result[k] = v
            else:
                data = extractor(files)
                # Mapping field
                field_map = {
                    "demo_age": "age",
                    "demo_gender": "gender",
                    "jenis_kelamin": "gender",
                    "stroke_type": "stroke_type",
                    "diagnosis_text": "diagnosis_text",
                }
                for f in fields:
                    if f in data:
                        result[f] = data[f]
                    elif f in field_map and field_map[f] in data:
                        result[f] = data[field_map[f]]
                    else:
                        result[f] = "unknown"
                # Merge extra fields dinamis (misal kategori obat baru dari drug database)
                for k, v in data.items():
                    if k not in result:
                        result[k] = v
        else:
            # Ekstraktor manual (GCS — bukan dict)
            val = extract_gcs(files)
            for f in fields:
                result[f] = val

    # Validasi semua field numerik
    result, _warnings = validate_extracted_data(result)

    return result


def extract_all_patients(
    anon_dir: Path | str,
    selected_categories: list[str] | None = None,
    selected_drug_keys: list[str] | None = None,
    selected_fields: dict[str, list[str]] | None = None,
    *extra_args,
) -> list[dict[str, str]]:
    """
    Ekstraksi untuk semua pasien dalam folder anonim.
    Mendukung 2 struktur folder:
      - NESTED: subfolder per pasien ├── pasien_001/*.anon.txt
      - FLAT:   semua file langsung     ├── *.anon.txt (tanpa subfolder)
    Args:
        anon_dir: folder teks anonim
        selected_categories: list kategori (None = semua)
        selected_fields: dict {kategori: [field1, ...]} — filter field per kategori (None = semua)
    """
    anon_dir = Path(anon_dir)
    if not anon_dir.exists():
        return []

    # Cek: nested (subfolder) atau flat (file langsung)?
    patient_dirs = sorted([d.name for d in anon_dir.iterdir() if d.is_dir()])
    flat_files = sorted([f for f in anon_dir.glob("*.anon.txt") if f.is_file()])

    results = []

    if patient_dirs:
        # ── STRUKTUR NESTED: subfolder per pasien ──
        for pid in patient_dirs:
            r = extract_one_patient(anon_dir, pid, selected_categories, selected_drug_keys, selected_fields)
            results.append(r)
    elif flat_files:
        # ── STRUKTUR FLAT: semua file .anon.txt di root folder ──
        # Gabung semua file sebagai satu "pasien virtual"
        files = []
        for fp in flat_files:
            text = normalize_text(fp.read_text(encoding="utf-8", errors="ignore"))
            if len(text.strip()) < 20:
                continue
            files.append({
                "source_file": fp.name,
                "doc_type": get_doc_type(fp.name),
                "text": text,
                "char_count": len(text),
            })
        if files:
            patient_id = anon_dir.name  # pakai nama folder sebagai ID
            result: dict[str, str] = {"patient_id": patient_id}

            if selected_categories is None:
                _cats_map2 = get_extractor_categories()
                cats = list(_cats_map2.keys())
            else:
                cats = [c for c in selected_categories if c in _cats_map2]

            for cat in cats:
                info = _cats_map2[cat]
                extractor = info["extractor"]
                fields = info["fields"]
                
                # Filter field sesuai selected_fields
                if selected_fields and cat in selected_fields:
                    fields = [f for f in fields if f in selected_fields[cat]]
                    if not fields:
                        continue

                if extractor is not None:
                    # Jika Medikasi, kirim selected_drug_keys
                    if cat == "Medikasi" and selected_drug_keys is not None:
                        data = extract_medications(files, selected_drug_keys)
                        # Hanya include field yang ada di data (sub-kategori terpilih)
                        for k, v in data.items():
                            result[k] = v
                    else:
                        data = extractor(files)
                        field_map = {
                            "demo_age": "age",
                            "demo_gender": "gender",
                            "jenis_kelamin": "gender",
                            "stroke_type": "stroke_type",
                            "diagnosis_text": "diagnosis_text",
                        }
                        for f in fields:
                            if f in data:
                                result[f] = data[f]
                            elif f in field_map and field_map[f] in data:
                                result[f] = data[field_map[f]]
                            else:
                                result[f] = "unknown"
                        # Merge extra fields dinamis (kategori obat baru)
                        for k, v in data.items():
                            if k not in result:
                                result[k] = v
                else:
                    val = extract_gcs(files)
                    for f in fields:
                        result[f] = val

            # Validasi numerik
            result, _warnings = validate_extracted_data(result)
            results.append(result)

    return results


# ================================================================
# SELF-TEST
# ================================================================

def self_test() -> bool:
    """Jalankan self-test anonimisasi dengan sample."""
    variants = [
        ("Mugi Rahayu", "DOKTER_UMUM"),
        ("Sri Yujianingsih", "APOTEKER"),
        ("Riki Septian", "PERAWAT"),
        ("Adi Maulana", "DOKTER_SPESIALIS_RADIOLOGI"),
    ]
    sample = """
RS AL ISLAM BANDUNG
No RM: 123456
NIK: 3201010101010001
Nama Pasien: Ahmad Fulan
Tanggal Lahir: 01-01-1960
Alamat: Jl. Contoh No 1 Bandung
No SEP: 0123R0010526V000001
No Lab: LAB-12345
08-05-2026
10:30:00
Sri Yujianingsih
Apt.
S
Pasien mengeluh lemah anggota gerak kanan. GCS E4M6V5. TD 180/100.
Dokter IGD: dr. Mugi Rahayu
Perawat: Riki Septian, Ners
Print copy by : Adi Maulana, dr, Sp.Rad
HP keluarga 081234567890
email pasien pasien@example.com
"""
    role_patterns = compile_role_patterns(variants)
    anon, counts, leftovers, _ = anonymize_text(sample, role_patterns)
    leaks = [
        x for x in [
            "Ahmad Fulan", "3201010101010001", "081234567890",
            "pasien@example.com", "Mugi Rahayu", "Sri Yujianingsih",
            "Riki Septian", "Adi Maulana",
        ]
        if x.lower() in anon.lower()
    ]
    if leaks:
        print("SELF-TEST GAGAL — bocor:", leaks, file=sys.stderr)
        print("anon:")
        print(anon)
        return False
    print("SELF-TEST OK")
    print("Counts:", json.dumps(counts, indent=2, ensure_ascii=False))
    print("Leftovers:", json.dumps(leftovers, indent=2, ensure_ascii=False))
    return True


# ================================================================
# CLI ENTRY POINT
# ================================================================

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(0 if self_test() else 1)
    print("pipeline_core.py — gunakan dari run_stroke_app.py atau import langsung.")
