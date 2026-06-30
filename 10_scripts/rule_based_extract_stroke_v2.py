from pathlib import Path
import re
import json
import csv
from datetime import datetime

# ============================================================
# RULE-BASED EXTRACT DATA STROKE - VERSION 2
#
# Fungsi:
# - Membaca semua folder pasien di 03_anonymized_text/STROKE_001/*.txt
# - Ekstrak data eksplisit dengan Python/regex:
#   GCS, TD, lab utama, NIHSS, obat/tindakan CP, diagnosis, radiologi CT
# - Output:
#   04_rule_based_output/STROKE_001_rule_based.json
#   05_dataset_excel/stroke_rule_based_dataset.csv
#   05_dataset_excel/stroke_rule_based_dataset.xlsx  (kalau openpyxl tersedia)
#
# Jalankan dari folder scripts:
#   python rule_based_extract_stroke_v2.py
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
ANON_DIR = BASE_DIR / "03_anonymized_text"
OUT_JSON_DIR = BASE_DIR / "04_rule_based_output"
OUT_DATASET_DIR = BASE_DIR / "05_dataset_excel"

OUT_JSON_DIR.mkdir(parents=True, exist_ok=True)
OUT_DATASET_DIR.mkdir(parents=True, exist_ok=True)

# Isi "STROKE_001" kalau mau 1 pasien saja.
# Isi None kalau mau semua folder pasien di 03_anonymized_text.
PATIENT_ID_FILTER = "STROKE_001"

DATASET_CSV = OUT_DATASET_DIR / "stroke_rule_based_dataset.csv"
DATASET_XLSX = OUT_DATASET_DIR / "stroke_rule_based_dataset.xlsx"


# ============================================================
# UTILITY
# ============================================================

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text

def clean_snippet(text: str, max_len: int = 500) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len] + " ...[truncated]"
    return text

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

def read_patient_files(patient_dir: Path):
    files = []
    for fp in sorted(patient_dir.glob("*.txt")):
        low = fp.name.lower()
        if "relevant_context" in low or "rule_based" in low:
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        files.append({
            "source_file": fp.name,
            "doc_type": get_doc_type(fp.name),
            "text": normalize_text(text),
            "char_count": len(text)
        })
    return files

def context(text, start, end, radius=100, max_len=450):
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return clean_snippet(text[a:b], max_len=max_len)

def first_by_priority(candidates):
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x.get("priority", 9), x.get("pos", 10**9)))[0]

def number_str(x):
    if x is None:
        return "unknown"
    x = str(x).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", x)
    return m.group(0) if m else "unknown"


# ============================================================
# DIAGNOSIS
# ============================================================

def extract_diagnosis(files):
    patterns = [
        r".{0,80}(stroke\s+infark|stroke\s+iskemik|stroke\s+non\s+hemoragik|SNH|infark\s+cerebri|cerebral\s+infarct).{0,150}",
        r".{0,80}(stroke\s+hemoragik|SH|ICH|PIS|SAH|SAB|IVH|perdarahan\s+intracerebral|perdarahan\s+intraserebral|perdarahan\s+subarachnoid).{0,150}",
        r".{0,80}(diagnosis|diagnosa|assessment|asesmen|kesimpulan).{0,200}(stroke|infark|iskemik|hemoragik|ICH|PIS|SAH|SAB|IVH).{0,200}",
    ]
    pr = {"resume": 1, "radiology": 2, "cppt_igd": 3, "cppt_ranap": 4, "other": 5}
    candidates = []
    for f in files:
        if f["doc_type"] not in pr:
            continue
        for pat in patterns:
            for m in re.finditer(pat, f["text"], flags=re.I | re.S):
                ev = clean_snippet(m.group(0), 450)
                candidates.append({
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": pr.get(f["doc_type"], 9),
                    "pos": m.start(),
                    "evidence": ev
                })
    best = first_by_priority(candidates)
    if not best:
        return {"stroke_type_rule": "unknown", "diagnosis_text_rule": "unknown", "evidence": "", "all_candidates": []}

    low = best["evidence"].lower()
    ischemic_terms = ["stroke infark", "stroke iskemik", "stroke non hemoragik", "snh", "infark cerebri", "cerebral infarct", "iskemik"]
    hemorrhagic_terms = ["stroke hemoragik", "ich", "pis", "sah", "sab", "ivh", "perdarahan", "hemoragik"]

    is_isch = any(t in low for t in ischemic_terms)
    is_hemo = any(t in low for t in hemorrhagic_terms)

    if is_isch and not is_hemo:
        stype = "ischemic"
    elif is_hemo and not is_isch:
        stype = "hemorrhagic"
    elif is_isch and is_hemo:
        stype = "mixed_or_unclear"
    else:
        stype = "unclear"

    return {
        "stroke_type_rule": stype,
        "diagnosis_text_rule": best["evidence"],
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:10]
    }


# ============================================================
# GCS, TD, NIHSS
# ============================================================

def extract_gcs(files):
    candidates = []
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3, "other": 4}

    component_patterns = [
        r"\bGCS\s*[:=]?\s*E\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
        r"\bGCS\s*[:=]?\s*E\s*(\d)\s*V\s*(\d)\s*M\s*(\d)\b",
        r"\bE\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
        r"\bE\s*(\d)\s*V\s*(\d)\s*M\s*(\d)\b",
    ]
    total_patterns = [
        r"\bGCS\s*[:=]?\s*(1[0-5]|[3-9])\b",
        r"\bGlasgow\s*Coma\s*Scale\s*[:=]?\s*(1[0-5]|[3-9])\b",
    ]
    consciousness_patterns = [
        r"\bcompos\s*mentis\b", r"\bCM\b", r"\bsomnolen\b",
        r"\bsopor\b", r"\bkoma\b", r"\bapatis\b", r"\bdelirium\b"
    ]
    consciousness = "unknown"

    for f in files:
        if f["doc_type"] not in pr:
            continue
        text = f["text"]
        for pat in total_patterns:
            for m in re.finditer(pat, text, flags=re.I):
                candidates.append({
                    "value": m.group(1),
                    "text": m.group(0),
                    "source_file": f["source_file"],
                    "priority": pr.get(f["doc_type"], 9),
                    "pos": m.start(),
                    "evidence": context(text, m.start(), m.end())
                })
        for pat in component_patterns:
            for m in re.finditer(pat, text, flags=re.I):
                nums = [int(x) for x in m.groups()]
                candidates.append({
                    "value": str(sum(nums)),
                    "text": m.group(0),
                    "source_file": f["source_file"],
                    "priority": pr.get(f["doc_type"], 9),
                    "pos": m.start(),
                    "evidence": context(text, m.start(), m.end())
                })
        for pat in consciousness_patterns:
            m = re.search(pat, text, flags=re.I)
            if m and consciousness == "unknown":
                consciousness = m.group(0)

    best = first_by_priority(candidates)
    if not best:
        return {"gcs_initial_total": "unknown", "gcs_initial_text": "unknown", "consciousness_text": consciousness, "evidence": "", "all_candidates": []}

    return {
        "gcs_initial_total": best["value"],
        "gcs_initial_text": best["text"],
        "consciousness_text": consciousness,
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:10]
    }

def extract_bp(files):
    patterns = [
        r"\bTD\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bTensi\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bTekanan\s*Darah\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bBP\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
    ]
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3, "other": 4}
    candidates = []
    for f in files:
        if f["doc_type"] not in pr:
            continue
        for pat in patterns:
            for m in re.finditer(pat, f["text"], flags=re.I):
                sbp, dbp = int(m.group(1)), int(m.group(2))
                if 50 <= sbp <= 300 and 30 <= dbp <= 200:
                    candidates.append({
                        "blood_pressure_initial": f"{sbp}/{dbp}",
                        "systolic_bp_initial": str(sbp),
                        "diastolic_bp_initial": str(dbp),
                        "source_file": f["source_file"],
                        "priority": pr.get(f["doc_type"], 9),
                        "pos": m.start(),
                        "evidence": context(f["text"], m.start(), m.end())
                    })
    best = first_by_priority(candidates)
    if not best:
        return {"blood_pressure_initial": "unknown", "systolic_bp_initial": "unknown", "diastolic_bp_initial": "unknown", "evidence": "", "all_candidates": []}
    out = dict(best)
    out["all_candidates"] = candidates[:10]
    return out

def extract_nihss(files):
    patterns = [r"\bNIHSS\s*[:=]?\s*(\d{1,2})\b", r"\bNIH\s*Stroke\s*Scale\s*[:=]?\s*(\d{1,2})\b"]
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3, "other": 4}
    candidates = []
    for f in files:
        if f["doc_type"] not in pr:
            continue
        for pat in patterns:
            for m in re.finditer(pat, f["text"], flags=re.I):
                score = int(m.group(1))
                if 0 <= score <= 42:
                    candidates.append({
                        "nihss_score": str(score),
                        "source_file": f["source_file"],
                        "priority": pr.get(f["doc_type"], 9),
                        "pos": m.start(),
                        "evidence": context(f["text"], m.start(), m.end())
                    })
    best = first_by_priority(candidates)
    if not best:
        return {"nihss_documented": "no", "nihss_score": "unknown", "evidence": "", "all_candidates": []}
    return {"nihss_documented": "yes", "nihss_score": best["nihss_score"], "source_file": best["source_file"], "evidence": best["evidence"], "all_candidates": candidates[:10]}


# ============================================================
# LAB
# ============================================================

LAB_PATTERNS = {
    "hb": [r"\bHb\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b", r"\bHemoglobin\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b"],
    "leukocyte": [r"\bLeukosit\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b", r"\bWBC\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b"],
    "platelet": [r"\bTrombosit\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b", r"\bPlatelet\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b", r"\bPLT\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b"],
    "random_blood_glucose": [r"\bGDS\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b", r"\bGlukosa\s*Sewaktu\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b", r"\bGula\s*Darah\s*Sewaktu\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b"],
    "fasting_blood_glucose": [r"\bGDP\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b", r"\bGlukosa\s*Puasa\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b"],
    "hba1c": [r"\bHbA1c\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b", r"\bA1c\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b"],
    "ureum": [r"\bUreum\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b", r"\bUrea\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b"],
    "creatinine": [r"\bKreatinin\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b", r"\bCreatinine\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b", r"\bCr\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b"],
    "sodium": [r"\bNatrium\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b", r"\bSodium\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b", r"\bNa\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b"],
    "potassium": [r"\bKalium\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b", r"\bPotassium\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b", r"\bK\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b"],
    "pt": [r"\bPT\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b"],
    "aptt": [r"\bAPTT\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b"],
    "inr": [r"\bINR\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b"],
    "ldl": [r"\bLDL\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b"],
    "total_cholesterol": [r"\bKolesterol\s*Total\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b", r"\bCholesterol\s*Total\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b"],
    "triglyceride": [r"\bTrigliserida\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b", r"\bTriglyceride\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b"],
}

def extract_labs(files):
    out = {k: {"value": "unknown", "source_file": "", "evidence": "", "all_candidates": []} for k in LAB_PATTERNS}
    pr = {"lab": 1, "resume": 2, "cppt_igd": 3, "cppt_ranap": 4, "other": 5}
    for lab, patterns in LAB_PATTERNS.items():
        candidates = []
        for f in files:
            if f["doc_type"] not in pr:
                continue
            for pat in patterns:
                for m in re.finditer(pat, f["text"], flags=re.I):
                    candidates.append({
                        "value": number_str(m.group(1)),
                        "raw": m.group(0),
                        "source_file": f["source_file"],
                        "priority": pr.get(f["doc_type"], 9),
                        "pos": m.start(),
                        "evidence": context(f["text"], m.start(), m.end())
                    })
        best = first_by_priority(candidates)
        if best:
            out[lab] = {"value": best["value"], "source_file": best["source_file"], "evidence": best["evidence"], "all_candidates": candidates[:10]}
    return out


# ============================================================
# RADIOLOGY CT
# ============================================================

def clean_radiology_admin(text: str) -> str:
    lines = []
    noise = [
        r"medical\s*record\s*number", r"no\.?\s*foto", r"no\.?\s*rm", r"telp", r"telepon",
        r"bandung", r"jawa\s*barat", r"x\s*ray\s*examination", r"dicetak",
        r"tanggal\s*cetak", r"nama\s*pasien", r"tanggal\s*lahir", r"alamat",
        r"dokter\s*pengirim", r"unit\s*asal", r"ruangan", r"jenis\s*kelamin",
    ]
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        low = line.lower()
        if any(re.search(p, low) for p in noise):
            continue
        lines.append(line)
    return "\n".join(lines)

def extract_radiology_sections(text: str):
    text = clean_radiology_admin(text)
    text = normalize_text(text)
    sections = []

    # Ambil terutama bagian setelah label hasil/kesan/expertise.
    patterns = [
        r"(?:HASIL|Hasil|hasil)\s*[:\-]?\s*(.{30,1500})",
        r"(?:KESAN|Kesan|kesan)\s*[:\-]?\s*(.{20,1200})",
        r"(?:KESIMPULAN|Kesimpulan|kesimpulan)\s*[:\-]?\s*(.{20,1200})",
        r"(?:EXPERTISE|Expertise|expertise)\s*[:\-]?\s*(.{30,1500})",
        r"(?:IMPRESSION|Impression|impression)\s*[:\-]?\s*(.{20,1200})",
    ]

    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I | re.S):
            snip = m.group(1)
            stop = re.search(r"\n\s*(?:Dokter|Tanda\s*Tangan|Catatan|Dicetak|No\.?\s*Foto|Medical\s*Record)\b", snip, flags=re.I)
            if stop:
                snip = snip[:stop.start()]
            snip = clean_snippet(snip, 900)
            if len(snip) >= 20:
                sections.append(snip)

    if not sections:
        pat = r".{0,80}(tidak\s+tampak|tampak|terlihat|didapatkan|kesan|infark|hipodens|perdarahan|ICH|PIS|SAH|SAB|IVH|edema|midline\s*shift|hidrosefalus|atrofi|lacunar|lakunar).{0,400}"
        for m in re.finditer(pat, text, flags=re.I | re.S):
            snip = clean_snippet(m.group(0), 700)
            if len(snip) >= 30:
                sections.append(snip)

    unique = []
    seen = set()
    for s in sections:
        key = re.sub(r"\s+", " ", s.lower()).strip()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:5]

def extract_radiology(files):
    candidates = []
    for f in files:
        if f["doc_type"] not in ["radiology", "resume", "cppt_igd", "cppt_ranap"]:
            continue
        for section in extract_radiology_sections(f["text"]):
            candidates.append({"source_file": f["source_file"], "doc_type": f["doc_type"], "text": section})

    candidates = sorted(candidates, key=lambda x: {"radiology": 1, "resume": 2, "cppt_igd": 3, "cppt_ranap": 4}.get(x["doc_type"], 9))

    if not candidates:
        return {
            "ct_scan_documented": "unknown", "ct_scan_result_text": "unknown", "ct_scan_source_file": "",
            "ct_scan_location": "unknown", "infarct_present": "unknown", "bleeding_present": "unknown",
            "ich_present": "unknown", "sah_sab_present": "unknown", "ivh_present": "unknown",
            "midline_shift_present": "unknown", "hydrocephalus_present": "unknown", "radiology_all_candidates": []
        }

    combined = " ".join(x["text"] for x in candidates[:5])
    low = combined.lower()

    def has(terms):
        return any(t.lower() in low for t in terms)

    no_bleed = has(["tidak tampak tanda-tanda perdarahan", "tidak tampak perdarahan", "tak tampak perdarahan", "no hemorrhage", "no bleeding"])
    bleed_term = has(["perdarahan", "hemorrhage", "bleeding", "ich", "pis", "sah", "sab", "ivh"])
    if bleed_term and no_bleed:
        bleeding = "no"
    elif bleed_term:
        bleeding = "yes"
    else:
        bleeding = "unknown"

    no_midline = has(["tidak tampak mid line shift", "tidak tampak midline shift", "tidak tampak pergeseran midline", "no midline shift"])
    if no_midline:
        midline = "no"
    elif has(["midline shift", "mid line shift", "deviasi midline", "pergeseran midline"]):
        midline = "yes"
    else:
        midline = "unknown"

    locs = [
        "basal ganglia", "ganglia basalis", "thalamus", "talamus", "pons", "cerebellum",
        "serebelum", "capsula interna", "kapsula interna", "frontal", "parietal",
        "temporal", "occipital", "oksipital", "mca", "aca", "pca", "centrum semiovale",
        "corona radiata", "periventrikel", "ventrikel", "lobus",
    ]
    found_locs = sorted({loc for loc in locs if loc in low})

    return {
        "ct_scan_documented": "yes",
        "ct_scan_result_text": candidates[0]["text"],
        "ct_scan_source_file": candidates[0]["source_file"],
        "ct_scan_location": ", ".join(found_locs) if found_locs else "unknown",
        "infarct_present": "yes" if has(["infark", "infarct", "hipodens", "hypodense", "lacunar", "lakunar"]) else "unknown",
        "bleeding_present": bleeding,
        "ich_present": "yes" if bleeding == "yes" and has(["ich", "intracerebral", "pis", "intraserebral"]) else "unknown",
        "sah_sab_present": "yes" if bleeding == "yes" and has(["sah", "sab", "subarachnoid"]) else "unknown",
        "ivh_present": "yes" if bleeding == "yes" and has(["ivh", "intraventricular", "intraventrikel"]) else "unknown",
        "midline_shift_present": midline,
        "hydrocephalus_present": "yes" if has(["hidrosefalus", "hydrocephalus"]) else "unknown",
        "radiology_all_candidates": candidates[:10]
    }


# ============================================================
# ONSET, OBAT, CP ACTIONS
# ============================================================

def extract_onset_complaint(files):
    patterns = [
        r".{0,80}(onset|sejak|SMRS|sebelum masuk rumah sakit|last known well|tadi pagi|tadi malam|bangun tidur).{0,180}",
        r".{0,80}(lemah|kelemahan|anggota gerak|bicara pelo|mulut mencong|penurunan kesadaran|kejang|nyeri kepala|muntah).{0,180}",
    ]
    pr = {"cppt_igd": 1, "resume": 2, "cppt_ranap": 3, "other": 4}
    candidates = []
    for f in files:
        if f["doc_type"] not in pr:
            continue
        for pat in patterns:
            for m in re.finditer(pat, f["text"], flags=re.I | re.S):
                candidates.append({
                    "source_file": f["source_file"], "priority": pr.get(f["doc_type"], 9),
                    "pos": m.start(), "evidence": clean_snippet(m.group(0), 350)
                })
    best = first_by_priority(candidates)
    if not best:
        return {"onset_or_chief_complaint_text": "unknown", "source_file": "", "evidence": "", "all_candidates": []}
    return {"onset_or_chief_complaint_text": best["evidence"], "source_file": best["source_file"], "evidence": best["evidence"], "all_candidates": candidates[:10]}

MEDICATION_KEYWORDS = {
    "aspirin_given": ["aspirin", "asetosal", "ascardia"],
    "clopidogrel_given": ["clopidogrel", "clopid"],
    "cilostazol_given": ["cilostazol"],
    "statin_given": ["statin", "atorvastatin", "simvastatin", "rosuvastatin"],
    "anticoagulant_given": ["warfarin", "heparin", "enoxaparin", "rivaroxaban", "apixaban", "dabigatran"],
    "antihypertensive_given": ["amlodipin", "amlodipine", "captopril", "nicardipine", "nikardipin", "labetalol", "valsartan", "candesartan", "bisoprolol"],
    "mannitol_given": ["manitol", "mannitol"],
    "citicoline_given": ["citicoline", "sitikolin", "citicholine"],
    "insulin_given": ["insulin", "novorapid", "lantus", "apidra", "levemir"],
    "antiepileptic_given": ["phenytoin", "fenitoin", "levetiracetam", "asam valproat", "valproat"],
}

CP_ACTION_KEYWORDS = {
    "neurologist_consult_documented": ["konsul neurologi", "konsul neuro", "dokter saraf", "dpjp saraf", "sp.s", "sp.s."],
    "neurosurgery_consult_documented": ["bedah saraf", "sp.bs", "spbs", "konsul bedah saraf"],
    "icu_hcu_documented": ["icu", "hcu", "intensive care"],
    "physiotherapy_rehab_documented": ["fisioterapi", "rehab medik", "rehabilitasi medik", "mobilisasi"],
    "nutrition_consult_documented": ["konsul gizi", "ahli gizi", "gizi", "diet"],
    "family_education_documented": ["edukasi keluarga", "edukasi", "penjelasan keluarga", "informed consent"],
    "fall_risk_assessment_documented": ["risiko jatuh", "fall risk", "morse"],
    "swallowing_screen_documented": ["skrining menelan", "swallowing", "disfagia", "tes menelan"],
    "discharge_medication_documented": ["obat pulang", "terapi pulang", "resep pulang"],
}

def keyword_presence(files, keyword_dict):
    result = {}
    for field, keywords in keyword_dict.items():
        found = []
        for f in files:
            if f["doc_type"] not in ["resume", "cppt_igd", "cppt_ranap", "other"]:
                continue
            low = f["text"].lower()
            for kw in keywords:
                idx = low.find(kw.lower())
                if idx != -1:
                    found.append({
                        "keyword": kw, "source_file": f["source_file"],
                        "evidence": context(f["text"], idx, idx + len(kw), 120, 400)
                    })
        result[field] = {
            "value": "yes" if found else "unknown",
            "source_file": found[0]["source_file"] if found else "",
            "evidence": found[0]["evidence"] if found else "",
            "all_candidates": found[:10]
        }
    return result


# ============================================================
# BUILD OUTPUT
# ============================================================

def process_patient(patient_dir: Path):
    patient_id = patient_dir.name
    files = read_patient_files(patient_dir)
    if not files:
        raise RuntimeError(f"Tidak ada file .txt untuk {patient_id}")

    result = {
        "patient_study_id": patient_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "documents_read": [{"source_file": f["source_file"], "doc_type": f["doc_type"], "char_count": f["char_count"]} for f in files],
        "diagnosis": extract_diagnosis(files),
        "onset_chief_complaint": extract_onset_complaint(files),
        "gcs": extract_gcs(files),
        "blood_pressure": extract_bp(files),
        "labs": extract_labs(files),
        "nihss": extract_nihss(files),
        "radiology": extract_radiology(files),
        "medications": keyword_presence(files, MEDICATION_KEYWORDS),
        "cp_actions": keyword_presence(files, CP_ACTION_KEYWORDS),
        "important_note": "Rule-based extraction only. Clinician validation required."
    }

    (OUT_JSON_DIR / f"{patient_id}_rule_based.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return result

def flatten_result(r):
    row = {
        "patient_study_id": r["patient_study_id"],
        "created_at": r["created_at"],
        "stroke_type_rule": r["diagnosis"]["stroke_type_rule"],
        "diagnosis_text_rule": r["diagnosis"]["diagnosis_text_rule"],
        "gcs_initial_total": r["gcs"]["gcs_initial_total"],
        "gcs_initial_text": r["gcs"]["gcs_initial_text"],
        "consciousness_text": r["gcs"]["consciousness_text"],
        "blood_pressure_initial": r["blood_pressure"]["blood_pressure_initial"],
        "systolic_bp_initial": r["blood_pressure"]["systolic_bp_initial"],
        "diastolic_bp_initial": r["blood_pressure"]["diastolic_bp_initial"],
        "nihss_documented": r["nihss"]["nihss_documented"],
        "nihss_score": r["nihss"]["nihss_score"],
        "onset_or_chief_complaint_text": r["onset_chief_complaint"]["onset_or_chief_complaint_text"],
        "ct_scan_documented": r["radiology"]["ct_scan_documented"],
        "ct_scan_result_text": r["radiology"]["ct_scan_result_text"],
        "ct_scan_source_file": r["radiology"]["ct_scan_source_file"],
        "ct_scan_location": r["radiology"]["ct_scan_location"],
        "infarct_present": r["radiology"]["infarct_present"],
        "bleeding_present": r["radiology"]["bleeding_present"],
        "ich_present": r["radiology"]["ich_present"],
        "sah_sab_present": r["radiology"]["sah_sab_present"],
        "ivh_present": r["radiology"]["ivh_present"],
        "midline_shift_present": r["radiology"]["midline_shift_present"],
        "hydrocephalus_present": r["radiology"]["hydrocephalus_present"],
        "needs_manual_review": "yes",
        "review_notes": "Rule-based extraction. Validate with source evidence in JSON."
    }
    for lab, info in r["labs"].items():
        row[lab] = info["value"]
    for k, info in r["medications"].items():
        row[k] = info["value"]
    for k, info in r["cp_actions"].items():
        row[k] = info["value"]
    return row

def save_dataset(rows):
    if not rows:
        return
    fieldnames = []
    for row in rows:
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)

    with DATASET_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        wb = Workbook()
        ws = wb.active
        ws.title = "rule_based_dataset"
        ws.append(fieldnames)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            ws.append([row.get(k, "") for k in fieldnames])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            max_len = 10
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value) if cell.value is not None else ""
                max_len = max(max_len, min(len(val), 60))
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.column_dimensions[col_letter].width = max_len + 2
        wb.save(DATASET_XLSX)
    except Exception as e:
        print(f"Info: gagal membuat XLSX, CSV tetap tersedia. Error: {e}")

def main():
    if not ANON_DIR.exists():
        raise FileNotFoundError(f"Folder tidak ditemukan: {ANON_DIR}")

    if PATIENT_ID_FILTER:
        patient_dirs = [ANON_DIR / PATIENT_ID_FILTER]
    else:
        patient_dirs = [p for p in sorted(ANON_DIR.iterdir()) if p.is_dir()]

    rows = []
    for pdir in patient_dirs:
        try:
            print(f"Memproses: {pdir.name}")
            result = process_patient(pdir)
            rows.append(flatten_result(result))

            print(f"  Stroke type : {result['diagnosis']['stroke_type_rule']}")
            print(f"  GCS         : {result['gcs']['gcs_initial_total']} | {result['gcs']['gcs_initial_text']}")
            print(f"  TD          : {result['blood_pressure']['blood_pressure_initial']}")
            print(f"  NIHSS       : {result['nihss']['nihss_score']}")
            print(f"  CT          : {result['radiology']['ct_scan_documented']} | {result['radiology']['ct_scan_result_text'][:120]}")
        except Exception as e:
            print(f"ERROR {pdir.name}: {e}")

    save_dataset(rows)
    print("\nSELESAI")
    print(f"JSON folder : {OUT_JSON_DIR}")
    print(f"CSV dataset : {DATASET_CSV}")
    print(f"XLSX dataset: {DATASET_XLSX}")
    print("\nBuka JSON untuk cek evidence. CSV/XLSX hanya tabel ringkas.")

if __name__ == "__main__":
    main()
