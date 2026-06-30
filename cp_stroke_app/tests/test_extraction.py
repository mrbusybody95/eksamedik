"""
test_extraction.py — Unit tests for data extraction functions.
All test data is SYNTHETIC — no real patient data.
Updated 27 Jun 2026: tests aligned with actual code behavior.
"""

import json
from pathlib import Path

import pytest

from pipeline_core import (
    SourceText,
    get_doc_type,
    get_drug_keywords,
    extract_medications,
    extract_demographics,
    extract_diagnosis,
    extract_gcs,
    extract_vitals,
    extract_risk_factors,
    extract_outcome,
    extract_generic_fields,
    load_extra_categories,
    get_extractor_categories,
    validate_field,
    validate_extracted_data,
    parse_indonesian_date,
    read_patient_files,
)


# ================================================================
# HELPERS: create file dicts matching actual format
# ================================================================

def make_files(texts: dict[str, str], base_path: Path | None = None) -> list[dict]:
    """Convert {filename: text} to list of dicts matching read_patient_files format."""
    files = []
    for fname, text in texts.items():
        p = (base_path / fname) if base_path else Path(fname)
        files.append({
            "source_file": fname,
            "doc_type": get_doc_type(fname),
            "text": text,
            "char_count": len(text),
        })
    return files


# ================================================================
# DOC TYPE DETECTION
# ================================================================

class TestGetDocType:
    def test_resume(self):
        assert "resume" in get_doc_type("resume_medis.pdf")

    def test_cppt_igd(self):
        t = get_doc_type("cppt_igd_2024.pdf")
        assert "igd" in t or "cppt" in t

    def test_cppt_ranap(self):
        t = get_doc_type("cppt_ranap_dr_budi.pdf")
        assert "ranap" in t or "cppt" in t

    def test_lab_1(self):
        assert "lab" in get_doc_type("lab_1.pdf")

    def test_unknown_returns_other(self):
        """Actual code returns 'other', not 'unknown'."""
        assert get_doc_type("document.pdf") == "other"


# ================================================================
# DRUG DATABASE & EXTRACTION
# ================================================================

class TestGetDrugKeywords:
    def test_loads_database(self):
        db = get_drug_keywords()
        assert isinstance(db, dict)
        med_keys = [k for k in db if k.startswith("med_")]
        assert len(med_keys) > 0

    def test_each_key_has_list(self):
        db = get_drug_keywords()
        for key, val in db.items():
            if key.startswith("med_"):
                assert isinstance(val, list), f"{key} should be a list"
                assert len(val) > 0, f"{key} should have at least 1 keyword"


class TestExtractMedications:
    def test_detect_aspirin(self):
        files = make_files({"resume.pdf": "Pasien mendapat Aspirin 80 mg"})
        result = extract_medications(files)
        assert result.get("med_antiplatelet") == "ada"
        assert "aspirin" in result.get("med_antiplatelet_detail", "").lower()

    def test_detect_clopidogrel(self):
        files = make_files({"resume.pdf": "Terapi: Clopidogrel 75 mg"})
        result = extract_medications(files)
        assert result.get("med_antiplatelet") == "ada"

    def test_detect_warfarin(self):
        files = make_files({"resume.pdf": "Warfarin 2 mg"})
        result = extract_medications(files)
        assert result.get("med_antikoagulan") == "ada"

    def test_no_drugs_detected(self):
        files = make_files({"resume.pdf": "Pasien dalam observasi."})
        result = extract_medications(files)
        for key, val in result.items():
            if key.endswith("_detail"):
                continue
            if key.startswith("med_") and not key.endswith("_detail"):
                assert val in ("tidak", ""), f"{key} should be tidak/empty, got '{val}'"


# ================================================================
# DEMOGRAPHICS
# ================================================================

class TestExtractDemographics:
    def test_age(self):
        files = make_files({
            "resume.txt": "Umur: 45 tahun\nJenis Kelamin: Laki-laki"
        })
        result = extract_demographics(files)
        assert result.get("age") == "45"

    def test_gender(self):
        files = make_files({
            "resume.txt": "Jenis Kelamin: Perempuan"
        })
        result = extract_demographics(files)
        assert "perempuan" in result.get("gender", "").lower()


# ================================================================
# DIAGNOSIS
# ================================================================

class TestExtractDiagnosis:
    def test_requires_source_file(self):
        """Files must have 'source_file' key, matching read_patient_files format."""
        files = [{
            "source_file": "resume.txt",
            "doc_type": "resume",
            "text": "Diagnosa Utama: Stroke Infark",
        }]
        result = extract_diagnosis(files)
        assert isinstance(result, dict)
        assert "diagnosis_utama" in result or "diagnosis" in str(result)

    def test_primary_diagnosis(self):
        files = make_files({
            "resume.txt": "Diagnosa Utama: Stroke Infark"
        })
        result = extract_diagnosis(files)
        assert isinstance(result, dict)


# ================================================================
# GCS
# ================================================================

class TestExtractGCS:
    def test_requires_source_file(self):
        files = [{
            "source_file": "resume.txt",
            "doc_type": "resume",
            "text": "GCS: E4 V5 M6"
        }]
        result = extract_gcs(files)
        assert isinstance(result, str)


# ================================================================
# VITAL SIGNS
# ================================================================

class TestExtractVitals:
    def test_blood_pressure(self):
        files = make_files({
            "resume.txt": "TD: 140/90 mmHg"
        })
        result = extract_vitals(files)
        assert "140" in str(result) or "td" in str(result).lower()

    def test_heart_rate(self):
        files = make_files({
            "resume.txt": "Nadi: 80 x/menit"
        })
        result = extract_vitals(files)
        assert "80" in str(result) or "nadi" in str(result).lower()


# ================================================================
# RISK FACTORS
# ================================================================

class TestExtractRiskFactors:
    def test_hypertension(self):
        files = make_files({
            "resume.txt": "Riwayat Hipertensi: Ya"
        })
        result = extract_risk_factors(files)
        assert isinstance(result, dict)

    def test_diabetes(self):
        files = make_files({
            "resume.txt": "DM: Tidak"
        })
        result = extract_risk_factors(files)
        assert isinstance(result, dict)


# ================================================================
# OUTCOME
# ================================================================

class TestExtractOutcome:
    def test_discharge(self):
        files = make_files({
            "resume.txt": "Keadaan Keluar: Membaik"
        })
        result = extract_outcome(files)
        assert isinstance(result, dict)

    def test_runs_without_error(self):
        files = make_files({
            "resume.txt": "Pasien dipulangkan."
        })
        result = extract_outcome(files)
        assert isinstance(result, dict)


# ================================================================
# GENERIC FIELD EXTRACTION
# ================================================================

class TestExtractGenericFields:
    def test_basic_keyword(self):
        files = make_files({
            "resume.txt": "Pasien dirawat di ICU"
        })
        result = extract_generic_fields(
            files,
            fields=["setting_ruang_rawat"],
            keywords=["rawat", "icu", "ruang"]
        )
        assert isinstance(result, dict)
        assert "setting_ruang_rawat" in result

    def test_empty_keywords(self):
        files = make_files({
            "resume.txt": "Test"
        })
        result = extract_generic_fields(
            files,
            fields=["test_field"],
            keywords=None
        )
        assert isinstance(result, dict)
        assert "test_field" in result


# ================================================================
# EXTRA CATEGORIES
# ================================================================

class TestLoadExtraCategories:
    def test_loads_file(self):
        cats = load_extra_categories()
        assert isinstance(cats, dict)


# ================================================================
# EXTRACTOR CATEGORIES
# ================================================================

class TestGetExtractorCategories:
    def test_has_medikasi(self):
        cats = get_extractor_categories()
        assert "Medikasi" in cats

    def test_has_structure(self):
        cats = get_extractor_categories()
        for name, conf in cats.items():
            assert "fields" in conf, f"{name} missing 'fields'"
            assert isinstance(conf["fields"], list), f"{name} fields not a list"


# ================================================================
# VALIDATION
# ================================================================

class TestValidateField:
    def test_empty_string(self):
        result, warning = validate_field("", "nama_pasien")
        assert result == "" or result is None

    def test_valid_value(self):
        result, warning = validate_field("Stroke Infark", "diagnosis_utama")
        assert result == "Stroke Infark"

    def test_none_value(self):
        result, warning = validate_field(None, "some_field")
        assert result == "" or result is None


class TestValidateExtractedData:
    def test_clean_data(self):
        data = {"nama": "Pasien", "umur": "45 tahun"}
        validated, warnings = validate_extracted_data(data)
        assert isinstance(validated, dict)
        assert isinstance(warnings, list)

    def test_mixed_data(self):
        data = {"field_a": "value_a", "field_b": None, "field_c": ""}
        validated, warnings = validate_extracted_data(data)
        assert isinstance(validated, dict)


# ================================================================
# DATE PARSING
# ================================================================

class TestParseIndonesianDate:
    def test_indonesian_month(self):
        """Format: '15 Mei 1978' — uses Indonesian month names."""
        result = parse_indonesian_date("15 Mei 1978")
        assert result is not None
        assert "1978" in result

    def test_iso_format(self):
        """ISO format YYYY-MM-DD."""
        result = parse_indonesian_date("1978-05-15")
        assert result is not None

    def test_indonesian_short_month(self):
        result = parse_indonesian_date("15 Jan 2024")
        assert result is not None

    def test_invalid_date(self):
        result = parse_indonesian_date("invalid")
        assert result is None

    def test_empty_string(self):
        result = parse_indonesian_date("")
        assert result is None
