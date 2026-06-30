from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# SCRIPT ANONIMISASI TAHAP 2 - RECURSIVE SUBFOLDER VERSION
# Sesuai struktur:
#
# project/
# ├── 02_text_extracted/
# │   └── STROKE_001/
# │       ├── cppt igd.txt
# │       ├── cppt ranap.txt
# │       ├── lab 2.txt
# │       ├── lab igd.txt
# │       ├── rad 1.txt
# │       ├── rad 2.txt
# │       └── resume.txt
# ├── 03_anonymized_text/
# ├── 04_anonymization_report/
# └── 06_scripts/
#     ├── anonymize_stage2_role_ppa_recursive.py
#     └── staff_doctors.csv
#
# Output:
# 03_anonymized_text/STROKE_001/cppt igd.txt
# 03_anonymized_text/STROKE_001/cppt ranap.txt
# dst.
#
# Jalankan dari folder 06_scripts:
#   python anonymize_stage2_role_ppa_recursive.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"

DOCTOR_CSV = Path(__file__).resolve().parent / "staff_doctors.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# MAPPING DOKTER SPESIALIS / SUBSPESIALIS
# Tambahkan sesuai kebutuhan.
# ============================================================

SPECIALIST_MAP = {
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI",

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

    "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",
}

# ============================================================
# POLA PPA NON-DOKTER
# ============================================================

ROLE_PATTERNS = [
    # Perawat / Ners / Amd.Kep
    (r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}", "[PERAWAT]"),
    (r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b", "[PERAWAT]"),
    (r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|AMK|A\.?Md\.?\s*Kep\.?)\b", "[PERAWAT]"),
    (r"\b(?:Perawat|Petugas\s+Perawat|Nama\s+Perawat)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Perawat: [PERAWAT]"),

    # Bidan
    (r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}", "[BIDAN]"),
    (r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b", "[BIDAN]"),

    # Apoteker / farmasi
    (r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}", "[APOTEKER]"),
    (r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b", "[APOTEKER]"),
    (r"\b(?:Farmasi|Petugas\s+Farmasi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Farmasi: [APOTEKER]"),

    # Analis lab / ATLM
    (r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[ANALIS_LAB]"),
    (r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b", "[ANALIS_LAB]"),

    # Radiografer
    (r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[RADIOGRAFER]"),

    # Fisioterapis
    (r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[FISIOTERAPIS]"),

    # Gizi
    (r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[NUTRISIONIS]"),
]

# ============================================================
# IDENTITAS PASIEN / RS / KONTAK
# ============================================================

HOSPITAL_NAMES = [
    # Tambahkan variasi nama RS bila perlu.
    # "RS AL ISLAM BANDUNG",
    # "RUMAH SAKIT AL ISLAM BANDUNG",
]

PATIENT_ID_PATTERNS = [
    (r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_RM]"),
    (r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", "[NIK]"),
    (r"\b\d{16}\b", "[NIK]"),
    (r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", "[NO_HP]"),
    (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
    (r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Nama Pasien: [PASIEN]"),
    (r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}", "Alamat: [ALAMAT]"),
]

# ============================================================
# FUNGSI UTILITAS
# ============================================================

def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def count_sub(pattern: str, repl: str, text: str, flags=re.IGNORECASE):
    new_text, n = re.subn(pattern, repl, text, flags=flags)
    return new_text, n


def safe_regex_name(name: str) -> str:
    name = name.strip()
    escaped = re.escape(name)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\.", r"\.?")
    return escaped


def infer_doctor_role_from_text(text: str) -> str:
    lower = text.lower()
    lower = re.sub(r"\s+", " ", lower)

    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if degree.lower() in lower:
            return role

    if re.search(r"\bsp\.?\s*[a-z]", lower, flags=re.IGNORECASE):
        return "DOKTER_SPESIALIS"

    if re.search(r"\bdrg\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_GIGI"

    if re.search(r"\bdr\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_UMUM"

    return "DOKTER"


def build_doctor_regex_general():
    specialist = r"(?:,\s*)?(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?"
    subspec_extra = r"(?:\s*,?\s*(?:KIC|FINASIM|FIHA|FINA|PhD|M\.?Kes|M\.?Sc|MM|SH|MH))*"

    prefix = r"(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*"

    pattern1 = rf"\bdrg?\.?\s*[A-Z][A-Za-z.'` -]{{2,80}}{specialist}{subspec_extra}"
    pattern2 = rf"\b{prefix}(?:drg?\.?\s*)?[A-Z][A-Za-z.'` -]{{2,80}}{specialist}{subspec_extra}"

    return [pattern2, pattern1]


def load_doctor_names(csv_path: Path):
    doctors = []
    if not csv_path.exists():
        print(f"PERINGATAN: staff_doctors.csv tidak ditemukan di {csv_path}")
        print("Script tetap berjalan, tetapi deteksi dokter hanya memakai pola umum.")
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


def anonymize_hospital_names(text: str):
    total = 0

    for name in HOSPITAL_NAMES:
        if not name.strip():
            continue
        pattern = safe_regex_name(name)
        text, n = count_sub(pattern, "[RUMAH_SAKIT]", text)
        total += n

    generic_patterns = [
        (r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", "[RUMAH_SAKIT]"),
        (r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]"),
        (r"\b(?:Telp\.?|Telepon|Fax)\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]

    for pattern, repl in generic_patterns:
        text, n = count_sub(pattern, repl, text)
        total += n

    return text, total


def anonymize_patient_identifiers(text: str):
    counts = {}
    for pattern, repl in PATIENT_ID_PATTERNS:
        key = repl.strip("[]").split(":")[0]
        text, n = count_sub(pattern, repl, text)
        counts[key] = counts.get(key, 0) + n
    return text, counts


def anonymize_doctors_from_csv(text: str, doctors):
    counts = {}

    for name, role in sorted(doctors, key=lambda x: len(x[0]), reverse=True):
        label = f"[{role}]"
        pattern = safe_regex_name(name)
        text, n = count_sub(pattern, label, text)
        counts[role] = counts.get(role, 0) + n

    return text, counts


def anonymize_doctors_general(text: str):
    counts = {}

    def repl(match):
        original = match.group(0)
        role = infer_doctor_role_from_text(original)
        counts[role] = counts.get(role, 0) + 1

        prefix_match = re.match(
            r"(?i)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*",
            original
        )
        if prefix_match:
            prefix = prefix_match.group(1)
            return f"{prefix}: [{role}]"

        return f"[{role}]"

    for pattern in build_doctor_regex_general():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    return text, counts


def anonymize_other_ppa(text: str):
    counts = {}

    for pattern, label in ROLE_PATTERNS:
        def repl(match, label=label):
            clean_label = re.search(r"\[([A-Z_]+)\]", label)
            key = clean_label.group(1) if clean_label else label
            counts[key] = counts.get(key, 0) + 1
            return label

        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    return text, counts


def detect_possible_leftovers(text: str):
    suspicious_patterns = {
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ns_leftover": r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_amd_kep_leftover": r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
        "possible_bidan_leftover": r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}",
    }

    result = {}
    for key, pattern in suspicious_patterns.items():
        result[key] = len(re.findall(pattern, text, flags=re.IGNORECASE))
    return result


def merge_counts(*dicts):
    merged = {}
    for d in dicts:
        for k, v in d.items():
            merged[k] = merged.get(k, 0) + v
    return merged


def anonymize_text(text: str, doctors):
    text = normalize_spaces(text)

    text, hospital_count = anonymize_hospital_names(text)
    text, patient_counts = anonymize_patient_identifiers(text)

    text, doctor_csv_counts = anonymize_doctors_from_csv(text, doctors)
    text, doctor_general_counts = anonymize_doctors_general(text)
    text, ppa_counts = anonymize_other_ppa(text)

    leftovers = detect_possible_leftovers(text)

    counts = merge_counts(
        {"RUMAH_SAKIT_ALAMAT_RS": hospital_count},
        patient_counts,
        doctor_csv_counts,
        doctor_general_counts,
        ppa_counts,
        leftovers,
    )

    return text, counts


def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)

    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    doctors = load_doctor_names(DOCTOR_CSV)

    # PENTING:
    # rglob membaca semua file .txt di dalam subfolder pasien.
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
    print("\nCek kolom possible_*_leftover di report.")
    print("Kalau masih ada angka, buka file terkait dan cek manual dengan Ctrl+F.")


if __name__ == "__main__":
    main()
