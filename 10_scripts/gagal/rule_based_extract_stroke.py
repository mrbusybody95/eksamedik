from pathlib import Path
import re
import json
import csv
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent

ANON_DIR = BASE_DIR / "03_anonymized_text"
OUT_JSON_DIR = BASE_DIR / "04_rule_based_output"
OUT_CSV_DIR = BASE_DIR / "05_dataset_excel"

OUT_JSON_DIR.mkdir(exist_ok=True)
OUT_CSV_DIR.mkdir(exist_ok=True)

# Mulai 1 pasien dulu
PATIENT_ID = "STROKE_001"
PATIENT_DIR = ANON_DIR / PATIENT_ID

OUT_JSON = OUT_JSON_DIR / f"{PATIENT_ID}_rule_based.json"
OUT_CSV = OUT_CSV_DIR / f"{PATIENT_ID}_rule_based.csv"


# =========================
# Utility
# =========================

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def clean_snippet(text: str, max_len: int = 350) -> str:
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
    files_data = []

    txt_files = sorted(patient_dir.glob("*.txt"))

    for file_path in txt_files:
        if "relevant_context" in file_path.name.lower():
            continue

        text = file_path.read_text(encoding="utf-8", errors="ignore")
        text = normalize_text(text)

        files_data.append({
            "source_file": file_path.name,
            "doc_type": get_doc_type(file_path.name),
            "text": text
        })

    return files_data


def find_first(patterns, text, flags=re.IGNORECASE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match
    return None


def find_all_with_context(patterns, text, source_file, doc_type, label, max_results=10, context_chars=80):
    results = []

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            snippet = clean_snippet(text[start:end])

            results.append({
                "label": label,
                "value": match.group(0).strip(),
                "source_file": source_file,
                "doc_type": doc_type,
                "evidence": snippet
            })

            if len(results) >= max_results:
                return results

    return results


def parse_number(value: str):
    if value is None:
        return None

    value = value.replace(",", ".")
    match = re.search(r"\d+(\.\d+)?", value)

    if match:
        return match.group(0)

    return value


# =========================
# GCS
# =========================

def gcs_total_from_components(text: str):
    """
    Menangkap E4M6V5 / E4 V5 M6 / E 4 M 6 V 5, dsb.
    """
    patterns = [
        r"\bGCS\s*[:=]?\s*E\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
        r"\bGCS\s*[:=]?\s*E\s*(\d)\s*V\s*(\d)\s*M\s*(\d)\b",
        r"\bE\s*(\d)\s*M\s*(\d)\s*V\s*(\d)\b",
        r"\bE\s*(\d)\s*V\s*(\d)\s*M\s*(\d)\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            nums = [int(x) for x in m.groups()]
            return sum(nums), m.group(0)

    return None, None


def extract_gcs(files_data):
    candidates = []

    for f in files_data:
        text = f["text"]

        # Prioritaskan CPPT IGD dan resume
        doc_priority = {
            "cppt_igd": 1,
            "resume": 2,
            "cppt_ranap": 3,
            "other": 4,
            "radiology": 5,
            "lab": 6
        }.get(f["doc_type"], 9)

        # GCS angka total
        patterns_total = [
            r"\bGCS\s*[:=]?\s*(1[0-5]|[3-9])\b",
            r"\bGlasgow\s*Coma\s*Scale\s*[:=]?\s*(1[0-5]|[3-9])\b",
        ]

        for pattern in patterns_total:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)
                candidates.append({
                    "value": m.group(1),
                    "text": m.group(0),
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": doc_priority,
                    "evidence": clean_snippet(text[start:end])
                })

        # GCS komponen
        total, raw = gcs_total_from_components(text)
        if total:
            idx = text.lower().find(raw.lower())
            start = max(0, idx - 80)
            end = min(len(text), idx + len(raw) + 80)
            candidates.append({
                "value": str(total),
                "text": raw,
                "source_file": f["source_file"],
                "doc_type": f["doc_type"],
                "priority": doc_priority,
                "evidence": clean_snippet(text[start:end])
            })

        # Kesadaran non-angka
        consciousness_patterns = [
            r"\bcompos\s*mentis\b",
            r"\bCM\b",
            r"\bsomnolen\b",
            r"\bsopor\b",
            r"\bkoma\b",
            r"\bapatis\b",
            r"\bdelirium\b",
        ]

        for pattern in consciousness_patterns:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)
                candidates.append({
                    "value": "unknown",
                    "text": m.group(0),
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": doc_priority + 1,
                    "evidence": clean_snippet(text[start:end])
                })

    if not candidates:
        return {
            "gcs_initial_total": "unknown",
            "gcs_initial_text": "unknown",
            "consciousness_text": "unknown",
            "evidence": ""
        }

    candidates = sorted(candidates, key=lambda x: x["priority"])
    best = candidates[0]

    consciousness = "unknown"
    for c in candidates:
        if c["text"].lower() in ["compos mentis", "cm", "somnolen", "sopor", "koma", "apatis", "delirium"]:
            consciousness = c["text"]
            break

    return {
        "gcs_initial_total": best["value"],
        "gcs_initial_text": best["text"],
        "consciousness_text": consciousness,
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:5]
    }


# =========================
# Tekanan darah
# =========================

def extract_blood_pressure(files_data):
    candidates = []

    patterns = [
        r"\bTD\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bTensi\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bTekanan\s*Darah\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bBP\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
        r"\bBlood\s*Pressure\s*[:=]?\s*(\d{2,3})\s*/\s*(\d{2,3})\b",
    ]

    for f in files_data:
        doc_priority = {
            "cppt_igd": 1,
            "resume": 2,
            "cppt_ranap": 3,
            "other": 4,
        }.get(f["doc_type"], 9)

        text = f["text"]

        for pattern in patterns:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                sbp = m.group(1)
                dbp = m.group(2)

                # Hindari angka tidak masuk akal
                if not (50 <= int(sbp) <= 300 and 30 <= int(dbp) <= 200):
                    continue

                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)

                candidates.append({
                    "blood_pressure": f"{sbp}/{dbp}",
                    "systolic": sbp,
                    "diastolic": dbp,
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": doc_priority,
                    "evidence": clean_snippet(text[start:end])
                })

    if not candidates:
        return {
            "blood_pressure_initial": "unknown",
            "systolic_bp_initial": "unknown",
            "diastolic_bp_initial": "unknown",
            "evidence": ""
        }

    candidates = sorted(candidates, key=lambda x: x["priority"])
    best = candidates[0]

    return {
        "blood_pressure_initial": best["blood_pressure"],
        "systolic_bp_initial": best["systolic"],
        "diastolic_bp_initial": best["diastolic"],
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:5]
    }


# =========================
# Lab
# =========================

LAB_PATTERNS = {
    "hb": [
        r"\bHb\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
        r"\bHemoglobin\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
    ],
    "leukocyte": [
        r"\bLeukosit\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
        r"\bLeukocyte\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
        r"\bWBC\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
    ],
    "platelet": [
        r"\bTrombosit\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
        r"\bPlatelet\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
        r"\bPLT\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
    ],
    "random_blood_glucose": [
        r"\bGDS\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
        r"\bGlukosa\s*Sewaktu\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
        r"\bGula\s*Darah\s*Sewaktu\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
    ],
    "fasting_blood_glucose": [
        r"\bGDP\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
        r"\bGlukosa\s*Puasa\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
        r"\bGula\s*Darah\s*Puasa\s*[:=]?\s*(\d{2,4}[,.]?\d*)\b",
    ],
    "hba1c": [
        r"\bHbA1c\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
        r"\bA1c\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
    ],
    "ureum": [
        r"\bUreum\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
        r"\bUrea\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
    ],
    "creatinine": [
        r"\bKreatinin\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
        r"\bCreatinine\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
        r"\bCr\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
    ],
    "sodium": [
        r"\bNatrium\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b",
        r"\bSodium\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b",
        r"\bNa\s*[:=]?\s*(\d{2,3}[,.]?\d*)\b",
    ],
    "potassium": [
        r"\bKalium\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
        r"\bPotassium\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
        r"\bK\s*[:=]?\s*(\d{1,2}[,.]?\d*)\b",
    ],
    "pt": [
        r"\bPT\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
    ],
    "aptt": [
        r"\bAPTT\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
    ],
    "inr": [
        r"\bINR\s*[:=]?\s*(\d{1,3}[,.]?\d*)\b",
    ],
    "ldl": [
        r"\bLDL\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
    ],
    "total_cholesterol": [
        r"\bKolesterol\s*Total\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
        r"\bTotal\s*Cholesterol\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
    ],
    "triglyceride": [
        r"\bTrigliserida\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
        r"\bTriglyceride\s*[:=]?\s*(\d{1,4}[,.]?\d*)\b",
    ],
}


def extract_labs(files_data):
    result = {}

    for lab_name in LAB_PATTERNS.keys():
        result[lab_name] = {
            "value": "unknown",
            "source_file": "",
            "evidence": "",
            "all_candidates": []
        }

    for lab_name, patterns in LAB_PATTERNS.items():
        candidates = []

        for f in files_data:
            text = f["text"]

            doc_priority = {
                "lab": 1,
                "resume": 2,
                "cppt_igd": 3,
                "cppt_ranap": 4,
                "other": 5,
            }.get(f["doc_type"], 9)

            for pattern in patterns:
                for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                    raw_value = m.group(1)
                    value = parse_number(raw_value)

                    start = max(0, m.start() - 80)
                    end = min(len(text), m.end() + 80)

                    candidates.append({
                        "value": value,
                        "raw": m.group(0),
                        "source_file": f["source_file"],
                        "doc_type": f["doc_type"],
                        "priority": doc_priority,
                        "evidence": clean_snippet(text[start:end])
                    })

        if candidates:
            candidates = sorted(candidates, key=lambda x: x["priority"])
            best = candidates[0]

            result[lab_name] = {
                "value": best["value"],
                "source_file": best["source_file"],
                "evidence": best["evidence"],
                "all_candidates": candidates[:5]
            }

    return result


# =========================
# NIHSS
# =========================

def extract_nihss(files_data):
    candidates = []

    patterns = [
        r"\bNIHSS\s*[:=]?\s*(\d{1,2})\b",
        r"\bNIH\s*Stroke\s*Scale\s*[:=]?\s*(\d{1,2})\b",
    ]

    for f in files_data:
        text = f["text"]
        doc_priority = {
            "cppt_igd": 1,
            "resume": 2,
            "cppt_ranap": 3,
            "other": 4,
        }.get(f["doc_type"], 9)

        for pattern in patterns:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                score = int(m.group(1))

                if not (0 <= score <= 42):
                    continue

                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)

                candidates.append({
                    "nihss_score": str(score),
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": doc_priority,
                    "evidence": clean_snippet(text[start:end])
                })

    if not candidates:
        return {
            "nihss_documented": "no",
            "nihss_score": "unknown",
            "evidence": ""
        }

    candidates = sorted(candidates, key=lambda x: x["priority"])
    best = candidates[0]

    return {
        "nihss_documented": "yes",
        "nihss_score": best["nihss_score"],
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:5]
    }


# =========================
# Obat dan tindakan penting
# =========================

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
    "antibiotic_given": ["ceftriaxone", "cefixime", "levofloxacin", "meropenem", "ampicillin", "sulbactam"],
    "ppi_given": ["omeprazole", "lansoprazole", "pantoprazole", "esomeprazole"],
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


def keyword_presence(files_data, keyword_dict):
    result = {}

    for field, keywords in keyword_dict.items():
        found_items = []

        for f in files_data:
            text_lower = f["text"].lower()
            text = f["text"]

            # Terapi dan CP lebih mungkin di resume/cppt
            if f["doc_type"] not in ["resume", "cppt_igd", "cppt_ranap", "other"]:
                continue

            for kw in keywords:
                kw_lower = kw.lower()

                idx = text_lower.find(kw_lower)
                if idx != -1:
                    start = max(0, idx - 100)
                    end = min(len(text), idx + len(kw) + 100)

                    found_items.append({
                        "keyword": kw,
                        "source_file": f["source_file"],
                        "doc_type": f["doc_type"],
                        "evidence": clean_snippet(text[start:end])
                    })

        if found_items:
            result[field] = {
                "value": "yes",
                "evidence": found_items[0]["evidence"],
                "source_file": found_items[0]["source_file"],
                "all_candidates": found_items[:5]
            }
        else:
            result[field] = {
                "value": "unknown",
                "evidence": "",
                "source_file": ""
            }

    return result


# =========================
# Radiologi / CT scan
# =========================

def extract_radiology(files_data):
    radiology_texts = []

    for f in files_data:
        if f["doc_type"] in ["radiology", "resume", "cppt_igd", "cppt_ranap"]:
            text = f["text"]

            # Cari paragraf/baris yang kemungkinan hasil radiologi
            patterns = [
                r".{0,120}(CT\s*scan|CT-scan|MSCT|radiologi|kepala|cerebri|infark|hipodens|perdarahan|ICH|PIS|SAH|SAB|IVH|midline|thalamus|talamus|pons|basal ganglia).{0,300}"
            ]

            for pattern in patterns:
                for m in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                    snippet = clean_snippet(m.group(0), max_len=500)

                    radiology_texts.append({
                        "source_file": f["source_file"],
                        "doc_type": f["doc_type"],
                        "text": snippet
                    })

    # Buat ringkasan hasil CT dari file radiologi, prioritas radiology > resume > cppt
    radiology_texts = sorted(
        radiology_texts,
        key=lambda x: {"radiology": 1, "resume": 2, "cppt_igd": 3, "cppt_ranap": 4}.get(x["doc_type"], 9)
    )

    combined = " ".join([x["text"] for x in radiology_texts[:5]])
    combined_lower = combined.lower()

    def present(keywords):
        return any(kw.lower() in combined_lower for kw in keywords)

    result = {
        "ct_scan_documented": "yes" if radiology_texts else "unknown",
        "ct_scan_result_text": radiology_texts[0]["text"] if radiology_texts else "unknown",
        "ct_scan_source_file": radiology_texts[0]["source_file"] if radiology_texts else "",
        "infarct_present": "yes" if present(["infark", "infarct", "hipodens", "hypodense"]) else "unknown",
        "bleeding_present": "yes" if present(["perdarahan", "hemorrhage", "bleeding", "ich", "pis", "sah", "sab", "ivh"]) else "unknown",
        "ich_present": "yes" if present(["ich", "intracerebral", "pis", "intraserebral"]) else "unknown",
        "sah_sab_present": "yes" if present(["sah", "sab", "subarachnoid", "subarachnoid"]) else "unknown",
        "ivh_present": "yes" if present(["ivh", "intraventricular", "intraventrikel"]) else "unknown",
        "midline_shift_present": "yes" if present(["midline shift", "deviasi midline"]) else "unknown",
        "hydrocephalus_present": "yes" if present(["hidrosefalus", "hydrocephalus"]) else "unknown",
        "radiology_all_candidates": radiology_texts[:10]
    }

    # Lokasi stroke/perdarahan/infark sederhana
    location_keywords = [
        "basal ganglia", "ganglia basalis", "thalamus", "talamus", "pons",
        "cerebellum", "serebelum", "capsula interna", "kapsula interna",
        "frontal", "parietal", "temporal", "occipital", "oksipital",
        "mca", "aca", "pca", "centrum semiovale", "corona radiata"
    ]

    found_locations = []
    for loc in location_keywords:
        if loc in combined_lower:
            found_locations.append(loc)

    result["ct_scan_location"] = ", ".join(sorted(set(found_locations))) if found_locations else "unknown"

    return result


# =========================
# Diagnosis stroke eksplisit
# =========================

def extract_stroke_diagnosis(files_data):
    candidates = []

    patterns = [
        r".{0,80}(stroke\s+infark|stroke\s+iskemik|stroke\s+non\s+hemoragik|SNH|infark\s+cerebri|cerebral\s+infarct).{0,120}",
        r".{0,80}(stroke\s+hemoragik|SH|ICH|PIS|SAH|SAB|IVH|perdarahan\s+intracerebral|perdarahan\s+intraserebral|perdarahan\s+subarachnoid).{0,120}",
        r".{0,80}(diagnosis|assessment|asesmen|kesimpulan).{0,160}(stroke|infark|iskemik|hemoragik|ICH|PIS|SAH|SAB|IVH).{0,160}",
    ]

    for f in files_data:
        if f["doc_type"] not in ["resume", "radiology", "cppt_igd", "cppt_ranap", "other"]:
            continue

        priority = {
            "resume": 1,
            "radiology": 2,
            "cppt_igd": 3,
            "cppt_ranap": 4,
            "other": 5
        }.get(f["doc_type"], 9)

        for pattern in patterns:
            for m in re.finditer(pattern, f["text"], flags=re.IGNORECASE | re.DOTALL):
                snippet = clean_snippet(m.group(0), max_len=400)

                candidates.append({
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": priority,
                    "evidence": snippet
                })

    if not candidates:
        return {
            "stroke_type_rule": "unknown",
            "diagnosis_text_rule": "unknown",
            "evidence": ""
        }

    candidates = sorted(candidates, key=lambda x: x["priority"])
    best = candidates[0]
    text_lower = best["evidence"].lower()

    ischemic_terms = ["stroke infark", "stroke iskemik", "stroke non hemoragik", "snh", "infark cerebri", "cerebral infarct", "iskemik"]
    hemorrhagic_terms = ["stroke hemoragik", "ich", "pis", "sah", "sab", "ivh", "perdarahan", "hemoragik"]

    is_ischemic = any(t in text_lower for t in ischemic_terms)
    is_hemorrhagic = any(t in text_lower for t in hemorrhagic_terms)

    if is_ischemic and not is_hemorrhagic:
        stroke_type = "ischemic"
    elif is_hemorrhagic and not is_ischemic:
        stroke_type = "hemorrhagic"
    elif is_ischemic and is_hemorrhagic:
        stroke_type = "mixed_or_unclear"
    else:
        stroke_type = "unclear"

    return {
        "stroke_type_rule": stroke_type,
        "diagnosis_text_rule": best["evidence"],
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:5]
    }


# =========================
# Onset dan keluhan
# =========================

def extract_onset_and_complaint(files_data):
    candidates = []

    patterns = [
        r".{0,80}(onset|sejak|SMRS|sebelum masuk rumah sakit|last known well|tadi pagi|tadi malam|bangun tidur).{0,180}",
        r".{0,80}(lemah|kelemahan|anggota gerak|bicara pelo|mulut mencong|penurunan kesadaran|kejang|nyeri kepala|muntah).{0,180}",
    ]

    for f in files_data:
        if f["doc_type"] not in ["cppt_igd", "resume", "cppt_ranap", "other"]:
            continue

        priority = {
            "cppt_igd": 1,
            "resume": 2,
            "cppt_ranap": 3,
            "other": 4
        }.get(f["doc_type"], 9)

        for pattern in patterns:
            for m in re.finditer(pattern, f["text"], flags=re.IGNORECASE | re.DOTALL):
                candidates.append({
                    "source_file": f["source_file"],
                    "doc_type": f["doc_type"],
                    "priority": priority,
                    "evidence": clean_snippet(m.group(0), max_len=350)
                })

    if not candidates:
        return {
            "onset_or_chief_complaint_text": "unknown",
            "source_file": "",
            "evidence": ""
        }

    candidates = sorted(candidates, key=lambda x: x["priority"])
    best = candidates[0]

    return {
        "onset_or_chief_complaint_text": best["evidence"],
        "source_file": best["source_file"],
        "evidence": best["evidence"],
        "all_candidates": candidates[:5]
    }


# =========================
# Build final row
# =========================

def build_flat_row(result):
    """
    Membuat row CSV sederhana dari JSON nested.
    """
    row = {}

    row["patient_study_id"] = result["patient_study_id"]
    row["created_at"] = result["created_at"]

    row["stroke_type_rule"] = result["diagnosis"]["stroke_type_rule"]
    row["diagnosis_text_rule"] = result["diagnosis"]["diagnosis_text_rule"]

    row["gcs_initial_total"] = result["gcs"]["gcs_initial_total"]
    row["gcs_initial_text"] = result["gcs"]["gcs_initial_text"]
    row["consciousness_text"] = result["gcs"]["consciousness_text"]

    row["blood_pressure_initial"] = result["blood_pressure"]["blood_pressure_initial"]
    row["systolic_bp_initial"] = result["blood_pressure"]["systolic_bp_initial"]
    row["diastolic_bp_initial"] = result["blood_pressure"]["diastolic_bp_initial"]

    row["nihss_documented"] = result["nihss"]["nihss_documented"]
    row["nihss_score"] = result["nihss"]["nihss_score"]

    for lab_name, lab_info in result["labs"].items():
        row[lab_name] = lab_info["value"]

    for k, v in result["radiology"].items():
        if isinstance(v, str):
            row[k] = v

    row["onset_or_chief_complaint_text"] = result["onset_chief_complaint"]["onset_or_chief_complaint_text"]

    for k, v in result["medications"].items():
        row[k] = v["value"]

    for k, v in result["cp_actions"].items():
        row[k] = v["value"]

    row["needs_manual_review"] = "yes"
    row["review_notes"] = "Rule-based extraction only. Clinician validation required."

    return row


def save_csv(row, out_csv):
    fieldnames = list(row.keys())

    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def main():
    if not PATIENT_DIR.exists():
        print(f"ERROR: Folder pasien tidak ditemukan: {PATIENT_DIR}")
        return

    files_data = read_patient_files(PATIENT_DIR)

    if not files_data:
        print(f"ERROR: Tidak ada file .txt di {PATIENT_DIR}")
        return

    result = {
        "patient_study_id": PATIENT_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "documents_read": [
            {
                "source_file": f["source_file"],
                "doc_type": f["doc_type"],
                "char_count": len(f["text"])
            }
            for f in files_data
        ],
        "diagnosis": extract_stroke_diagnosis(files_data),
        "onset_chief_complaint": extract_onset_and_complaint(files_data),
        "gcs": extract_gcs(files_data),
        "blood_pressure": extract_blood_pressure(files_data),
        "labs": extract_labs(files_data),
        "nihss": extract_nihss(files_data),
        "radiology": extract_radiology(files_data),
        "medications": keyword_presence(files_data, MEDICATION_KEYWORDS),
        "cp_actions": keyword_presence(files_data, CP_ACTION_KEYWORDS),
        "important_note": "This is rule-based extraction. It should be validated manually by a clinician."
    }

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    flat_row = build_flat_row(result)
    save_csv(flat_row, OUT_CSV)

    print("SELESAI")
    print(f"JSON output: {OUT_JSON}")
    print(f"CSV output : {OUT_CSV}")
    print("")
    print("Ringkasan cepat:")
    print(f"- Stroke type rule : {result['diagnosis']['stroke_type_rule']}")
    print(f"- GCS              : {result['gcs']['gcs_initial_total']} | {result['gcs']['gcs_initial_text']}")
    print(f"- TD               : {result['blood_pressure']['blood_pressure_initial']}")
    print(f"- NIHSS            : {result['nihss']['nihss_score']}")
    print(f"- CT documented    : {result['radiology']['ct_scan_documented']}")
    print(f"- CT result        : {result['radiology']['ct_scan_result_text'][:150]}")
    print("")
    print("Catatan: cek manual JSON untuk evidence dan kandidat lain.")


if __name__ == "__main__":
    main()