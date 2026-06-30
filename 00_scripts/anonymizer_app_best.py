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
- Mode Ekstraksi: ekstrak data klinis, staf, lab, radiologi, onset → JSON

Cara pakai:
    python anonymizer_app.py
"""

from __future__ import annotations

import csv
import json
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


# ============================================================
# EXTRACTION ENGINE
# ============================================================

# ── pola tanggal generik ────────────────────────────────────────────────────
_DATE_RE = re.compile(
    r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan(?:uari)?|Feb(?:ruari)?|Mar(?:et)?|Apr(?:il)?|Mei|"
    r"Jun(?:i)?|Jul(?:i)?|Agu(?:stus)?|Sep(?:tember)?|Okt(?:ober)?|"
    r"Nov(?:ember)?|Des(?:ember)?)\s+\d{2,4})\b",
    re.I,
)

# ── pola data klinis ────────────────────────────────────────────────────────
_KELUHAN_RE = re.compile(
    r"(?:Keluhan\s*(?:Utama)?\s*[:\-]?\s*)([^\n]{3,200})", re.I
)
_ANAMNESIS_RE = re.compile(
    r"(?:Anamnesis|Riwayat\s*Penyakit\s*(?:Sekarang)?)\s*[:\-]?\s*([^\n]{3,300})", re.I
)
_DIAGNOSA_RE = re.compile(
    r"(?:Diagnos[ia]s?\s*(?:Kerja|Masuk|Akhir|Utama|Banding)?\s*[:\-]?\s*)([^\n]{3,200})", re.I
)
_TERAPI_RE = re.compile(
    r"(?:Terapi|Tatalaksana|Planning|Pengobatan|Intervensi)\s*[:\-]?\s*([^\n]{3,200})", re.I
)

# ── pola onset ──────────────────────────────────────────────────────────────
_ONSET_RE = re.compile(
    r"(?:Onset|sejak|mulai\s*(?:dari|tanggal)?|onset\s*(?:gejala)?)\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"
    r"|\d+\s*(?:hari|minggu|bulan|tahun|jam|menit)\s*(?:yang\s*lalu|SMRS|SM)?[^\n]{0,60})",
    re.I,
)
_SMRS_RE = re.compile(
    r"(\d+\s*(?:hari|minggu|bulan|tahun|jam|menit)\s*(?:SMRS|SM|yang\s*lalu|sebelum\s*MRS))",
    re.I,
)

# ── pola staf ────────────────────────────────────────────────────────────────
_DPJP_RE     = re.compile(r"(?:DPJP)\s*[:\-]?\s*([^\n\[\]]{3,80})", re.I)
_DOKTER_RE   = re.compile(r"(?:Dokter\s*(?:IGD|Jaga|Pemeriksa|Pengirim|Operator)?)\s*[:\-]?\s*([^\n\[\]]{3,80})", re.I)
_PERAWAT_RE  = re.compile(r"(?:Perawat|Ns\.?|Ners)\s*[:\-]?\s*([^\n\[\]]{3,80})", re.I)
_BIDAN_RE    = re.compile(r"(?:Bidan|Bd\.?)\s*[:\-]?\s*([^\n\[\]]{3,80})", re.I)
_APOTEKER_RE = re.compile(r"(?:Apoteker|apt\.?)\s*[:\-]?\s*([^\n\[\]]{3,80})", re.I)

# ── pola lab ─────────────────────────────────────────────────────────────────
# cocokkan: "Hemoglobin   10.2   g/dL" atau "Hemoglobin : 10.2"
_LAB_ITEM_RE = re.compile(
    r"^[ \t]*([A-Za-z][A-Za-z0-9 \(\)/\-]{2,50}?)"   # nama pemeriksaan
    r"[ \t]*[:\|]?[ \t]*"
    r"([\d\.,]+(?:\s*[\-–]\s*[\d\.,]+)?)"              # nilai (bisa range)
    r"(?:[ \t]*((?:[a-zA-Z%\/µ][A-Za-z0-9\/µ%\.]*)))?",# satuan (opsional)
    re.MULTILINE,
)
_LAB_DATE_CTX_RE = re.compile(
    r"(?:Tanggal|Tgl\.?|Date)\s*[:\-]?\s*" + _DATE_RE.pattern, re.I
)

# ── pola radiologi ───────────────────────────────────────────────────────────
_RADIO_JENIS_RE = re.compile(
    r"\b(Foto\s+Thorax|Rontgen\s+[A-Za-z ]{3,40}|CT[-\s]Scan\s+[A-Za-z ]{3,40}"
    r"|MRI\s+[A-Za-z ]{3,40}|USG\s+[A-Za-z ]{3,40}"
    r"|Foto\s+[A-Za-z ]{3,40}|EKG|EEG|Echo(?:kardiografi)?)\b",
    re.I,
)
_RADIO_KESAN_RE = re.compile(
    r"(?:Kesan|Kesimpulan|Hasil|Interpretasi|Conclusion)\s*[:\-]?\s*([^\n]{5,400}(?:\n[^\n]{0,200}){0,4})",
    re.I,
)
_RADIO_DATE_RE = re.compile(
    r"(?:Tanggal|Tgl\.?)\s*(?:Pemeriksaan)?\s*[:\-]?\s*" + _DATE_RE.pattern, re.I
)

# nama pemeriksaan lab yang sering fals-positive → difilter
_LAB_STOPNAMES = {
    "keluhan", "diagnosa", "terapi", "planning", "sesuai", "pasien",
    "nama", "tanggal", "alamat", "umur", "jenis", "penjamin", "dokter",
    "hasil", "satuan", "nilai", "rujukan", "keterangan", "catatan",
    "tanda", "vital", "tekanan", "darah", "suhu", "spo", "gcs", "ews",
    "print", "copy", "halaman", "no", "nomor",
}

def _clean(s: str) -> str:
    """Strip whitespace dan karakter sisa dari match group."""
    return re.sub(r"\s+", " ", (s or "").strip(" \t:,-"))


def extract_klinis(text: str) -> dict:
    """Ekstrak data klinis: keluhan, anamnesis, diagnosis, terapi."""
    out: dict = {}

    keluhan = [_clean(m.group(1)) for m in _KELUHAN_RE.finditer(text)]
    if keluhan:
        out["keluhan_utama"] = keluhan[0]

    anamnesis = [_clean(m.group(1)) for m in _ANAMNESIS_RE.finditer(text)]
    if anamnesis:
        out["anamnesis"] = anamnesis[0]

    diagnosa = [_clean(m.group(1)) for m in _DIAGNOSA_RE.finditer(text)]
    if diagnosa:
        out["diagnosis"] = list(dict.fromkeys(d for d in diagnosa if len(d) > 3))

    terapi = [_clean(m.group(1)) for m in _TERAPI_RE.finditer(text)]
    if terapi:
        out["terapi"] = list(dict.fromkeys(t for t in terapi if len(t) > 3))

    return out


def extract_onset(text: str) -> dict:
    """Ekstrak onset awal gejala / waktu sebelum MRS."""
    items = []
    for m in _ONSET_RE.finditer(text):
        v = _clean(m.group(1))
        if v and v not in items:
            items.append(v)
    for m in _SMRS_RE.finditer(text):
        v = _clean(m.group(1))
        if v and v not in items:
            items.append(v)
    return {"onset": items} if items else {}


def extract_staf(text: str) -> dict:
    """Ekstrak nama / label staf dari teks ASLI (sebelum anonimisasi) atau hasil."""
    out: dict = {}

    def _grab(pattern: re.Pattern, key: str) -> None:
        vals = list(dict.fromkeys(
            _clean(m.group(1)) for m in pattern.finditer(text)
            if len(_clean(m.group(1))) > 2
        ))
        if vals:
            out[key] = vals

    _grab(_DPJP_RE,     "dpjp")
    _grab(_DOKTER_RE,   "dokter")
    _grab(_PERAWAT_RE,  "perawat")
    _grab(_BIDAN_RE,    "bidan")
    _grab(_APOTEKER_RE, "apoteker")
    return out


def extract_lab(text: str) -> dict:
    """Ekstrak item laboratorium: nama + nilai (+ satuan bila ada)."""
    # cari tanggal pemeriksaan terdekat di konteks
    tanggal_lab: list[str] = [m.group(1) for m in _LAB_DATE_CTX_RE.finditer(text)]

    items: list[dict] = []
    seen: set[str] = set()
    for m in _LAB_ITEM_RE.finditer(text):
        nama   = _clean(m.group(1))
        nilai  = _clean(m.group(2))
        satuan = _clean(m.group(3)) if m.group(3) else ""

        # filter false-positive
        if not nama or nama.lower() in _LAB_STOPNAMES:
            continue
        if len(nama) < 3 or not re.search(r"[a-zA-Z]{2}", nama):
            continue
        # nilai harus numerik
        if not re.search(r"\d", nilai):
            continue

        key = f"{nama.lower()}:{nilai}"
        if key in seen:
            continue
        seen.add(key)

        entry: dict = {"nama": nama, "nilai": nilai}
        if satuan:
            entry["satuan"] = satuan
        items.append(entry)

    out: dict = {}
    if items:
        out["items"] = items
    if tanggal_lab:
        out["tanggal"] = list(dict.fromkeys(tanggal_lab))
    return out


def extract_radiologi(text: str) -> dict:
    """Ekstrak jenis pemeriksaan radiologi, tanggal, dan kesan/interpretasi."""
    jenis: list[str] = list(dict.fromkeys(
        _clean(m.group(0)) for m in _RADIO_JENIS_RE.finditer(text)
    ))
    tanggal: list[str] = list(dict.fromkeys(
        _clean(m.group(1)) for m in _RADIO_DATE_RE.finditer(text) if m.group(1)
    ))
    kesan_raw = [_clean(m.group(1)) for m in _RADIO_KESAN_RE.finditer(text)]
    kesan = list(dict.fromkeys(k for k in kesan_raw if len(k) > 5))

    out: dict = {}
    if jenis:
        out["jenis_pemeriksaan"] = jenis
    if tanggal:
        out["tanggal"] = tanggal
    if kesan:
        out["kesan"] = kesan
    return out


def extract_all(
    text: str,
    target_klinis: bool = True,
    target_onset:  bool = True,
    target_staf:   bool = True,
    target_lab:    bool = True,
    target_radio:  bool = True,
) -> dict:
    """
    Jalankan semua ekstraktor yang diaktifkan.
    Kembalikan dict terstruktur siap di-serialize ke JSON.
    """
    result: dict = {"diekstrak_pada": datetime.now().isoformat(timespec="seconds")}

    if target_klinis:
        klinis = extract_klinis(text)
        if klinis:
            result["klinis"] = klinis

    if target_onset:
        onset = extract_onset(text)
        if onset:
            result["onset"] = onset["onset"]

    if target_staf:
        staf = extract_staf(text)
        if staf:
            result["staf"] = staf

    if target_lab:
        lab = extract_lab(text)
        if lab:
            result["laboratorium"] = lab

    if target_radio:
        radio = extract_radiologi(text)
        if radio:
            result["radiologi"] = radio

    return result


# ── worker extraction ────────────────────────────────────────────────────────

@dataclass
class ExtractResult:
    file_rel:     str
    output_path:  str
    extracted_at: str
    data:         dict = field(default_factory=dict)
    error:        str  = ""


def run_extraction(
    input_dirs:    list[Path],
    output_dir:    Path,
    progress_q:    "queue.Queue[str]",
    result_q:      "queue.Queue[list[ExtractResult]]",
    target_klinis: bool = True,
    target_onset:  bool = True,
    target_staf:   bool = True,
    target_lab:    bool = True,
    target_radio:  bool = True,
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        txt_files: list[tuple[Path, Path]] = []
        for in_dir in input_dirs:
            for fp in sorted(in_dir.rglob("*.txt")):
                if fp.stem.endswith("_anonim") or fp.stem.endswith("_ekstrak"):
                    continue
                txt_files.append((in_dir, fp))

        progress_q.put(f"[Ekstraksi] File .txt ditemukan: {len(txt_files)}")
        if not txt_files:
            progress_q.put("[Ekstraksi] PERINGATAN: Tidak ada file .txt.")
            result_q.put([])
            return

        results: list[ExtractResult] = []
        for idx, (base_dir, fp) in enumerate(txt_files, 1):
            rel = fp.relative_to(base_dir)
            out = output_dir / (fp.stem + "_ekstrak.json")
            progress_q.put(f"[Ekstraksi] [{idx}/{len(txt_files)}] {rel}")
            try:
                raw  = fp.read_text(encoding="utf-8", errors="ignore")
                data = extract_all(
                    raw,
                    target_klinis=target_klinis,
                    target_onset=target_onset,
                    target_staf=target_staf,
                    target_lab=target_lab,
                    target_radio=target_radio,
                )
                data["sumber_file"] = str(rel)
                out.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                n_entitas = sum(
                    len(v) if isinstance(v, list) else 1
                    for v in data.values()
                    if not isinstance(v, str)
                )
                progress_q.put(f"  → ✓ {n_entitas} entitas  → {out.name}")
                results.append(ExtractResult(
                    file_rel    = str(rel),
                    output_path = str(out),
                    extracted_at= datetime.now().isoformat(timespec="seconds"),
                    data        = data,
                ))
            except Exception as exc:
                progress_q.put(f"  ✗ ERROR: {exc}")
                results.append(ExtractResult(
                    file_rel    = str(rel),
                    output_path = "",
                    extracted_at= datetime.now().isoformat(timespec="seconds"),
                    error       = str(exc),
                ))

        # tulis indeks ringkasan
        summary = [
            {"file": r.file_rel, "output": r.output_path, "error": r.error}
            for r in results
        ]
        idx_path = output_dir / f"indeks_ekstraksi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        idx_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        progress_q.put(f"\n✅ [Ekstraksi] Selesai. {len(results)} file. Indeks: {idx_path.name}")
        result_q.put(results)
    except Exception as exc:
        progress_q.put(f"✗ [Ekstraksi] Pipeline error: {exc}")
        result_q.put([])


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
        self.root.title("Anonimisasi & Ekstraksi Rekam Medis")
        self.root.geometry("1200x780")
        self.root.minsize(980, 640)
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

        # ── Ekstraksi ──────────────────────────────────────────────────────
        self.extract_output_var: StringVar = StringVar()
        self.extract_status_var: StringVar = StringVar(value="")
        self.extract_progress_q: queue.Queue[str] = queue.Queue()
        self.extract_result_q:   queue.Queue[list[ExtractResult]] = queue.Queue()
        self.extract_worker:     threading.Thread | None = None
        self.last_extract_results: list[ExtractResult] = []

        # checkboxes target ekstraksi
        self.ex_klinis: BooleanVar = BooleanVar(value=True)
        self.ex_onset:  BooleanVar = BooleanVar(value=True)
        self.ex_staf:   BooleanVar = BooleanVar(value=True)
        self.ex_lab:    BooleanVar = BooleanVar(value=True)
        self.ex_radio:  BooleanVar = BooleanVar(value=True)

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
        Label(outer, text="Anonimisasi & Ekstraksi Rekam Medis",
              font=self.FONT_BIG, bg=self.COL_BG, fg="#111827").pack(anchor=W)
        Label(outer, text="Pipeline masking identitas pasien & staf + ekstraksi data klinis/lab/radiologi ke JSON",
              font=self.FONT_SM, bg=self.COL_BG, fg=self.COL_GRAY).pack(anchor=W, pady=(2, 12))

        # ── dua kolom utama
        cols = ttk.Frame(outer)
        cols.pack(fill=BOTH, expand=True)
        left  = ttk.Frame(cols, padding=(0, 0, 12, 0))
        right = ttk.Frame(cols)
        left.pack(side=LEFT, fill=BOTH, expand=False, anchor="n")
        right.pack(side=LEFT, fill=BOTH, expand=True)
        left.config(width=390)

        # ── KIRI: notebook (Anonimisasi | Ekstraksi)
        self.left_nb = ttk.Notebook(left)
        self.left_nb.pack(fill=BOTH, expand=True)

        tab_anon = ttk.Frame(self.left_nb)
        self.left_nb.add(tab_anon, text="🔒 Anonimisasi")
        self._card(tab_anon, self._build_input_panel)
        self._card(tab_anon, self._build_csv_panel)
        self._card(tab_anon, self._build_output_panel)
        self._card(tab_anon, self._build_action_panel)

        tab_extract = ttk.Frame(self.left_nb)
        self.left_nb.add(tab_extract, text="🔬 Ekstraksi")
        self._build_extract_left(tab_extract)

        # ── KANAN: log + preview + hasil ekstraksi
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

    # ── panel kiri ekstraksi ─────────────────────────────────────────────────

    def _build_extract_left(self, parent: ttk.Frame) -> None:
        """Panel kiri tab Ekstraksi: pilih target, output folder, tombol jalankan."""
        self._card(parent, self._build_extract_target_panel)
        self._card(parent, self._build_extract_output_panel)
        self._card(parent, self._build_extract_action_panel)

    def _build_extract_target_panel(self, p: Frame) -> None:
        self._section_label(p, "🎯 Target Ekstraksi")
        self._hint(p, "Pilih data apa saja yang ingin diekstrak dari file rekam medis.")
        targets = [
            (self.ex_klinis, "🩺 Data Klinis (keluhan, diagnosis, terapi)"),
            (self.ex_onset,  "⏱ Onset Awal Gejala / Waktu SMRS"),
            (self.ex_staf,   "👨‍⚕️ Staf Medis (dokter, perawat, apoteker)"),
            (self.ex_lab,    "🧪 Laboratorium (nama tes, nilai, tanggal)"),
            (self.ex_radio,  "📷 Radiologi (jenis, kesan, tanggal)"),
        ]
        for var, label in targets:
            from tkinter import Checkbutton
            cb = Checkbutton(
                p, text=label, variable=var,
                font=self.FONT_SM, bg=self.COL_CARD, fg="#111827",
                activebackground=self.COL_CARD, cursor="hand2",
            )
            cb.pack(anchor=W, pady=1)

    def _build_extract_output_panel(self, p: Frame) -> None:
        self._section_label(p, "📁 Folder Output JSON")
        self._hint(p, "Setiap file .txt menghasilkan satu file _ekstrak.json.")
        row = Frame(p, bg=self.COL_CARD)
        row.pack(fill=X, pady=(4, 0))
        from tkinter import Entry
        self.ex_out_entry = Entry(
            row, textvariable=self.extract_output_var,
            font=self.FONT_SM, fg="#111827",
            highlightthickness=1, highlightbackground="#d1d5db",
            relief="flat", bd=4,
        )
        self.ex_out_entry.pack(side=LEFT, fill=X, expand=True)
        self._btn(row, "Pilih", self._choose_extract_output, side=RIGHT, pad=6)

    def _build_extract_action_panel(self, p: Frame) -> None:
        btn_row = Frame(p, bg=self.COL_CARD)
        btn_row.pack(fill=X)
        self.extract_btn = ttk.Button(
            btn_row, text="🔬 Mulai Ekstraksi",
            style="Accent.TButton", command=self._run_extraction,
        )
        self.extract_btn.pack(side=LEFT)
        self.extract_anon_btn = ttk.Button(
            btn_row, text="▶+🔬 Anonimisasi + Ekstraksi",
            command=self._run_both,
        )
        self.extract_anon_btn.pack(side=LEFT, padx=(8, 0))
        Label(p, textvariable=self.extract_status_var, font=self.FONT_SM,
              bg=self.COL_CARD, fg=self.COL_GRAY, wraplength=360).pack(anchor=W, pady=(6, 0))

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

        # Tab 4: Hasil Ekstraksi
        tab_ex = ttk.Frame(nb)
        nb.add(tab_ex, text="🔬 Hasil Ekstraksi")

        ex_ctrl = ttk.Frame(tab_ex)
        ex_ctrl.pack(fill=X, padx=8, pady=6)
        ttk.Label(ex_ctrl, text="File JSON:").pack(side=LEFT)
        self.ex_prev_var = StringVar()
        self.ex_prev_combo = ttk.Combobox(
            ex_ctrl, textvariable=self.ex_prev_var, state="readonly", width=52
        )
        self.ex_prev_combo.pack(side=LEFT, padx=(6, 0))
        self.ex_prev_combo.bind("<<ComboboxSelected>>", self._load_extract_preview)

        # ringkasan pills / badge per file
        self.ex_summary_var = StringVar(value="")
        Label(ex_ctrl, textvariable=self.ex_summary_var, font=self.FONT_SM,
              bg=self.COL_BG, fg=self.COL_GRAY).pack(side=LEFT, padx=(12, 0))

        # area JSON
        ex_text_frame = Frame(tab_ex, bg=self.COL_BG)
        ex_text_frame.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        vsb_ex = ttk.Scrollbar(ex_text_frame, orient="vertical")
        vsb_ex.pack(side=RIGHT, fill=Y)
        hsb_ex = ttk.Scrollbar(ex_text_frame, orient="horizontal")
        hsb_ex.pack(side=BOTTOM, fill=X)
        self.ex_text = Text(
            ex_text_frame, wrap="none", state="disabled",
            font=("Consolas", 9), relief="flat",
            yscrollcommand=vsb_ex.set, xscrollcommand=hsb_ex.set,
        )
        self.ex_text.pack(fill=BOTH, expand=True)
        vsb_ex.config(command=self.ex_text.yview)
        hsb_ex.config(command=self.ex_text.xview)
        # tag warna untuk JSON highlighting
        self.ex_text.tag_configure("key",    foreground="#1d4ed8")
        self.ex_text.tag_configure("string", foreground="#15803d")
        self.ex_text.tag_configure("number", foreground="#b45309")
        self.ex_text.tag_configure("bool",   foreground="#7c3aed")

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

    # ── polling ekstraksi ─────────────────────────────────────────────────

    def _poll(self) -> None:
        # log anonimisasi
        while not self.progress_q.empty():
            msg = self.progress_q.get_nowait()
            self.log_tree.insert("", END, values=(msg,))
            self.log_tree.yview_moveto(1)
        if not self.result_q.empty():
            results = self.result_q.get_nowait()
            self.last_results = results
            self._on_done(results)
            # bila mode bersamaan, aktifkan juga tombol ekstraksi selesai
            if hasattr(self, "_both_mode") and self._both_mode:
                pass  # handled by _on_extract_done

        # log ekstraksi
        while not self.extract_progress_q.empty():
            msg = self.extract_progress_q.get_nowait()
            self.log_tree.insert("", END, values=(msg,))
            self.log_tree.yview_moveto(1)
        if not self.extract_result_q.empty():
            ex_results = self.extract_result_q.get_nowait()
            self.last_extract_results = ex_results
            self._on_extract_done(ex_results)

        self.root.after(150, self._poll)

    # ── ekstraksi actions ─────────────────────────────────────────────────

    def _choose_extract_output(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder output JSON")
        if path:
            self.extract_output_var.set(path)

    def _validate_extract_ready(self) -> bool:
        valid = [p for p in self.input_dirs if p.is_dir()]
        if not valid:
            messagebox.showerror("Input kosong",
                "Tambahkan folder input di tab Anonimisasi terlebih dahulu.")
            return False
        out = self.extract_output_var.get().strip()
        if not out:
            # default: saudara dari folder input pertama
            default = str(valid[0].parent / "04_ekstraksi_json")
            self.extract_output_var.set(default)
        if not any([self.ex_klinis.get(), self.ex_onset.get(), self.ex_staf.get(),
                    self.ex_lab.get(), self.ex_radio.get()]):
            messagebox.showwarning("Target kosong", "Pilih minimal satu target ekstraksi.")
            return False
        return True

    def _run_extraction(self) -> None:
        if not self._validate_extract_ready():
            return
        if self.extract_worker and self.extract_worker.is_alive():
            return
        valid = [p for p in self.input_dirs if p.is_dir()]
        out   = Path(self.extract_output_var.get().strip())
        self.extract_btn.config(state="disabled")
        self.extract_anon_btn.config(state="disabled")
        self.extract_status_var.set("Sedang mengekstrak...")
        self.extract_worker = threading.Thread(
            target=run_extraction,
            args=(valid, out, self.extract_progress_q, self.extract_result_q),
            kwargs=dict(
                target_klinis=self.ex_klinis.get(),
                target_onset=self.ex_onset.get(),
                target_staf=self.ex_staf.get(),
                target_lab=self.ex_lab.get(),
                target_radio=self.ex_radio.get(),
            ),
            daemon=True,
        )
        self.extract_worker.start()

    def _run_both(self) -> None:
        """Jalankan anonimisasi dan ekstraksi secara bersamaan (thread terpisah)."""
        self._both_mode = True
        # jalankan anonimisasi
        valid = [p for p in self.input_dirs if p.is_dir()]
        if not valid:
            messagebox.showerror("Input kosong", "Tambahkan folder input terlebih dahulu.")
            self._both_mode = False
            return
        out_anon = self.output_var.get().strip()
        if not out_anon:
            messagebox.showerror("Output kosong", "Tentukan folder output anonimisasi terlebih dahulu.")
            self._both_mode = False
            return
        if not self._validate_extract_ready():
            self._both_mode = False
            return

        # set default extract output jika belum diset
        if not self.extract_output_var.get().strip():
            self.extract_output_var.set(str(valid[0].parent / "04_ekstraksi_json"))

        out_ex = Path(self.extract_output_var.get().strip())

        # disable semua tombol
        self.run_btn.config(state="disabled")
        self.check_btn.config(state="disabled")
        self.extract_btn.config(state="disabled")
        self.extract_anon_btn.config(state="disabled")
        self.log_tree.delete(*self.log_tree.get_children())
        self.status_var.set("Anonimisasi + Ekstraksi berjalan...")
        self.extract_status_var.set("Berjalan bersamaan...")

        self.worker = threading.Thread(
            target=run_pipeline,
            args=(valid, Path(out_anon), self.csv_path, self.progress_q, self.result_q),
            daemon=True,
        )
        self.extract_worker = threading.Thread(
            target=run_extraction,
            args=(valid, out_ex, self.extract_progress_q, self.extract_result_q),
            kwargs=dict(
                target_klinis=self.ex_klinis.get(),
                target_onset=self.ex_onset.get(),
                target_staf=self.ex_staf.get(),
                target_lab=self.ex_lab.get(),
                target_radio=self.ex_radio.get(),
            ),
            daemon=True,
        )
        self.worker.start()
        self.extract_worker.start()

    def _on_extract_done(self, results: list[ExtractResult]) -> None:
        self.extract_btn.config(state="normal")
        self.extract_anon_btn.config(state="normal")
        if hasattr(self, "_both_mode"):
            self._both_mode = False
        n_ok  = sum(1 for r in results if not r.error)
        n_err = sum(1 for r in results if r.error)
        self.extract_status_var.set(f"Selesai — {n_ok} file ✓  {n_err} error.")

        # isi combo preview ekstraksi
        json_files = [r.output_path for r in results if r.output_path]
        self.ex_prev_combo["values"] = json_files
        if json_files:
            self.ex_prev_var.set(json_files[0])
            self._load_extract_preview()

        if n_err:
            messagebox.showwarning("Ekstraksi",
                f"Ekstraksi selesai dengan {n_err} error. Lihat Log Proses.")
        else:
            messagebox.showinfo("Ekstraksi Selesai",
                f"✅ {n_ok} file berhasil diekstrak ke JSON.")

    def _load_extract_preview(self, *_) -> None:
        path = self.ex_prev_var.get()
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
            content = json.dumps(data, ensure_ascii=False, indent=2)
            # ringkasan badge
            keys = [k for k in data if k not in ("diekstrak_pada", "sumber_file")]
            self.ex_summary_var.set("  |  ".join(
                f"{k.upper()}: {len(data[k]) if isinstance(data[k], list) else '✓'}"
                for k in keys
            ))
        except Exception as exc:
            content = f"Gagal membaca JSON: {exc}"
            self.ex_summary_var.set("")

        self.ex_text.config(state="normal")
        self.ex_text.delete("1.0", END)
        self._insert_json_highlighted(content)
        self.ex_text.config(state="disabled")

    def _insert_json_highlighted(self, text: str) -> None:
        """Insert JSON teks dengan highlighting warna sederhana."""
        key_re    = re.compile(r'"([^"]+)"\s*:')
        str_re    = re.compile(r':\s*("[^"]*")')
        num_re    = re.compile(r':\s*(-?\d[\d\.]*)')
        bool_re   = re.compile(r':\s*(true|false|null)\b')
        for line in text.splitlines(keepends=True):
            pos = 0
            segments = []
            for m in re.finditer(
                r'("[^"]+"\s*:)|(:\s*"[^"]*")|(:\s*-?\d[\d\.]*)|(:\s*(?:true|false|null)\b)',
                line
            ):
                if m.start() > pos:
                    segments.append((line[pos:m.start()], ""))
                raw = m.group(0)
                if m.group(1):
                    segments.append((raw, "key"))
                elif m.group(2):
                    segments.append((raw, "string"))
                elif m.group(3):
                    segments.append((raw, "number"))
                else:
                    segments.append((raw, "bool"))
                pos = m.end()
            if pos < len(line):
                segments.append((line[pos:], ""))
            for txt, tag in segments:
                if tag:
                    self.ex_text.insert(END, txt, tag)
                else:
                    self.ex_text.insert(END, txt)

    # ── main ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


# ============================================================
if __name__ == "__main__":
    AnonymizerApp().run()
