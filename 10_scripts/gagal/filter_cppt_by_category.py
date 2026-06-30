from pathlib import Path
import re
import csv
from datetime import datetime
from collections import defaultdict

# ============================================================
# SCRIPT: filter_cppt_by_category.py
# Tujuan:
#   Memfilter dan "meringkas" CPPT panjang menjadi CPPT klinis
#   terstruktur per kategori agar lebih ringan dibaca LLM.
#
# Input:
#   03_anonymized_text/STROKE_001/cppt igd.txt
#   03_anonymized_text/STROKE_001/cppt ranap.txt
#
# Output:
#   05_filtered_text/STROKE_001/cppt igd filtered categorized.txt
#   05_filtered_text/STROKE_001/cppt ranap filtered categorized.txt
#
# Cara pakai:
#   1. Simpan file ini di folder 08_scripts
#   2. Buka CMD/Terminal di folder 08_scripts
#   3. Jalankan:
#        python filter_cppt_by_category.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "03_anonymized_text"
OUTPUT_DIR = BASE_DIR / "05_filtered_text"
LOG_DIR = BASE_DIR / "09_logs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Script hanya memproses file .txt yang namanya mengandung kata ini.
CPPT_FILE_PATTERNS = [
    "cppt",
]

# Ambil konteks sekitar baris penting.
# 1 artinya: 1 baris sebelum + baris keyword + 1 baris sesudah.
CONTEXT_BEFORE = 1
CONTEXT_AFTER = 1

# Kalau hasil masih terlalu panjang, ubah menjadi angka, misalnya 25000.
# Kalau tidak ingin dibatasi, biarkan None.
MAX_CHARS_PER_OUTPUT = None

# ============================================================
# KATEGORI KEYWORD
# ============================================================

CATEGORY_KEYWORDS = {
    "01_EPISODE_PERAWATAN": [
        "igd", "ranap", "rawat inap", "tanggal masuk", "tanggal pulang",
        "rujuk", "alih rawat", "konsul", "dpjp", "neurologi", "penyakit saraf",
        "hcu", "icu", "krs", "mpp", "admission", "discharge",
    ],

    "02_ONSET_KRONOLOGI": [
        "onset", "sejak", "smrs", "hmrs", "jam", "pukul", "pk.",
        "tiba-tiba", "mendadak", "bangun tidur", "last known well", "lkw",
        "keluhan utama", "awalnya", "sebelumnya", "durasi", "hari", "minggu",
    ],

    "03_GEJALA_NEUROLOGIS": [
        "lemah", "kelemahan", "lumpuh", "paresis", "parese", "hemiparesis",
        "hemiparese", "hemiplegi", "hemiplegia", "pelo", "bicara pelo",
        "bicara tidak jelas", "afasia", "disartria", "mulut mencong",
        "wajah mencong", "deviasi", "baal", "kebas", "kesemutan",
        "penurunan kesadaran", "tidak sadar", "kejang", "nyeri kepala hebat",
        "sakit kepala hebat", "muntah", "vertigo", "gangguan penglihatan",
        "pandangan kabur", "diplopia", "sulit menelan", "disfagia", "tersedak",
    ],

    "04_PEMERIKSAAN_NEUROLOGIS": [
        "gcs", "e1", "e2", "e3", "e4", "m1", "m2", "m3", "m4", "m5", "m6",
        "v1", "v2", "v3", "v4", "v5", "compos mentis", "composmentis",
        "apatis", "somnolen", "sopor", "koma", "pupil", "isokor", "anisokor",
        "refleks cahaya", "lateralisasi", "motorik", "sensorik", "nervus",
        "nihss", "mrs", "rankin", "babinski", "refleks patologis",
        "kekuatan", "kekuatan otot", "ekstremitas", "dekstra", "sinistra",
        "kanan", "kiri", "n. vii", "n vii", "nervus vii", "fasialis",
    ],

    "05_VITAL_SIGN_KONDISI_AWAL": [
        "td", "tensi", "tekanan darah", "nadi", "rr", "napas", "spo2",
        "saturasi", "suhu", "gds", "gula darah", "hiperglikemia",
        "hipoglikemia", "hipertensi", "hipotensi", "demam", "hemodinamik",
        "kesadaran", "nyeri",
    ],

    "06_DIAGNOSIS_KLASIFIKASI_STROKE": [
        "stroke", "cva", "snh", "snhem", "snh ec", "snh trombotik",
        "snh emboli", "snh kardioemboli", "stroke iskemik", "stroke infark",
        "infark serebri", "infark cerebri", "sh", "ich", "pis",
        "perdarahan intraserebral", "perdarahan intra serebral",
        "sah", "perdarahan subaraknoid", "sdh", "edh", "tia",
        "transient ischemic attack", "stroke mimic",
    ],

    "07_RADIOLOGI_CT_MRI": [
        "ct", "ct scan", "msct", "mri", "mra", "cta", "angiografi",
        "radiologi", "kesan", "infark", "iskemik", "ischemic", "hipodens",
        "hiperdens", "perdarahan", "hemorrhage", "hemoragik", "ich", "sah",
        "sdh", "edh", "midline shift", "edema cerebri", "edema serebri",
        "lakunar", "lacunar", "atrofi", "hidrosefalus", "sumbatan",
        "oklusi", "stenosis", "sinusitis", "lesi",
    ],

    "08_LAB_PENTING": [
        "hb", "hemoglobin", "leukosit", "trombosit", "hematokrit",
        "pt", "aptt", "inr", "gds", "gdp", "gd2pp", "hba1c",
        "ureum", "kreatinin", "egfr", "natrium", "kalium", "chlorida",
        "klorida", "kolesterol", "ldl", "hdl", "trigliserida", "asam urat",
        "troponin", "d-dimer", "ddimer", "crp", "sgot", "sgpt", "albumin",
    ],

    "09_KOMORBID_FAKTOR_RISIKO": [
        "hipertensi", "ht", "diabetes", "dm", "dislipidemia", "kolesterol",
        "af", "atrial fibrillation", "fibrilasi atrium", "penyakit jantung",
        "pjk", "chf", "gagal jantung", "ckd", "gagal ginjal",
        "riwayat stroke", "stroke sebelumnya", "tia", "merokok", "obesitas",
        "hiperurisemia", "asam urat", "sirosis", "keganasan", "ca ",
    ],

    "10_TERAPI_AKUT_DAN_RAWAT": [
        "aspilet", "asetosal", "aspirin", "clopidogrel", "simarc", "warfarin",
        "heparin", "enoxaparin", "rivaroxaban", "apixaban", "atorvastatin",
        "simvastatin", "rosuvastatin", "alteplase", "rtpa", "trombolisis",
        "thrombolysis", "antiplatelet", "antikoagulan", "manitol",
        "citicoline", "sitikolin", "neuroprotector", "amlodipin",
        "candesartan", "nicardipine", "labetalol", "insulin", "rehab medik",
        "fisioterapi", "terapi wicara", "ngt", "sonde", "diet", "oksigen",
    ],

    "11_SWALLOWING_NUTRISI_KOMPLIKASI": [
        "disfagia", "sulit menelan", "tidak bisa menelan", "tersedak",
        "batuk saat minum", "ngt", "sonde", "aspirasi", "pneumonia",
        "infeksi paru", "isk", "infeksi saluran kemih", "infeksi", "demam",
        "sepsis", "dekubitus", "dvt", "kejang", "perburukan neurologis",
        "penurunan kesadaran", "edema otak", "edema cerebri", "malnutrisi",
    ],

    "12_REHABILITASI_FUNGSIONAL": [
        "fisioterapi", "rehab medik", "mobilisasi", "latihan gerak", "rom",
        "duduk", "berdiri", "jalan", "alat bantu", "terapi wicara",
        "terapi okupasi", "adl", "activity daily living",
    ],

    "13_OUTCOME_KONDISI_PULANG": [
        "pulang", "kontrol", "rawat jalan", "rujuk", "alih rawat", "icu",
        "hcu", "meninggal", "death", "krs", "aps", "pulang paksa",
        "membaik", "stabil", "perburukan", "defisit menetap", "masih lemah",
        "masih pelo", "mrs", "modified rankin", "rankin", "prognosis",
    ],
}

# Pola regex tambahan untuk menangkap data yang sering tidak terdeteksi keyword biasa.
REGEX_PATTERNS = {
    "04_PEMERIKSAAN_NEUROLOGIS": [
        r"\bE[1-4]\s*M[1-6]\s*V[1-5]\b",     # E4M6V5
        r"\b[0-5]\s*/\s*[0-5]\b",            # 3/5, 4/5
        r"\b[0-5]{4}\s*/\s*[0-5]{4}\b",      # 5555/3333
    ],
    "05_VITAL_SIGN_KONDISI_AWAL": [
        r"\bTD\s*[:=]?\s*\d{2,3}\s*/\s*\d{2,3}\b",
        r"\b\d{2,3}\s*/\s*\d{2,3}\s*mmhg\b",
        r"\bGDS\s*[:=]?\s*\d{2,3}\b",
        r"\bSpO2\s*[:=]?\s*\d{2,3}\s*%?\b",
    ],
    "08_LAB_PENTING": [
        r"\bHb\s*[:=]?\s*\d+([,.]\d+)?\b",
        r"\bLeukosit\s*[:=]?\s*\d+([,.]\d+)?\b",
        r"\bTrombosit\s*[:=]?\s*\d+([,.]\d+)?\b",
        r"\bINR\s*[:=]?\s*\d+([,.]\d+)?\b",
        r"\bNa\s*[:=]?\s*\d+([,.]\d+)?\b",
        r"\bK\s*[:=]?\s*\d+([,.]\d+)?\b",
    ],
}

# Baris noise yang boleh dibuang bila tidak mengandung keyword.
LOW_VALUE_PATTERNS = [
    r"^pasien tampak tidur\.?$",
    r"^keluarga mendampingi\.?$",
    r"^instruksi dokter dilanjutkan\.?$",
    r"^terapi dilanjutkan\.?$",
    r"^terapi oral diberikan\.?$",
    r"^pasien sudah makan\.?$",
    r"^edukasi diberikan\.?$",
    r"^observasi lanjut\.?$",
    r"^monitoring lanjut\.?$",
    r"^acc\.?$",
    r"^ok\.?$",
]

def normalize_line(line: str) -> str:
    line = line.replace("\x00", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return line

def is_cppt_file(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and path.suffix.lower() == ".txt" and any(pat in name for pat in CPPT_FILE_PATTERNS)

def line_categories(line: str):
    """
    Kembalikan daftar kategori yang cocok untuk satu baris.
    Satu baris bisa masuk beberapa kategori.
    """
    low = line.lower()
    matched = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in low:
                matched.append(category)
                break

    for category, patterns in REGEX_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, line, flags=re.IGNORECASE):
                if category not in matched:
                    matched.append(category)
                break

    return matched

def is_low_value(line: str) -> bool:
    low = line.lower().strip()
    return any(re.search(pattern, low, flags=re.IGNORECASE) for pattern in LOW_VALUE_PATTERNS)

def dedup_key(line: str) -> str:
    """
    Key untuk mengurangi duplikasi.
    Tanggal/jam dinormalisasi supaya kalimat sama berulang tidak terlalu banyak.
    """
    x = line.lower()
    x = re.sub(r"\d{1,2}[:.]\d{2}", "[TIME]", x)
    x = re.sub(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", "[DATE]", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x

def read_text_safely(path: Path) -> str:
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")

def extract_categorized_lines(lines):
    """
    Ambil baris penting dan kelompokkan per kategori.
    Bila satu baris cocok keyword, konteks sebelum/sesudah juga ikut masuk
    ke kategori yang sama.
    """
    category_to_items = defaultdict(list)
    seen_per_category = defaultdict(set)

    for i, line in enumerate(lines):
        cats = line_categories(line)
        if not cats:
            continue

        start = max(0, i - CONTEXT_BEFORE)
        end = min(len(lines), i + CONTEXT_AFTER + 1)

        for cat in cats:
            for j in range(start, end):
                context_line = lines[j]
                if not context_line:
                    continue

                # Buang baris noise jika baris itu sendiri tidak cocok kategori apa pun.
                if is_low_value(context_line) and not line_categories(context_line):
                    continue

                key = dedup_key(context_line)
                if key in seen_per_category[cat]:
                    continue

                seen_per_category[cat].add(key)
                category_to_items[cat].append((j + 1, context_line))

    return category_to_items

def write_output(input_file: Path, output_file: Path, category_to_items, total_lines: int):
    output_file.parent.mkdir(parents=True, exist_ok=True)

    total_selected = sum(len(items) for items in category_to_items.values())

    content = []
    content.append("=== CPPT FILTERED TERSTRUKTUR UNTUK LLM ===")
    content.append(f"Source file: {input_file.name}")
    content.append(f"Total baris asli: {total_lines}")
    content.append(f"Total baris terpilih lintas kategori: {total_selected}")
    content.append(f"Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append("")
    content.append("Catatan:")
    content.append("- File ini adalah hasil filter keyword/regex + konteks.")
    content.append("- Satu baris bisa muncul di lebih dari satu kategori jika relevan.")
    content.append("- Gunakan sebagai input LLM setelah data dianonimkan.")
    content.append("- Jika kategori kosong, artinya tidak terdeteksi dari CPPT tersebut, bukan berarti pasti tidak ada.")
    content.append("")

    if not category_to_items:
        content.append("[TIDAK ADA BARIS CPPT YANG COCOK DENGAN KEYWORD/REGEX]")
    else:
        for category in CATEGORY_KEYWORDS.keys():
            items = category_to_items.get(category, [])
            title = category.replace("_", " ")
            content.append("")
            content.append(f"=== {title} ===")

            if not items:
                content.append("[tidak terdeteksi]")
            else:
                for line_no, line in items:
                    content.append(f"[baris {line_no}] {line}")

    final_text = "\n".join(content)

    if MAX_CHARS_PER_OUTPUT is not None and len(final_text) > MAX_CHARS_PER_OUTPUT:
        final_text = final_text[:MAX_CHARS_PER_OUTPUT]
        final_text += "\n\n[TERPOTONG KARENA MELEBIHI MAX_CHARS_PER_OUTPUT]\n"

    output_file.write_text(final_text, encoding="utf-8")

def main():
    if not INPUT_DIR.exists():
        print(f"ERROR: Folder input tidak ditemukan: {INPUT_DIR}")
        print("Pastikan folder 03_anonymized_text ada di root project.")
        return

    cppt_files = [p for p in INPUT_DIR.rglob("*.txt") if is_cppt_file(p)]

    if not cppt_files:
        print("Tidak ditemukan file CPPT .txt di folder 03_anonymized_text.")
        print("Pastikan nama file mengandung kata 'cppt'.")
        return

    log_rows = []

    for input_file in cppt_files:
        rel_path = input_file.relative_to(INPUT_DIR)
        patient_folder = rel_path.parent

        output_name = input_file.stem + " filtered categorized.txt"
        output_file = OUTPUT_DIR / patient_folder / output_name

        raw_text = read_text_safely(input_file)
        lines = [normalize_line(line) for line in raw_text.splitlines()]
        lines = [line for line in lines if line]

        category_to_items = extract_categorized_lines(lines)
        write_output(input_file, output_file, category_to_items, len(lines))

        total_selected = sum(len(items) for items in category_to_items.values())
        categories_detected = [cat for cat, items in category_to_items.items() if items]

        log_rows.append({
            "patient_folder": str(patient_folder),
            "input_file": str(rel_path),
            "output_file": str(output_file.relative_to(BASE_DIR)),
            "total_lines": len(lines),
            "selected_lines_across_categories": total_selected,
            "categories_detected_count": len(categories_detected),
            "categories_detected": "; ".join(sorted(categories_detected)),
        })

        print(f"OK: {rel_path} -> {output_file.relative_to(BASE_DIR)}")
        print(f"    Baris asli: {len(lines)} | Baris terpilih lintas kategori: {total_selected}")
        print(f"    Kategori terdeteksi: {len(categories_detected)}")

    log_file = LOG_DIR / "filter_cppt_by_category_log.csv"
    with log_file.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "patient_folder",
            "input_file",
            "output_file",
            "total_lines",
            "selected_lines_across_categories",
            "categories_detected_count",
            "categories_detected",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(log_rows)

    print("")
    print("Selesai.")
    print(f"Total file CPPT diproses: {len(log_rows)}")
    print(f"Hasil filter ada di: {OUTPUT_DIR.relative_to(BASE_DIR)}")
    print(f"Log tersimpan di: {log_file.relative_to(BASE_DIR)}")

if __name__ == "__main__":
    main()
