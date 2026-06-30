from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# ANONIMISASI STAGE 6 FIXED - DOCTORS CSV + STAFF_EXTRA CSV + RADIOLOGY FOOTER/PHONE CLEANUP
#
# Struktur folder:
# Pipeline RME Stroke/
# ├── 02_text_extracted/STROKE_001/*.txt
# ├── 03_anonymized_text/
# ├── 04_anonymization_report/
# └── 06_scripts/
#     ├── anonymize_stage6_staff_extra_recursive.py
#     ├── staff_doctors.csv
#     └── staff_extra.csv       <-- opsional
#
# Jalankan dari folder 06_scripts:
#   python anonymize_stage6_staff_extra_recursive.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"
SCRIPT_DIR = Path(__file__).resolve().parent
DOCTOR_CSV = SCRIPT_DIR / "staff_doctors.csv"
EXTRA_CSV = SCRIPT_DIR / "staff_extra.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

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

HOSPITAL_NAMES = [
    # Nama RS/variasi yang sering muncul di header radiologi/lab.
    # Silakan tambah variasi lain kalau masih muncul saat Ctrl+F.
    "RS AL ISLAM BANDUNG",
    "RUMAH SAKIT AL ISLAM BANDUNG",
    "RS AL-ISLAM BANDUNG",
    "RUMAH SAKIT AL-ISLAM BANDUNG",
]

CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning", "sesuai", "observasi",
    "pasien", "nyeri", "lemah", "sesak", "muntah", "demam", "stroke", "infark",
    "pneumonia", "hematemesis", "anamnesis", "pemeriksaan", "tekanan", "darah",
    "suhu", "spo2", "gcs", "ews", "hasil", "nilai", "rujukan", "satuan", "klinik",
    "poliklinik", "penjamin", "alamat", "umur", "tgl", "lahir", "perempuan", "laki",
    "hematologi", "cell", "counter", "hemoglobin", "leukosit", "trigliserida",
    "foto", "thorax", "kesan", "cor", "pulmo", "aorta", "bronkho",
}

HONORIFICS = {"h", "hj", "haji", "hajah"}
TITLE_WORDS = {
    "dr", "drg", "sp", "spd", "spn", "sps", "sprad", "sppk", "sppd", "spjp",
    "mkes", "mhkes", "mm", "msc", "phd", "finasim", "fiha", "kic",
    "apt", "ners", "ns", "amd", "kep", "rad", "fis", "gizi",
}

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text

def merge_counts(*dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out

def infer_role(s: str) -> str:
    low = s.lower()
    compact = re.sub(r"[\s,\.]+", "", low)
    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        key = degree.replace(".", "").replace(" ", "").lower()
        if key in compact:
            return role
    if re.search(r"\bsp\.?\s*[a-z]", low, flags=re.I):
        return "DOKTER_SPESIALIS"
    if re.search(r"\bdrg\.?\b", low, flags=re.I):
        return "DOKTER_GIGI"
    if re.search(r"\bdr\.?\b|\bdr\s*,", low, flags=re.I):
        return "DOKTER_UMUM"
    return "DOKTER"

def clean_staff_name(name: str) -> str:
    x = name.strip()
    x = re.sub(r"(?i)\bdrg?\.?\s*", " ", x)
    x = re.sub(r"(?i)\bSp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?", " ", x)
    x = re.sub(r"(?i)\b(?:M\.?Kes|MH\.?Kes|M\.?Sc|MM|PhD|FINASIM|FIHA|KIC|SH|MH)\b\. ?", " ", x)
    x = re.sub(r"(?i)\b(?:H\.?|Hj\.?|Haji|Hajah)\b\. ?", " ", x)
    x = re.sub(r"(?i)\b(?:Apt\.?|apt\.?|Ners|Ns\.?|Amd\.?\s*Kep\.?|Amd\.?\s*Rad\.?|Amd\.?\s*Fis\.?|S\.?\s*Kep\.?)\b\. ?", " ", x)
    x = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'` -]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x

def tokens_from_name(name: str):
    x = clean_staff_name(name)
    toks = []
    for t in x.split():
        t_clean = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'`]", "", t).strip()
        if not t_clean:
            continue
        low = t_clean.lower().strip(".")
        if low in HONORIFICS or low in TITLE_WORDS:
            continue
        if len(t_clean) <= 1:
            continue
        toks.append(t_clean)
    return toks

def flexible_name_pattern(variant: str) -> str:
    parts = [re.escape(p) for p in variant.split() if p.strip()]
    sep = r"(?:\s|,|\.)+"
    return r"\b" + sep.join(parts) + r"\b"

def build_variants_from_tokens(toks):
    variants = set()
    if len(toks) >= 2:
        variants.add(" ".join(toks))
        variants.add(" ".join(toks[:2]))
        variants.add(toks[0] + " " + toks[-1])
    if len(toks) >= 3:
        variants.add(" ".join([toks[0], toks[1], toks[-1]]))
        variants.add(" ".join(toks[-2:]))
        variants.add(" ".join(toks[:3]))
    if len(toks) >= 4:
        variants.add(" ".join(toks[-3:]))
    safe = set()
    for v in variants:
        if len(v.split()) < 2 or len(v) < 7:
            continue
        if set(v.lower().split()) & CLINICAL_STOPWORDS:
            continue
        safe.add(v)
    return safe

def load_staff_csv(csv_path: Path, default_role="PPA", fuzzy=True):
    records = []
    if not csv_path.exists():
        print(f"Info: {csv_path.name} tidak ditemukan. Dilewati.")
        return records
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or default_role
            if not name:
                continue
            if role in {"DOKTER", "PPA"} and re.search(r"\bdrg?\.?|\bSp\. ?", name, flags=re.I):
                role = infer_role(name)
            toks = tokens_from_name(name)
            variants = build_variants_from_tokens(toks) if fuzzy else set()
            clean = clean_staff_name(name)
            if len(clean.split()) >= 2:
                variants.add(clean)
            for v in variants:
                records.append((v, role))
    print(f"{csv_path.name}: {len(records)} varian terbaca")
    return records

def load_all_staff_variants():
    records = []
    records.extend(load_staff_csv(DOCTOR_CSV, default_role="DOKTER", fuzzy=True))
    records.extend(load_staff_csv(EXTRA_CSV, default_role="PPA", fuzzy=True))
    seen = set()
    unique = []
    for v, r in sorted(records, key=lambda x: len(x[0]), reverse=True):
        key = (v.lower(), r)
        if key not in seen:
            seen.add(key)
            unique.append((v, r))
    print(f"Total varian staff terbaca: {len(unique)}")
    return unique

def anonymize_patient_rs(text: str):
    counts = {}
    patterns = [
        ("NO_RM", r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_RM]"),
        ("NIK", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", "[NIK]"),
        ("NIK_16", r"\b\d{16}\b", "[NIK]"),
        ("NO_HP", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", "[NO_HP]"),
        ("EMAIL", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        ("NAMA_PASIEN", r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Nama Pasien: [PASIEN]"),
        ("ALAMAT", r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}", "Alamat: [ALAMAT]"),
    ]
    for key, pat, repl in patterns:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n
    total = 0
    for name in HOSPITAL_NAMES:
        if name.strip():
            text, n = re.subn(flexible_name_pattern(name), "[RUMAH_SAKIT]", text, flags=re.I)
            total += n
    for pat, repl in [
        (r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", "[RUMAH_SAKIT]"),
        (r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]"),
        (r"\b(?:Telp\.?|Telepon|Phone|Fax)\.?\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]:
        text, n = re.subn(pat, repl, text, flags=re.I)
        total += n
    counts["RUMAH_SAKIT_ALAMAT_RS"] = total
    return text, counts


def cleanup_radiology_footer_and_rs_phone(text: str):
    """
    Tambahan minimal untuk Stage 6:
    membersihkan sisa nomor telepon RS dan footer/header administratif radiologi/lab
    tanpa menghapus isi klinis seperti hasil, kesan, infark, perdarahan, midline shift.
    """
    counts = {}

    # 1) Bersihkan nomor telepon/fax RS yang kadang tidak kena karena formatnya berbeda.
    phone_patterns = [
        # Telp: 022-xxxxxxx / Telepon (022) xxxx / Fax. 022 ...
        ("RS_PHONE_WITH_LABEL",
         r"(?i)\b(?:Telp|Telpon|Telepon|Tlp|Phone|Fax|Faks)\.?\s*[:\-]?\s*(?:\(?0\d{2,4}\)?[\s\-]*)?\d{3,5}[\s\-]?\d{3,5}(?:[\s\-]?\d{1,5})?",
         "[TELEPON_RS]"),

        # Nomor dengan kode area, misal (022) 7562049 atau 022-7562049
        ("RS_PHONE_AREA_CODE",
         r"\b(?:\(?0\d{2,4}\)?[\s\-]*)\d{3,5}[\s\-]?\d{3,5}\b",
         "[TELEPON_RS]"),

        # Sisa label yang menempel dengan kota setelah replacement sebelumnya
        ("PHONE_LABEL_ATTACHED_LOCATION",
         r"(?i)\[TELEPON_RS\]\s*[A-Z]*\s*(?:BANDUNG|JAWA\s*BARAT)(?:\s*[-,]\s*(?:BANDUNG|JAWA\s*BARAT))*\.?",
         "[TELEPON_RS] [LOKASI_RS]"),
    ]

    for key, pat, repl in phone_patterns:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n

    # 2) Bersihkan identitas administratif radiologi/lab yang sering berada di bagian atas/bawah.
    admin_patterns = [
        ("MEDICAL_RECORD_NUMBER",
         r"(?i)\b(?:MEDICAL\s*RECORD\s*NUMBER|Medical\s*Record\s*Number|No\.?\s*Medical\s*Record|MRN)\s*[:\-]?\s*[A-Za-z0-9\-\/\. ]{3,80}",
         "[NO_RM]"),

        ("NO_FOTO",
         r"(?i)\bNo\.?\s*Foto\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+",
         "[NO_FOTO]"),

        ("NO_REG",
         r"(?i)\b(?:No\.?\s*Reg(?:istrasi)?|No\.?\s*Register|No\.?\s*Kunjungan|No\.?\s*Lab)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+",
         "[NO_REGISTER]"),

        ("BANDUNG_JABAR",
         r"(?i)\bBandung\s*[-,]?\s*Jawa\s*Barat\b\.?",
         "[LOKASI_RS]"),

        ("RADIOLOGY_HEADER",
         r"(?i)\b(?:Radiologi\s+X\s*RAY\s+EXAMINATION|X\s*RAY\s+EXAMINATION|LEMBAR\s+HASIL\s+(?:PEMERIKSAAN|RADIOLOGI|LABORATORIUM))\b",
         "[HEADER_HASIL]"),
    ]

    for key, pat, repl in admin_patterns:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = counts.get(key, 0) + n

    # 3) Hapus baris administratif bawah radiologi/lab.
    #    Sengaja per baris, bukan blok panjang, supaya hasil/kesan tetap aman.
    admin_line_patterns = [
        r"(?i)^\s*(?:No\.?\s*Foto|No\.?\s*RM|Medical\s*Record|No\.?\s*Reg|No\.?\s*Lab)\b.*$",
        r"(?i)^\s*(?:Nama\s*Pasien|Tanggal\s*Lahir|Jenis\s*Kelamin|Alamat|Umur)\b.*$",
        r"(?i)^\s*(?:Dokter\s*Pengirim|Unit\s*Asal|Ruangan|Penjamin)\b.*$",
        r"(?i)^\s*(?:Dicetak|Tanggal\s*Cetak|Print\s*Copy|Halaman|Page)\b.*$",
        r"(?i)^\s*(?:Telp|Telpon|Telepon|Tlp|Phone|Fax|Faks)\b.*$",
        r"(?i)^\s*(?:Bandung|Jawa\s*Barat)\b.*$",
    ]

    for idx, pat in enumerate(admin_line_patterns, start=1):
        text, n = re.subn(pat, "", text, flags=re.I | re.M)
        counts[f"RAD_ADMIN_LINE_REMOVED_{idx}"] = n

    # 4) Rapikan sisa label berulang dan baris kosong.
    text, n = re.subn(r"(?:\[TELEPON_RS\]\s*){2,}", "[TELEPON_RS]", text)
    counts["DOUBLE_PHONE_LABEL"] = n

    text, n = re.subn(r"(?:\[LOKASI_RS\]\s*){2,}", "[LOKASI_RS]", text)
    counts["DOUBLE_LOCATION_LABEL"] = n

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text, counts

def anonymize_staff_variants(text: str, variants):
    counts = {}
    for variant, role in variants:
        label = f"[{role}]"
        pat = flexible_name_pattern(variant)
        text, n = re.subn(pat, label, text, flags=re.I)
        counts[f"CSV_STAFF_{role}"] = counts.get(f"CSV_STAFF_{role}", 0) + n
    return text, counts

def anonymize_doctor_regex(text: str):
    counts = {}
    degree = r"(?:drg?\.?|Drg?\.?)"
    sp = r"(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)"
    honor = r"(?:H\.?|Hj\.?)"
    suffix = r"(?:\s*,?\s*(?:H\.?|Hj\.?|KIC|FINASIM|FIHA|M\.?Kes|MH\.?Kes|M\.?Sc|MM|SH|MH))*"
    def repl(m):
        old = m.group(0)
        role = infer_role(old)
        counts[role] = counts.get(role, 0) + 1
        pref = re.match(r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?", old.strip())
        if pref:
            return f"{pref.group(1)}: [{role}]"
        if re.search(r"(?i)diverifikasi\s+oleh", old):
            return re.sub(r"(?is)(diverifikasi\s+oleh\s*:?).*", rf"\1 [{role}]", old)
        if re.search(r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:", old):
            return re.sub(r"(?is)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:).*", rf"\1 [{role}]", old)
        return f"[{role}]"
    patterns = [
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-z.'` -]{{2,60}}(?:\n\s*[A-Z][A-Za-z.'` -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\. ?",
        rf"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\. ?\)?",
        rf"\b{degree}\s*[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?{sp}?{suffix}\. ?",
        rf"\b[A-Z][A-Za-z.'` -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\. ?",
        rf"(?m)^[A-Z][A-Za-z.'` -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-z.'` -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\. ?",
        rf"\([A-Z][A-Za-z.'` -]{{2,120}},\s*{honor}?\.?\s*{degree}\. ?\s*,?\s*{sp}?{suffix}\. ?\)",
        rf"\([A-Z][A-Za-z.'` -]{{2,120}},\s*\[DOKTER(?:_[A-Z_]+)?\]\)",
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])(?:\s*:\s*\d{{1,2}}\s+\w+\s+\d{{4}},?)?",
    ]
    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.I | re.S)
    return text, counts

def anonymize_cppt_provider_header(text: str):
    counts = {}
    date_pat = r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    time_pat = r"\d{1,2}:\d{2}(?::\d{2})?"
    def repl(m):
        header = m.group("header")
        block = m.group("block")
        soap = m.group("soap")
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        joined = " ".join(lines)
        low = joined.lower()
        if any(w in low for w in CLINICAL_STOPWORDS):
            return m.group(0)
        if len(lines) > 5 or len(joined) > 180:
            return m.group(0)
        role = "PPA"
        if re.search(r"\[APOTEKER\]|\bapt\.?\b|apoteker", joined, flags=re.I):
            role = "APOTEKER"
        elif re.search(r"\[PERAWAT\]|\bners\b|\bns\.?\b|\bamd\.?\s*kep\b|\bs\.?\s*kep\b", joined, flags=re.I):
            role = "PERAWAT"
        elif re.search(r"\[NUTRISIONIS\]|gizi|nutrisionis|dietisien", joined, flags=re.I):
            role = "NUTRISIONIS"
        elif re.search(r"\[FISIOTERAPIS\]|ftr|fisio|amd\.?\s*fis", joined, flags=re.I):
            role = "FISIOTERAPIS"
        elif re.search(r"\bdrg?\.?\b|\bdr\b|\bsp\.?|\[DOKTER", joined, flags=re.I):
            role = infer_role(joined)
        elif re.search(r"\[RADIOGRAFER\]|amd\.?\s*rad", joined, flags=re.I):
            role = "RADIOGRAFER"
        counts[f"CPPT_HEADER_{role}"] = counts.get(f"CPPT_HEADER_{role}", 0) + 1
        return f"{header}[{role}]\n{soap}"
    pat = rf"(?ms)(?P<header>^\s*{date_pat}\s*\n\s*{time_pat}\s*\n)(?P<block>(?:(?!^\s*[SOAP]\s*$).+\n){{1,5}})(?P<soap>^\s*[SOAP]\s*$)"
    text = re.sub(pat, repl, text)
    return text, counts

def anonymize_other_ppa(text: str):
    counts = {}
    patterns = [
        ("PERAWAT", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b"),
        ("PERAWAT", r"\[PERAWAT\]\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\b\. ?"),
        ("BIDAN", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("BIDAN", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b"),
        ("APOTEKER", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("APOTEKER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b"),
        ("APOTEKER", r"\[APOTEKER\]\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\b\. ?"),
        ("ANALIS_LAB", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("ANALIS_LAB", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b"),
        ("RADIOGRAFER", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        ("RADIOGRAFER", r"\[RADIOGRAFER\]\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b\. ?"),
        ("FISIOTERAPIS", r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("FISIOTERAPIS", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Fis\.?|A\.?Md\.?\s*Fis\.?|S\.?\s*Tr\.?\s*Fis\.?)\b"),
        ("FISIOTERAPIS", r"\[FISIOTERAPIS\]\s*[\.,]*\s*(?:Amd\.?\s*Fis\.?|A\.?Md\.?\s*Fis\.?|S\.?\s*Tr\.?\s*Fis\.?)\b\. ?"),
        ("NUTRISIONIS", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
    ]
    for role, pat in patterns:
        text, n = re.subn(pat, f"[{role}]", text, flags=re.I)
        counts[role] = counts.get(role, 0) + n
    return text, counts

def cleanup_context_and_labels(text: str):
    counts = {}
    staff = r"(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|FISIOTERAPIS|NUTRISIONIS|BIDAN|ANALIS_LAB)(?:_[A-Z_]+)?"
    cleanups = [
        ("colon_name_stafflabel", rf"(?m)^(\s*:\s*)[A-Z][A-Za-z.'` -]{{2,80}},?\s*(\[{staff}\])", r"\1\2"),
        ("dokter_label_plus_name_label", r"(?is)(Dokter\s*:\s*)\[DOKTER\]\s*\n\s*:\s*[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
        ("paren_name_before_stafflabel", rf"\(\s*(?:[A-Z][A-Za-z.'` -]{{2,120}},\s*)?(\[{staff}\])\s*\)", r"(\1)"),
        ("label_doctor_dr", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*drg?\. ?", r"\1"),
        ("label_doctor_sp", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?\. ?", r"\1"),
        ("label_perawat_ners", r"(\[PERAWAT\])\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\. ?", r"\1"),
        ("label_apoteker_apt", r"(\[APOTEKER\])\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\. ?", r"\1"),
        ("label_radio_amd", r"(\[RADIOGRAFER\])\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\. ?", r"\1"),
        ("label_fisio_amd", r"(\[FISIOTERAPIS\])\s*[\.,]*\s*(?:Amd\.?\s*Fis\.?|A\.?Md\.?\s*Fis\.?|S\.?\s*Tr\.?\s*Fis\.?)\. ?", r"\1"),
        ("print_copy_name_label", rf"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-z.'` -]{{2,80}},?\s*(\[{staff}\])", r"\1\2"),
    ]
    for key, pat, repl in cleanups:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n
    text, n = re.subn(rf"(\[{staff}\])(?:\s*,?\s*\1)+", r"\1", text, flags=re.I)
    counts["double_staff_label"] = n
    return text, counts

def detect_leftovers(text: str):
    patterns = {
        "possible_name_before_staff_label": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|FISIOTERAPIS|NUTRISIONIS|BIDAN|ANALIS_LAB)",
        "possible_comma_dr_leftover": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*(?:H\.?|Hj\.?)?\.?\s*drg?\. ?",
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ners_leftover": r"\b(?:Ns\.?|Ners)\b",
        "possible_apt_leftover": r"\b(?:Apt\.?|apt\.?)\b",
        "possible_amd_kep_leftover": r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
        "possible_amd_rad_leftover": r"\bA\.?Md\.?\s*Rad\.?\b|\bAmd\.?\s*Rad\.?\b",
        "possible_amd_fis_leftover": r"\bA\.?Md\.?\s*Fis\.?\b|\bAmd\.?\s*Fis\.?\b",
        "possible_print_copy_by_leftover": r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,80}",
    }
    return {k: len(re.findall(p, text, flags=re.I)) for k, p in patterns.items()}


LONG_FILE_THRESHOLD = 25000

def anonymize_doctor_regex_light(text: str):
    """
    Versi ringan untuk file panjang (terutama cppt_ranap).
    Tidak memakai regex multiline berat. Cukup membersihkan pola dokter/staf umum per baris.
    """
    counts = {}
    patterns = [
        ("DOKTER_UMUM", r"\bdr\.?\s+[A-Z][A-Za-z.'` -]{2,60}"),
        ("DOKTER_GIGI", r"\bdrg\.?\s+[A-Z][A-Za-z.'` -]{2,60}"),
        ("DOKTER_SPESIALIS", r"\b[A-Z][A-Za-z.'` -]{2,70}\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?"),
        ("DOKTER_SPESIALIS", r"\bdr\.?\s+[A-Z][A-Za-z.'` -]{2,70}\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?"),
        ("DOKTER", r"(?i)(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,70}"),
        ("DOKTER", r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,70}"),
    ]
    for role, pat in patterns:
        text, n = re.subn(pat, f"[{role}]", text, flags=re.I)
        counts[f"LIGHT_{role}"] = counts.get(f"LIGHT_{role}", 0) + n
    return text, counts


def anonymize_text_fast_long(text: str, staff_variants):
    """
    FAST MODE untuk file panjang yang sebelumnya stuck.
    Menghindari regex multiline berat dan staff CSV pass kedua.
    """
    text = normalize_text(text)

    text, c1 = anonymize_patient_rs(text)
    text, c1b = cleanup_radiology_footer_and_rs_phone(text)

    # Staff CSV satu kali saja. Ini cukup untuk mayoritas nama yang sudah ada di staff_doctors/staff_extra.
    text, c2 = anonymize_staff_variants(text, staff_variants)

    # Dokter regex ringan, bukan versi multiline berat.
    text, c3 = anonymize_doctor_regex_light(text)

    text, c4 = anonymize_other_ppa(text)
    # CPPT provider header dilewati untuk file panjang agar tidak stuck.
    c5 = {"CPPT_HEADER_SKIPPED_FAST_MODE": 1}
    text, c6 = cleanup_context_and_labels(text)
    text, c6b = cleanup_radiology_footer_and_rs_phone(text)

    # Jangan pass kedua staff CSV pada file panjang.
    c7 = {"CSV_STAFF_SECOND_PASS_SKIPPED_FAST_MODE": 1}
    text, c8 = anonymize_other_ppa(text)
    text, c9 = cleanup_context_and_labels(text)
    text, c9b = cleanup_radiology_footer_and_rs_phone(text)

    c10 = detect_leftovers(text)
    return text, merge_counts(c1, c1b, c2, c3, c4, c5, c6, c6b, c7, c8, c9, c9b, c10)

def anonymize_text(text: str, staff_variants):
    # File panjang, terutama cppt_ranap, memakai fast mode agar tidak stuck.
    if len(text) > LONG_FILE_THRESHOLD:
        return anonymize_text_fast_long(text, staff_variants)

    text = normalize_text(text)

    text, c1 = anonymize_patient_rs(text)
    # Tambahan: bersihkan sisa header/footer radiologi dan nomor telepon RS lebih awal
    text, c1b = cleanup_radiology_footer_and_rs_phone(text)

    text, c2 = anonymize_staff_variants(text, staff_variants)
    text, c3 = anonymize_doctor_regex(text)
    text, c4 = anonymize_other_ppa(text)
    text, c5 = anonymize_cppt_provider_header(text)
    text, c6 = cleanup_context_and_labels(text)

    # Tambahan: ulangi setelah label dokter/PPA karena beberapa footer baru terlihat setelah cleanup
    text, c6b = cleanup_radiology_footer_and_rs_phone(text)

    # Untuk file kecil, pass kedua tetap boleh; untuk file panjang sudah diskip di fast mode.
    text, c7 = anonymize_staff_variants(text, staff_variants)
    text, c8 = anonymize_other_ppa(text)
    text, c9 = cleanup_context_and_labels(text)

    # Tambahan akhir untuk sisa yang masih menempel
    text, c9b = cleanup_radiology_footer_and_rs_phone(text)

    c10 = detect_leftovers(text)
    return text, merge_counts(c1, c1b, c2, c3, c4, c5, c6, c6b, c7, c8, c9, c9b, c10)

def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)
    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")
    staff_variants = load_all_staff_variants()
    txt_files = sorted(IN_DIR.rglob("*.txt"))
    if not txt_files:
        print(f"Tidak ada file .txt di {IN_DIR} maupun subfoldernya.")
        return
    print(f"Total file .txt ditemukan: {len(txt_files)}")
    rows = []
    for i, fp in enumerate(txt_files, start=1):
        rel = fp.relative_to(IN_DIR)
        out = OUT_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n[{i}/{len(txt_files)}] Mulai: {rel}", flush=True)
        raw = fp.read_text(encoding="utf-8", errors="ignore")
        print(f"Ukuran: {len(raw)} karakter", flush=True)
        if len(raw) > LONG_FILE_THRESHOLD:
            print("Mode: FAST untuk file panjang", flush=True)
        else:
            print("Mode: FULL", flush=True)
        anon, counts = anonymize_text(raw, staff_variants)
        out.write_text(anon, encoding="utf-8")
        print(f"Selesai: {rel}", flush=True)
        row = {
            "patient_folder": rel.parts[0] if len(rel.parts) > 1 else "",
            "file": str(rel),
            "output_file": str(out.relative_to(BASE_DIR)),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        row.update(counts)
        rows.append(row)
        print(f"Anonimisasi: {rel}")
        print(f"Berhasil disimpan ke: {out}")
    keys = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)
    report = REPORT_DIR / "anonymization_report.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print("\nSelesai.")
    print(f"Hasil anonim: {OUT_DIR}")
    print(f"Report audit: {report}")
    print("\nCek manual dengan Ctrl+F:")
    print("dr | Dr | Sp. | Ners | Apt | Amd.Kep | Amd.Rad | Amd.Fis | Print copy by")
    print("Kalau masih ada nama staf bocor, masukkan ke staff_extra.csv lalu jalankan ulang.")

if __name__ == "__main__":
    main()
