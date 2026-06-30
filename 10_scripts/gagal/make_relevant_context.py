from pathlib import Path
import re
import hashlib
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
ANON_DIR = BASE_DIR / "03_anonymized_text"

PATIENT_ID = "STROKE_001"
PATIENT_DIR = ANON_DIR / PATIENT_ID
OUTPUT_FILE = PATIENT_DIR / f"{PATIENT_ID}_relevant_context_compact.txt"

# Batas maksimal karakter output final
MAX_TOTAL_CHARS = 15000

# Maksimal snippet per kategori
MAX_SNIPPETS_PER_GROUP = {
    "DIAGNOSIS_STROKE": 4,
    "ONSET_CHIEF_COMPLAINT": 5,
    "NEURO_EXAM": 5,
    "VITAL_SIGNS": 4,
    "LAB": 6,
    "RADIOLOGY_CT": 6,
    "THERAPY_CP_AUDIT": 6,
    "OUTCOME_LOS": 4,
}

KEYWORD_GROUPS = {
    "DIAGNOSIS_STROKE": [
        "stroke", "cva", "cvd", "infark", "infarct", "iskemik", "ischemic",
        "snh", "stroke non hemoragik", "hemoragik", "hemorrhagic",
        "ich", "intracerebral", "pis", "perdarahan intraserebral",
        "sah", "sab", "subarachnoid", "ivh", "tia"
    ],

    "ONSET_CHIEF_COMPLAINT": [
        "onset", "sejak", "smrs", "last known well", "tadi pagi",
        "tadi malam", "bangun tidur", "keluhan utama",
        "lemah", "kelemahan", "anggota gerak", "bicara pelo",
        "pelo", "afasia", "sulit bicara", "mulut mencong",
        "baal", "kebas", "penurunan kesadaran", "kejang",
        "nyeri kepala", "sakit kepala", "muntah"
    ],

    "NEURO_EXAM": [
        "gcs", "e4m6v5", "e4v5m6", "compos mentis", "cm",
        "somnolen", "sopor", "koma", "hemiparese", "hemiparesis",
        "hemiplegi", "hemiplegia", "parese", "lateralisasi",
        "motorik", "kekuatan motorik", "dekstra", "dextra",
        "kanan", "sinistra", "kiri", "nihss", "mrs"
    ],

    "VITAL_SIGNS": [
        "td", "tensi", "tekanan darah", "bp", "nadi", "rr",
        "suhu", "spo2", "saturasi"
    ],

    "LAB": [
        "hb", "hemoglobin", "leukosit", "wbc", "trombosit", "platelet",
        "gds", "gdp", "glukosa", "gula darah", "hba1c",
        "ureum", "kreatinin", "creatinine", "natrium", "sodium",
        "kalium", "potassium", "pt", "aptt", "inr",
        "ldl", "hdl", "trigliserida", "urin rutin"
    ],

    "RADIOLOGY_CT": [
        "ct scan", "ct-scan", "msct", "kepala", "cerebri",
        "infark", "infarct", "hipodens", "perdarahan",
        "hemorrhage", "ich", "pis", "sah", "sab", "ivh",
        "edema", "midline shift", "hidrosefalus", "atrofi",
        "lacunar", "lakunar", "basal ganglia", "thalamus",
        "talamus", "pons", "cerebellum", "serebelum",
        "capsula interna", "frontal", "parietal", "temporal",
        "occipital", "mca", "aca", "pca"
    ],

    "THERAPY_CP_AUDIT": [
        "aspirin", "asetosal", "clopidogrel", "cilostazol",
        "antiplatelet", "statin", "atorvastatin", "simvastatin",
        "rosuvastatin", "antikoagulan", "heparin", "enoxaparin",
        "antihipertensi", "amlodipin", "captopril", "nicardipine",
        "nikardipin", "labetalol", "manitol", "mannitol",
        "citicoline", "konsul neurologi", "dpjp saraf", "dokter saraf",
        "bedah saraf", "icu", "hcu", "rehab medik", "fisioterapi",
        "mobilisasi", "skrining menelan", "swallowing", "disfagia",
        "gizi", "edukasi", "risiko jatuh", "obat pulang"
    ],

    "OUTCOME_LOS": [
        "tanggal masuk", "tgl masuk", "masuk rs", "tanggal keluar",
        "tgl keluar", "tanggal pulang", "tgl pulang", "lama rawat",
        "los", "pulang", "meninggal", "dirujuk", "aps",
        "membaik", "perbaikan", "resume pulang", "kontrol"
    ]
}

# Prioritas file. Yang lebih tinggi diproses dulu.
DOC_PRIORITY_ORDER = {
    "resume": 1,
    "radiology": 2,
    "lab": 3,
    "cppt_igd": 4,
    "cppt_ranap": 5,
    "other": 9,
}


def get_doc_type(filename: str) -> str:
    name = filename.lower()

    if "resume" in name:
        return "resume"
    if "rad" in name or "radiologi" in name or "ct" in name:
        return "radiology"
    if "lab" in name or "laboratorium" in name:
        return "lab"
    if "cppt_igd" in name or ("cppt" in name and "igd" in name):
        return "cppt_igd"
    if "cppt_ranap" in name or "ranap" in name or "rawat_inap" in name:
        return "cppt_ranap"

    return "other"


def clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    return line


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def make_soft_paragraphs(text: str, max_lines_per_block=4):
    """
    Menggabungkan beberapa baris pendek supaya kalimat yang pecah 2-5 baris
    bisa terbaca sebagai satu blok.
    """
    lines = [clean_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    blocks = []
    buffer = []

    for line in lines:
        buffer.append(line)

        # Jika sudah 4 baris, atau baris tampak berakhir kalimat, tutup blok
        if len(buffer) >= max_lines_per_block or re.search(r"[.!?;:]$", line):
            blocks.append(" ".join(buffer))
            buffer = []

    if buffer:
        blocks.append(" ".join(buffer))

    return blocks


def keyword_found(text: str, keywords):
    text_lower = text.lower()
    found = []

    for kw in keywords:
        kw_lower = kw.lower()

        # Keyword pendek harus exact word
        if len(kw_lower) <= 3:
            pattern = r"\b" + re.escape(kw_lower) + r"\b"
            if re.search(pattern, text_lower):
                found.append(kw)
        else:
            if kw_lower in text_lower:
                found.append(kw)

    return found


def snippet_hash(snippet: str) -> str:
    """
    Membuat hash agar snippet duplikat tidak masuk berkali-kali.
    """
    normalized = re.sub(r"\s+", " ", snippet.lower()).strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def extract_compact_snippets(blocks, keywords, before=1, after=1, max_snippets=5):
    snippets = []
    seen = set()

    for i, block in enumerate(blocks):
        found = keyword_found(block, keywords)
        if not found:
            continue

        start = max(0, i - before)
        end = min(len(blocks), i + after + 1)
        snippet = " ".join(blocks[start:end])

        # Batasi panjang snippet individual
        if len(snippet) > 900:
            snippet = snippet[:900] + " ...[truncated]"

        h = snippet_hash(snippet)
        if h in seen:
            continue

        seen.add(h)
        snippets.append({
            "matched_keywords": sorted(set(found)),
            "snippet": snippet
        })

        if len(snippets) >= max_snippets:
            break

    return snippets


def group_allowed_for_doc(group_name: str, doc_type: str) -> bool:
    """
    Mengurangi duplikasi:
    - Radiologi fokus ke RADIOLOGY_CT dan diagnosis.
    - Lab fokus ke LAB.
    - CPPT ranap fokus ke terapi dan outcome.
    """
    if doc_type == "radiology":
        return group_name in ["RADIOLOGY_CT", "DIAGNOSIS_STROKE"]

    if doc_type == "lab":
        return group_name in ["LAB"]

    if doc_type == "resume":
        return group_name in [
            "DIAGNOSIS_STROKE",
            "RADIOLOGY_CT",
            "LAB",
            "THERAPY_CP_AUDIT",
            "OUTCOME_LOS",
            "NEURO_EXAM"
        ]

    if doc_type == "cppt_igd":
        return group_name in [
            "ONSET_CHIEF_COMPLAINT",
            "NEURO_EXAM",
            "VITAL_SIGNS",
            "DIAGNOSIS_STROKE",
            "THERAPY_CP_AUDIT"
        ]

    if doc_type == "cppt_ranap":
        return group_name in [
            "THERAPY_CP_AUDIT",
            "OUTCOME_LOS",
            "NEURO_EXAM"
        ]

    return True


def process_patient():
    if not PATIENT_DIR.exists():
        raise FileNotFoundError(f"Folder pasien tidak ditemukan: {PATIENT_DIR}")

    txt_files = [
        f for f in PATIENT_DIR.glob("*.txt")
        if "relevant_context" not in f.name.lower()
    ]

    if not txt_files:
        raise FileNotFoundError(f"Tidak ada file .txt di folder: {PATIENT_DIR}")

    # Urutkan berdasarkan prioritas dokumen
    txt_files = sorted(
        txt_files,
        key=lambda f: (DOC_PRIORITY_ORDER.get(get_doc_type(f.name), 9), f.name.lower())
    )

    grouped_results = defaultdict(list)
    documents_found = []

    global_seen_snippets = set()

    for txt_file in txt_files:
        doc_type = get_doc_type(txt_file.name)
        documents_found.append((txt_file.name, doc_type))

        text = txt_file.read_text(encoding="utf-8", errors="ignore")
        text = normalize_text(text)
        blocks = make_soft_paragraphs(text, max_lines_per_block=4)

        for group_name, keywords in KEYWORD_GROUPS.items():
            if not group_allowed_for_doc(group_name, doc_type):
                continue

            max_snippets = MAX_SNIPPETS_PER_GROUP.get(group_name, 4)

            # Untuk CPPT ranap dibuat lebih hemat
            if doc_type == "cppt_ranap":
                max_snippets = min(max_snippets, 3)

            snippets = extract_compact_snippets(
                blocks=blocks,
                keywords=keywords,
                before=1,
                after=1,
                max_snippets=max_snippets
            )

            for s in snippets:
                h = snippet_hash(s["snippet"])
                if h in global_seen_snippets:
                    continue

                global_seen_snippets.add(h)

                grouped_results[group_name].append({
                    "source_file": txt_file.name,
                    "doc_type": doc_type,
                    "matched_keywords": s["matched_keywords"],
                    "snippet": s["snippet"]
                })

    output_parts = []

    output_parts.append(f"PATIENT_ID: {PATIENT_ID}")
    output_parts.append("")
    output_parts.append("===== DOCUMENTS FOUND =====")
    for filename, doc_type in documents_found:
        output_parts.append(f"- {filename} | doc_type: {doc_type}")

    output_parts.append("")
    output_parts.append("===== INSTRUCTION FOR LLM =====")
    output_parts.append("Filtered anonymized EMR context.")
    output_parts.append("Extract only explicitly documented information.")
    output_parts.append("Do not guess undocumented NIHSS, mRS, onset, diagnosis, or treatment.")
    output_parts.append("Use unknown if not found and unclear if ambiguous.")
    output_parts.append("")

    for group_name in KEYWORD_GROUPS.keys():
        output_parts.append("")
        output_parts.append(f"===== {group_name} =====")

        entries = grouped_results.get(group_name, [])

        if not entries:
            output_parts.append("[NO RELEVANT SNIPPET FOUND]")
            continue

        max_entries = MAX_SNIPPETS_PER_GROUP.get(group_name, 4)

        for idx, item in enumerate(entries[:max_entries], start=1):
            kws = ", ".join(item["matched_keywords"])
            output_parts.append("")
            output_parts.append(
                f"[{idx}] source: {item['source_file']} | "
                f"doc_type: {item['doc_type']} | matched: {kws}"
            )
            output_parts.append(item["snippet"])

    final_text = "\n".join(output_parts)

    if len(final_text) > MAX_TOTAL_CHARS:
        final_text = final_text[:MAX_TOTAL_CHARS]
        final_text += "\n\n...[OUTPUT TRUNCATED BECAUSE MAX_TOTAL_CHARS WAS REACHED]"

    OUTPUT_FILE.write_text(final_text, encoding="utf-8")

    print("SELESAI")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Jumlah karakter output: {len(final_text)}")


if __name__ == "__main__":
    process_patient()