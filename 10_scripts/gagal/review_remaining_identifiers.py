from pathlib import Path
import re
from collections import defaultdict, Counter

BASE_DIR = Path(__file__).resolve().parents[1]

IN_DIR = BASE_DIR / "03_anonymized_text"
OUT_DIR = BASE_DIR / "04_review_candidates"
OUT_DIR.mkdir(exist_ok=True)

REPORT_FILE = OUT_DIR / "review_kandidat_bocor.txt"

MEDICAL_WORDS = {
    "Stroke", "Infark", "Lacunar", "Lakuner", "Thalamus", "Capsula",
    "Interna", "Eksterna", "Nukleus", "Lentiformis", "Subcortical",
    "Atrophy", "Cerebri", "Hydrocephalus", "Ventricel", "Ventrikel",
    "Sinus", "Ritme", "Atrial", "Fibrilasi", "Pneumonia", "CAP",
    "Hematemesis", "Melena", "Vertigo", "Dispepsia", "Hipertensi",
    "Diabetes", "Dyslipidemia", "Dislipidemia", "CKD", "CHF",
    "Anemia", "Bronchopneumonia", "Cardiomegali", "Elongasio",
    "Atherosclerosis", "Aorta", "Kanan", "Kiri", "Bilateral",
    "Sentral", "Perifer", "Normal", "Abnormal", "Akut", "Kronis",
    "Subakut", "Multiple", "Multipel", "Lesi", "Edema", "Herniasi",
    "Paracetamol", "Citicolin", "Ranitidin", "Sucralfat", "NaCl",
    "Mannitol", "Clopidogrel", "Amlodipin", "Atorvastatin",
    "Ceftriaxone", "Omeprazole", "Pantoprazole", "Ondansetron",
    "Metformin", "Insulin", "Furosemide", "Spironolactone",
    "Bisoprolol", "Candesartan", "Aspilet", "Simvastatin",
    "Terapi", "Diagnosis", "Diagnosa", "Keluhan", "Utama",
    "Riwayat", "Pemeriksaan", "Fisik", "Laboratorium", "Radiologi",
    "Assessment", "Planning", "Subjective", "Objective",
    "Instruksi", "Observasi", "Konsul", "Advis", "Advice",
    "Dokter", "Perawat", "Pasien", "Nama", "Alamat", "Kota",
    "Tanggal", "Lahir", "Umur", "Jenis", "Kelamin", "Penjamin",
    "Tanda", "Tangan", "Catatan", "Penanggung", "Jawab",
    "Halaman", "Pulang", "Masuk", "Rawat", "Inap", "Jalan",
    "IGD", "ICU", "HCU", "Poli", "Bangsal", "Ruangan",
    "Selesai", "Terima", "Kasih", "Kepercayaan",
}

COMMON_SHORT_WORDS = {
    "No", "RM", "TD", "HR", "RR", "S", "O", "A", "P", "KU", "CM",
    "GCS", "E", "M", "V", "IV", "IM", "PO", "CT", "MRI", "RS",
    "BPJS", "NIK", "SIP", "DPJP", "PPA", "IGD", "ICU", "HCU",
    "BAK", "BAB", "RPD", "RPS", "TTV", "CRT", "EKG", "USG",
    "Na", "Cl", "K", "Ca", "Mg", "Hb", "Ht", "Leu", "LED",
    "SGOT", "SGPT", "Ureum", "Kreatinin",
}

NAME_WORD = r"[A-Z][a-zA-Z'`.-]{2,}"
NAME_PHRASE = rf"{NAME_WORD}(?:\s+{NAME_WORD}){{0,4}}"

CREDENTIAL_PATTERN = r"""
(?:dr\.?|Dr\.?|H\.?|Hj\.?|Amd\.?\s*Kep\.?|S\.?\s*Kep\.?|Ns\.?|SKep\.?|S\.?Ked\.?|
Sp\.?\s*[A-Za-z]+(?:\.[A-Za-z]+)?|Sp\.?S\.?|Sp\.?PD\.?|Sp\.?PK\.?|Sp\.?Rad\.?|
M\.?Kes\.?|MH\.?Kes\.?|M\.?Biomed\.?)
"""

SUSPICIOUS_CONTEXT = [
    "dr", "dokter", "dpjp", "perawat", "bidan", "apoteker", "ppa",
    "petugas", "pemeriksa", "verifikator", "validator",
    "penanggung jawab", "print copy", "by", "advis", "konsul",
    "catatan", "tanda tangan", "sip", "str"
]


def is_probably_not_name(candidate: str) -> bool:
    candidate_clean = candidate.strip(" ,.:;-()[]")
    words = candidate_clean.split()

    if not candidate_clean:
        return True

    if "[" in candidate_clean or "]" in candidate_clean:
        return True

    if len(candidate_clean) <= 2:
        return True

    if candidate_clean in COMMON_SHORT_WORDS:
        return True

    if candidate_clean in MEDICAL_WORDS:
        return True

    if re.fullmatch(r"[0-9\s\-/.]+", candidate_clean):
        return True

    if words and all(
        w.strip(" ,.:;-()[]") in MEDICAL_WORDS or w in COMMON_SHORT_WORDS
        for w in words
    ):
        return True

    return False


def get_context_line(lines, index, window=1):
    start = max(0, index - window)
    end = min(len(lines), index + window + 1)

    selected = []

    for i in range(start, end):
        prefix = ">> " if i == index else "   "
        selected.append(f"{prefix}{i + 1}: {lines[i]}")

    return "\n".join(selected)


def scan_file(txt_path: Path):
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    findings = []

    for i, line in enumerate(lines):
        if re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", line):
            findings.append({
                "type": "EMAIL_MUNGKIN_BOCOR",
                "value": line.strip(),
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    for i, line in enumerate(lines):
        if re.search(r"(\+62|62|0)8[1-9][0-9]{6,11}", line):
            findings.append({
                "type": "NO_HP_MUNGKIN_BOCOR",
                "value": line.strip(),
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    for i, line in enumerate(lines):
        numbers = re.findall(r"\b\d{6,}\b", line)
        for num in numbers:
            findings.append({
                "type": "ANGKA_PANJANG_MUNGKIN_IDENTIFIER",
                "value": num,
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    for i, line in enumerate(lines):
        if re.search(r"\bSIP\b|IPFK|DPMPTSP|\bSTR\b", line, flags=re.IGNORECASE):
            findings.append({
                "type": "SIP_STR_IZIN_PRAKTIK_MUNGKIN_BOCOR",
                "value": line.strip(),
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    for i, line in enumerate(lines):
        low = line.lower()
        if any(ctx in low for ctx in SUSPICIOUS_CONTEXT):
            findings.append({
                "type": "BARIS_KONTEKS_STAF_DOKTER_PERLU_REVIEW",
                "value": line.strip(),
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    pattern_name_credential = rf"\b({NAME_PHRASE})\s*,\s*({CREDENTIAL_PATTERN})"

    for i, line in enumerate(lines):
        for m in re.finditer(pattern_name_credential, line, flags=re.IGNORECASE | re.VERBOSE):
            candidate = m.group(1).strip()

            if not is_probably_not_name(candidate):
                findings.append({
                    "type": "NAMA_DENGAN_GELAR_MUNGKIN_BOCOR",
                    "value": m.group(0).strip(),
                    "line": i + 1,
                    "context": get_context_line(lines, i)
                })

    pattern_dr_name = rf"\bdr\.?\s*({NAME_PHRASE})"

    for i, line in enumerate(lines):
        for m in re.finditer(pattern_dr_name, line, flags=re.IGNORECASE | re.VERBOSE):
            candidate = m.group(1).strip()

            if not is_probably_not_name(candidate):
                findings.append({
                    "type": "DR_NAMA_MUNGKIN_BOCOR",
                    "value": m.group(0).strip(),
                    "line": i + 1,
                    "context": get_context_line(lines, i)
                })

    pattern_capital_name = rf"\b({NAME_WORD}\s+{NAME_WORD}(?:\s+{NAME_WORD}){{0,3}})\b"

    for i, line in enumerate(lines):
        for m in re.finditer(pattern_capital_name, line):
            candidate = m.group(1).strip()

            if is_probably_not_name(candidate):
                continue

            line_low = line.lower()
            nearby_context = any(ctx in line_low for ctx in SUSPICIOUS_CONTEXT)
            short_line = len(line.strip()) <= 60

            if nearby_context or short_line:
                findings.append({
                    "type": "NAMA_KAPITAL_MUNGKIN_BOCOR",
                    "value": candidate,
                    "line": i + 1,
                    "context": get_context_line(lines, i)
                })

    for i, line in enumerate(lines):
        if re.search(
            r"\b(Alamat|Kota|Penjamin|Asuransi|Yakes|Telkom|Pensiunan)\b",
            line,
            flags=re.IGNORECASE
        ):
            findings.append({
                "type": "BARIS_IDENTITAS_ADMINISTRATIF_PERLU_REVIEW",
                "value": line.strip(),
                "line": i + 1,
                "context": get_context_line(lines, i)
            })

    return findings


def write_report(all_findings):
    with REPORT_FILE.open("w", encoding="utf-8") as f:
        f.write("LAPORAN REVIEW KANDIDAT IDENTIFIER YANG MASIH MUNGKIN BOCOR\n")
        f.write("=" * 80 + "\n\n")

        f.write("Catatan:\n")
        f.write("- Ini bukan berarti semuanya pasti bocor.\n")
        f.write("- Ini adalah daftar kandidat untuk dicek manual.\n")
        f.write("- Kalau benar identifier, tambahkan ke script anonymize_text.py atau hapus manual.\n\n")

        total = sum(len(v) for v in all_findings.values())
        f.write(f"Total temuan kandidat: {total}\n")
        f.write(f"Jumlah file dengan temuan: {len(all_findings)}\n\n")

        type_counter = Counter()
        value_counter = Counter()

        for file_path, findings in all_findings.items():
            for item in findings:
                type_counter[item["type"]] += 1
                value_counter[item["value"]] += 1

        f.write("RINGKASAN TIPE TEMUAN\n")
        f.write("-" * 80 + "\n")

        for t, count in type_counter.most_common():
            f.write(f"{t}: {count}\n")

        f.write("\n\nKANDIDAT PALING SERING MUNCUL\n")
        f.write("-" * 80 + "\n")

        for value, count in value_counter.most_common(100):
            f.write(f"{count}x | {value}\n")

        f.write("\n\nDETAIL PER FILE\n")
        f.write("=" * 80 + "\n\n")

        for file_path, findings in all_findings.items():
            f.write(f"FILE: {file_path}\n")
            f.write("-" * 80 + "\n")

            for idx, item in enumerate(findings, start=1):
                f.write(f"\n[{idx}] {item['type']}\n")
                f.write(f"Nilai: {item['value']}\n")
                f.write(f"Baris: {item['line']}\n")
                f.write("Konteks:\n")
                f.write(item["context"])
                f.write("\n")

            f.write("\n\n")


def main():
    txt_files = list(IN_DIR.rglob("*.txt"))

    if not txt_files:
        print(f"Tidak ada file TXT di folder: {IN_DIR}")
        print("Jalankan dulu anonymize_text.py sampai ada hasil di folder 03_anonymized_text.")
        return

    print(f"Menemukan {len(txt_files)} file TXT untuk direview.\n")

    all_findings = defaultdict(list)

    for txt_path in txt_files:
        relative_path = txt_path.relative_to(IN_DIR)
        print(f"Review: {relative_path}")

        findings = scan_file(txt_path)

        if findings:
            all_findings[str(relative_path)].extend(findings)

    write_report(all_findings)

    print("\nSelesai.")
    print(f"Laporan review dibuat di:")
    print(REPORT_FILE)

    total = sum(len(v) for v in all_findings.values())
    print(f"\nTotal kandidat temuan: {total}")

    if total == 0:
        print("Tidak ditemukan kandidat identifier mencurigakan.")
    else:
        print("Buka file review_kandidat_bocor.txt lalu cek manual.")


if __name__ == "__main__":
    main()
