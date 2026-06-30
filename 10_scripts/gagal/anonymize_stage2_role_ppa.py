from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# SCRIPT ANONIMISASI TAHAP 2 - ROLE-PRESERVING PPA/STAFF
# Untuk file .txt hasil ekstraksi rekam medis
#
# Input:
#   02_text_extracted/*.txt
#   staff_doctors.csv  -> opsional, berisi daftar nama dokter
#
# Output:
#   03_anonymized_text/*.txt
#   04_anonymization_report/anonymization_report.csv
#
# Cara pakai:
#   1. Simpan script ini di folder scripts/
#   2. Pastikan struktur folder:
#        project/
#        ├── 02_text_extracted/
#        ├── 03_anonymized_text/
#        ├── 04_anonymization_report/
#        └── scripts/
#            ├── anonymize_stage2_role_ppa.py
#            └── staff_doctors.csv
#   3. Jalankan:
#        python anonymize_stage2_role_ppa.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"

DOCTOR_CSV = Path(__file__).resolve().parent / "staff_doctors.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 1. DAFTAR MAPPING SPESIALIS / SUBSPESIALIS
# Tambahkan sesuai kebutuhan RS.
# ============================================================

SPECIALIST_MAP = {
    # Neurologi
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",  # variasi lama/umum tertentu

    # Radiologi
    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI",

    # Penyakit Dalam
    "sp.pd": "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.pd-kger": "DOKTER_SUBSPESIALIS_GERIATRI",
    "sp.pd-kgh": "DOKTER_SUBSPESIALIS_GINJAL_HIPERTENSI",
    "sp.pd-kgeh": "DOKTER_SUBSPESIALIS_GASTROENTERO_HEPATOLOGI",
    "sp.pd-khom": "DOKTER_SUBSPESIALIS_HEMATO_ONKOLOGI",
    "sp.pd-kai": "DOKTER_SUBSPESIALIS_ALERGI_IMUNOLOGI",
    "sp.pd-kpsi": "DOKTER_SUBSPESIALIS_PSikosomatik".upper(),
    "sp.pd-kptI".lower(): "DOKTER_SUBSPESIALIS_PENYAKIT_TROPIS_INFEKSI",
    "sp.pd-kemd": "DOKTER_SUBSPESIALIS_ENDOKRIN_METABOLIK_DIABETES",
    "sp.pd-kr": "DOKTER_SUBSPESIALIS_REUMATOLOGI",
    "sp.pd-kkv": "DOKTER_SUBSPESIALIS_KARDIOVASKULAR",

    # Jantung
    "sp.jp": "DOKTER_SPESIALIS_JANTUNG",
    "sp.jp(k)": "DOKTER_SUBSPESIALIS_JANTUNG",

    # Anestesi
    "sp.an": "DOKTER_SPESIALIS_ANESTESI",
    "sp.an-kic": "DOKTER_SUBSPESIALIS_INTENSIVE_CARE",

    # Bedah
    "sp.b": "DOKTER_SPESIALIS_BEDAH",
    "sp.btkv": "DOKTER_SPESIALIS_BEDAH_TORAKS_KARDIOVASKULAR",
    "sp.bs": "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot": "DOKTER_SPESIALIS_ORTOPEDI",
    "sp.u": "DOKTER_SPESIALIS_UROLOGI",

    # Anak
    "sp.a": "DOKTER_SPESIALIS_ANAK",
    "sp.a(k)": "DOKTER_SUBSPESIALIS_ANAK",

    # Obgyn
    "sp.og": "DOKTER_SPESIALIS_OBGYN",
    "sp.og(k)": "DOKTER_SUBSPESIALIS_OBGYN",

    # Paru
    "sp.p": "DOKTER_SPESIALIS_PARU",

    # Saraf/rehab/jiwa/THT/mata/kulit
    "sp.kfr": "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj": "DOKTER_SPESIALIS_KEDOKTERAN_JIWA",
    "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m": "DOKTER_SPESIALIS_MATA",
    "sp.kk": "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv": "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",

    # Patologi/lab
    "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",
}

# ============================================================
# 2. POLA PPA NON-DOKTER
# Bisa diperluas kalau nanti fisioterapis/gizi sudah terlihat formatnya.
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

    # Fisioterapis - pola awal, bisa ditambah nanti
    (r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[FISIOTERAPIS]"),

    # Gizi / dietisien - pola awal, bisa ditambah nanti
    (r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "[NUTRISIONIS]"),
]

# ============================================================
# 3. IDENTITAS PASIEN / RS / KONTAK
# Sesuaikan hospital/street keywords kalau perlu.
# ============================================================

HOSPITAL_NAMES = [
    # Tambahkan nama RS sendiri di sini jika ingin diganti.
    # Contoh:
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
# 4. UTILITAS REGEX
# ============================================================

def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def count_sub(pattern: str, repl: str, text: str, flags=re.IGNORECASE):
    new_text, n = re.subn(pattern, repl, text, flags=flags)
    return new_text, n


def safe_regex_name(name: str) -> str:
    """
    Membuat regex nama lebih fleksibel:
    - spasi bisa lebih dari satu
    - titik pada gelar boleh ada/tidak sebagian
    """
    name = name.strip()
    escaped = re.escape(name)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\.", r"\.?")
    return escaped


def infer_doctor_role_from_text(text: str) -> str:
    lower = text.lower()
    lower = re.sub(r"\s+", " ", lower)

    # Urutkan dari gelar paling panjang supaya subspesialis menang dulu.
    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if degree.lower() in lower:
            return role

    # Ada Sp. tapi tidak masuk mapping
    if re.search(r"\bsp\.?\s*[a-z]", lower, flags=re.IGNORECASE):
        return "DOKTER_SPESIALIS"

    # drg.
    if re.search(r"\bdrg\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_GIGI"

    # dr. tanpa Sp
    if re.search(r"\bdr\.?\b", lower, flags=re.IGNORECASE):
        return "DOKTER_UMUM"

    return "DOKTER"


def build_doctor_regex_general():
    """
    Pola umum dokter.
    Menangkap:
      dr. Nama
      dr Nama
      dr. Nama, Sp.N
      Dokter IGD: dr. Nama
      DPJP: dr. Nama Sp.PD-KKV
      Konsulen: dr. Nama, Sp.N(K)
    """
    doctor_name = r"(?:drg?\.?\s*)?[A-Z][A-Za-z.'` -]{2,80}"
    specialist = r"(?:,\s*)?(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)?"
    subspec_extra = r"(?:\s*,?\s*(?:KIC|FINASIM|FIHA|FINA|PhD|M\.?Kes|M\.?Sc|MM|SH|MH))*"

    prefix = r"(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*"

    pattern1 = rf"\bdrg?\.?\s*[A-Z][A-Za-z.'` -]{{2,80}}{specialist}{subspec_extra}"
    pattern2 = rf"\b{prefix}(?:drg?\.?\s*)?[A-Z][A-Za-z.'` -]{{2,80}}{specialist}{subspec_extra}"

    return [pattern2, pattern1]


def load_doctor_names(csv_path: Path):
    """
    Format staff_doctors.csv:
      name,role
      dr. Ahmad Sp.N,DOKTER_SPESIALIS_NEUROLOGI
      dr. Budi,DOKTER_UMUM

    Kolom role boleh kosong. Kalau kosong, script menebak dari gelar.
    """
    doctors = []
    if not csv_path.exists():
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
    return doctors


def anonymize_hospital_names(text: str):
    total = 0
    for name in HOSPITAL_NAMES:
        if not name.strip():
            continue
        pattern = safe_regex_name(name)
        text, n = count_sub(pattern, "[RUMAH_SAKIT]", text)
        total += n

    # Pola umum alamat/telepon RS, tidak terlalu agresif.
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
        before_label = repl.strip("[]").split(":")[0]
        text, n = count_sub(pattern, repl, text)
        counts[before_label] = counts.get(before_label, 0) + n
    return text, counts


def anonymize_doctors_from_csv(text: str, doctors):
    counts = {}

    # Nama panjang dulu agar tidak tertimpa nama pendek.
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

        # Pertahankan konteks jika ada prefix seperti DPJP:
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
    """
    Deteksi sisa pola yang mungkin masih mengandung nama staf.
    Ini tidak mengubah teks, hanya membantu audit.
    """
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

    # Dokter dari CSV dulu, lebih presisi.
    text, doctor_csv_counts = anonymize_doctors_from_csv(text, doctors)

    # Lalu pola umum dokter.
    text, doctor_general_counts = anonymize_doctors_general(text)

    # Lalu PPA lain.
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
    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    doctors = load_doctor_names(DOCTOR_CSV)

    txt_files = sorted(IN_DIR.glob("*.txt"))
    if not txt_files:
        print(f"Tidak ada file .txt di {IN_DIR}")
        return

    report_rows = []

    for file_path in txt_files:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        anonymized, counts = anonymize_text(raw, doctors)

        out_path = OUT_DIR / file_path.name
        out_path.write_text(anonymized, encoding="utf-8")

        row = {
            "file": file_path.name,
            "output_file": str(out_path.relative_to(BASE_DIR)),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        row.update(counts)
        report_rows.append(row)

        print(f"OK: {file_path.name} -> {out_path.name}")

    # Buat report CSV dengan semua kolom yang muncul
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
    print(f"Input : {IN_DIR}")
    print(f"Output: {OUT_DIR}")
    print(f"Report: {report_path}")
    print("\nCatatan:")
    print("- Cek kolom possible_*_leftover di report.")
    print("- Kalau masih ada sisa nama dokter/PPA, tambahkan ke pola atau staff_doctors.csv.")


if __name__ == "__main__":
    main()
