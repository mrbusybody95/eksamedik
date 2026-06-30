"""
Aplikasi Anonimisasi Rekam Medis
=================================
GUI untuk menjalankan pipeline anonimisasi teks rekam medis
dari folder 02_text_extracted → 03_anonymized_text.

Fitur:
- Pilih beberapa folder input (multi-select)
- Pilih file staff_doctors.csv (opsional)
- Preview hasil sebelum simpan
- Report audit CSV + ringkasan sisa kebocoran
- Tombol cek kebocoran pasca-proses

Cara pakai:
    python anonymizer_app.py
"""

from __future__ import annotations

import csv
import queue
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH, BOTTOM, END, LEFT, RIGHT, TOP, W, X, Y,
    BooleanVar, Frame, Label, Listbox, Menu,
    Scrollbar, StringVar, Text, Tk,
    filedialog, messagebox, ttk,
)


# ============================================================
# CORE ANONYMIZATION ENGINE (dari stage5 + perbaikan)
# ============================================================

SPECIALIST_MAP = {
    "sp.n":      "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s":      "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.rad":    "DOKTER_SPESIALIS_RADIOLOGI",
    "sp.pk":     "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa":     "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",
    "sp.pd":     "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.jp":     "DOKTER_SPESIALIS_JANTUNG",
    "sp.an":     "DOKTER_SPESIALIS_ANESTESI",
    "sp.b":      "DOKTER_SPESIALIS_BEDAH",
    "sp.bs":     "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot":     "DOKTER_SPESIALIS_ORTOPEDI",
    "sp.u":      "DOKTER_SPESIALIS_UROLOGI",
    "sp.a":      "DOKTER_SPESIALIS_ANAK",
    "sp.og":     "DOKTER_SPESIALIS_OBGYN",
    "sp.p":      "DOKTER_SPESIALIS_PARU",
    "sp.kfr":    "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj":     "DOKTER_SPESIALIS_KEDOKTERAN_JIWA",
    "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m":      "DOKTER_SPESIALIS_MATA",
    "sp.kk":     "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv":     "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",
}

CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning", "sesuai",
    "observasi", "pasien", "nyeri", "lemah", "sesak", "muntah", "demam",
    "stroke", "infark", "pneumonia", "hematemesis", "anamnesis",
    "pemeriksaan", "tekanan", "darah", "suhu", "spo2", "gcs", "ews",
    "hasil", "nilai", "rujukan", "satuan", "klinik", "poliklinik",
    "penjamin", "alamat", "umur", "tgl", "lahir", "perempuan", "laki",
    "hematologi", "cell", "counter", "hemoglobin", "leukosit",
    "trigliserida", "foto", "thorax", "kesan", "cor", "pulmo",
}

HONORIFICS  = {"h", "hj", "haji", "hajah"}
TITLE_WORDS = {
    "dr", "drg", "sp", "spd", "spn", "sps", "sprad", "sppk", "sppd", "spjp",
    "mkes", "mhkes", "mm", "msc", "phd", "finasim", "fiha", "kic",
}


# ── helpers ─────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", text)


def merge_counts(*dicts: dict) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def infer_role(s: str) -> str:
    low     = s.lower()
    compact = re.sub(r"[\s,.]+", "", low)
    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: -len(x[0])):
        key = degree.replace(".", "").replace(" ", "")
        if key in compact:
            return role
    if re.search(r"\bsp\.?\s*[a-z]", low):
        return "DOKTER_SPESIALIS"
    if re.search(r"\bdrg\.?\b", low):
        return "DOKTER_GIGI"
    if re.search(r"\bdr\.?\b|\bdr\s*,", low):
        return "DOKTER_UMUM"
    return "DOKTER"


def clean_staff_name(name: str) -> str:
    x = name.strip()
    x = re.sub(r"(?i)\bdrg?\.?\s*", " ", x)
    x = re.sub(r"(?i)\bSp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?", " ", x)
    x = re.sub(r"(?i)\b(?:M\.?Kes|MH\.?Kes|M\.?Sc|MM|PhD|FINASIM|FIHA|KIC|SH|MH)\b\.?", " ", x)
    x = re.sub(r"(?i)\b(?:H\.?|Hj\.?|Haji|Hajah)\b\.?", " ", x)
    x = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def tokens_from_name(name: str) -> list[str]:
    toks = []
    for t in clean_staff_name(name).split():
        tc = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ']", "", t).strip()
        if not tc:
            continue
        low = tc.lower().strip(".")
        if low in HONORIFICS or low in TITLE_WORDS or len(tc) <= 1:
            continue
        toks.append(tc)
    return toks


def flexible_name_pattern(variant: str) -> str:
    parts = [re.escape(p) for p in variant.split() if p.strip()]
    sep = r"(?:\s|,|\.)+"
    return r"\b" + sep.join(parts) + r"\b"


def build_variants_from_tokens(toks: list[str]) -> set[str]:
    variants: set[str] = set()
    if len(toks) >= 2:
        variants.add(" ".join(toks))
        variants.add(" ".join(toks[:2]))
        variants.add(toks[0] + " " + toks[-1])
    if len(toks) >= 3:
        variants.add(" ".join([toks[0], toks[1], toks[-1]]))
        variants.add(" ".join(toks[-2:]))
    if len(toks) >= 4:
        variants.add(" ".join(toks[:3]))
        variants.add(" ".join(toks[-3:]))

    safe: set[str] = set()
    for v in variants:
        words = v.split()
        if len(words) < 2 or len(v) < 7:
            continue
        if any(w in CLINICAL_STOPWORDS for w in v.lower().split()):
            continue
        safe.add(v)
    return safe


def load_staff_variants(csv_path: Path | None) -> list[tuple[str, str]]:
    """Baca staff_doctors.csv → list[(variant_nama, role)]."""
    if csv_path is None or not csv_path.exists():
        return []

    variants: list[tuple[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or infer_role(name)
            if not name:
                continue
            toks = tokens_from_name(name)
            for v in build_variants_from_tokens(toks):
                variants.append((v, role))

    # panjang dulu, deduplikasi
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for v, r in sorted(variants, key=lambda x: -len(x[0])):
        key = (v.lower(), r)
        if key not in seen:
            seen.add(key)
            unique.append((v, r))
    return unique


# ── anonymize functions ──────────────────────────────────────────────────────

def anonymize_patient_rs(text: str) -> tuple[str, dict]:
    counts: dict = {}
    patterns = [
        ("NO_RM",       r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_RM]"),
        ("NIK",         r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b",                                            "[NIK]"),
        ("NIK_16",      r"\b\d{16}\b",                                                                                            "[NIK]"),
        ("NO_HP",       r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b",                                                               "[NO_HP]"),
        ("EMAIL",       r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",                                                "[EMAIL]"),
        ("NAMA_PASIEN", r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.' -]{2,80}",                                          "Nama Pasien: [PASIEN]"),
        ("TANGGAL_LAHIR",r"\b(?:Tgl\.?\s*Lahir|Tanggal\s*Lahir|TTL|DOB)\s*[:\-]?\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}",        "[TANGGAL_LAHIR]"),
        ("NO_SEP",      r"\b(?:No\.?\s*SEP|SEP|BPJS)\s*[:\-]?\s*[A-Za-z0-9\-\/]{6,}",                                          "[NO_SEP]"),
        ("ALAMAT",      r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}",                                                                     "Alamat: [ALAMAT]"),
    ]
    for key, pat, repl in patterns:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n

    rs_total = 0
    for pat, repl in [
        (r"\b(?:Rumah\s*Sakit|RSUD|RSUP|RSJ|RS)\s+[A-Z][A-Za-z0-9&.' -]{2,80}", "[RUMAH_SAKIT]"),
        (r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.' ,\-\/]{5,120}",               "[ALAMAT_RS]"),
        (r"\b(?:Telp\.?|Telepon|Phone|Fax)\.?\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}",  "[TELEPON_RS]"),
    ]:
        text, n = re.subn(pat, repl, text, flags=re.I)
        rs_total += n
    counts["RUMAH_SAKIT_ALAMAT"] = rs_total
    return text, counts


def anonymize_staff_csv_fuzzy(text: str, variants: list[tuple[str, str]]) -> tuple[str, dict]:
    counts: dict = {}
    for variant, role in variants:
        pat = flexible_name_pattern(variant)
        text, n = re.subn(pat, f"[{role}]", text, flags=re.I)
        key = f"CSV_{role}"
        counts[key] = counts.get(key, 0) + n
    return text, counts


def anonymize_doctor_regex(text: str) -> tuple[str, dict]:
    counts: dict = {}
    degree = r"(?:drg?\.?|Drg?\.?)"
    sp     = r"(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)"
    honor  = r"(?:H\.?|Hj\.?)"
    suffix = r"(?:\s*,?\s*(?:H\.?|Hj\.?|KIC|FINASIM|FIHA|M\.?Kes|MH\.?Kes|M\.?Sc|MM|SH|MH))*"

    def repl(m: re.Match) -> str:
        old  = m.group(0)
        role = infer_role(old)
        counts[role] = counts.get(role, 0) + 1

        pref = re.match(
            r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?",
            old.strip(),
        )
        if pref:
            return f"{pref.group(1)}: [{role}]"
        if re.search(r"(?i)diverifikasi\s+oleh", old):
            return re.sub(r"(?is)(diverifikasi\s+oleh\s*:?).*", rf"\1 [{role}]", old)
        if re.search(r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:", old):
            return re.sub(r"(?is)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:).*", rf"\1 [{role}]", old)
        return f"[{role}]"

    patterns = [
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-z.' -]{{2,60}}(?:\n\s*[A-Z][A-Za-z.' -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\.?",
        rf"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-z.' -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\.?\)?",
        rf"\b{degree}\s*[A-Z][A-Za-z.' -]{{2,80}}(?:,\s*)?{sp}?{suffix}\.?",
        rf"\b[A-Z][A-Za-z.' -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"(?m)^[A-Z][A-Za-z.' -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-z.' -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"\([A-Z][A-Za-z.' -]{{2,120}},\s*{honor}?\.?\s*{degree}\.?\s*,?\s*{sp}?{suffix}\.?\)",
        rf"\([A-Z][A-Za-z.' -]{{2,120}},\s*\[DOKTER(?:_[A-Z_]+)?\]\)",
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.' -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])(?:\s*:\s*\d{{1,2}}\s+\w+\s+\d{{4}},?)?",
    ]
    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.I | re.S)
    return text, counts


def anonymize_other_ppa(text: str) -> tuple[str, dict]:
    counts: dict = {}
    patterns = [
        ("PERAWAT",     r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.' -]{2,80}"),
        ("PERAWAT",     r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b"),
        ("PERAWAT",     r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b"),
        ("PERAWAT",     r"\[PERAWAT\]\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\.?"),
        ("BIDAN",       r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.' -]{2,80}"),
        ("BIDAN",       r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b"),
        ("APOTEKER",    r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.' -]{2,80}"),
        ("APOTEKER",    r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b"),
        ("APOTEKER",    r"\[APOTEKER\]\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\.?"),
        ("ANALIS_LAB",  r"\b(?:Analis|ATLM|Petugas\s+Lab)\s*[:\-]?\s*[A-Z][A-Za-z.' -]{2,80}"),
        ("ANALIS_LAB",  r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b"),
        ("RADIOGRAFER", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.' -]{2,80}"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        ("RADIOGRAFER", r"\[RADIOGRAFER\]\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\.?"),
        ("FISIOTERAPIS", r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.' -]{2,80}"),
        ("NUTRISIONIS", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.' -]{2,80}"),
    ]
    for role, pat in patterns:
        text, n = re.subn(pat, f"[{role}]", text, flags=re.I)
        counts[role] = counts.get(role, 0) + n
    return text, counts


def anonymize_cppt_provider_header(text: str) -> tuple[str, dict]:
    counts: dict = {}
    date_pat = r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    time_pat = r"\d{1,2}:\d{2}(?::\d{2})?"

    def repl(m: re.Match) -> str:
        header = m.group("header")
        block  = m.group("block")
        soap   = m.group("soap")
        lines  = [ln.strip() for ln in block.splitlines() if ln.strip()]
        joined = " ".join(lines)
        low    = joined.lower()

        if any(w in low for w in CLINICAL_STOPWORDS):
            return m.group(0)
        if len(lines) > 5 or len(joined) > 160:
            return m.group(0)

        role = "PPA"
        if re.search(r"\[APOTEKER\]|\bapt\.?\b|apoteker", joined, flags=re.I):
            role = "APOTEKER"
        elif re.search(r"\[PERAWAT\]|\bners\b|\bns\.?\b|\bamd\.?\s*kep\b|\bs\.?\s*kep\b", joined, flags=re.I):
            role = "PERAWAT"
        elif re.search(r"\[NUTRISIONIS\]|gizi|nutrisionis|dietisien", joined, flags=re.I):
            role = "NUTRISIONIS"
        elif re.search(r"\bdrg?\.?\b|\bdr\b|\bsp\.?|\[DOKTER", joined, flags=re.I):
            role = infer_role(joined)
        elif re.search(r"\[RADIOGRAFER\]|amd\.?\s*rad", joined, flags=re.I):
            role = "RADIOGRAFER"

        counts[f"CPPT_{role}"] = counts.get(f"CPPT_{role}", 0) + 1
        return f"{header}[{role}]\n{soap}"

    pat = (
        rf"(?ms)(?P<header>^\s*{date_pat}\s*\n\s*{time_pat}\s*\n)"
        rf"(?P<block>(?:(?!^\s*[SOAP]\s*$).+\n){{1,5}})"
        rf"(?P<soap>^\s*[SOAP]\s*$)"
    )
    text = re.sub(pat, repl, text)
    return text, counts


def cleanup_context_and_labels(text: str) -> tuple[str, dict]:
    counts: dict = {}
    cleanups = [
        ("colon_name_doctorlabel",
         r"(?m)^(\s*:\s*)[A-Z][A-Za-z.' -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])",
         r"\1\2"),
        ("dokter_label_plus_name_label",
         r"(?is)(Dokter\s*:\s*)\[DOKTER\]\s*\n\s*:\s*[A-Z][A-Za-z.' -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])",
         r"\1\2"),
        ("paren_name_before_doctorlabel",
         r"\(\s*(?:[A-Z][A-Za-z.' -]{2,120},\s*)?(\[DOKTER(?:_[A-Z_]+)?\])\s*\)",
         r"(\1)"),
        ("label_doctor_dr",
         r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*drg?\.?",
         r"\1"),
        ("label_doctor_sp",
         r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?\.?",
         r"\1"),
        ("label_perawat_ners",
         r"(\[PERAWAT\])\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\.?",
         r"\1"),
        ("label_apoteker_apt",
         r"(\[APOTEKER\])\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\.?",
         r"\1"),
        ("label_radio_amd",
         r"(\[RADIOGRAFER\])\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\.?",
         r"\1"),
        ("print_copy_name_label",
         r"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-z.' -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])",
         r"\1\2"),
    ]
    for key, pat, repl in cleanups:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n

    for role in ["DOKTER", "PERAWAT", "APOTEKER", "RADIOGRAFER", "NUTRISIONIS"]:
        pat = rf"(\[{role}(?:_[A-Z_]+)?\])(?:\s*,?\s*\1)+"
        text, n = re.subn(pat, r"\1", text, flags=re.I)
        counts[f"dedup_{role}"] = n

    return text, counts


LEFTOVER_PATTERNS: dict[str, str] = {
    "sisa_nama_sebelum_label": r"\b[A-Z][A-Za-z.' -]{2,80}\s*,?\s*\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|NUTRISIONIS)",
    "sisa_dr":                 r"\bdrg?\.?\s+[A-Z][A-Za-z.' -]{2,80}",
    "sisa_sp":                 r"\bSp\.?\s*[A-Za-z]+",
    "sisa_ners":               r"\b(?:Ns\.?|Ners)\b",
    "sisa_apt":                r"\b(?:Apt\.?|apt\.?)\b",
    "sisa_amd_kep":            r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
    "sisa_amd_rad":            r"\bA\.?Md\.?\s*Rad\.?\b|\bAmd\.?\s*Rad\.?\b",
    "sisa_print_copy":         r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.' -]{2,80}",
}


def detect_leftovers(text: str) -> dict:
    """Kembalikan {kategori: jumlah} — untuk disimpan ke counts."""
    return {k: len(re.findall(p, text, flags=re.I)) for k, p in LEFTOVER_PATTERNS.items()}


def collect_leak_snippets(text: str, file_rel: str) -> list[tuple[str, str, str]]:
    """
    Kembalikan list (file_rel, kategori, contoh_teks) untuk semua sisa yang ditemukan.
    Mengambil konteks ±40 karakter di sekitar match agar mudah dibaca.
    """
    snippets: list[tuple[str, str, str]] = []
    for kategori, pat in LEFTOVER_PATTERNS.items():
        for m in re.finditer(pat, text, flags=re.I):
            start  = max(0, m.start() - 40)
            end    = min(len(text), m.end() + 40)
            # ambil konteks, bersihkan whitespace berlebih
            ctx = text[start:end].replace("\n", " ")
            ctx = re.sub(r"\s{2,}", " ", ctx).strip()
            # tambahkan elipsis bila terpotong
            if start > 0:
                ctx = "…" + ctx
            if end < len(text):
                ctx = ctx + "…"
            snippets.append((file_rel, kategori, ctx))
    return snippets


def anonymize_text(text: str, variants: list[tuple[str, str]]) -> tuple[str, dict]:
    """Pipeline lengkap anonimisasi."""
    text = normalize_text(text)
    text, c1 = anonymize_patient_rs(text)
    text, c2 = anonymize_staff_csv_fuzzy(text, variants)
    text, c3 = anonymize_doctor_regex(text)
    text, c4 = anonymize_other_ppa(text)
    text, c5 = anonymize_cppt_provider_header(text)
    text, c6 = cleanup_context_and_labels(text)
    # pass kedua (membuka sisa pola yang tersembunyi setelah cleanup)
    text, c7 = anonymize_staff_csv_fuzzy(text, variants)
    text, c8 = cleanup_context_and_labels(text)
    c9       = detect_leftovers(text)
    return text, merge_counts(c1, c2, c3, c4, c5, c6, c7, c8, c9)


# ============================================================
# WORKER (background thread)
# ============================================================

@dataclass
class ProcessResult:
    file_rel:       str
    output_path:    str
    processed_at:   str
    counts:         dict = field(default_factory=dict)
    error:          str  = ""
    leak_snippets:  list = field(default_factory=list)  # list[(file_rel, kategori, contoh)]


def run_pipeline(
    input_dirs:  list[Path],
    output_dir:  Path,           # hanya untuk report CSV; file anonim disimpan di sebelah aslinya
    csv_path:    Path | None,
    progress_q:  "queue.Queue[str]",
    result_q:    "queue.Queue[list[ProcessResult]]",
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        progress_q.put("Memuat daftar staf dari CSV...")
        variants = load_staff_variants(csv_path)
        progress_q.put(f"Varian nama staf dari CSV: {len(variants)}")

        # kumpulkan semua .txt dari semua folder input
        txt_files: list[tuple[Path, Path]] = []   # (base_dir, file_path)
        for in_dir in input_dirs:
            for fp in sorted(in_dir.rglob("*.txt")):
                # lewati file yang sudah merupakan hasil anonimisasi
                if fp.stem.endswith("_anonim"):
                    continue
                txt_files.append((in_dir, fp))

        progress_q.put(f"File .txt ditemukan: {len(txt_files)}")

        if not txt_files:
            progress_q.put("PERINGATAN: Tidak ada file .txt di folder input.")
            result_q.put([])
            return

        results: list[ProcessResult] = []
        for idx, (base_dir, fp) in enumerate(txt_files, 1):
            rel = fp.relative_to(base_dir)
            # simpan hasil di sebelah file asli, dengan sufiks _anonim
            out = fp.parent / (fp.stem + "_anonim" + fp.suffix)

            progress_q.put(f"[{idx}/{len(txt_files)}] {rel}")
            try:
                raw          = fp.read_text(encoding="utf-8", errors="ignore")
                anon, counts = anonymize_text(raw, variants)
                out.write_text(anon, encoding="utf-8")

                snippets   = collect_leak_snippets(anon, str(rel))
                total_sisa = sum(v for k, v in counts.items() if k.startswith("sisa_"))
                status     = "✓" if total_sisa == 0 else f"⚠ {total_sisa} sisa"
                progress_q.put(f"  → {status}  → {out.name}")

                results.append(ProcessResult(
                    file_rel      = str(rel),
                    output_path   = str(out),
                    processed_at  = datetime.now().isoformat(timespec="seconds"),
                    counts        = counts,
                    leak_snippets = snippets,
                ))

            except Exception as exc:
                results.append(ProcessResult(
                    file_rel     = str(rel),
                    output_path  = "",
                    processed_at = datetime.now().isoformat(timespec="seconds"),
                    error        = str(exc),
                ))
                progress_q.put(f"  ✗ ERROR: {exc}")

        # tulis report CSV ke folder report terpusat
        _write_report(results, output_dir)
        progress_q.put(f"\n✅ Selesai. {len(results)} file diproses.")
        progress_q.put(f"Report: {output_dir}")
        result_q.put(results)

    except Exception as exc:
        progress_q.put(f"✗ Pipeline error: {exc}")
        result_q.put([])


def _write_report(results: list[ProcessResult], output_dir: Path) -> None:
    if not results:
        return
    all_keys: list[str] = []
    for r in results:
        for k in ["file_rel", "output_path", "processed_at", "error"]:
            if k not in all_keys:
                all_keys.append(k)
        for k in r.counts:
            if k not in all_keys:
                all_keys.append(k)

    report_path = output_dir / f"report_anonimisasi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        for r in results:
            row: dict = {
                "file_rel":     r.file_rel,
                "output_path":  r.output_path,
                "processed_at": r.processed_at,
                "error":        r.error,
            }
            row.update(r.counts)
            writer.writerow(row)


# ============================================================
# GUI
# ============================================================

class AnonymizerApp:
    COL_BG   = "#f8f9fb"
    COL_CARD = "#ffffff"
    COL_BLUE = "#2563eb"
    COL_RED  = "#dc2626"
    COL_GRAY = "#6b7280"
    FONT     = ("Segoe UI", 10)
    FONT_SB  = ("Segoe UI Semibold", 10)
    FONT_BIG = ("Segoe UI Semibold", 16)
    FONT_SM  = ("Segoe UI", 9)

    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Anonimisasi Rekam Medis")
        self.root.geometry("1060x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=self.COL_BG)

        self.input_dirs:  list[Path] = []
        self.csv_path:    Path | None = None
        self.output_var:  StringVar = StringVar()
        self.status_var:  StringVar = StringVar(value="Tambahkan folder input untuk memulai.")
        self.progress_q:  queue.Queue[str] = queue.Queue()
        self.result_q:    queue.Queue[list[ProcessResult]] = queue.Queue()
        self.worker:      threading.Thread | None = None
        self.last_results: list[ProcessResult] = []
        self._all_leak_snippets: list[tuple[str, str, str]] = []

        self._build_ui()
        self.root.after(150, self._poll)

    # ── build UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",  background=self.COL_BG)
        s.configure("TLabel",  background=self.COL_BG, font=self.FONT)
        s.configure("TButton", font=self.FONT, padding=(10, 6))
        s.configure("Accent.TButton", font=self.FONT_SB, padding=(14, 8))
        s.configure("Treeview", font=self.FONT_SM, rowheight=24)
        s.configure("Treeview.Heading", font=self.FONT_SB)

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=BOTH, expand=True)

        # ── judul
        Label(outer, text="Anonimisasi Rekam Medis",
              font=self.FONT_BIG, bg=self.COL_BG, fg="#111827").pack(anchor=W)
        Label(outer, text="Pipeline masking identitas pasien & staf dari file .txt",
              font=self.FONT_SM, bg=self.COL_BG, fg=self.COL_GRAY).pack(anchor=W, pady=(2, 12))

        # ── dua kolom utama
        cols = ttk.Frame(outer)
        cols.pack(fill=BOTH, expand=True)
        left  = ttk.Frame(cols, padding=(0, 0, 12, 0))
        right = ttk.Frame(cols)
        left.pack(side=LEFT, fill=BOTH, expand=False, anchor="n")
        right.pack(side=LEFT, fill=BOTH, expand=True)
        left.config(width=360)

        # ── KIRI: panel pengaturan
        self._card(left, self._build_input_panel)
        self._card(left, self._build_csv_panel)
        self._card(left, self._build_output_panel)
        self._card(left, self._build_action_panel)

        # ── KANAN: log + preview
        self._build_right_panel(right)

    def _card(self, parent: ttk.Frame, build_fn) -> None:
        card = Frame(parent, bg=self.COL_CARD,
                     highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill=X, pady=(0, 8))
        inner = Frame(card, bg=self.COL_CARD, padx=12, pady=10)
        inner.pack(fill=X)
        build_fn(inner)

    def _section_label(self, parent, text: str) -> None:
        Label(parent, text=text, font=self.FONT_SB,
              bg=self.COL_CARD, fg="#374151").pack(anchor=W)

    def _hint(self, parent, text: str) -> None:
        Label(parent, text=text, font=self.FONT_SM,
              bg=self.COL_CARD, fg=self.COL_GRAY, wraplength=300, justify="left").pack(anchor=W)

    # ── kiri panels ────────────────────────────────────────────────────────

    def _build_input_panel(self, p: Frame) -> None:
        self._section_label(p, "📂 Folder Input (.txt)")
        self._hint(p, "Pilih satu atau beberapa folder berisi file .txt hasil ekstraksi PDF.")

        self.folder_list = Listbox(
            p, height=5, bg=self.COL_CARD, fg="#111827",
            selectbackground=self.COL_BLUE, selectforeground="white",
            highlightthickness=1, highlightbackground="#d1d5db",
            font=self.FONT_SM, activestyle="none", borderwidth=0,
        )
        self.folder_list.pack(fill=X, pady=(6, 6))
        # klik kanan untuk hapus
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Hapus terpilih", command=self._remove_selected)
        self.folder_list.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        btn_row = Frame(p, bg=self.COL_CARD)
        btn_row.pack(fill=X)
        self._btn(btn_row, "Tambah Folder",         self._add_folder,         side=LEFT)
        self._btn(btn_row, "Tambah Subfolder",      self._add_subfolders,     side=LEFT, pad=6)
        self._btn(btn_row, "Kosongkan",             self._clear_folders,      side=RIGHT)

    def _build_csv_panel(self, p: Frame) -> None:
        self._section_label(p, "👤 staff_doctors.csv (opsional)")
        self._hint(p, "CSV berkolom 'name' dan 'role'. Dipakai untuk fuzzy matching nama staf.")

        self.csv_var = StringVar(value="(belum dipilih)")
        Label(p, textvariable=self.csv_var, font=self.FONT_SM,
              bg=self.COL_CARD, fg="#374151", wraplength=300).pack(anchor=W, pady=(4, 4))
        btn_row = Frame(p, bg=self.COL_CARD)
        btn_row.pack(fill=X)
        self._btn(btn_row, "Pilih CSV", self._choose_csv, side=LEFT)
        self._btn(btn_row, "Hapus",     self._clear_csv,  side=LEFT, pad=6)

    def _build_output_panel(self, p: Frame) -> None:
        self._section_label(p, "📋 Folder Laporan (Report CSV)")
        self._hint(p, "File _anonim.txt disimpan di sebelah file aslinya. Folder ini hanya untuk report audit.")
        row = Frame(p, bg=self.COL_CARD)
        row.pack(fill=X, pady=(4, 0))
        from tkinter import Entry
        self.out_entry = Entry(row, textvariable=self.output_var,
                               font=self.FONT_SM, fg="#111827",
                               highlightthickness=1, highlightbackground="#d1d5db",
                               relief="flat", bd=4)
        self.out_entry.pack(side=LEFT, fill=X, expand=True)
        self._btn(row, "Pilih", self._choose_output, side=RIGHT, pad=6)

    def _build_action_panel(self, p: Frame) -> None:
        btn_row = Frame(p, bg=self.COL_CARD)
        btn_row.pack(fill=X)
        self.run_btn = ttk.Button(
            btn_row, text="▶  Mulai Anonimisasi",
            style="Accent.TButton", command=self._run,
        )
        self.run_btn.pack(side=LEFT)
        self.check_btn = ttk.Button(
            btn_row, text="🔍 Cek Kebocoran",
            command=self._show_leak_summary, state="disabled",
        )
        self.check_btn.pack(side=LEFT, padx=(8, 0))

        Label(p, textvariable=self.status_var, font=self.FONT_SM,
              bg=self.COL_CARD, fg=self.COL_GRAY, wraplength=300).pack(anchor=W, pady=(6, 0))

    # ── kanan panel ────────────────────────────────────────────────────────

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        nb = ttk.Notebook(parent)
        nb.pack(fill=BOTH, expand=True)

        # Tab 1: Log
        tab_log = ttk.Frame(nb)
        nb.add(tab_log, text="Log Proses")
        vsb_log = ttk.Scrollbar(tab_log, orient="vertical")
        vsb_log.pack(side=RIGHT, fill=Y)
        self.log_tree = ttk.Treeview(tab_log, columns=("msg",), show="headings",
                                     yscrollcommand=vsb_log.set)
        self.log_tree.heading("msg", text="Aktivitas")
        self.log_tree.column("msg", width=680, anchor=W)
        self.log_tree.pack(fill=BOTH, expand=True)
        vsb_log.config(command=self.log_tree.yview)

        # Tab 2: Preview hasil
        tab_prev = ttk.Frame(nb)
        nb.add(tab_prev, text="Preview Hasil")

        ctrl_row = ttk.Frame(tab_prev)
        ctrl_row.pack(fill=X, padx=8, pady=6)
        ttk.Label(ctrl_row, text="File output:").pack(side=LEFT)
        self.prev_var = StringVar()
        self.prev_combo = ttk.Combobox(ctrl_row, textvariable=self.prev_var,
                                       state="readonly", width=55)
        self.prev_combo.pack(side=LEFT, padx=(6, 0))
        self.prev_combo.bind("<<ComboboxSelected>>", self._load_preview)

        vsb_prev = ttk.Scrollbar(tab_prev, orient="vertical")
        vsb_prev.pack(side=RIGHT, fill=Y)
        self.preview_text = Text(
            tab_prev, wrap="word", state="disabled",
            font=("Consolas", 9), relief="flat",
            yscrollcommand=vsb_prev.set,
        )
        self.preview_text.pack(fill=BOTH, expand=True, padx=(8, 0))
        vsb_prev.config(command=self.preview_text.yview)

        # Tab 3: Ringkasan kebocoran
        tab_leak = ttk.Frame(nb)
        nb.add(tab_leak, text="Ringkasan Kebocoran")

        info_row = Frame(tab_leak, bg="#fef9c3")
        info_row.pack(fill=X)
        Label(
            info_row,
            text="  ⚠  Teks di bawah adalah cuplikan dari file hasil — bukan dari data asli. "
                 "Gunakan ini untuk verifikasi manual sebelum file dibagikan.",
            bg="#fef9c3", fg="#854d0e",
            font=self.FONT_SM, anchor=W, pady=4,
        ).pack(fill=X)

        # filter bar
        filter_row = Frame(tab_leak, bg=self.COL_BG)
        filter_row.pack(fill=X, padx=8, pady=(6, 2))
        Label(filter_row, text="Filter kategori:", font=self.FONT_SM,
              bg=self.COL_BG).pack(side=LEFT)
        self.leak_filter_var = StringVar(value="(semua)")
        self.leak_filter_combo = ttk.Combobox(
            filter_row, textvariable=self.leak_filter_var,
            state="readonly", width=30,
        )
        self.leak_filter_combo["values"] = ["(semua)"] + list(LEFTOVER_PATTERNS.keys())
        self.leak_filter_combo.pack(side=LEFT, padx=(6, 0))
        self.leak_filter_combo.bind("<<ComboboxSelected>>", self._apply_leak_filter)

        self.leak_count_var = StringVar(value="")
        Label(filter_row, textvariable=self.leak_count_var,
              font=self.FONT_SM, bg=self.COL_BG, fg=self.COL_GRAY).pack(side=LEFT, padx=(12, 0))

        # tabel
        tree_frame = Frame(tab_leak, bg=self.COL_BG)
        tree_frame.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

        vsb_leak = ttk.Scrollbar(tree_frame, orient="vertical")
        vsb_leak.pack(side=RIGHT, fill=Y)
        hsb_leak = ttk.Scrollbar(tree_frame, orient="horizontal")
        hsb_leak.pack(side=BOTTOM, fill=X)

        self.leak_tree = ttk.Treeview(
            tree_frame,
            columns=("file", "kategori", "contoh"),
            show="headings",
            yscrollcommand=vsb_leak.set,
            xscrollcommand=hsb_leak.set,
        )
        self.leak_tree.heading("file",     text="File")
        self.leak_tree.heading("kategori", text="Kategori Sisa")
        self.leak_tree.heading("contoh",   text="Cuplikan Teks (konteks ±40 karakter)")
        self.leak_tree.column("file",      width=200, stretch=False)
        self.leak_tree.column("kategori",  width=180, stretch=False)
        self.leak_tree.column("contoh",    width=600)
        self.leak_tree.pack(fill=BOTH, expand=True)
        vsb_leak.config(command=self.leak_tree.yview)
        hsb_leak.config(command=self.leak_tree.xview)

        # tag warna per kategori (lebih mudah dibaca)
        for i, cat in enumerate(LEFTOVER_PATTERNS.keys()):
            colors = ["#fef2f2", "#fff7ed", "#fefce8", "#f0fdf4", "#eff6ff",
                      "#fdf4ff", "#f0fdfa", "#fff1f2"]
            self.leak_tree.tag_configure(cat, background=colors[i % len(colors)])

        # simpan semua snippets untuk filtering
        self._all_leak_snippets: list[tuple[str, str, str]] = []

    # ── helper widget ─────────────────────────────────────────────────────

    def _btn(self, parent, text: str, cmd, side=LEFT, pad: int = 0) -> ttk.Button:
        b = ttk.Button(parent, text=text, command=cmd)
        b.pack(side=side, padx=(pad, 0))
        return b

    # ── folder actions ────────────────────────────────────────────────────

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder input .txt")
        if not path:
            return
        p = Path(path)
        if p not in self.input_dirs:
            self.input_dirs.append(p)
            self.folder_list.insert(END, str(p))
        if not self.output_var.get():
            self.output_var.set(str(p.parent / "03_anonymized_text"))
        self._update_status()

    def _add_subfolders(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder INDUK (semua subfoldernya akan ditambahkan)")
        if not path:
            return
        added = 0
        for child in sorted(Path(path).iterdir()):
            if child.is_dir() and child not in self.input_dirs:
                self.input_dirs.append(child)
                self.folder_list.insert(END, str(child))
                added += 1
        if not self.output_var.get():
            self.output_var.set(str(Path(path) / "03_anonymized_text"))
        self._update_status()
        if added == 0:
            messagebox.showinfo("Info", "Tidak ada subfolder baru yang ditemukan.")

    def _remove_selected(self) -> None:
        for idx in reversed(self.folder_list.curselection()):
            self.folder_list.delete(idx)
            del self.input_dirs[idx]
        self._update_status()

    def _clear_folders(self) -> None:
        self.folder_list.delete(0, END)
        self.input_dirs.clear()
        self._update_status()

    def _choose_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Pilih staff_doctors.csv",
            filetypes=[("CSV", "*.csv"), ("Semua", "*.*")]
        )
        if path:
            self.csv_path = Path(path)
            self.csv_var.set(str(self.csv_path))

    def _clear_csv(self) -> None:
        self.csv_path = None
        self.csv_var.set("(belum dipilih)")

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder output")
        if path:
            self.output_var.set(path)

    def _update_status(self) -> None:
        n = len(self.input_dirs)
        self.status_var.set(f"{n} folder input siap." if n else "Tambahkan folder input untuk memulai.")

    # ── run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        valid = [p for p in self.input_dirs if p.is_dir()]
        if not valid:
            messagebox.showerror("Folder input kosong", "Tambahkan minimal satu folder input yang valid.")
            return
        out = self.output_var.get().strip()
        if not out:
            messagebox.showerror("Folder output kosong", "Tentukan folder output terlebih dahulu.")
            return
        if self.worker and self.worker.is_alive():
            return

        self.run_btn.config(state="disabled")
        self.check_btn.config(state="disabled")
        self.log_tree.delete(*self.log_tree.get_children())
        self.leak_tree.delete(*self.leak_tree.get_children())
        self._all_leak_snippets = []
        self.status_var.set("Sedang memproses…")
        self.last_results = []

        self.worker = threading.Thread(
            target=run_pipeline,
            args=(valid, Path(out), self.csv_path, self.progress_q, self.result_q),
            daemon=True,
        )
        self.worker.start()

    # ── polling ────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        # ambil pesan log
        while not self.progress_q.empty():
            msg = self.progress_q.get_nowait()
            self.log_tree.insert("", END, values=(msg,))
            self.log_tree.yview_moveto(1)

        # ambil hasil (bila selesai)
        if not self.result_q.empty():
            results = self.result_q.get_nowait()
            self.last_results = results
            self._on_done(results)

        self.root.after(150, self._poll)

    def _on_done(self, results: list[ProcessResult]) -> None:
        self.run_btn.config(state="normal")
        self.status_var.set(f"Selesai — {len(results)} file diproses.")

        # isi preview combo
        out_files = [r.output_path for r in results if r.output_path]
        self.prev_combo["values"] = out_files
        if out_files:
            self.prev_var.set(out_files[0])
            self._load_preview()

        # kumpulkan semua snippets dari seluruh hasil
        all_snippets: list[tuple[str, str, str]] = []
        for r in results:
            all_snippets.extend(r.leak_snippets)
        self._all_leak_snippets = all_snippets

        # reset filter & isi tabel
        self.leak_filter_var.set("(semua)")
        self._populate_leak_table(all_snippets)

        self.check_btn.config(state="normal")
        total_sisa = len(all_snippets)
        if total_sisa > 0:
            messagebox.showwarning(
                "Perhatian — Sisa kebocoran",
                f"Ditemukan {total_sisa} kemungkinan sisa identitas yang belum termasking.\n"
                "Lihat tab 'Ringkasan Kebocoran' untuk cuplikan teksnya."
            )
        else:
            messagebox.showinfo("Selesai", "Anonimisasi selesai. Tidak ada sisa kebocoran terdeteksi.")

    def _populate_leak_table(self, snippets: list[tuple[str, str, str]]) -> None:
        """Isi tabel kebocoran dengan list (file_rel, kategori, contoh)."""
        self.leak_tree.delete(*self.leak_tree.get_children())
        for file_rel, kategori, contoh in snippets:
            self.leak_tree.insert(
                "", END,
                values=(file_rel, kategori, contoh),
                tags=(kategori,),
            )
        n = len(snippets)
        self.leak_count_var.set(f"{n} temuan" if n else "✓ Tidak ada sisa")

    def _apply_leak_filter(self, *_) -> None:
        """Filter tabel kebocoran berdasarkan kategori."""
        selected = self.leak_filter_var.get()
        if selected == "(semua)":
            filtered = self._all_leak_snippets
        else:
            filtered = [(f, k, c) for f, k, c in self._all_leak_snippets if k == selected]
        self._populate_leak_table(filtered)

    def _load_preview(self, *_) -> None:
        path = self.prev_var.get()
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            content = f"Gagal membaca file: {exc}"
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", END)
        self.preview_text.insert("1.0", content)
        self.preview_text.config(state="disabled")

    def _show_leak_summary(self) -> None:
        total = len(self._all_leak_snippets)
        if total == 0:
            messagebox.showinfo("Kebocoran", "✅ Tidak ada sisa identitas terdeteksi di semua file.")
        else:
            messagebox.showwarning(
                "Ringkasan Kebocoran",
                f"⚠ Total {total} kemungkinan sisa identitas.\n\n"
                "Lihat tab 'Ringkasan Kebocoran' untuk melihat\n"
                "cuplikan teks dan verifikasi manual."
            )

    # ── main ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


# ============================================================
if __name__ == "__main__":
    AnonymizerApp().run()
