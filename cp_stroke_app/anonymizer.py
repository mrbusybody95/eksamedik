
from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# ANONIMISASI STAGE 5 - STAFF CSV FUZZY RECURSIVE
#
# Fokus perbaikan:
# 1. Tetap membaca subfolder:
#    02_text_extracted/STROKE_001/*.txt
#
# 2. Memakai staff_doctors.csv bukan hanya exact full name,
#    tapi juga varian nama:
#      dr. Adi Maulana Sp.Rad
#      Adi Maulana
#      Adi Maulana S
#      Maulana Adi
#      Adi ... Maulana
#
# 3. Membersihkan pola sisa seperti:
#      : Mugi Rahayu, [DOKTER_UMUM]
#      Sri Yujianingsih
#      [APOTEKER]Apt.
#      Riki Septian
#      [PERAWAT]., Ners
#      (Adi Maulana S, [DOKTER_SPESIALIS_RADIOLOGI])
#
# Jalankan dari folder 06_scripts:
#   python anonymize_stage5_staff_csv_fuzzy_recursive.py
#
# File wajib:
#   06_scripts/staff_doctors.csv
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"
DOCTOR_CSV = Path(__file__).resolve().parent / "staff_doctors.csv"

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

# Tambahkan nama RS bila perlu
HOSPITAL_NAMES = [
    # "RS AL ISLAM BANDUNG",
    # "RUMAH SAKIT AL ISLAM BANDUNG",
]

# Kata umum klinis yang tidak boleh dianggap nama
CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning", "sesuai", "observasi",
    "pasien", "nyeri", "lemah", "sesak", "muntah", "demam", "stroke", "infark",
    "pneumonia", "hematemesis", "anamnesis", "pemeriksaan", "tekanan", "darah",
    "suhu", "spo2", "gcs", "ews", "hasil", "nilai", "rujukan", "satuan", "klinik",
    "poliklinik", "penjamin", "alamat", "umur", "tgl", "lahir", "perempuan", "laki",
    "hasil", "nilai", "satuan", "hematologi", "cell", "counter", "hemoglobin",
    "leukosit", "trigliserida", "foto", "thorax", "kesan", "cor", "pulmo",
}

HONORIFICS = {"h", "hj", "haji", "hajah"}
TITLE_WORDS = {
    "dr", "drg", "sp", "spd", "spn", "sps", "sprad", "sppk", "sppd", "spjp",
    "mkes", "mhkes", "mm", "msc", "phd", "finasim", "fiha", "kic",
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
    """
    Buang gelar dokter/spesialis dari nama.
    """
    x = name.strip()
    x = re.sub(r"(?i)\bdrg?\.?\s*", " ", x)
    x = re.sub(r"(?i)\bSp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?", " ", x)
    x = re.sub(r"(?i)\b(?:M\.?Kes|MH\.?Kes|M\.?Sc|MM|PhD|FINASIM|FIHA|KIC|SH|MH)\b\.?", " ", x)
    x = re.sub(r"(?i)\b(?:H\.?|Hj\.?|Haji|Hajah)\b\.?", " ", x)
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
    """
    Pattern nama fleksibel:
    spasi di CSV dapat cocok dengan spasi/newline/koma/titik.
    """
    parts = [re.escape(p) for p in variant.split() if p.strip()]
    sep = r"(?:\s|,|\.)+"
    return r"\b" + sep.join(parts) + r"\b"

def build_variants_from_tokens(toks):
    """
    Buat varian dari nama:
    - full name
    - first + second
    - first + last
    - first + second + last
    - first + middle + last
    Hanya untuk token >=2 agar tidak menghapus kata umum.
    """
    variants = set()
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

    # Hindari varian terlalu pendek/berisiko
    safe = set()
    for v in variants:
        words = v.split()
        if len(words) < 2:
            continue
        if len(v) < 7:
            continue
        low = v.lower()
        if any(w in CLINICAL_STOPWORDS for w in low.split()):
            continue
        safe.add(v)
    return safe

def load_staff_variants():
    """
    Membaca staff_doctors.csv lalu membuat banyak pattern varian.
    Return list of (variant, role)
    """
    variants = []
    if not DOCTOR_CSV.exists():
        print(f"PERINGATAN: staff_doctors.csv tidak ditemukan: {DOCTOR_CSV}")
        return variants

    with DOCTOR_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or infer_role(name)
            if not name:
                continue
            toks = tokens_from_name(name)
            for v in build_variants_from_tokens(toks):
                variants.append((v, role))

    # Deduplicate, long variants first
    seen = set()
    unique = []
    for v, r in sorted(variants, key=lambda x: len(x[0]), reverse=True):
        key = (v.lower(), r)
        if key not in seen:
            seen.add(key)
            unique.append((v, r))

    print(f"Varian nama dokter dari CSV terbaca: {len(unique)}")
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

def anonymize_staff_csv_fuzzy(text: str, variants):
    """
    Hapus semua varian nama dokter dari CSV.
    Ini yang kamu minta: deteksi salah satu/varian kata nama dokter.
    """
    counts = {}
    for variant, role in variants:
        label = f"[{role}]"
        pat = flexible_name_pattern(variant)
        text, n = re.subn(pat, label, text, flags=re.I)
        counts[f"CSV_FUZZY_{role}"] = counts.get(f"CSV_FUZZY_{role}", 0) + n
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

        pref = re.match(
            r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?",
            old.strip()
        )
        if pref:
            return f"{pref.group(1)}: [{role}]"
        if re.search(r"(?i)diverifikasi\s+oleh", old):
            return re.sub(r"(?is)(diverifikasi\s+oleh\s*:?).*", rf"\1 [{role}]", old)
        if re.search(r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:", old):
            return re.sub(r"(?is)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:).*", rf"\1 [{role}]", old)
        return f"[{role}]"

    patterns = [
        # Diverifikasi oleh: nama ... dr sp
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-z.'` -]{{2,60}}(?:\n\s*[A-Z][A-Za-z.'` -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\.?",

        # Prefix dokter
        rf"\b(?:DPJP|DPJ[Pp]|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\.?\)?",

        # dr Nama
        rf"\b{degree}\s*[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?{sp}?{suffix}\.?",

        # Nama, dr / Nama, Dr., Sp.S
        rf"\b[A-Z][A-Za-z.'` -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",

        # Multi-line nama lalu Dr/Sp
        rf"(?m)^[A-Z][A-Za-z.'` -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-z.'` -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",

        # Dalam kurung tanda tangan dokter
        rf"\([A-Z][A-Za-z.'` -]{{2,120}},\s*{honor}?\.?\s*{degree}\.?\s*,?\s*{sp}?{suffix}\.?\)",

        # Dalam kurung: nama sudah jadi [DOKTER...], tapi masih ada nama/gelar lain
        rf"\([A-Z][A-Za-z.'` -]{{2,120}},\s*\[DOKTER(?:_[A-Z_]+)?\]\)",

        # Print copy by
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])(?:\s*:\s*\d{{1,2}}\s+\w+\s+\d{{4}},?)?",
    ]

    for pat in patterns:
        text = re.sub(pat, repl, text, flags=re.I | re.S)

    return text, counts

def anonymize_cppt_provider_header(text: str):
    """
    Hapus provider CPPT setelah tanggal-jam dan sebelum S/O/A/P.
    Ini menangkap:
      07-05-2026
      09:32:00
      Sri Yujianingsih
      [APOTEKER]Apt.
      S
    atau:
      09-05-2026
      14:47:00
      Muhamad Jihan
      Febi
      [PERAWAT]., Ners
      S
    """
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

        counts[f"CPPT_HEADER_{role}"] = counts.get(f"CPPT_HEADER_{role}", 0) + 1
        return f"{header}[{role}]\n{soap}"

    pat = rf"(?ms)(?P<header>^\s*{date_pat}\s*\n\s*{time_pat}\s*\n)(?P<block>(?:(?!^\s*[SOAP]\s*$).+\n){{1,5}})(?P<soap>^\s*[SOAP]\s*$)"
    text = re.sub(pat, repl, text)
    return text, counts

def anonymize_other_ppa(text: str):
    counts = {}
    patterns = [
        # Perawat
        ("PERAWAT", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b"),
        ("PERAWAT", r"\[PERAWAT\]\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\b\.?"),

        # Bidan
        ("BIDAN", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("BIDAN", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b"),

        # Apoteker
        ("APOTEKER", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("APOTEKER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b"),
        ("APOTEKER", r"\[APOTEKER\]\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\b\.?"),

        # Lab
        ("ANALIS_LAB", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("ANALIS_LAB", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b"),

        # Radiografer
        ("RADIOGRAFER", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        ("RADIOGRAFER", r"\[RADIOGRAFER\]\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b\.?"),

        # Gizi/fisio
        ("FISIOTERAPIS", r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("NUTRISIONIS", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
    ]
    for role, pat in patterns:
        text, n = re.subn(pat, f"[{role}]", text, flags=re.I)
        counts[role] = counts.get(role, 0) + n
    return text, counts

def cleanup_context_and_labels(text: str):
    counts = {}
    cleanups = [
        # : Nama, [DOKTER_UMUM] -> : [DOKTER_UMUM]
        ("colon_name_doctorlabel", r"(?m)^(\s*:\s*)[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),

        # Dokter: [DOKTER]\n: Nama, [DOKTER_UMUM] -> Dokter: [DOKTER_UMUM]
        ("dokter_label_plus_name_label", r"(?is)(Dokter\s*:\s*)\[DOKTER\]\s*\n\s*:\s*[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),

        # ([DOKTER], [DOKTER_SPESIALIS]) / (Nama, [DOKTER_SPESIALIS]) -> ([DOKTER_SPESIALIS])
        ("paren_name_before_doctorlabel", r"\(\s*(?:[A-Z][A-Za-z.'` -]{2,120},\s*)?(\[DOKTER(?:_[A-Z_]+)?\])\s*\)", r"(\1)"),

        # label + sisa gelar
        ("label_doctor_dr", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*drg?\.?", r"\1"),
        ("label_doctor_sp", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?\.?", r"\1"),
        ("label_perawat_ners", r"(\[PERAWAT\])\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\.?", r"\1"),
        ("label_apoteker_apt", r"(\[APOTEKER\])\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\.?", r"\1"),
        ("label_radio_amd", r"(\[RADIOGRAFER\])\s*[\.,]*\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\.?", r"\1"),

        # Print copy by : nama, [DOKTER] -> Print copy by : [DOKTER]
        ("print_copy_name_label", r"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
    ]
    for key, pat, repl in cleanups:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = n

    # Hilangkan label ganda persis
    for role in ["DOKTER", "PERAWAT", "APOTEKER", "RADIOGRAFER", "NUTRISIONIS"]:
        pat = rf"(\[{role}(?:_[A-Z_]+)?\])(?:\s*,?\s*\1)+"
        text, n = re.subn(pat, r"\1", text, flags=re.I)
        counts[f"double_{role}"] = n

    return text, counts

def detect_leftovers(text: str):
    patterns = {
        "possible_csv_name_like_before_label": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*\[(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|NUTRISIONIS)",
        "possible_comma_dr_leftover": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*(?:H\.?|Hj\.?)?\.?\s*drg?\.?",
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ners_leftover": r"\b(?:Ns\.?|Ners)\b",
        "possible_apt_leftover": r"\b(?:Apt\.?|apt\.?)\b",
        "possible_amd_kep_leftover": r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
        "possible_amd_rad_leftover": r"\bA\.?Md\.?\s*Rad\.?\b|\bAmd\.?\s*Rad\.?\b",
        "possible_print_copy_by_leftover": r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,80}",
    }
    return {k: len(re.findall(p, text, flags=re.I)) for k, p in patterns.items()}

def anonymize_text(text: str, variants=None):
    if variants is None:
        variants = load_staff_variants()
    text = normalize_text(text)

    # Urutan sengaja:
    # 1 identitas pasien/RS
    # 2 fuzzy dari CSV dokter
    # 3 regex dokter umum
    # 4 PPA umum
    # 5 header CPPT
    # 6 cleanup
    # 7 ulang fuzzy + cleanup, karena kadang label baru membuka sisa pola
    text, c1 = anonymize_patient_rs(text)
    text, c2 = anonymize_staff_csv_fuzzy(text, variants)
    text, c3 = anonymize_doctor_regex(text)
    text, c4 = anonymize_other_ppa(text)
    text, c5 = anonymize_cppt_provider_header(text)
    text, c6 = cleanup_context_and_labels(text)
    text, c7 = anonymize_staff_csv_fuzzy(text, variants)
    text, c8 = cleanup_context_and_labels(text)
    c9 = detect_leftovers(text)

    return text, merge_counts(c1, c2, c3, c4, c5, c6, c7, c8, c9)


def process_folder(input_folder, output_folder):
    """
    Dipakai oleh app.py / Streamlit.
    Membaca semua file .txt secara recursive dari input_folder,
    menulis hasil anonim ke output_folder dengan struktur subfolder yang sama,
    lalu mengembalikan daftar ringkasan file yang diproses.
    """
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    if not input_folder.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {input_folder}")

    variants = load_staff_variants()
    txt_files = sorted(input_folder.rglob("*.txt"))

    processed = []
    rows = []

    for fp in txt_files:
        rel = fp.relative_to(input_folder)
        out = output_folder / rel
        out.parent.mkdir(parents=True, exist_ok=True)

        raw = fp.read_text(encoding="utf-8", errors="ignore")
        anon, counts = anonymize_text(raw, variants)
        out.write_text(anon, encoding="utf-8")

        item = {
            "patient_folder": rel.parts[0] if len(rel.parts) > 1 else "",
            "file": str(rel),
            "output_file": str(out),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        item.update(counts)
        rows.append(item)
        processed.append(str(rel))

    # Buat report CSV di output folder agar mudah diunduh dari aplikasi
    if rows:
        keys = []
        for row in rows:
            for k in row:
                if k not in keys:
                    keys.append(k)

        report = output_folder / "anonymization_report.csv"
        with report.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)

    return processed

def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)

    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    variants = load_staff_variants()
    txt_files = sorted(IN_DIR.rglob("*.txt"))

    if not txt_files:
        print(f"Tidak ada file .txt di {IN_DIR} maupun subfoldernya.")
        return

    print(f"Total file .txt ditemukan: {len(txt_files)}")
    rows = []

    for fp in txt_files:
        rel = fp.relative_to(IN_DIR)
        out = OUT_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)

        raw = fp.read_text(encoding="utf-8", errors="ignore")
        anon, counts = anonymize_text(raw, variants)
        out.write_text(anon, encoding="utf-8")

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
    print("dr | Dr | Sp. | Ners | Apt | Amd.Kep | Amd.Rad | Print copy by")
    print("Cek juga kolom possible_*_leftover di anonymization_report.csv")

if __name__ == "__main__":
    main()
