from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# SCRIPT ANONIMISASI TAHAP 3 - LEAKFIX RECURSIVE
#
# Perbaikan dari tahap 2:
# - Membaca semua .txt dalam subfolder pasien: 02_text_extracted/STROKE_001/*.txt
# - Mempertahankan struktur subfolder di 03_anonymized_text
# - Lebih agresif menangkap format dokter/PPA yang bocor:
#     Nama,
#     dr.
#
#     Nama
#     Putri, dr
#
#     Nama
#     Santoso, dr, Sp.N
#
#     Rahmawati,dr, Sp.PK.
#     (Nama, H. dr., Sp.Rad., MH.Kes.)
#     Print copy by: Nama, dr: tanggal
#     [RADIOGRAFER], Amd.Rad.
#
# Jalankan dari folder 06_scripts:
#   python anonymize_stage3_leakfix_recursive.py
#
# Letakkan staff_doctors.csv di folder yang sama dengan script.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"

DOCTOR_CSV = Path(__file__).resolve().parent / "staff_doctors.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# MAPPING SPESIALIS / SUBSPESIALIS
# ============================================================

SPECIALIST_MAP = {
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",

    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI",
    "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",

    "sp.pd": "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.pd-kger": "DOKTER_SUBSPESIALIS_GERIATRI",
    "sp.pd-kgh": "DOKTER_SUBSPESIALIS_GINJAL_HIPERTENSI",
    "sp.pd-kgeh": "DOKTER_SUBSPESIALIS_GASTROENTERO_HEPATOLOGI",
    "sp.pd-khom": "DOKTER_SUBSPESIALIS_HEMATO_ONKOLOGI",
    "sp.pd-kai": "DOKTER_SUBSPESIALIS_ALERGI_IMUNOLOGI",
    "sp.pd-kpsi": "DOKTER_SUBSPESIALIS_PSIKOSOMATIK",
    "sp.pd-kpti": "DOKTER_SUBSPESIALIS_PENYAKIT_TROPIS_INFEKSI",
    "sp.pd-kemd": "DOKTER_SUBSPESIALIS_ENDOKRIN_METABOLIK_DIABETES",
    "sp.pd-kr": "DOKTER_SUBSPESIALIS_REUMATOLOGI",
    "sp.pd-kkv": "DOKTER_SUBSPESIALIS_KARDIOVASKULAR",

    "sp.jp": "DOKTER_SPESIALIS_JANTUNG",
    "sp.jp(k)": "DOKTER_SUBSPESIALIS_JANTUNG",

    "sp.an": "DOKTER_SPESIALIS_ANESTESI",
    "sp.an-kic": "DOKTER_SUBSPESIALIS_INTENSIVE_CARE",

    "sp.b": "DOKTER_SPESIALIS_BEDAH",
    "sp.btkv": "DOKTER_SPESIALIS_BEDAH_TORAKS_KARDIOVASKULAR",
    "sp.bs": "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot": "DOKTER_SPESIALIS_ORTOPEDI",
    "sp.u": "DOKTER_SPESIALIS_UROLOGI",

    "sp.a": "DOKTER_SPESIALIS_ANAK",
    "sp.a(k)": "DOKTER_SUBSPESIALIS_ANAK",

    "sp.og": "DOKTER_SPESIALIS_OBGYN",
    "sp.og(k)": "DOKTER_SUBSPESIALIS_OBGYN",

    "sp.p": "DOKTER_SPESIALIS_PARU",
    "sp.kfr": "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj": "DOKTER_SPESIALIS_KEDOKTERAN_JIWA",
    "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m": "DOKTER_SPESIALIS_MATA",
    "sp.kk": "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv": "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",
}

HOSPITAL_NAMES = [
    # Tambahkan bila perlu:
    # "RS AL ISLAM BANDUNG",
    # "RUMAH SAKIT AL ISLAM BANDUNG",
]

# ============================================================
# UTILITAS
# ============================================================

def normalize_text_basic(text: str) -> str:
    # Jangan hilangkan newline, karena newline penting untuk deteksi nama lalu dr di baris berikutnya.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def safe_regex_name(name: str) -> str:
    name = name.strip()
    escaped = re.escape(name)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\.", r"\.?")
    return escaped


def compact_degree(s: str) -> str:
    s = s.lower()
    s = s.replace(" ", "")
    s = s.replace(",", "")
    s = s.strip(".")
    return s


def infer_doctor_role_from_text(text: str) -> str:
    lower = text.lower()
    lower = re.sub(r"\s+", " ", lower)

    # Normalisasi ringan agar Sp. PD - KKV tetap terbaca.
    normalized = lower.replace(" ", "")
    normalized = normalized.replace(",", "")
    normalized = normalized.strip()

    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        d = degree.lower().replace(" ", "")
        if d in normalized:
            return role

    if re.search(r"\bsp\.?\s*[a-z]", lower, flags=re.IGNORECASE):
        return "DOKTER_SPESIALIS"

    if re.search(r"\bdrg\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_GIGI"

    if re.search(r"\bdr\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_UMUM"

    return "DOKTER"


def load_doctor_names(csv_path: Path):
    doctors = []
    if not csv_path.exists():
        print(f"PERINGATAN: staff_doctors.csv tidak ditemukan di {csv_path}")
        print("Script tetap jalan, tapi nama dokter hanya ditangkap dari pola umum.")
        return doctors

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip()
            if not name:
                continue
            if not role:
                role = infer_doctor_role_from_text(name)
            doctors.append((name, role))

    print(f"Daftar dokter terbaca: {len(doctors)} nama")
    return doctors


def merge_counts(*dicts):
    merged = {}
    for d in dicts:
        for k, v in d.items():
            merged[k] = merged.get(k, 0) + v
    return merged


# ============================================================
# ANONIMISASI IDENTITAS PASIEN / KONTAK / RS
# ============================================================

def anonymize_patient_identifiers(text: str):
    patterns = [
        ("NO_RM", r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_RM]"),
        ("NIK", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", "[NIK]"),
        ("NIK_16_DIGIT", r"\b\d{16}\b", "[NIK]"),
        ("NO_HP", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", "[NO_HP]"),
        ("EMAIL", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        ("NAMA_PASIEN", r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Nama Pasien: [PASIEN]"),
        ("ALAMAT", r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}", "Alamat: [ALAMAT]"),
    ]

    counts = {}
    for key, pattern, repl in patterns:
        text, n = re.subn(pattern, repl, text, flags=re.IGNORECASE)
        counts[key] = counts.get(key, 0) + n

    total_hosp = 0
    for name in HOSPITAL_NAMES:
        if name.strip():
            text, n = re.subn(safe_regex_name(name), "[RUMAH_SAKIT]", text, flags=re.IGNORECASE)
            total_hosp += n

    generic_hosp = [
        (r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", "[RUMAH_SAKIT]"),
        (r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]"),
        (r"\b(?:Telp\.?|Telepon|Fax)\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]
    for pattern, repl in generic_hosp:
        text, n = re.subn(pattern, repl, text, flags=re.IGNORECASE)
        total_hosp += n

    counts["RUMAH_SAKIT_ALAMAT_RS"] = total_hosp
    return text, counts


# ============================================================
# ANONIMISASI DOKTER
# ============================================================

def anonymize_doctors_from_csv(text: str, doctors):
    counts = {}

    for name, role in sorted(doctors, key=lambda x: len(x[0]), reverse=True):
        label = f"[{role}]"
        pattern = safe_regex_name(name)
        text, n = re.subn(pattern, label, text, flags=re.IGNORECASE)
        counts[role] = counts.get(role, 0) + n

    return text, counts


def anonymize_doctor_patterns_aggressive(text: str):
    counts = {}

    def repl_doctor(match):
        original = match.group(0)
        role = infer_doctor_role_from_text(original)
        counts[role] = counts.get(role, 0) + 1

        # Pertahankan prefix penting.
        prefix_match = re.match(
            r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*",
            original.strip()
        )
        if prefix_match:
            return f"{prefix_match.group(1)}: [{role}]"

        # Pertahankan konteks print copy by.
        if re.search(r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:", original):
            return re.sub(r"(?is)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:).*", rf"\1 [{role}]", original)

        return f"[{role}]"

    # Format satu baris: dr. Nama Sp.N / Nama, dr, Sp.N / Nama,dr, Sp.PK.
    patterns = [
        # Prefix + nama/gelar
        r"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:drg?\.?\s*)?[A-Z][A-Za-z.'` -]{2,80}(?:,\s*)?(?:drg?\.?)?(?:,\s*)?(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?(?:\s*,?\s*(?:KIC|FINASIM|FIHA|M\.?Kes|M\.?Sc|MM|MH\.?Kes|SH|MH))*\.?\)?",

        # dr. Nama ...
        r"\bdrg?\.?\s*[A-Z][A-Za-z.'` -]{2,80}(?:,\s*)?(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?(?:\s*,?\s*(?:KIC|FINASIM|FIHA|M\.?Kes|M\.?Sc|MM|MH\.?Kes|SH|MH))*\.?",

        # Nama, dr / Nama, dr, Sp.N / Nama,dr, Sp.PK.
        r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*drg?\.?(?:\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?(?:\s*,?\s*(?:KIC|FINASIM|FIHA|M\.?Kes|M\.?Sc|MM|MH\.?Kes|SH|MH))*\.?",

        # Dalam kurung: (Nama, H. dr., Sp.Rad., MH.Kes.)
        r"\([A-Z][A-Za-z.'` -]{2,100},\s*(?:H\.?\s*)?drg?\.?\s*,?\s*(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?(?:\s*,?\s*(?:KIC|FINASIM|FIHA|M\.?Kes|M\.?Sc|MM|MH\.?Kes|SH|MH))*\.?\)",

        # Print copy by: Nama, dr / Nama, [DOKTER_UMUM]
        r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:drg?\.?|\[DOKTER(?:_[A-Z_]+)?\])(?:\s*:\s*\d{1,2}\s+\w+\s+\d{4},?)?",
    ]

    for pattern in patterns:
        text = re.sub(pattern, repl_doctor, text, flags=re.IGNORECASE | re.DOTALL)

    return text, counts


def anonymize_splitline_doctors(text: str):
    """
    Menangkap pola nama di baris sebelum gelar:
      Mugi Rahayu,
      dr.

      Nogita Ramansa
      Putri, dr

      Dianathasari
      Santoso, dr, Sp.N
    """
    counts = {}

    def repl_split(match):
        original = match.group(0)
        role = infer_doctor_role_from_text(original)
        counts[role] = counts.get(role, 0) + 1
        return f"[{role}]"

    # 2 baris nama + gelar dokter
    patterns = [
        # Nama,
        # dr. / dr, Sp.N
        r"(?m)^[A-Z][A-Za-z.'` -]{2,60},?\s*\n\s*drg?\.?(?:\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?\.?",

        # Nama
        # NamaBelakang, dr / dr, Sp.N
        r"(?m)^[A-Z][A-Za-z.'` -]{2,60}\s*\n\s*[A-Z][A-Za-z.'` -]{2,60}\s*,\s*drg?\.?(?:\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?\.?",

        # Nama
        # NamaBelakang
        # dr.  (lebih jarang)
        r"(?m)^[A-Z][A-Za-z.'` -]{2,60}\s*\n\s*[A-Z][A-Za-z.'` -]{2,60}\s*\n\s*drg?\.?(?:\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?\.?",
    ]

    for pattern in patterns:
        text = re.sub(pattern, repl_split, text, flags=re.IGNORECASE)

    return text, counts


# ============================================================
# ANONIMISASI PPA NON-DOKTER
# ============================================================

def anonymize_other_ppa(text: str):
    counts = {}

    role_patterns = [
        # Perawat
        ("PERAWAT", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b"),
        ("PERAWAT", r"\b(?:Perawat|Petugas\s+Perawat|Nama\s+Perawat)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),

        # Bidan
        ("BIDAN", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("BIDAN", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b"),

        # Apoteker
        ("APOTEKER", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("APOTEKER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b"),
        ("APOTEKER", r"\b(?:Farmasi|Petugas\s+Farmasi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),

        # Lab
        ("ANALIS_LAB", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("ANALIS_LAB", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b"),

        # Radiografer / radiologi
        ("RADIOGRAFER", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        # Bersihkan sisa gelar setelah label radiografer
        ("RADIOGRAFER", r"\[RADIOGRAFER\]\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),

        # Fisioterapis
        ("FISIOTERAPIS", r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),

        # Gizi
        ("NUTRISIONIS", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
    ]

    for role, pattern in role_patterns:
        def repl(match, role=role):
            counts[role] = counts.get(role, 0) + 1
            return f"[{role}]"

        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    return text, counts


# ============================================================
# POST-PROCESSING SISA GELAR / LABEL DOBEL
# ============================================================

def cleanup_leftover_degrees(text: str):
    counts = {}

    cleanup_patterns = [
        ("SISA_DR_SETELAH_LABEL", r"\[DOKTER(?:_[A-Z_]+)?\]\s*,?\s*drg?\.?", "[DOKTER]"),
        ("SISA_SP_SETELAH_LABEL", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?\.?", r"\1"),
        ("SISA_AMD_RAD_SETELAH_LABEL", r"(\[RADIOGRAFER\])\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\.?", r"\1"),
        ("SISA_AMD_KEP_SETELAH_LABEL", r"(\[PERAWAT\])\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|S\.?\s*Kep\.?|Ners)\.?", r"\1"),
    ]

    for key, pattern, repl in cleanup_patterns:
        text, n = re.subn(pattern, repl, text, flags=re.IGNORECASE)
        counts[key] = n

    # Rapikan label dokter umum yang tertulis "Dokter: [DOKTER]" kalau tanpa role.
    text = re.sub(r"(?i)\bDokter\s*:\s*\[DOKTER\]", "Dokter: [DOKTER]", text)

    return text, counts


# ============================================================
# AUDIT LEFTOVER
# ============================================================

def detect_possible_leftovers(text: str):
    suspicious_patterns = {
        "possible_name_before_dr_leftover": r"(?m)^[A-Z][A-Za-z.'` -]{2,60},?\s*\n\s*drg?\.?",
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_comma_dr_leftover": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*drg?\.?",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ns_leftover": r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_amd_kep_leftover": r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
        "possible_amd_rad_leftover": r"\bA\.?Md\.?\s*Rad\.?\b|\bAmd\.?\s*Rad\.?\b",
        "possible_bidan_leftover": r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_print_copy_by_leftover": r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,80}",
    }

    result = {}
    for key, pattern in suspicious_patterns.items():
        result[key] = len(re.findall(pattern, text, flags=re.IGNORECASE))
    return result


def anonymize_text(text: str, doctors):
    text = normalize_text_basic(text)

    text, patient_counts = anonymize_patient_identifiers(text)

    # Urutan penting:
    # 1 CSV dokter
    # 2 split-line dokter
    # 3 pola dokter agresif
    # 4 PPA
    # 5 cleanup sisa gelar
    text, csv_counts = anonymize_doctors_from_csv(text, doctors)
    text, split_counts = anonymize_splitline_doctors(text)
    text, doctor_counts = anonymize_doctor_patterns_aggressive(text)
    text, ppa_counts = anonymize_other_ppa(text)
    text, cleanup_counts = cleanup_leftover_degrees(text)

    leftovers = detect_possible_leftovers(text)

    counts = merge_counts(
        patient_counts,
        csv_counts,
        split_counts,
        doctor_counts,
        ppa_counts,
        cleanup_counts,
        leftovers,
    )
    return text, counts


# ============================================================
# MAIN
# ============================================================

def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)

    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    doctors = load_doctor_names(DOCTOR_CSV)

    txt_files = sorted(IN_DIR.rglob("*.txt"))

    if not txt_files:
        print(f"Tidak ada file .txt di {IN_DIR} maupun subfoldernya.")
        return

    print(f"Total file .txt ditemukan: {len(txt_files)}")

    report_rows = []

    for file_path in txt_files:
        relative_path = file_path.relative_to(IN_DIR)
        out_path = OUT_DIR / relative_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        anonymized, counts = anonymize_text(raw, doctors)
        out_path.write_text(anonymized, encoding="utf-8")

        row = {
            "patient_folder": relative_path.parts[0] if len(relative_path.parts) > 1 else "",
            "file": str(relative_path),
            "output_file": str(out_path.relative_to(BASE_DIR)),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        row.update(counts)
        report_rows.append(row)

        print(f"Anonimisasi: {relative_path}")
        print(f"Berhasil disimpan ke: {out_path}")

    all_keys = []
    for row in report_rows:
        for key in row.keys():
            if key not in all_keys:
                all_keys.append(key)

    report_path = REPORT_DIR / "anonymization_report.csv"
    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(report_rows)

    print("\nSelesai.")
    print(f"Semua file hasil anonim ada di folder: {OUT_DIR}")
    print(f"Report audit ada di: {report_path}")
    print("\nPENTING:")
    print("- Cek kolom possible_*_leftover di report.")
    print("- Kalau masih ada angka, buka file terkait dan cek manual dengan Ctrl+F.")
    print("- Cari: dr, Sp., Amd.Kep, Amd.Rad, Ns., Ners, Print copy by.")


if __name__ == "__main__":
    main()
