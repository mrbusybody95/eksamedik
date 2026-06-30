from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# ANONIMISASI FAST SAFE - ANTI STUCK
#
# Tujuan:
# - Memproses SEMUA file txt di 02_text_extracted secara recursive.
# - Tidak macet di cppt_ranap panjang.
# - Membersihkan pasien, RM, NIK, alamat, RS, telepon RS, header/footer radiologi.
# - Staff CSV dipakai dengan exact/simple replacement saja supaya cepat.
#
# Struktur:
# Pipeline RME Stroke/
# ├── 02_text_extracted/STROKE_001/*.txt
# ├── 03_anonymized_text/
# ├── 04_anonymization_report/
# └── 10_scripts/
#     ├── anonymize_FAST_SAFE_no_stuck.py
#     ├── staff_doctors.csv
#     └── staff_extra.csv
#
# Jalankan:
#   python anonymize_FAST_SAFE_no_stuck.py
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

# Jika ingin file panjang diproses super minimal, ubah angka ini lebih kecil.
LONG_FILE_THRESHOLD = 10000

HOSPITAL_NAMES = [
    "RS AL ISLAM BANDUNG",
    "RUMAH SAKIT AL ISLAM BANDUNG",
    "RS AL ISLAM",
    "RSAI",
]

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text

def subn_count(text, key, pattern, repl, flags=re.I):
    text, n = re.subn(pattern, repl, text, flags=flags)
    return text, {key: n}

def merge_counts(*dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out

def load_staff_names_simple():
    names = []
    for csv_path in [DOCTOR_CSV, EXTRA_CSV]:
        if not csv_path.exists():
            print(f"Info: {csv_path.name} tidak ditemukan. Dilewati.")
            continue
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                role = (row.get("role") or "").strip() or "STAFF"
                if not name:
                    continue
                names.append((name, role))
        print(f"{csv_path.name}: terbaca")
    # urut panjang dulu supaya nama panjang kena duluan
    names = sorted(set(names), key=lambda x: len(x[0]), reverse=True)
    print(f"Total nama staff exact terbaca: {len(names)}")
    return names

def cleanup_patient_rs_phone_radiology(text: str):
    counts = {}

    patterns = [
        # RM / MRN
        ("NO_RM_LABEL", r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis|Medical\s*Record\s*Number)\s*[:\-]?\s*[A-Za-z0-9\-\/\. ]{2,80}", "[NO_RM]"),
        ("NO_RM_DASHED", r"\b\d{2}[-/]\d{2}[-/]\d{2}[-/]\d{2}\b", "[NO_RM]"),
        ("NIK_LABEL", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", "[NIK]"),
        ("NIK_16", r"\b\d{16}\b", "[NIK]"),

        # Nomor HP / telepon umum
        ("NO_HP", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", "[NO_HP]"),

        # Telepon rumah sakit: 022 / (022) / 62-22, Telp/Fax
        ("TELEPON_RS_LABEL", r"\b(?:Telp\.?|Telepon|Phone|Fax|Tel)\.?\s*[:\-]?\s*(?:\+?62\s*[-]?\s*)?(?:\(?0?22\)?|22)[0-9\-\s\(\)]{4,30}", "[TELEPON_RS]"),
        ("TELEPON_RS_022", r"\b(?:\(?022\)?|022)[\s\-]?\d{3,5}[\s\-]?\d{3,5}\b", "[TELEPON_RS]"),
        ("TELEPON_RS_62_22", r"\b(?:\+?62)[\s\-]?22[\s\-]?\d{3,5}[\s\-]?\d{3,5}\b", "[TELEPON_RS]"),

        ("EMAIL", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        ("NAMA_PASIEN", r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Nama Pasien: [PASIEN]"),
        ("ALAMAT", r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}", "Alamat: [ALAMAT]"),

        # Header radiologi / lab
        ("NO_FOTO", r"(?i)\bNo\.?\s*Foto\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_FOTO]"),
        ("NO_REG", r"(?i)\b(?:No\.?\s*Reg(?:istrasi)?|No\.?\s*Register|No\.?\s*Kunjungan)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_REGISTER]"),
        ("NO_LAB", r"(?i)\bNo\.?\s*Lab\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_LAB]"),
        ("LOKASI_RS", r"(?i)\bBandung\s*[-,]?\s*Jawa\s*Barat\b\.?", "[LOKASI_RS]"),
        ("HEADER_XRAY", r"(?i)\bRadiologi\s+X\s*RAY\s+EXAMINATION\b", "[HEADER_RADIOLOGI]"),
        ("HEADER_HASIL", r"(?i)\bLEMBAR\s+HASIL\s+(?:PEMERIKSAAN|RADIOLOGI|LABORATORIUM)\b", "[HEADER_HASIL]"),
    ]

    for key, pat, repl in patterns:
        text, n = re.subn(pat, repl, text, flags=re.I | re.M)
        counts[key] = counts.get(key, 0) + n

    # Nama RS literal
    total_rs = 0
    for name in HOSPITAL_NAMES:
        if name:
            pat = re.escape(name)
            text, n = re.subn(pat, "[RUMAH_SAKIT]", text, flags=re.I)
            total_rs += n

    # Nama RS generik
    text, n = re.subn(r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", "[RUMAH_SAKIT]", text, flags=re.I)
    total_rs += n

    # Alamat RS
    text, n = re.subn(r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]", text, flags=re.I)
    total_rs += n

    counts["RUMAH_SAKIT_ALAMAT_RS"] = total_rs

    # Buang baris footer/header administratif yang tidak perlu
    admin_line_patterns = [
        r"(?im)^\s*(?:No\.?\s*Foto|No\.?\s*RM|Medical\s*Record|No\.?\s*Reg|No\.?\s*Lab)\b.*$",
        r"(?im)^\s*(?:Nama\s*Pasien|Tanggal\s*Lahir|Jenis\s*Kelamin|Alamat)\b.*$",
        r"(?im)^\s*(?:Dokter\s*Pengirim|Unit\s*Asal|Ruangan|Penjamin)\b.*$",
        r"(?im)^\s*(?:Dicetak|Tanggal\s*Cetak|Print\s*Copy|Halaman)\b.*$",
        r"(?im)^\s*(?:Telp\.?|Telepon|Phone|Fax)\b.*$",
    ]
    for idx, pat in enumerate(admin_line_patterns, start=1):
        text, n = re.subn(pat, "", text, flags=re.I | re.M)
        counts[f"ADMIN_LINE_REMOVED_{idx}"] = n

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, counts

def anonymize_staff_exact_fast(text: str, staff_names):
    counts = {}
    # exact/simple replacement, bukan fuzzy regex berat
    for name, role in staff_names:
        if len(name) < 5:
            continue
        label = f"[{role}]"
        pattern = re.escape(name)
        text, n = re.subn(pattern, label, text, flags=re.I)
        if n:
            counts[f"STAFF_EXACT_{role}"] = counts.get(f"STAFF_EXACT_{role}", 0) + n
    return text, counts

def anonymize_doctor_ppa_light(text: str):
    counts = {}
    patterns = [
        ("DOKTER", r"\bdr\.?\s+[A-Z][A-Za-z.'` -]{2,80}(?:,\s*Sp\.?\s*[A-Za-z\.\-\s]+)?", "[DOKTER]"),
        ("DOKTER_GIGI", r"\bdrg\.?\s+[A-Z][A-Za-z.'` -]{2,80}", "[DOKTER_GIGI]"),
        ("DOKTER_SPESIALIS", r"\b[A-Z][A-Za-z.'` -]{2,80},?\s*Sp\.?\s*[A-Za-z\.\-\s]+", "[DOKTER_SPESIALIS]"),
        ("PERAWAT", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}", "[PERAWAT]"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|Ners)\b", "[PERAWAT]"),
        ("APOTEKER", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}", "[APOTEKER]"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?)\b", "[RADIOGRAFER]"),
        ("FISIOTERAPIS", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Fis\.?|A\.?Md\.?\s*Fis\.?)\b", "[FISIOTERAPIS]"),
    ]
    for key, pat, repl in patterns:
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[key] = counts.get(key, 0) + n
    return text, counts

def cleanup_labels(text: str):
    counts = {}
    staff = r"(?:DOKTER|PERAWAT|APOTEKER|RADIOGRAFER|FISIOTERAPIS|NUTRISIONIS|BIDAN|ANALIS_LAB|DOKTER_SPESIALIS|DOKTER_GIGI)(?:_[A-Z_]+)?"
    # double label
    text, n = re.subn(rf"(\[{staff}\])(?:\s*,?\s*\1)+", r"\1", text, flags=re.I)
    counts["DOUBLE_LABEL"] = n
    # label + gelar sisa
    cleanups = [
        (r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*drg?\. ?", r"\1"),
        (r"(\[DOKTER(?:_[A-Z_]+)?\])\s*[\.,]*\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*\. ?", r"\1"),
        (r"(\[PERAWAT\])\s*[\.,]*\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\. ?", r"\1"),
        (r"(\[APOTEKER\])\s*[\.,]*\s*(?:Apt\.?|apt\.?|S\.?\s*Farm\.?|M\.?\s*Farm\.?)\. ?", r"\1"),
    ]
    for i, (pat, repl) in enumerate(cleanups, 1):
        text, n = re.subn(pat, repl, text, flags=re.I)
        counts[f"LABEL_CLEAN_{i}"] = n
    return text, counts

def detect_leftovers(text: str):
    patterns = {
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ners_leftover": r"\b(?:Ns\.?|Ners)\b",
        "possible_apt_leftover": r"\b(?:Apt\.?|apt\.?)\b",
        "possible_phone_022_leftover": r"\b(?:\(?022\)?|022)[\s\-]?\d{3,5}[\s\-]?\d{3,5}\b",
        "possible_medrec_leftover": r"(?i)\bmedical\s*record\s*number\b",
        "possible_no_foto_leftover": r"(?i)\bno\.?\s*foto\b",
    }
    return {k: len(re.findall(p, text, flags=re.I)) for k, p in patterns.items()}

def anonymize_text_fast_safe(text: str, staff_names):
    text = normalize_text(text)
    text, c1 = cleanup_patient_rs_phone_radiology(text)
    text, c2 = anonymize_staff_exact_fast(text, staff_names)
    text, c3 = anonymize_doctor_ppa_light(text)
    text, c4 = cleanup_labels(text)
    text, c5 = cleanup_patient_rs_phone_radiology(text)
    c6 = detect_leftovers(text)
    return text, merge_counts(c1, c2, c3, c4, c5, c6)

def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)

    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    staff_names = load_staff_names_simple()

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

        anon, counts = anonymize_text_fast_safe(raw, staff_names)
        out.write_text(anon, encoding="utf-8")

        row = {
            "patient_folder": rel.parts[0] if len(rel.parts) > 1 else "",
            "file": str(rel),
            "output_file": str(out.relative_to(BASE_DIR)),
            "input_char_count": len(raw),
            "output_char_count": len(anon),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        row.update(counts)
        rows.append(row)

        print(f"Selesai: {rel}", flush=True)
        print(f"Disimpan ke: {out}", flush=True)

    keys = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)

    report = REPORT_DIR / "anonymization_report_fast_safe.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    print("\nSELESAI SEMUA.")
    print(f"Hasil anonim: {OUT_DIR}")
    print(f"Report audit: {report}")
    print("\nCek manual Ctrl+F:")
    print("dr | Dr | Sp. | Ners | Apt | Amd.Kep | Amd.Rad | Amd.Fis | Print copy by | 022 | Medical Record | No Foto | Bandung")

if __name__ == "__main__":
    main()
