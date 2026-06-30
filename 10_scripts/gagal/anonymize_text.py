from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parents[1]

IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
OUT_DIR.mkdir(exist_ok=True)

# ============================================================
# KONFIGURASI MANUAL
# ============================================================

HOSPITAL_NAMES = [
    "RS Al Islam Bandung",
    "Rumah Sakit Al Islam Bandung",
    "RSAI Bandung",
    "RSAI",
]

HOSPITAL_ADDRESSES = [
    "Jl. Soekarno Hatta",
    "Jalan Soekarno Hatta",
    "Bandung",
]

OTHER_ORG_NAMES = [
    "Yakes Telkom Pensiunan",
]

# Jika ada nama staf yang sering muncul, tambahkan di sini
KNOWN_STAFF_NAMES = [
    "Muhammad Ilham Muttaqin",
    "Mugi Rahayu",
    "Nuri Amalia",
    "Pipit Pitriyani",
    "Nia Kurniasih",
    "Nopita Ramansa",
    "Putri",
    "Rahmawati",
    "Dede Setiapriagung",
    "Nuri",
]

# Jika ada nama pasien tertentu yang ingin dipastikan terhapus
KNOWN_PATIENT_NAMES = [
    "Benjamin",
]

# ============================================================
# REGEX BANTUAN
# ============================================================

NAME_WORD = r"(?:[A-Z][a-zA-Z'`.-]+)"
NAME_PHRASE = rf"{NAME_WORD}(?:\s+{NAME_WORD}){{0,4}}"

# gelar / identitas yang sering muncul
CREDENTIALS = r"""
(?:Amd\.?\s*Kep\.?|S\.?\s*Kep\.?|Ns\.?|SKep\.?|S\.?Ked\.?|dr\.?|Dr\.?|H\.?|Hj\.?)
(?:\s*,\s*(?:Amd\.?\s*Kep\.?|S\.?\s*Kep\.?|Ns\.?|SKep\.?|S\.?Ked\.?|dr\.?|Dr\.?|H\.?|Hj\.?|Sp\.?\s*[A-Za-z]+(?:\.[A-Za-z]+)?|M\.?Kes\.?|MH\.?Kes\.?|M\.?Biomed\.?|Sp\.?Rad\.?|Sp\.?S\.?|Sp\.?PD\.?|Sp\.?PK\.?))*
|
(?:Sp\.?\s*[A-Za-z]+(?:\.[A-Za-z]+)?|M\.?Kes\.?|MH\.?Kes\.?|M\.?Biomed\.?|Sp\.?Rad\.?|Sp\.?S\.?|Sp\.?PD\.?|Sp\.?PK\.?)
(?:\s*,\s*(?:Sp\.?\s*[A-Za-z]+(?:\.[A-Za-z]+)?|M\.?Kes\.?|MH\.?Kes\.?|M\.?Biomed\.?|Amd\.?\s*Kep\.?|S\.?\s*Kep\.?|Ns\.?|SKep\.?|dr\.?|Dr\.?|H\.?|Hj\.?))*
"""

ROLE_WORDS = [
    "Dokter", "DPJP", "Perawat", "Bidan", "Apoteker", "Fisioterapis",
    "Ahli Gizi", "Petugas", "PPA", "Pemeriksa", "Verifikator", "Validator"
]

ROLE_PATTERN = r"|".join([re.escape(x) for x in ROLE_WORDS])


# ============================================================
# FUNGSI UMUM
# ============================================================

def replace_list_items(text: str, items: list[str], replacement: str) -> str:
    for item in items:
        item = item.strip()
        if not item:
            continue
        pattern = re.escape(item)
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def normalize_spaces(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_candidate_names(text: str) -> set[str]:
    """
    Cari kandidat nama orang yang kemungkinan adalah staf / dokter / pasien,
    lalu nanti diganti global.
    """
    candidates = set()

    # --------------------------------------------------------
    # 1) Nama setelah label umum
    # --------------------------------------------------------
    label_patterns = [
        rf"\b(?:Nama\s*Pasien|Nama|Pasien)\s*[:\-]\s*({NAME_PHRASE})",
        rf"\b(?:Dokter|DPJP|Perawat|Bidan|Apoteker|PPA|Petugas)\s*[:\-]\s*({NAME_PHRASE})",
        rf"\b(?:Penanggung\s*Jawab|PJ)\s*[:\-]\s*({NAME_PHRASE})",
    ]
    for pat in label_patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.VERBOSE):
            name = m.group(1).strip(" ,.-")
            if len(name) >= 3:
                candidates.add(name)

    # --------------------------------------------------------
    # 2) Nama + gelar di satu baris
    # contoh:
    # Pipit Pitriyani, Amd.Kep.
    # Nuri Amalia, Hj. Dr., Sp.S.
    # Rahmawati, dr., Sp.PK.
    # --------------------------------------------------------
    pattern_name_with_cred = rf"\b({NAME_PHRASE})\s*,\s*({CREDENTIALS})"
    for m in re.finditer(pattern_name_with_cred, text, flags=re.IGNORECASE | re.VERBOSE):
        name = m.group(1).strip(" ,.-")
        if len(name) >= 3:
            candidates.add(name)

    # --------------------------------------------------------
    # 3) dr. Nama
    # contoh: dr. Nuri / dr.Nuri / dr Ahmad
    # --------------------------------------------------------
    pattern_dr_name = rf"\bdr\.?\s*({NAME_PHRASE})"
    for m in re.finditer(pattern_dr_name, text, flags=re.IGNORECASE | re.VERBOSE):
        name = m.group(1).strip(" ,.-")
        if len(name) >= 2:
            candidates.add(name)

    # --------------------------------------------------------
    # 4) advis / konsul / oleh / by : Nama
    # --------------------------------------------------------
    context_patterns = [
        rf"\b(?:advis|konsul(?:\s+ke)?|oleh|by)\s*[:\-]?\s*(?:dr\.?\s*)?({NAME_PHRASE})",
        rf"\b(?:print\s*copy\s*ke-\d+\s*by)\s*[:\-]?\s*({NAME_PHRASE})",
    ]
    for pat in context_patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.VERBOSE):
            name = m.group(1).strip(" ,.-")
            if len(name) >= 2:
                candidates.add(name)

    # --------------------------------------------------------
    # 5) Nama berdiri sendiri pada satu baris, diikuti gelar atau profesi di baris berikutnya
    # contoh:
    # Nuri Amalia, Hj.
    # Dr., Sp.S.
    # --------------------------------------------------------
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        l1 = line.strip()
        l2 = lines[i + 1].strip()

        if re.fullmatch(rf"{NAME_PHRASE},?\s*(?:H\.?|Hj\.?)?", l1, flags=re.IGNORECASE | re.VERBOSE):
            if re.search(r"\b(?:dr\.?|Dr\.?|Amd\.?\s*Kep\.?|Sp\.?|S\.?Kep\.?|Ns\.?)", l2, flags=re.IGNORECASE):
                name = re.sub(r",?\s*(H\.?|Hj\.?)?$", "", l1).strip(" ,.-")
                if len(name) >= 3:
                    candidates.add(name)

    # --------------------------------------------------------
    # 6) Tambahkan known names manual
    # --------------------------------------------------------
    for n in KNOWN_STAFF_NAMES + KNOWN_PATIENT_NAMES:
        n = n.strip()
        if n:
            candidates.add(n)

    # Filter sederhana
    cleaned = set()
    blacklist = {
        "CT", "MRI", "NaCl", "Paracetamol", "Citicolin", "Ranitidin",
        "Sucralfat", "CAP", "TD", "HR", "RR", "SIP"
    }

    for c in candidates:
        c = c.strip(" ,.-")
        if len(c) < 2:
            continue
        if c in blacklist:
            continue
        cleaned.add(c)

    return cleaned


def replace_candidate_names(text: str, candidates: set[str]) -> str:
    """
    Ganti semua kandidat nama secara global.
    Prioritaskan nama yang lebih panjang dulu agar tidak bentrok.
    """
    for name in sorted(candidates, key=len, reverse=True):
        pattern = rf"\b{re.escape(name)}\b"
        text = re.sub(pattern, "[NAMA]", text, flags=re.IGNORECASE)
    return text


def anonymize_text(text: str) -> str:
    # ========================================================
    # 1. Hapus nama RS / alamat / organisasi
    # ========================================================
    text = replace_list_items(text, HOSPITAL_NAMES, "[NAMA_RS]")
    text = replace_list_items(text, HOSPITAL_ADDRESSES, "[ALAMAT_RS]")
    text = replace_list_items(text, OTHER_ORG_NAMES, "[NAMA_INSTANSI]")

    # ========================================================
    # 2. Hapus identitas numerik dan kontak
    # ========================================================
    text = re.sub(
        r"\b(No\.?\s*RM|Nomor\s*RM|No\.?\s*Rekam\s*Medis|Nomor\s*Rekam\s*Medis|MRN|RM)\s*[:\-]?\s*[A-Za-z0-9\-\/]+",
        r"\1: [NO_RM]",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\b\d{16}\b", "[NIK]", text)

    text = re.sub(
        r"\b(No\.?\s*KTP|Nomor\s*KTP|KTP)\s*[:\-]?\s*[0-9]+",
        r"\1: [NO_KTP]",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\b(No\.?\s*BPJS|Nomor\s*BPJS|BPJS)\s*[:\-]?\s*[0-9]+",
        r"\1: [NO_BPJS]",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\b(No\.?\s*Registrasi|Nomor\s*Registrasi|No\.?\s*Reg|Registrasi|Episode|Billing)\s*[:\-]?\s*[A-Za-z0-9\-\/]+",
        r"\1: [NO_REGISTRASI]",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"(\+62|62|0)8[1-9][0-9]{6,11}", "[NO_HP]", text)

    text = re.sub(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "[EMAIL]",
        text,
    )

    # ========================================================
    # 3. Tanggal lahir
    # ========================================================
    text = re.sub(
        r"\b(Tanggal\s*Lahir|Tgl\.?\s*Lahir|TTL|DOB)\s*[:\-]?\s*([0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4}|[0-9]{4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,2})",
        r"\1: [TANGGAL_LAHIR]",
        text,
        flags=re.IGNORECASE,
    )

    # ========================================================
    # 4. Alamat
    # ========================================================
    text = re.sub(
        r"\b(Alamat|Alamat\s*Pasien|Kota|Alamat\s*KTP)\s*[:\-]?\s*.*",
        lambda m: f"{m.group(1)}: [ALAMAT_PASIEN]",
        text,
        flags=re.IGNORECASE,
    )

    # ========================================================
    # 5. Label nama pasien
    # ========================================================
    text = re.sub(
        rf"\b(Nama\s*Pasien|Nama)\s*[:\-]?\s*({NAME_PHRASE})",
        r"\1: [NAMA_PASIEN]",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    # ========================================================
    # 6. Pola dokter / staf berlabel
    # ========================================================
    text = re.sub(
        rf"\b({ROLE_PATTERN})\s*[:\-]?\s*({NAME_PHRASE})",
        r"\1: [NAMA_STAF]",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    text = re.sub(
        r"\b(Tanda\s*Tangan|TTD|Pemeriksa|Verifikator|Validator|Penanggung\s*Jawab)\s*[:\-]?\s*([A-Z][A-Za-z\s\.'\-]{2,80})",
        r"\1: [NAMA_STAF]",
        text,
        flags=re.IGNORECASE,
    )

    # ========================================================
    # 7. Pola advis/konsul/by
    # ========================================================
    text = re.sub(
        rf"\b(advis|konsul(?:\s+ke)?|oleh|by)\s*[:\-]?\s*dr\.?\s*({NAME_PHRASE})(?:\s*,\s*{CREDENTIALS})?",
        r"\1 dr. [NAMA_DOKTER]",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    text = re.sub(
        rf"\b(print\s*copy\s*ke-\d+\s*by)\s*[:\-]?\s*({NAME_PHRASE})(?:\s*,\s*{CREDENTIALS})?",
        r"\1: [NAMA_STAF]",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    # ========================================================
    # 8. Pola dr. Nama, Sp...
    # ========================================================
    text = re.sub(
        rf"\bdr\.?\s*({NAME_PHRASE})(?:\s*,\s*{CREDENTIALS})?",
        r"dr. [NAMA_DOKTER]",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    # ========================================================
    # 9. Nama + gelar
    # contoh: Pipit Pitriyani, Amd.Kep.
    # ========================================================
    text = re.sub(
        rf"\b({NAME_PHRASE})\s*,\s*({CREDENTIALS})",
        r"[NAMA_STAF], \2",
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    # ========================================================
    # 10. Ambil semua kandidat nama lalu ganti global
    # ========================================================
    candidates = extract_candidate_names(text)
    text = replace_candidate_names(text, candidates)

    # ========================================================
    # 11. Rapikan placeholder spesifik
    # ========================================================
    text = re.sub(r"\[NAMA\]\s*,\s*(Amd\.?\s*Kep\.?|S\.?\s*Kep\.?|Ns\.?)", "[NAMA_STAF], \\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\[NAMA\]\s*,\s*(dr\.?|Dr\.?)", "[NAMA_DOKTER], \\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\[NAMA\]\s*,\s*(Sp\.?\s*[A-Za-z.]+)", "[NAMA_DOKTER], \\1", text, flags=re.IGNORECASE)

    # Jika masih ada "Putri, dr. [NAMA_DOKTER]" atau sejenisnya
    text = re.sub(
        r"\b([A-Z][a-zA-Z]+)\s*,\s*dr\.\s*\[NAMA_DOKTER\]",
        "dr. [NAMA_DOKTER]",
        text
    )

    # ========================================================
    # 12. Rapikan spasi
    # ========================================================
    text = normalize_spaces(text)

    return text


def main():
    txt_files = list(IN_DIR.rglob("*.txt"))

    if not txt_files:
        print(f"Tidak ada file TXT di folder {IN_DIR}.")
        print("Jalankan dulu extract_pdf_text.py.")
        return

    print(f"Menemukan {len(txt_files)} file TXT untuk dianonimkan.\n")

    for txt_path in txt_files:
        relative_path = txt_path.relative_to(IN_DIR)
        out_path = OUT_DIR / relative_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Anonimisasi: {txt_path}")

        text = txt_path.read_text(encoding="utf-8", errors="ignore")
        anonymized = anonymize_text(text)
        out_path.write_text(anonymized, encoding="utf-8")

        print(f"Berhasil disimpan ke: {out_path}\n")

    print("Selesai. Semua file hasil anonimisasi ada di folder 03_anonymized_text.")


if __name__ == "__main__":
    main()