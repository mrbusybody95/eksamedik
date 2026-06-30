from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH, END, LEFT, RIGHT, TOP, BOTTOM, X, Y,
    Button, Frame, Label, Listbox, StringVar, Text, Scrollbar,
    Tk, filedialog, messagebox, ttk, BooleanVar, Checkbutton
)

import pandas as pd
from pypdf import PdfReader

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
    from PIL import Image
    import io
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

MASKS = {
    "nama_pasien":    "[NAMA_PASIEN]",
    "mrn":            "[MRN]",
    "nik":            "[NIK]",
    "phone":          "[PHONE]",
    "alamat":         "[ALAMAT]",
    "tanggal_lahir":  "[TANGGAL_LAHIR]",
    "staff":          "[STAFF]",
    "rumah_sakit":    "[RUMAH_SAKIT]",
    "no_sep":         "[NO_SEP]",
    "email":          "[EMAIL]",
    "header_footer_rs": "[HEADER_FOOTER_RS]",
}

# Range validasi klinis
VALID_SYSTOLIC  = (60, 260)
VALID_DIASTOLIC = (30, 180)
VALID_GDS       = (20, 800)   # mg/dL


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatientResult:
    patient_folder: str
    source_files: str
    detected_documents: str = ""
    diagnosis_stroke: str = ""
    diagnosis_source: str = ""
    onset: str = ""
    onset_source: str = ""
    gcs: str = ""
    gcs_source: str = ""
    tekanan_darah_awal: str = ""
    tekanan_darah_source: str = ""
    gula_darah_sewaktu: str = ""
    gula_darah_source: str = ""
    hasil_ct_scan: str = ""
    ct_scan_source: str = ""
    hasil_laboratorium: str = ""
    laboratorium_source: str = ""
    terapi_antiplatelet: str = ""
    antiplatelet_source: str = ""
    statin: str = ""
    statin_source: str = ""
    antihipertensi: str = ""
    antihipertensi_source: str = ""
    komorbid: str = ""
    komorbid_source: str = ""
    lama_rawat: str = ""
    lama_rawat_source: str = ""
    kondisi_pulang: str = ""
    kondisi_pulang_source: str = ""
    mrs: str = ""
    mrs_source: str = ""
    masked_text_path: str = ""


@dataclass
class ResumeResult:
    patient_folder: str
    diagnosis_stroke: str
    lama_rawat: str
    kondisi_pulang: str
    mrs: str
    terapi_antiplatelet: str
    statin: str
    antihipertensi: str
    resume_text_path: str


@dataclass
class DocumentRecord:
    patient_folder: str
    document_type: str
    file_name: str
    relative_path: str
    character_count: int
    extraction_status: str
    ocr_used: bool = False


@dataclass
class DocumentText:
    path: Path
    patient_folder: str
    document_type: str
    raw_text: str
    masked_text: str
    ocr_used: bool = False


@dataclass
class LeakFinding:
    patient_folder: str
    category: str
    evidence: str


@dataclass
class AuditFinding:
    patient_folder: str
    item: str
    status: str
    note: str


@dataclass
class ExtractionLog:
    patient_folder: str
    status: str
    message: str
    pdf_count: int
    character_count: int


# ---------------------------------------------------------------------------
# Teks utilities
# ---------------------------------------------------------------------------

def compact_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def is_text_empty(text: str) -> bool:
    """Cek apakah teks hasil ekstraksi hampir kosong (kemungkinan scan)."""
    stripped = re.sub(r"\s+", "", text)
    return len(stripped) < 50


# ---------------------------------------------------------------------------
# Baca PDF — dengan fallback OCR
# ---------------------------------------------------------------------------

def _ocr_pdf_page_fitz(page) -> str:
    """OCR satu halaman PDF via PyMuPDF → PIL → pytesseract."""
    if not PYTESSERACT_AVAILABLE or fitz is None:
        return ""
    mat = fitz.Matrix(2.5, 2.5)          # 2.5× = ~180 dpi, cukup untuk teks RM
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_bytes))
    # Coba bahasa Indonesia + Inggris; fallback ke eng saja bila ind tidak ada
    langs = _get_tesseract_langs()
    try:
        return pytesseract.image_to_string(img, lang=langs, config="--psm 6")
    except Exception:
        try:
            return pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        except Exception:
            return ""


def _get_tesseract_langs() -> str:
    """Cek bahasa yang tersedia di Tesseract; prioritaskan ind+eng."""
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True, text=True
        )
        available = result.stdout + result.stderr
        if "ind" in available:
            return "ind+eng"
    except Exception:
        pass
    return "eng"


def read_pdf_text(pdf_path: Path, use_ocr: bool = True) -> tuple[str, bool]:
    """
    Baca PDF; kembalikan (teks, ocr_dipakai).
    Urutan: pypdf → fitz text → OCR (bila teks kosong & use_ocr=True).
    """
    # 1. coba pypdf
    text = _read_pypdf(pdf_path)
    if not is_text_empty(text):
        return text, False

    # 2. coba fitz text
    if fitz is not None:
        text_fitz = _read_fitz_text(pdf_path)
        if not is_text_empty(text_fitz):
            return text_fitz, False

    # 3. OCR bila diperlukan
    if use_ocr and fitz is not None and PYTESSERACT_AVAILABLE:
        text_ocr = _read_fitz_ocr(pdf_path)
        if not is_text_empty(text_ocr):
            return text_ocr, True

    # kembalikan teks terbaik yang ada (mungkin masih kosong)
    return text, False


def _read_pypdf(pdf_path: Path) -> str:
    try:
        reader = PdfReader(str(pdf_path))
        parts = []
        for i, page in enumerate(reader.pages, 1):
            t = page.extract_text() or ""
            parts.append(f"\n\n--- HALAMAN {i}: {pdf_path.name} ---\n{t}")
        return "\n".join(parts)
    except Exception:
        return ""


def _read_fitz_text(pdf_path: Path) -> str:
    parts = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            for i, page in enumerate(doc, 1):
                t = page.get_text("text") or ""
                parts.append(f"\n\n--- HALAMAN {i}: {pdf_path.name} ---\n{t}")
    except Exception:
        pass
    return "\n".join(parts)


def _read_fitz_ocr(pdf_path: Path) -> str:
    """OCR semua halaman PDF via PyMuPDF + pytesseract."""
    parts = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            for i, page in enumerate(doc, 1):
                t = _ocr_pdf_page_fitz(page)
                parts.append(f"\n\n--- HALAMAN {i}: {pdf_path.name} [OCR] ---\n{t}")
    except Exception:
        pass
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Klasifikasi dokumen
# ---------------------------------------------------------------------------

def classify_document(pdf_path: Path, text: str) -> str:
    sample = f"{pdf_path.name}\n{text[:2000]}".lower()
    scores: dict[str, list[str]] = {
        "CPPT IGD": [
            r"\bcppt\b.*\bigd\b", r"\bigd\b", r"instalasi gawat darurat",
            r"triase", r"asesmen awal.*igd",
        ],
        "LAB": [
            r"laboratorium", r"\blab\b", r"hematologi", r"kimia klinik",
            r"\bhb\b", r"leukosit", r"trombosit", r"kreatinin", r"ureum",
        ],
        "RAD": [
            r"radiologi", r"\brad\b", r"ct scan", r"msct",
            r"rontgen", r"imaging", r"kesan radiologi",
        ],
        "RESUME": [
            r"resume medis", r"ringkasan pulang", r"discharge summary",
            r"resume pasien pulang", r"kondisi pulang",
        ],
        "CPPT RANAP": [
            r"\bcppt\b", r"rawat inap", r"\branap\b",
            r"catatan perkembangan", r"soap",
        ],
    }
    best_type, best_score = "LAINNYA", 0
    for doc_type, patterns in scores.items():
        score = sum(1 for p in patterns if re.search(p, sample, re.I | re.S))
        if score > best_score:
            best_type, best_score = doc_type, score
    return best_type


# ---------------------------------------------------------------------------
# Anonimisasi — PERBAIKAN UTAMA
# ---------------------------------------------------------------------------

def mask_identity(text: str) -> tuple[str, dict[str, int]]:
    masked = text
    counts: dict[str, int] = {}

    def sub(key: str, pattern: str, flags: int = re.I | re.M) -> None:
        nonlocal masked
        masked, n = re.subn(pattern, MASKS[key], masked, flags=flags)
        counts[key] = counts.get(key, 0) + n

    # --- email (dahulukan sebelum regex lain supaya tidak bentrok) ---
    sub("email", r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)

    # --- NIK: 16 digit, bisa dipisah spasi/strip setiap 4 digit ---
    sub("nik", (
        r"(?:NIK|No\.?\s*KTP|KTP)\s*[:\-]?\s*"
        r"(?:\d[\d\s\-]{13,22}\d)"
        r"|"
        r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"
    ))

    # --- Nomor SEP/BPJS ---
    sub("no_sep",
        r"(?:SEP|No\.?\s*SEP|BPJS|No\.?\s*BPJS)\s*[:\-]?\s*[A-Z0-9\-\/]{6,}")

    # --- MRN (rekam medis) ---
    sub("mrn", (
        r"(?:No\.?\s*RM|Nomor\s*RM|RM|Rekam\s*Medis|Medical\s*Record)"
        r"\s*[:\-]?\s*[A-Z0-9\-\/\.]{3,}"
    ))

    # --- Telepon: format Indonesia beragam ---
    sub("phone", (
        r"(?:\+?62|0)[\s\-]?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,5}"
        r"|"
        r"\(\d{2,4}\)\s*\d{3,4}[\s\-]?\d{4,5}"
    ))

    # --- Tanggal lahir (label eksplisit) ---
    sub("tanggal_lahir", (
        r"(?:Tanggal\s*Lahir|Tgl\.?\s*Lahir|TTL|DOB|Lahir)\s*[:\-]?\s*"
        r"(?:\d{1,2}[\-\/]\d{1,2}[\-\/]\d{2,4}"
        r"|\d{1,2}\s+[A-Za-z]+\s+\d{4})"
    ))

    # --- Nama pasien: baris "Nama: ..." DAN pola di tengah kalimat ---
    # 1) baris label
    sub("nama_pasien",
        r"^[ \t]*(?:Nama\s*(?:Pasien|Lengkap)?|Pasien)\s*[:\-]\s*.+$",
        re.I | re.M)
    # 2) "An. Xx Xx" / "Tn. Xx" / "Ny. Xx" – nama dengan gelar
    sub("nama_pasien",
        r"\b(?:Tn|Ny|An|Nn|Sdr|Sdri)\.?\s+[A-Z][A-Za-z]{1,30}"
        r"(?:\s+[A-Z][A-Za-z]{1,30}){0,3}")

    # --- Staff (dr., dokter, perawat, ners, bidan + nama) ---
    sub("staff",
        r"(?:dr\.?|dokter|perawat|ners|bidan)\s+[A-Z][A-Za-z\.\s,]{2,50}",
        re.I)
    # nama tanpa prefix dr. tapi di konteks staf (SIP, DPJP, dll)
    staff_line_patterns = [
        r"^.*(?:Print\s+copy.*?by|Printed\s+by|Dicetak\s+oleh"
        r"|Dibuat\s+oleh|Diverifikasi\s+oleh|Validasi\s+oleh)\s*:\s*.+$",
        r"^\s*\([A-Z][A-Za-z .,'`\-]{2,80},\s*\[STAFF\]\)\s*$",
        r"^\s*(?:DPJP|Dokter\s*Pemeriksa|Dokter|Petugas|Perawat"
        r"|Radiografer|Verifikator)\s*[:\-]\s*.+$",
        r"^\s*SIP\s*[:\-]\s*[A-Z0-9\/\-. ]{5,}\s*$",
        r"^\s*SpS|SpSaraf|SpPD|SpR|SpB|SpBTKV|SpJP\s*$",   # gelar spesialis tanpa nama
    ]
    for p in staff_line_patterns:
        masked, n = re.subn(p, MASKS["staff"], masked, flags=re.I | re.M)
        counts["staff"] = counts.get("staff", 0) + n

    # --- Nama RS / faskes ---
    sub("rumah_sakit",
        r"(?:RS|RSUD|RSUP|RSJ|Rumah\s*Sakit|Klinik|Puskesmas"
        r"|RS\s*Islam|RS\s*Umum)\s+[A-Z0-9][A-Za-z0-9\.\s\-]{2,80}")

    # --- Alamat: baris label DAN "Jl./Jalan ... RT/RW ..." ---
    sub("alamat",
        r"^[ \t]*(?:Alamat|Domisili|Tempat\s*Tinggal)\s*[:\-]\s*.+$",
        re.I | re.M)
    sub("alamat",
        r"(?:Jl\.|Jalan)\s+[A-Z0-9][^\n]{5,100}"
        r"(?:RT\s*\d+[\s\/]+RW\s*\d+[^\n]{0,60})?",
        re.I)

    # --- Header/footer RS ---
    footer_patterns = [
        r"^\s*Terima\s+kasih\s+atas\s+kepercayaan.*$",
        r"^\s*(?:BANDUNG|JAWA\s+BARAT|DKI\s+JAKARTA|JAKARTA"
        r"|KOTA\s+[A-Z ]+|KAB\.?\s+[A-Z ]+)\s*(?:[-,]\s*[A-Z ]+)?\.?\s*$",
        r"^\s*Dicetak\s*:\s*\d{1,2}\s+\w+\s+\d{4}.*$",
    ]
    for p in footer_patterns:
        masked, n = re.subn(p, MASKS["header_footer_rs"], masked, flags=re.I | re.M)
        counts["header_footer_rs"] = counts.get("header_footer_rs", 0) + n

    # header RS di baris awal/akhir halaman
    lines = masked.splitlines()
    if lines:
        candidates = set(lines[:8] + lines[-8:])
        for cand in candidates:
            if re.search(
                r"\b(RS|RSUD|RSUP|Rumah\s*Sakit|Klinik|Puskesmas|Jl\.|Jalan|Telp|Fax)\b",
                cand, re.I
            ):
                n = masked.count(cand)
                masked = masked.replace(cand, MASKS["header_footer_rs"])
                counts["header_footer_rs"] = counts.get("header_footer_rs", 0) + n

    return masked, counts


# ---------------------------------------------------------------------------
# Cek kebocoran identitas pasca-masking
# ---------------------------------------------------------------------------

def find_leaks(masked_text: str, patient_folder: str) -> list[LeakFinding]:
    checks = [
        ("Kemungkinan NIK",
         r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"),
        ("Kemungkinan telepon",
         r"(?:\+?62|0)[\s\-]?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,5}"),
        ("Kemungkinan email",
         r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}"),
        ("Kemungkinan MRN",
         r"(?:No\.?\s*RM|Nomor\s*RM|Rekam\s*Medis).{0,25}"),
        ("Kemungkinan alamat",
         r"(?:Jl\.|Jalan|RT\s*\d+|RW\s*\d+|Kel\.|Kec\.).{0,60}"),
        ("Kemungkinan RS",
         r"(?:RS|RSUD|RSUP|Rumah\s*Sakit|Klinik|Puskesmas).{0,60}"),
        ("Kemungkinan staff",
         r"(?:DPJP|Dokter|Perawat|SIP\s*:).{0,80}"),
        ("Kemungkinan nama (gelar)",
         r"\b(?:Tn|Ny|An|Nn)\.?\s+[A-Z][A-Za-z]{1,30}"),
    ]
    findings: list[LeakFinding] = []
    for category, pattern in checks:
        for match in re.finditer(pattern, masked_text, re.I):
            evidence = compact_spaces(match.group(0))[:120]
            # abaikan bila sudah berisi token masking
            if not re.search(r"\[.+?\]", evidence):
                findings.append(LeakFinding(patient_folder, category, evidence))
    return findings


# ---------------------------------------------------------------------------
# Ekstraksi variabel klinis — dengan validasi range
# ---------------------------------------------------------------------------

def first_match(text: str, patterns: list[str],
                flags: int = re.I | re.M | re.S) -> str:
    for pattern in patterns:
        m = re.search(pattern, text, flags)
        if m:
            groups = m.groups()
            return compact_spaces(groups[0] if groups else m.group(0))
    return ""


def value_with_source(
    documents: list[DocumentText],
    preferred_types: list[str],
    patterns: list[str],
) -> tuple[str, str]:
    ordered  = [doc for dt in preferred_types for doc in documents if doc.document_type == dt]
    fallback = [doc for doc in documents if doc not in ordered]
    for doc in ordered + fallback:
        value = first_match(doc.masked_text, patterns)
        if value:
            return value, doc.document_type
    return "", ""


def yes_if_terms(text: str, terms: list[str]) -> str:
    found = [t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", text, re.I)]
    return ", ".join(found)


def terms_with_source(
    documents: list[DocumentText],
    preferred_types: list[str],
    terms: list[str],
) -> tuple[str, str]:
    ordered  = [doc for dt in preferred_types for doc in documents if doc.document_type == dt]
    fallback = [doc for doc in documents if doc not in ordered]
    found_terms: list[str] = []
    found_sources: list[str] = []
    for doc in ordered + fallback:
        value = yes_if_terms(doc.masked_text, terms)
        if value:
            found_terms.extend(t.strip() for t in value.split(","))
            found_sources.append(doc.document_type)
    clean_terms   = ", ".join(dict.fromkeys(t for t in found_terms if t))
    clean_sources = ", ".join(dict.fromkeys(found_sources))
    return clean_terms, clean_sources


def _validate_blood_pressure(raw: str) -> str:
    """Validasi & bersihkan nilai tekanan darah. Return '' bila di luar range."""
    m = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", raw)
    if not m:
        return raw
    sys, dia = int(m.group(1)), int(m.group(2))
    if VALID_SYSTOLIC[0] <= sys <= VALID_SYSTOLIC[1] \
       and VALID_DIASTOLIC[0] <= dia <= VALID_DIASTOLIC[1]:
        return f"{sys}/{dia} mmHg"
    return ""   # di luar range → buang


def _validate_gds(raw: str) -> str:
    """Validasi nilai GDS. Return '' bila tidak masuk akal."""
    m = re.search(r"(\d{2,4})", raw)
    if not m:
        return raw
    val = int(m.group(1))
    if VALID_GDS[0] <= val <= VALID_GDS[1]:
        return raw
    return ""


def _validate_gcs(raw: str) -> str:
    """Validasi skor GCS total (3-15)."""
    # tangkap E+V+M = total, atau total langsung
    m = re.search(r"(\d{1,2})", raw)
    if not m:
        return raw
    val = int(m.group(1))
    if 3 <= val <= 15:
        return raw
    # mungkin berformat E4V5M6 — jumlahkan
    m2 = re.findall(r"[EVM](\d)", raw, re.I)
    if m2:
        total = sum(int(x) for x in m2)
        if 3 <= total <= 15:
            return raw
    return ""


def _compute_lama_rawat(documents: list[DocumentText]) -> str:
    """
    Hitung lama rawat dari tanggal masuk & pulang bila LOS tidak tercatat.
    Format tanggal yang didukung: DD-MM-YYYY, DD/MM/YYYY, DD Month YYYY.
    """
    masuk_patterns = [
        r"(?:Tgl\.?\s*Masuk|Tanggal\s*Masuk|MRS|Masuk)\s*[:\-]\s*"
        r"(\d{1,2}[\-\/]\d{1,2}[\-\/]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]
    pulang_patterns = [
        r"(?:Tgl\.?\s*Pulang|Tanggal\s*Pulang|KRS|Pulang|Keluar)\s*[:\-]\s*"
        r"(\d{1,2}[\-\/]\d{1,2}[\-\/]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]
    BULAN = {
        "januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,
        "juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12,
        "january":1,"february":2,"march":3,"may":5,"june":6,"july":7,
        "august":8,"september":9,"october":10,"november":11,"december":12,
    }

    def parse_date(s: str):
        s = s.strip()
        m = re.match(r"(\d{1,2})[\-\/](\d{1,2})[\-\/](\d{4})", s)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
        if m:
            bulan = BULAN.get(m.group(2).lower())
            if bulan:
                try:
                    return datetime(int(m.group(3)), bulan, int(m.group(1)))
                except ValueError:
                    pass
        return None

    all_text = "\n".join(doc.masked_text for doc in documents)
    tgl_masuk  = first_match(all_text, masuk_patterns)
    tgl_pulang = first_match(all_text, pulang_patterns)
    if tgl_masuk and tgl_pulang:
        dt_masuk  = parse_date(tgl_masuk)
        dt_pulang = parse_date(tgl_pulang)
        if dt_masuk and dt_pulang and dt_pulang >= dt_masuk:
            selisih = (dt_pulang - dt_masuk).days
            return f"{selisih} hari (dihitung: {tgl_masuk} → {tgl_pulang})"
    return ""


def extract_clinical_variables(
    documents: list[DocumentText],
    patient_folder: str,
    output_dir: Path,
) -> PatientResult:
    pdfs   = [doc.path for doc in documents]
    result = PatientResult(
        patient_folder=patient_folder,
        source_files=", ".join(pdf.name for pdf in pdfs),
        detected_documents=", ".join(dict.fromkeys(doc.document_type for doc in documents)),
    )

    # Diagnosis stroke
    result.diagnosis_stroke, result.diagnosis_source = value_with_source(
        documents, ["RESUME", "CPPT IGD", "CPPT RANAP"], [
            r"(?:Diagnosis|Diagnosa|Dx)\s*[:\-]\s*([^\n]{0,160}stroke[^\n]{0,160})",
            r"(?:Diagnosis|Diagnosa|Dx)\s*[:\-]\s*([^\n]{0,160}(?:CVA|SNH|SH|ICH|SAH|infark)[^\n]{0,160})",
            r"\b(stroke\s+(?:iskemik|hemoragik|perdarahan|infark)[^\n]{0,120})",
            r"\b(CVA|SNH|SH|ICH|SAH|infark\s+serebri)[^\n]{0,120}",
        ])

    # Onset
    result.onset, result.onset_source = value_with_source(
        documents, ["CPPT IGD", "RESUME"], [
            r"(?:onset|mulai\s*keluhan|awitan)\s*[:\-]?\s*([^\n]{0,120})",
            r"(?:keluhan\s*sejak)\s*([^\n]{0,120})",
            r"(?:last\s*known\s*well|LKW)\s*[:\-]?\s*([^\n]{0,120})",
        ])

    # GCS — dengan validasi
    gcs_raw, gcs_src = value_with_source(
        documents, ["CPPT IGD", "CPPT RANAP"], [
            r"\bGCS\s*[:\-]?\s*([EVM0-9\/\+\s]{3,30})",
            r"\bGlasgow\s*Coma\s*Scale\s*[:\-]?\s*([^\n]{0,40})",
        ])
    result.gcs        = _validate_gcs(gcs_raw) if gcs_raw else ""
    result.gcs_source = gcs_src if result.gcs else ""

    # Tekanan darah — dengan validasi range
    td_raw, td_src = value_with_source(
        documents, ["CPPT IGD"], [
            r"(?:TD|Tekanan\s*Darah|Tensi)\s*[:\-]?\s*(\d{2,3}\s*/\s*\d{2,3}\s*(?:mmHg?)?)",
            r"\b(\d{2,3}\s*/\s*\d{2,3})\s*(?:mmHg?)?\b",
        ])
    result.tekanan_darah_awal   = _validate_blood_pressure(td_raw) if td_raw else ""
    result.tekanan_darah_source = td_src if result.tekanan_darah_awal else ""

    # GDS — dengan validasi range
    gds_raw, gds_src = value_with_source(
        documents, ["LAB", "CPPT IGD"], [
            r"(?:GDS|Gula\s*Darah\s*Sewaktu|Glukosa\s*Sewaktu)\s*[:\-]?\s*(\d{2,4}\s*(?:mg/dL|mg%|mmol/L)?)",
            r"(?:Glukosa|GDP|GD2PP|Blood\s*Glucose)\s*[:\-]?\s*(\d{2,4}\s*(?:mg/dL|mg%|mmol/L)?)",
        ])
    result.gula_darah_sewaktu   = _validate_gds(gds_raw) if gds_raw else ""
    result.gula_darah_source    = gds_src if result.gula_darah_sewaktu else ""

    # CT Scan
    result.hasil_ct_scan, result.ct_scan_source = value_with_source(
        documents, ["RAD", "RESUME"], [
            r"(?:kesan|impression)\s*[:\-]?\s*([^\n]{0,220}(?:infark|perdarahan|hemorrhage|iskemik|ICH|SAH)[^\n]{0,120})",
            r"(?:CT\s*Scan|MSCT|Head\s*CT|CT\s*Kepala)\s*[:\-]?\s*([^\n]{0,300}(?:infark|perdarahan|hemorrhage|iskemik|ICH|SAH)[^\n]{0,120})",
            r"(?:CT\s*Scan|MSCT|Head\s*CT|CT\s*Kepala)\s*[:\-]?\s*([^\n]{0,300})",
        ])

    # Lab
    result.hasil_laboratorium, result.laboratorium_source = value_with_source(
        documents, ["LAB"], [
            r"(?:Laboratorium|Lab)\s*[:\-]?\s*([^\n]{0,300})",
            r"((?:Hb|Leukosit|Trombosit|Ureum|Kreatinin|Na|K|Cl|INR|APTT|PT)"
            r"\s*[:\-]?\s*[^\n]{0,220})",
        ])

    # Terapi
    result.terapi_antiplatelet, result.antiplatelet_source = terms_with_source(
        documents, ["RESUME", "CPPT RANAP"],
        ["aspirin", "aspilet", "clopidogrel", "cilostazol", "ticagrelor"])
    result.statin, result.statin_source = terms_with_source(
        documents, ["RESUME", "CPPT RANAP"],
        ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin"])
    result.antihipertensi, result.antihipertensi_source = terms_with_source(
        documents, ["RESUME", "CPPT RANAP", "CPPT IGD"],
        ["amlodipine", "amlodipin", "captopril", "lisinopril", "bisoprolol",
         "valsartan", "candesartan", "nicardipine", "furosemide", "HCT",
         "nifedipin", "nifedipine", "ramipril", "irbesartan"])

    # Komorbid
    result.komorbid, result.komorbid_source = terms_with_source(
        documents, ["RESUME", "CPPT IGD"],
        ["hipertensi", "diabetes", "DM", "dislipidemia", "hiperlipidemia",
         "atrial fibrilasi", "AF", "CKD", "gagal ginjal", "penyakit jantung",
         "merokok", "obesitas"])

    # Lama rawat — coba teks dulu, lalu hitung dari tanggal
    lama_text, lama_src = value_with_source(
        documents, ["RESUME"], [
            r"(?:lama\s*rawat|LOS)\s*[:\-]?\s*([^\n]{0,50})",
            r"(?:dirawat\s*selama)\s*([^\n]{0,50})",
        ])
    if lama_text:
        result.lama_rawat        = lama_text
        result.lama_rawat_source = lama_src
    else:
        computed = _compute_lama_rawat(documents)
        if computed:
            result.lama_rawat        = computed
            result.lama_rawat_source = "Dihitung otomatis"

    # Kondisi pulang
    result.kondisi_pulang, result.kondisi_pulang_source = value_with_source(
        documents, ["RESUME"], [
            r"(?:kondisi\s*pulang|keadaan\s*pulang|status\s*pulang)\s*[:\-]?\s*([^\n]{0,120})",
            r"(?:pulang)\s*[:\-]?\s*(membaik|sembuh|meninggal|rujuk|pulang\s*paksa|APS)",
        ])

    # mRS
    result.mrs, result.mrs_source = value_with_source(
        documents, ["RESUME", "CPPT RANAP"], [
            r"\bmRS\s*[:\-]?\s*([0-6])\b",
            r"\bmodified\s*Rankin\s*Scale\s*[:\-]?\s*([0-6])\b",
        ])

    # Simpan teks anonim
    masked_text = "\n\n".join(doc.masked_text for doc in documents)
    patient_output_dir = output_patient_dir(output_dir, patient_folder)
    patient_output_dir.mkdir(parents=True, exist_ok=True)
    text_path = patient_output_dir / "SEMUA_DOKUMEN_anonim.txt"
    text_path.write_text(masked_text, encoding="utf-8")
    result.masked_text_path = str(text_path)
    return result


# ---------------------------------------------------------------------------
# Audit pathway
# ---------------------------------------------------------------------------

def audit_pathway(result: PatientResult) -> list[AuditFinding]:
    checks = [
        ("Diagnosis stroke tercatat",       bool(result.diagnosis_stroke),     result.diagnosis_stroke),
        ("Onset tercatat",                  bool(result.onset),                result.onset),
        ("GCS tercatat & valid",            bool(result.gcs),                  result.gcs),
        ("Tekanan darah awal tercatat",     bool(result.tekanan_darah_awal),   result.tekanan_darah_awal),
        ("GDS tercatat & valid",            bool(result.gula_darah_sewaktu),   result.gula_darah_sewaktu),
        ("CT scan tercatat",                bool(result.hasil_ct_scan),        result.hasil_ct_scan),
        ("Terapi antiplatelet tercatat",    bool(result.terapi_antiplatelet),  result.terapi_antiplatelet),
        ("Statin tercatat",                 bool(result.statin),               result.statin),
        ("Kondisi pulang tercatat",         bool(result.kondisi_pulang),       result.kondisi_pulang),
        ("mRS tercatat",                    bool(result.mrs),                  result.mrs),
    ]
    return [
        AuditFinding(result.patient_folder, item, "Terpenuhi" if ok else "Belum ditemukan", note)
        for item, ok, note in checks
    ]


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def safe_output_stem(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", s).strip("_") or "pasien"


def output_patient_dir(output_dir: Path, patient_label: str) -> Path:
    parts = re.split(r"[\\/]+", patient_label)
    clean = [safe_output_stem(p) for p in parts if p.strip()]
    return output_dir.joinpath(*clean) if clean else output_dir / "pasien"


def build_document_texts(
    patient: Path,
    input_dir: Path,
    output_dir: Path,
    patient_label: str,
    use_ocr: bool = True,
) -> tuple[list[DocumentText], list[DocumentRecord], dict[str, int]]:
    documents: list[DocumentText] = []
    records:   list[DocumentRecord] = []
    total_counts: dict[str, int] = {}

    for pdf in sorted(patient.rglob("*.pdf")):
        raw_text, ocr_used = read_pdf_text(pdf, use_ocr=use_ocr)
        masked_text, counts = mask_identity(raw_text)
        for k, v in counts.items():
            total_counts[k] = total_counts.get(k, 0) + v
        doc_type = classify_document(pdf, masked_text or raw_text)
        status = "OCR" if ocr_used else ("Terbaca" if not is_text_empty(raw_text) else "Perlu OCR manual")
        try:
            rel_path = str(pdf.relative_to(patient))
        except ValueError:
            rel_path = pdf.name
        documents.append(DocumentText(pdf, patient_label, doc_type, raw_text, masked_text, ocr_used))
        records.append(DocumentRecord(patient_label, doc_type, pdf.name, rel_path, len(raw_text), status, ocr_used))

    # Simpan per jenis dokumen
    patient_output_dir = output_patient_dir(output_dir, patient_label)
    patient_output_dir.mkdir(parents=True, exist_ok=True)
    for doc_type in ["CPPT IGD", "LAB", "RAD", "RESUME", "CPPT RANAP", "LAINNYA"]:
        grouped = "\n\n".join(doc.masked_text for doc in documents if doc.document_type == doc_type)
        if grouped.strip():
            fname = f"{safe_output_stem(doc_type)}_anonim.txt"
            (patient_output_dir / fname).write_text(grouped, encoding="utf-8")

    return documents, records, total_counts


def discover_patient_folders(input_dir: Path) -> list[Path]:
    direct_pdf_dirs = sorted({pdf.parent for pdf in input_dir.rglob("*.pdf")})
    if input_dir in direct_pdf_dirs:
        direct_pdf_dirs.remove(input_dir)
        direct_pdf_dirs.insert(0, input_dir)
    if not direct_pdf_dirs:
        return []

    top_level_groups: dict[Path, list[Path]] = {}
    for folder in direct_pdf_dirs:
        try:
            relative = folder.relative_to(input_dir)
        except ValueError:
            continue
        top = input_dir if str(relative) == "." else input_dir / relative.parts[0]
        top_level_groups.setdefault(top, []).append(folder)

    patient_folders: list[Path] = []
    for top, folders in top_level_groups.items():
        if top == input_dir:
            patient_folders.append(input_dir)
        elif top in direct_pdf_dirs:
            patient_folders.append(top)
        elif len(folders) == 1:
            patient_folders.append(top)
        else:
            patient_folders.extend(folders)

    return sorted(dict.fromkeys(patient_folders))


def build_resume_result(
    result: PatientResult,
    documents: list[DocumentText],
    output_dir: Path,
) -> ResumeResult:
    patient_output_dir = output_patient_dir(output_dir, result.patient_folder)
    resume_text_path   = patient_output_dir / "RESUME_anonim.txt"
    if not resume_text_path.exists():
        resume_text = "\n\n".join(doc.masked_text for doc in documents if doc.document_type == "RESUME")
        if resume_text.strip():
            resume_text_path.write_text(resume_text, encoding="utf-8")
    return ResumeResult(
        patient_folder    = result.patient_folder,
        diagnosis_stroke  = result.diagnosis_stroke,
        lama_rawat        = result.lama_rawat,
        kondisi_pulang    = result.kondisi_pulang,
        mrs               = result.mrs,
        terapi_antiplatelet = result.terapi_antiplatelet,
        statin            = result.statin,
        antihipertensi    = result.antihipertensi,
        resume_text_path  = str(resume_text_path) if resume_text_path.exists() else "",
    )


# ---------------------------------------------------------------------------
# Proses utama
# ---------------------------------------------------------------------------

def process_inputs(
    input_dirs: list[Path],
    output_dir: Path,
    progress_queue: queue.Queue,
    use_ocr: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    patient_sources: list[tuple[Path, Path]] = []
    for input_dir in input_dirs:
        for patient in discover_patient_folders(input_dir):
            patient_sources.append((input_dir, patient))

    clinical_rows: list[PatientResult]  = []
    resume_rows:   list[ResumeResult]   = []
    document_rows: list[DocumentRecord] = []
    leak_rows:     list[LeakFinding]    = []
    audit_rows:    list[AuditFinding]   = []
    log_rows:      list[ExtractionLog]  = []

    progress_queue.put(
        f"Ditemukan {len(patient_sources)} folder pasien dari {len(input_dirs)} folder input."
        + (" OCR aktif." if use_ocr else " OCR nonaktif.")
    )
    if not patient_sources:
        selected = ", ".join(p.name for p in input_dirs)
        log_rows.append(ExtractionLog(selected, "Gagal", "Tidak ditemukan PDF.", 0, 0))

    seen_labels: dict[str, int] = {}
    for input_dir, patient in patient_sources:
        patient_label = (
            str(patient.relative_to(input_dir))
            if patient != input_dir else input_dir.name
        )
        if len(input_dirs) > 1 and patient != input_dir:
            patient_label = f"{input_dir.name}/{patient_label}"
        dup = seen_labels.get(patient_label, 0)
        seen_labels[patient_label] = dup + 1
        if dup:
            patient_label = f"{patient_label}_{dup + 1}"

        progress_queue.put(f"Memproses {patient_label}...")
        try:
            documents, records, mask_counts = build_document_texts(
                patient, input_dir, output_dir, patient_label, use_ocr=use_ocr
            )
            for rec in records:
                rec.patient_folder = patient_label
            document_rows.extend(records)

            raw_text    = "\n\n".join(doc.raw_text    for doc in documents)
            masked_text = "\n\n".join(doc.masked_text for doc in documents)
            pdfs        = [doc.path for doc in documents]

            if not pdfs:
                log_rows.append(ExtractionLog(patient_label, "Dilewati", "Tidak ada PDF", 0, 0))
                continue

            for doc in documents:
                doc.patient_folder = patient_label

            result = extract_clinical_variables(documents, patient_label, output_dir)
            clinical_rows.append(result)
            resume_rows.append(build_resume_result(result, documents, output_dir))
            leak_rows.extend(find_leaks(masked_text, patient_label))
            audit_rows.extend(audit_pathway(result))

            ocr_count = sum(1 for doc in documents if doc.ocr_used)
            if is_text_empty(compact_spaces(raw_text)):
                status  = "Perlu OCR manual"
                message = "Teks hampir kosong meski OCR sudah dicoba. PDF mungkin kualitas rendah."
            elif ocr_count:
                status  = "Selesai (OCR)"
                message = f"{ocr_count} file diproses via OCR. Masking: {json.dumps(mask_counts, ensure_ascii=False)}"
            else:
                status  = "Selesai"
                message = f"Masking: {json.dumps(mask_counts, ensure_ascii=False)}"

            log_rows.append(ExtractionLog(patient_label, status, message, len(pdfs), len(raw_text)))
        except Exception as exc:
            log_rows.append(ExtractionLog(patient_label, "Gagal", str(exc), 0, 0))

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = output_dir / f"hasil_ekstraksi_rekam_medis_{timestamp}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        pd.DataFrame([asdict(r) for r in clinical_rows ]).to_excel(writer, sheet_name="Data Klinis",         index=False)
        pd.DataFrame([asdict(r) for r in resume_rows   ]).to_excel(writer, sheet_name="Resume",              index=False)
        pd.DataFrame([asdict(r) for r in document_rows ]).to_excel(writer, sheet_name="Inventaris Dokumen",  index=False)
        pd.DataFrame([asdict(r) for r in audit_rows    ]).to_excel(writer, sheet_name="Audit Pathway",       index=False)
        pd.DataFrame([asdict(r) for r in leak_rows     ]).to_excel(writer, sheet_name="Kebocoran Identitas", index=False)
        pd.DataFrame([asdict(r) for r in log_rows      ]).to_excel(writer, sheet_name="Log Ekstraksi",       index=False)

    progress_queue.put(f"Selesai. File Excel: {excel_path}")
    return excel_path


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class MedicalExtractorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Ekstraksi Rekam Medis Stroke")
        self.root.geometry("1020x700")
        self.root.minsize(900, 580)

        self.output_dir:     StringVar  = StringVar()
        self.status:         StringVar  = StringVar(value="Tambahkan satu atau beberapa folder input.")
        self.use_ocr_var:    BooleanVar = BooleanVar(value=True)
        self.input_dirs:     list[Path] = []
        self.progress_queue: queue.Queue[str] = queue.Queue()
        self.worker:         threading.Thread | None = None

        self._build_ui()
        self.root.after(200, self._poll_progress)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame",       background="#f6f7f9")
        style.configure("Panel.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("TLabel",       background="#f6f7f9", foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18), background="#f6f7f9", foreground="#111827")
        style.configure("Hint.TLabel",  font=("Segoe UI", 9),  background="#f6f7f9", foreground="#6b7280")
        style.configure("Warn.TLabel",  font=("Segoe UI", 9),  background="#f6f7f9", foreground="#b45309")
        style.configure("TButton",      font=("Segoe UI", 10), padding=(12, 7))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(14, 8))
        style.configure("Treeview",     rowheight=26, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))

        self.root.configure(bg="#f6f7f9")
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill=BOTH, expand=True)

        # Judul
        ttk.Label(outer, text="Ekstraksi Rekam Medis Stroke", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Pilih beberapa folder input, deteksi jenis dokumen, anonimisasi, lalu export Excel.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        # Warning OCR
        ocr_status = "✓ OCR tersedia (pytesseract)" if PYTESSERACT_AVAILABLE else "⚠ OCR tidak tersedia — install pytesseract & tesseract"
        ocr_color  = "Hint.TLabel" if PYTESSERACT_AVAILABLE else "Warn.TLabel"
        ttk.Label(outer, text=ocr_status, style=ocr_color).pack(anchor="w", pady=(0, 10))

        # Panel folder input
        folder_panel = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        folder_panel.pack(fill=X, pady=(0, 12))

        ttk.Label(folder_panel, text="Folder Input").pack(anchor="w")
        self.folder_list = Listbox(
            folder_panel, height=5, activestyle="none",
            bg="#ffffff", fg="#111827",
            selectbackground="#2563eb", selectforeground="#ffffff",
            highlightthickness=1, highlightbackground="#d1d5db",
            borderwidth=0, font=("Segoe UI", 9),
        )
        self.folder_list.pack(fill=X, pady=(6, 10))

        folder_actions = ttk.Frame(folder_panel)
        folder_actions.pack(fill=X)
        ttk.Button(folder_actions, text="Tambah Folder",          command=self._add_input       ).pack(side=LEFT)
        ttk.Button(folder_actions, text="Tambah Semua Subfolder", command=self._add_child_inputs).pack(side=LEFT, padx=(8, 0))
        ttk.Button(folder_actions, text="Hapus Terpilih",         command=self._remove_selected ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(folder_actions, text="Kosongkan",              command=self._clear_inputs    ).pack(side=LEFT, padx=(8, 0))

        # Folder output
        ttk.Label(outer, text="Folder Output").pack(anchor="w")
        row_out = ttk.Frame(outer)
        row_out.pack(fill=X, pady=(4, 10))
        ttk.Entry(row_out, textvariable=self.output_dir).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row_out, text="Pilih", command=self._choose_output).pack(side=RIGHT, padx=(8, 0))

        # Opsi OCR
        ocr_frame = ttk.Frame(outer)
        ocr_frame.pack(fill=X, pady=(0, 8))
        Checkbutton(
            ocr_frame,
            text="Gunakan OCR untuk PDF scan/gambar",
            variable=self.use_ocr_var,
            bg="#f6f7f9", fg="#1f2937",
            activebackground="#f6f7f9",
            font=("Segoe UI", 10),
            state="normal" if PYTESSERACT_AVAILABLE else "disabled",
        ).pack(side=LEFT)
        ttk.Label(
            ocr_frame,
            text="(lebih lambat, tapi diperlukan untuk PDF scan)",
            style="Hint.TLabel",
        ).pack(side=LEFT, padx=(8, 0))

        # Tombol aksi
        actions = ttk.Frame(outer)
        actions.pack(fill=X, pady=(0, 10))
        self.run_button = ttk.Button(
            actions, text="Mulai Ekstraksi",
            style="Accent.TButton", command=self._run,
        )
        self.run_button.pack(side=LEFT)
        ttk.Label(actions, textvariable=self.status, style="Hint.TLabel").pack(side=LEFT, padx=(12, 0))

        # Log proses
        ttk.Label(outer, text="Log Proses").pack(anchor="w")

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill=BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical")
        scrollbar.pack(side=RIGHT, fill=Y)

        self.log_box = ttk.Treeview(
            log_frame,
            columns=("message",),
            show="headings",
            height=14,
            yscrollcommand=scrollbar.set,
        )
        self.log_box.heading("message", text="Aktivitas")
        self.log_box.column("message", width=950, anchor="w")
        self.log_box.pack(fill=BOTH, expand=True)
        scrollbar.config(command=self.log_box.yview)

    # ------------------------------------------------------------------
    # Aksi folder
    # ------------------------------------------------------------------

    def _add_input(self) -> None:
        path = filedialog.askdirectory(title="Tambah folder data pasien atau folder induk")
        if path:
            selected = Path(path)
            if selected not in self.input_dirs:
                self.input_dirs.append(selected)
                self.folder_list.insert(END, str(selected))
            if not self.output_dir.get():
                self.output_dir.set(str(Path(path).parent / "output_ekstraksi"))
            self.status.set(f"{len(self.input_dirs)} folder input siap diproses.")

    def _add_child_inputs(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder induk yang berisi banyak folder pasien")
        if not path:
            return
        parent   = Path(path)
        children = [c for c in sorted(parent.iterdir()) if c.is_dir()]
        added    = 0
        for child in children:
            if child not in self.input_dirs:
                self.input_dirs.append(child)
                self.folder_list.insert(END, str(child))
                added += 1
        if not self.output_dir.get():
            self.output_dir.set(str(parent / "output_ekstraksi"))
        self.status.set(f"{added} subfolder ditambahkan. Total {len(self.input_dirs)} folder input.")

    def _remove_selected(self) -> None:
        for idx in reversed(list(self.folder_list.curselection())):
            self.folder_list.delete(idx)
            del self.input_dirs[idx]
        self.status.set(f"{len(self.input_dirs)} folder input siap diproses.")

    def _clear_inputs(self) -> None:
        self.folder_list.delete(0, END)
        self.input_dirs.clear()
        self.status.set("Daftar folder input dikosongkan.")

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Pilih folder output")
        if path:
            self.output_dir.set(path)

    # ------------------------------------------------------------------
    # Review sebelum export  (FITUR BARU)
    # ------------------------------------------------------------------

    def _show_review_window(self, leak_rows: list[LeakFinding]) -> bool:
        """
        Tampilkan jendela review kebocoran identitas.
        Kembalikan True bila pengguna memilih untuk tetap lanjut export.
        """
        if not leak_rows:
            return True

        result: list[bool] = [False]
        win = Tk.__new__(Tk)
        win.__init__()
        win.title("⚠ Review Kebocoran Identitas")
        win.geometry("820x500")
        win.configure(bg="#fffbeb")

        Label(
            win,
            text=f"Ditemukan {len(leak_rows)} kemungkinan kebocoran identitas. Periksa sebelum export.",
            bg="#fffbeb", fg="#92400e",
            font=("Segoe UI Semibold", 11),
            wraplength=780, justify="left",
        ).pack(padx=20, pady=(16, 8), anchor="w")

        tree_frame = Frame(win, bg="#fffbeb")
        tree_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 8))
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        vsb.pack(side=RIGHT, fill=Y)
        tree = ttk.Treeview(
            tree_frame,
            columns=("folder", "kategori", "bukti"),
            show="headings",
            height=14,
            yscrollcommand=vsb.set,
        )
        vsb.config(command=tree.yview)
        tree.heading("folder",   text="Pasien")
        tree.heading("kategori", text="Kategori")
        tree.heading("bukti",    text="Teks yang mencurigakan")
        tree.column("folder",    width=160)
        tree.column("kategori",  width=180)
        tree.column("bukti",     width=430)
        for finding in leak_rows:
            tree.insert("", END, values=(finding.patient_folder, finding.category, finding.evidence))
        tree.pack(fill=BOTH, expand=True)

        btn_frame = Frame(win, bg="#fffbeb")
        btn_frame.pack(fill=X, padx=20, pady=(0, 16))

        def _lanjut():
            result[0] = True
            win.destroy()

        def _batal():
            result[0] = False
            win.destroy()

        Button(btn_frame, text="Lanjut Export Tetap",
               command=_lanjut, bg="#d97706", fg="white",
               font=("Segoe UI Semibold", 10), relief="flat", padx=16, pady=8).pack(side=LEFT)
        Button(btn_frame, text="Batalkan — Periksa Ulang",
               command=_batal, bg="#6b7280", fg="white",
               font=("Segoe UI", 10), relief="flat", padx=16, pady=8).pack(side=LEFT, padx=(10, 0))

        win.wait_window()
        return result[0]

    # ------------------------------------------------------------------
    # Jalankan proses
    # ------------------------------------------------------------------

    def _run(self) -> None:
        output_path  = Path(self.output_dir.get())
        valid_inputs = [p for p in self.input_dirs if p.exists() and p.is_dir()]
        if not valid_inputs:
            messagebox.showerror("Folder belum valid", "Tambahkan minimal satu folder input yang valid.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.run_button.config(state="disabled")
        self.status.set("Sedang memproses...")
        self.log_box.delete(*self.log_box.get_children())
        self.worker = threading.Thread(
            target=self._worker_run,
            args=(valid_inputs, output_path, self.use_ocr_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _worker_run(
        self,
        input_paths: list[Path],
        output_path: Path,
        use_ocr: bool,
    ) -> None:
        try:
            process_inputs(input_paths, output_path, self.progress_queue, use_ocr=use_ocr)
        except Exception as exc:
            self.progress_queue.put(f"Gagal: {exc}")
        finally:
            self.progress_queue.put("__DONE__")

    def _poll_progress(self) -> None:
        while not self.progress_queue.empty():
            message = self.progress_queue.get_nowait()
            if message == "__DONE__":
                self.run_button.config(state="normal")
                self.status.set("Selesai.")
                messagebox.showinfo("Selesai", "Ekstraksi selesai. Cek folder output.")
            else:
                self.log_box.insert("", END, values=(message,))
                self.log_box.yview_moveto(1)
        self.root.after(200, self._poll_progress)

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    MedicalExtractorApp().run()
