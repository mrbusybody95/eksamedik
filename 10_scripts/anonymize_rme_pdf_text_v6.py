from __future__ import annotations

"""
Anonimisasi RME PDF/TXT v6.
- Input: PDF/TXT rekam medis (CPPT IGD, CPPT ranap, lab, radiologi) secara rekursif.
- Output: teks anonim + audit CSV/JSON.
- Prinsip: tidak mengirim data pasien ke API/LLM; semua regex/OCR lokal.

Contoh:
  python anonymize_rme_pdf_text_v6.py --input ../01_raw_pdf --output ../03_anonymized_text_v6 --report ../04_anonymization_report_v6 --staff-csv staff_doctors.csv
  python anonymize_rme_pdf_text_v6.py --self-test
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None
try:
    import fitz  # type: ignore
except Exception:
    fitz = None
try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    import io
except Exception:
    pytesseract = None
    Image = None
    io = None

LABEL = {
    "patient": "[PASIEN]", "family": "[KELUARGA]", "mrn": "[NO_RM]", "nik": "[NIK]",
    "phone": "[NO_HP]", "email": "[EMAIL]", "address": "[ALAMAT]", "birth": "[TANGGAL_LAHIR]",
    "sep": "[NO_SEP]", "visit": "[NO_KUNJUNGAN]", "lab": "[NO_LAB]", "rad": "[NO_RADIOLOGI]",
    "hospital": "[RUMAH_SAKIT]",
}

CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning", "observasi", "pasien", "nyeri",
    "lemah", "sesak", "muntah", "demam", "stroke", "infark", "anamnesis", "pemeriksaan",
    "tekanan", "darah", "suhu", "spo2", "gcs", "ews", "hasil", "nilai", "rujukan", "satuan",
    "alamat", "umur", "tgl", "lahir", "hematologi", "hemoglobin", "leukosit", "foto", "thorax",
    "kesan", "cor", "pulmo", "ct", "scan", "kepala", "normal", "abnormal", "igd", "ranap",
}
TITLE_WORDS = {
    "dr", "drg", "prof", "sp", "spd", "spn", "sps", "sprad", "sppk", "sppa", "sppd", "spjp",
    "span", "spb", "spbs", "spot", "spu", "spa", "spog", "spp", "spkfr", "spkj", "sptht",
    "spm", "spkk", "spdv", "mkes", "mhkes", "mm", "mmrs", "msc", "phd", "finasim", "fiha",
    "kic", "fics", "cahm", "khom", "subsp", "h", "hj", "haji", "hajah", "kom", "pol",
}
SPECIALIST_MAP = {
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI", "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI", "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI", "sp.pd": "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.jp": "DOKTER_SPESIALIS_JANTUNG", "sp.an": "DOKTER_SPESIALIS_ANESTESI",
    "sp.b": "DOKTER_SPESIALIS_BEDAH", "sp.bs": "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot": "DOKTER_SPESIALIS_ORTOPEDI", "sp.u": "DOKTER_SPESIALIS_UROLOGI",
    "sp.a": "DOKTER_SPESIALIS_ANAK", "sp.og": "DOKTER_SPESIALIS_OBGYN",
    "sp.p": "DOKTER_SPESIALIS_PARU", "sp.kfr": "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj": "DOKTER_SPESIALIS_KEDOKTERAN_JIWA", "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m": "DOKTER_SPESIALIS_MATA", "sp.kk": "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv": "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",
}
LEFTOVER_PATTERNS = {
    "leftover_nik_16": r"\b\d{16}\b",
    "leftover_phone": r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b",
    "leftover_email": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    "leftover_rm": r"(?i)\b(?:no\.?\s*rm|rekam\s*medis|mrn)\s*[:\-]?\s*[A-Za-z0-9\-/\.]{3,}",
    "leftover_sep": r"(?i)\b(?:no\.?\s*sep|sep)\s*[:\-]?\s*[A-Za-z0-9\-/\.]{5,}",
    "leftover_dr_name": r"(?i)\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
    "leftover_name_comma_dr": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*(?:H\.?|Hj\.?)?\s*drg?\.?:?",
    # Sp leftover: only match Sp. with specialist code, not clinical terms (spontan, SPO2)
    "leftover_sp": r"(?i)\bSp\.\s*[A-Za-z]{2,}\b",
    "leftover_ners_apt": r"(?i)\b(?:Ners|Ns\.?|Apt\.?|Amd\.?\s*Kep\.?|Amd\.?\s*Rad\.?)\b",
}

@dataclass
class SourceText:
    path: Path
    relative_path: Path
    text: str
    extraction_status: str
    ocr_used: bool = False


def add_count(counts: dict[str, int], key: str, n: int) -> None:
    counts[key] = counts.get(key, 0) + int(n)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text)


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


def flexible_name_pattern(variant: str) -> str:
    parts = [re.escape(p) for p in variant.split() if p.strip()]
    return r"(?<![A-Za-z])" + r"(?:\s|,|\.|\-|_)+".join(parts) + r"(?![A-Za-z])"


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


def load_staff_variants(staff_csv: Path | None) -> list[tuple[str, str]]:
    if not staff_csv or not staff_csv.exists():
        return []
    variants: list[tuple[str, str]] = []
    with staff_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or infer_role(name)
            for v in build_variants(tokens_from_name(name)):
                variants.append((v, role))
    seen = set(); out = []
    for v, r in sorted(variants, key=lambda x: len(x[0]), reverse=True):
        key = (v.lower(), r)
        if key not in seen:
            seen.add(key); out.append((v, r))
    return out


def is_text_empty(text: str) -> bool:
    return len(re.sub(r"\s+", "", text or "")) < 50


def read_source(path: Path, root: Path, use_ocr: bool = True) -> SourceText:
    rel = path.relative_to(root)
    if path.suffix.lower() == ".txt":
        return SourceText(path, rel, path.read_text(encoding="utf-8", errors="ignore"), "txt", False)
    text = ""
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            text = "\n".join(f"\n--- HALAMAN {i}: {path.name} ---\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages, 1))
        except Exception:
            text = ""
    if not is_text_empty(text):
        return SourceText(path, rel, text, "pdf_pypdf", False)
    if fitz is not None:
        try:
            with fitz.open(str(path)) as doc:
                text = "\n".join(f"\n--- HALAMAN {i}: {path.name} ---\n{p.get_text('text') or ''}" for i, p in enumerate(doc, 1))
        except Exception:
            text = ""
    if not is_text_empty(text):
        return SourceText(path, rel, text, "pdf_fitz_text", False)
    if use_ocr and fitz is not None and pytesseract is not None and Image is not None and io is not None:
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


def apply_patterns(text: str, counts: dict[str, int], specs: list[tuple[str, str, str]], flags: int = re.I) -> str:
    for key, pat, repl in specs:
        text, n = re.subn(pat, repl, text, flags=flags)
        add_count(counts, key, n)
    return text


def anonymize_patient_docs(text: str, counts: dict[str, int]) -> str:
    specs = [
        ("mrn", r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", LABEL["mrn"]),
        ("nik_labeled", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", LABEL["nik"]),
        ("nik_16", r"\b\d{16}\b", LABEL["nik"]),
        ("sep", r"\b(?:No\.?\s*SEP|SEP)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]{5,}", LABEL["sep"]),
        ("visit", r"\b(?:No\.?\s*(?:Registrasi|Reg|Kunjungan|Visit)|Admission\s*No)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]{3,}", LABEL["visit"]),
        ("lab_id", r"\b(?:No\.?\s*(?:Lab|Laboratorium)|ID\s*Lab|Order\s*Lab)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]{3,}", LABEL["lab"]),
        ("rad_id", r"\b(?:No\.?\s*(?:Rad|Radiologi)|Accession\s*No|ID\s*Radiologi)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]{3,}", LABEL["rad"]),
        ("phone", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", LABEL["phone"]),
        ("email", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", LABEL["email"]),
        ("birthdate", r"\b(?:Tgl\.?\s*Lahir|Tanggal\s*Lahir|DOB)\s*[:\-]?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", "Tanggal Lahir: " + LABEL["birth"]),
        # Patient name: handles multiline "Nama\nPasien" and trailing ",HJ" etc.
        ("patient_name", r"(?is)(?:Nama\s*Pasien|Nama)[\s\n]*:[\s\n]*([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}(?:,\s*[A-Z]{1,3})?)", "Nama Pasien: " + LABEL["patient"]),
        # Family names
        ("family_name", r"(?is)(?:Penanggung\s*Jawab|Keluarga|Nama\s*Ayah|Nama\s*Ibu|Suami|Istri)[\s\n]*:[\s\n]*([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}(?:,\s*[A-Z]{1,3})?)", LABEL["family"]),
        # Address - line starting with Alamat/Domisili
        ("address", r"(?im)^\s*(?:Alamat|Domisili)\s*[:\-]?\s*.{5,160}$", "Alamat: " + LABEL["address"]),
        ("hospital", r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", LABEL["hospital"]),
        # CPPT field headers like "OA :", "B :", "C :", "D :", "E :", "S :" - run before rs_address
        ("cppt_field", r"(?im)^\s*(?:OA?|B|C|D|E|S)\s*:.*$", "[CPPT_FIELD]"),
        # Hospital address - only if NOT part of CPPT field (already masked above)
        ("rs_address", r"\b(?:Jl\.|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]"),
        ("rs_phone", r"\b(?:Telp\.?|Telepon|Phone|Fax)\.?\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]
    return apply_patterns(text, counts, specs)


def compile_role_patterns(variants: list[tuple[str, str]]) -> list[tuple[re.Pattern, str]]:
    """Group variants by role, compile ONE regex per role instead of per-variant.
    Speedup: ~8-10x for typical staff lists."""
    groups: dict[str, list[str]] = {}
    for v, role in variants:
        groups.setdefault(role, []).append(v)

    compiled: list[tuple[re.Pattern, str]] = []
    for role, names in groups.items():
        names.sort(key=len, reverse=True)  # longer first to match more specific variants
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


def anonymize_staff_csv(text: str, counts: dict[str, int], role_patterns: list[tuple[re.Pattern, str]]) -> str:
    for pat, role in role_patterns:
        text, n = pat.subn(f"[{role}]", text)
        add_count(counts, f"staff_csv_{role}", n)
    return text


def anonymize_doctor_regex(text: str, counts: dict[str, int]) -> str:
    degree = r"(?:drg?\.?|Drg?\.?)"
    sp = r"(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)"
    honor = r"(?:Prof\.?|H\.?|Hj\.?)"
    suffix = r"(?:\s*,?\s*(?:H\.?|Hj\.?|KIC|FINASIM|FIHA|FICS|M\.?Kes|MH\.?Kes|M\.?Sc|MM|MMRS|SH|MH|PhD|CAHM|KHOM|CH))*"
    def repl(m: re.Match[str]) -> str:
        old = m.group(0); role = infer_role(old); add_count(counts, f"doctor_regex_{role}", 1)
        pref = re.match(r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim|Diverifikasi\s+oleh|Print\s+copy\s+(?:ke-\d+\s+)?by)\s*[:\-]?", old.strip())
        return f"{pref.group(1)}: [{role}]" if pref else f"[{role}]"
    patterns = [
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,60}}(?:\n\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\.?",
        rf"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\.?\)?",
        rf"\b{degree}\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}(?:,\s*)?{sp}?{suffix}\.?",
        rf"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"(?m)^[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])",
    ]
    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.I | re.S)
    return text


def anonymize_other_ppa(text: str, counts: dict[str, int]) -> str:
    specs = [
        ("nurse", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[PERAWAT]"),
        ("nurse", r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b", "[PERAWAT]"),
        ("midwife", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[BIDAN]"),
        ("pharmacist", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[APOTEKER]"),
        ("pharmacist", r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b", "[APOTEKER]"),
        ("lab_staff", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[ANALIS_LAB]"),
        ("radiographer", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[RADIOGRAFER]"),
        ("nutrition", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80}", "[NUTRISIONIS]"),
    ]
    return apply_patterns(text, counts, specs)


def anonymize_cppt_header(text: str, counts: dict[str, int]) -> str:
    def repl(m: re.Match[str]) -> str:
        header, block, soap = m.group("header"), m.group("block"), m.group("soap")
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        joined = " ".join(lines); low = joined.lower()
        if any(w in low for w in CLINICAL_STOPWORDS) or len(lines) > 5 or len(joined) > 160:
            return m.group(0)
        role = "PPA"
        if re.search(r"\[APOTEKER\]|\bapt\.?\b|apoteker", joined, re.I): role = "APOTEKER"
        elif re.search(r"\[PERAWAT\]|\bners\b|\bns\.?\b|\bamd\.?\s*kep\b|\bs\.?\s*kep\b", joined, re.I): role = "PERAWAT"
        elif re.search(r"\bdrg?\.?\b|\bdr\b|\bsp\.?|\[DOKTER", joined, re.I): role = infer_role(joined)
        elif re.search(r"\[RADIOGRAFER\]|amd\.?\s*rad", joined, re.I): role = "RADIOGRAFER"
        add_count(counts, f"cppt_header_{role}", 1)
        return f"{header}[{role}]\n{soap}"
    # Simpler pattern: date\n time\n (1-5 lines that are not SOAP)\n SOAP
    pat = r"(?m)(?P<header>^\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*\n\s*\d{1,2}:\d{2}(?::\d{2})?\s*\n)(?P<block>(?:[^\n]+\n){1,5})(?P<soap>^\s*[SOAP]\s*$)"
    return re.sub(pat, repl, text)


def cleanup(text: str, counts: dict[str, int]) -> str:
    specs = [
        ("cleanup_colon_name_label", r"(?m)^(\s*:\s*)[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80},?\s*(\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|NUTRISIONIS|ANALIS_LAB)(?:_[A-Z_]+)?\])", r"\1\2"),
        ("cleanup_label_degree", r"(\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER)(?:_[A-Z_]+)?\])\s*[\.,]*\s*(?:drg?\.?|Sp\.?\s*[A-Za-z]+|Ners|Ns\.?|Apt\.?|Amd\.?\s*Kep\.?|Amd\.?\s*Rad\.?)\b\.?,?", r"\1"),
        ("cleanup_print_copy", r"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
    ]
    text = apply_patterns(text, counts, specs)
    text, n = re.subn(r"(\[[A-Z_]+\])(?:\s*,?\s*\1)+", r"\1", text); add_count(counts, "cleanup_duplicate_labels", n)
    return re.sub(r"[ \t]+\n", "\n", text)


def detect_leftovers(text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    counts, examples = {}, {}
    for key, pat in LEFTOVER_PATTERNS.items():
        hits = [m.group(0).strip().replace("\n", " ") for m in re.finditer(pat, text, re.I)]
        counts[key] = len(hits)
        if hits:
            examples[key] = [hashlib.sha256(h.encode("utf-8", "ignore")).hexdigest()[:16] for h in hits[:3]]
    return counts, examples


def anonymize_text(text: str, role_patterns: list[tuple[re.Pattern, str]]) -> tuple[str, dict[str, int], dict[str, int], dict[str, list[str]]]:
    counts: dict[str, int] = {}
    text = normalize_text(text)
    for _ in range(2):
        text = anonymize_patient_docs(text, counts)
        text = anonymize_staff_csv(text, counts, role_patterns)
        text = anonymize_doctor_regex(text, counts)
        text = anonymize_other_ppa(text, counts)
        text = anonymize_cppt_header(text, counts)
        text = cleanup(text, counts)
    leftovers, examples = detect_leftovers(text)
    return text, counts, leftovers, examples


def iter_sources(input_dir: Path) -> list[Path]:
    return sorted([p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".pdf", ".txt"}], key=lambda p: str(p).lower())


def process_directory(input_dir: Path, output_dir: Path, report_dir: Path, staff_csv: Path | None, use_ocr: bool = True) -> int:
    if not input_dir.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {input_dir}")
    variants = load_staff_variants(staff_csv)
    role_patterns = compile_role_patterns(variants)  # pre-compile once
    files = iter_sources(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True); report_dir.mkdir(parents=True, exist_ok=True)
    print(f"Input={input_dir}\nOutput={output_dir}\nReport={report_dir}\nStaff variants={len(variants)} → {len(role_patterns)} role patterns\nTotal file={len(files)}")
    rows = []
    for fp in files:
        src = read_source(fp, input_dir, use_ocr)
        anon, counts, leftovers, examples = anonymize_text(src.text, role_patterns)
        out_rel = src.relative_path.with_suffix(".anon.txt")
        out = output_dir / out_rel; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(anon, encoding="utf-8")
        row = {
            "source_file": str(src.relative_path), "output_file": str(out_rel),
            "patient_folder": src.relative_path.parts[0] if len(src.relative_path.parts) > 1 else "",
            "extraction_status": src.extraction_status, "ocr_used": src.ocr_used,
            "chars_in": len(src.text), "chars_out": len(anon), "processed_at": datetime.now().isoformat(timespec="seconds"),
            "needs_manual_review": any(v > 0 for v in leftovers.values()),
            "leftover_examples_sha256_16": json.dumps(examples, ensure_ascii=False),
        }
        row.update(counts); row.update(leftovers); rows.append(row)
        print(f"OK {src.relative_path} -> {out_rel} review={row['needs_manual_review']}")
    keys = []
    for r in rows:
        for k in r:
            if k not in keys: keys.append(k)
    if rows:
        with (report_dir / "anonymization_report_v6.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
        (report_dir / "anonymization_report_v6.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(files)


def self_test() -> int:
    variants = [("Mugi Rahayu", "DOKTER_UMUM"), ("Sri Yujianingsih", "APOTEKER"), ("Riki Septian", "PERAWAT"), ("Adi Maulana", "DOKTER_SPESIALIS_RADIOLOGI")]
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
    anon, counts, leftovers, _ = anonymize_text(sample, compile_role_patterns(variants))
    leaks = [x for x in ["Ahmad Fulan", "3201010101010001", "081234567890", "pasien@example.com", "Mugi Rahayu", "Sri Yujianingsih", "Riki Septian", "Adi Maulana"] if x.lower() in anon.lower()]
    print(anon); print("COUNTS", json.dumps(counts, indent=2, ensure_ascii=False)); print("LEFTOVERS", json.dumps(leftovers, indent=2, ensure_ascii=False))
    if leaks:
        print("SELF-TEST GAGAL, bocor:", leaks, file=sys.stderr); return 1
    print("SELF-TEST OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    base = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="Anonimisasi RME PDF/TXT CPPT/Lab/Radiologi")
    p.add_argument("--input", default=str(base / "02_text_extracted"))
    p.add_argument("--output", default=str(base / "03_anonymized_text_v6"))
    p.add_argument("--report", default=str(base / "04_anonymization_report_v6"))
    p.add_argument("--staff-csv", default=str(Path(__file__).resolve().parent / "staff_doctors.csv"))
    p.add_argument("--no-ocr", action="store_true")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv or sys.argv[1:])
    if args.self_test:
        return self_test()
    process_directory(Path(args.input), Path(args.output), Path(args.report), Path(args.staff_csv) if args.staff_csv else None, use_ocr=not args.no_ocr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
