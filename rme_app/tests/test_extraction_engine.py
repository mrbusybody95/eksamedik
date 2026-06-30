"""
test_extraction_engine.py — Tests for the generic disease extraction engine.
"""
import json
import sys
import pytest
from pathlib import Path

# Add rme_app to path
RME_APP_DIR = Path(__file__).resolve().parent.parent
if str(RME_APP_DIR) not in sys.path:
    sys.path.insert(0, str(RME_APP_DIR))

from extraction_engine import (
    list_profiles,
    load_profile,
    load_drug_profile,
    extract_one_patient,
    extract_all_patients,
    _extract_regex,
    _extract_keyword,
    _extract_builtin,
    _check_negation,
    BUILTIN_EXTRACTORS,
    PROFILES_DIR,
    _CORE_AVAILABLE,
)


# ================================================================
# PROFILE LOADING
# ================================================================

class TestProfileLoading:
    """Test disease profile loading and listing."""
    
    def test_list_profiles_finds_stroke(self):
        profiles = list_profiles()
        names = [p["name"] for p in profiles]
        assert "Stroke Infark" in names
    
    def test_list_profiles_excludes_template(self):
        profiles = list_profiles()
        filenames = [p["file"] for p in profiles]
        assert "_template.json" not in filenames
    
    def test_load_profile_by_name(self):
        profile = load_profile("Stroke Infark")
        assert profile["name"] == "Stroke Infark"
        assert "categories" in profile
    
    def test_load_profile_by_filename(self):
        profile = load_profile("stroke_infark.json")
        assert profile["name"] == "Stroke Infark"
    
    def test_load_profile_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_profile("Nonexistent Disease XYZ")
    
    def test_stroke_profile_has_all_categories(self, stroke_profile):
        expected_cats = [
            "Demografi", "Diagnosis Stroke", "GCS", "Vital Sign",
            "CT Scan", "Thorax", "Laboratorium", "Tanggal Laboratorium",
            "Demam", "Medikasi", "Faktor Risiko", "Tindakan Klinis",
            "Outcome", "Pengaturan", "Pemeriksaan Fisik",
        ]
        for cat in expected_cats:
            assert cat in stroke_profile["categories"], f"Missing category: {cat}"
    
    def test_stroke_profile_has_drug_reference(self, stroke_profile):
        assert stroke_profile.get("drug_profile") == "stroke.json"
    
    def test_load_drug_profile_stroke(self):
        drugs = load_drug_profile("stroke.json")
        assert "med_antiplatelet" in drugs
        assert "aspirin" in drugs["med_antiplatelet"]
        assert "med_antibiotik" in drugs
    
    def test_load_drug_profile_none(self):
        drugs = load_drug_profile(None)
        assert drugs == {}
    
    def test_load_drug_profile_nonexistent(self):
        drugs = load_drug_profile("nonexistent.json")
        assert drugs == {}


# ================================================================
# GENERIC REGEX EXTRACTOR
# ================================================================

class TestRegexExtractor:
    """Test the generic regex extraction engine."""
    
    def test_regex_basic_capture(self, sample_resume_file):
        category = {
            "fields": ["diagnosis_utama"],
            "patterns": {
                "diagnosis_utama": r"(?i)Diagnosis[:\s]+(.+?)(?:\n|$)",
            },
        }
        result = _extract_regex([sample_resume_file], category)
        assert "Stroke Infark" in result.get("diagnosis_utama", "").upper() or \
               "INFARK" in result.get("diagnosis_utama", "").upper()
    
    def test_regex_no_match_returns_unknown(self):
        category = {
            "fields": ["field_x"],
            "patterns": {
                "field_x": r"PATTERN_TIDAK_ADA (.+)",
            },
        }
        files = [{"text": "teks biasa tanpa pattern", "doc_type": "resume", "source_file": "x.txt"}]
        result = _extract_regex(files, category)
        assert result["field_x"] == "unknown"
    
    def test_regex_doc_type_filter(self, sample_resume_file, sample_igd_file):
        category = {
            "fields": ["gcs_val"],
            "patterns": {
                "gcs_val": r"GCS\s*(?:E\d+M\d+V\d+\s*=\s*)?(\d{1,2})",
            },
            "doc_types": ["cppt_igd"],  # only from IGD
        }
        result = _extract_regex([sample_resume_file, sample_igd_file], category)
        # IGD has GCS 13, resume has 15 — should get IGD (13) since we filter to cppt_igd
        assert result["gcs_val"] == "13"
    
    def test_regex_date_capture(self, sample_lab_file):
        category = {
            "fields": ["lab_tgl"],
            "patterns": {
                "lab_tgl": r"Tgl\.?\s*Sampling\s*:\s*(\d{1,2}\s+\w+\s+\d{4})",
            },
        }
        result = _extract_regex([sample_lab_file], category)
        assert "06" in result["lab_tgl"] or "Mei" in result["lab_tgl"]


# ================================================================
# GENERIC KEYWORD EXTRACTOR
# ================================================================

class TestKeywordExtractor:
    """Test the generic keyword extraction engine."""
    
    def test_keyword_found(self, sample_resume_file):
        category = {
            "fields": ["has_hipertensi"],
            "keywords": {
                "has_hipertensi": ["hipertensi"],
            },
        }
        result = _extract_keyword([sample_resume_file], category)
        assert result["has_hipertensi"] == "ada"
    
    def test_keyword_not_found(self, sample_resume_file):
        category = {
            "fields": ["has_hiv"],
            "keywords": {
                "has_hiv": ["HIV", "AIDS"],
            },
        }
        result = _extract_keyword([sample_resume_file], category)
        assert result["has_hiv"] == "tidak"
    
    def test_keyword_multiple_fields(self, patient_files):
        category = {
            "fields": ["setting_icu", "setting_kelas"],
            "keywords": {
                "setting_icu": ["icu", "hcu"],
                "setting_kelas": ["kelas", "ruang", "bangsal"],
            },
        }
        result = _extract_keyword(patient_files, category)
        assert result["setting_icu"] in ("ada", "tidak")
        assert result["setting_kelas"] in ("ada", "tidak")


# ================================================================
# BUILTIN EXTRACTORS VIA ENGINE
# ================================================================

class TestBuiltinExtractors:
    """Test builtin extractors dispatched through the engine."""
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_builtin_registry_has_all_extractors(self):
        expected = [
            "demographics", "diagnosis", "gcs", "vitals",
            "ct_scan", "thorax", "lab_dates", "lab_values",
            "demam", "medications", "risk_factors", "actions", "outcome",
        ]
        for name in expected:
            assert name in BUILTIN_EXTRACTORS, f"Missing builtin: {name}"
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_demographics_extraction(self, sample_resume_file, stroke_profile):
        cat_def = stroke_profile["categories"]["Demografi"]
        result = _extract_builtin([sample_resume_file], cat_def)
        assert result.get("age") == "66"
        assert result.get("gender") == "Laki-laki"
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_vitals_extraction(self, patient_files, stroke_profile):
        cat_def = stroke_profile["categories"]["Vital Sign"]
        result = _extract_builtin(patient_files, cat_def)
        assert result.get("td_sistol") != "unknown"
        assert result.get("hr") != "unknown"
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_gcs_extraction(self, patient_files, stroke_profile):
        cat_def = stroke_profile["categories"]["GCS"]
        result = _extract_builtin(patient_files, cat_def)
        assert result.get("gcs") not in (None, "unknown")
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_ct_scan_extraction(self, patient_files, stroke_profile):
        cat_def = stroke_profile["categories"]["CT Scan"]
        result = _extract_builtin(patient_files, cat_def)
        assert result.get("ct_documented") == "ada"
        assert result.get("ct_perdarahan") == "tidak_ada"


# ================================================================
# END-TO-END: extract_one_patient
# ================================================================

class TestExtractOnePatient:
    """End-to-end extraction tests using patient_dir."""
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_extract_with_real_test_data(self, stroke_profile):
        """Test with the real anonymized test data (CPPT ranap only)."""
        test_dir = RME_APP_DIR.parent / "03_anonymized_text_v6_test"
        if not test_dir.exists():
            pytest.skip("Test data directory not found")
        
        result = extract_one_patient(test_dir, stroke_profile)
        assert result["patient_id"] == test_dir.name
        assert "error" not in result
        # CPPT ranap has diagnosis + meds (filter by doc_type correctly)
        has_diagnosis = result.get("stroke_type") in ("INFARK", "HEMORAGIK", "MIXED")
        has_meds = result.get("med_ppi") == "ada" or result.get("med_antibiotik") == "ada"
        assert has_diagnosis or has_meds, \
            f"Expected diagnosis or med data from CPPT. Got: stroke_type={result.get('stroke_type')}, med_ppi={result.get('med_ppi')}"
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_extract_category_filter(self, stroke_profile):
        """Test extracting only specific categories."""
        test_dir = RME_APP_DIR.parent / "03_anonymized_text_v6_test"
        if not test_dir.exists():
            pytest.skip("Test data directory not found")
        
        result = extract_one_patient(
            test_dir, stroke_profile,
            selected_categories=["Laboratorium"],
        )
        # Should have lab fields
        assert "lab_hb" in result or "lab_leukosit" in result
        # Should NOT have other category fields (unless from another category)
        assert "demo_age" not in result  # Demografi not selected
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_extract_nonexistent_dir(self, stroke_profile):
        fake_dir = Path("/nonexistent/patient/dir")
        result = extract_one_patient(fake_dir, stroke_profile)
        assert result.get("error") == "folder_not_found"


# ================================================================
# END-TO-END: extract_all_patients
# ================================================================

class TestExtractAllPatients:
    """Test batch extraction."""
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_extract_all_with_real_data(self, stroke_profile):
        test_dir = RME_APP_DIR.parent / "03_anonymized_text_v6_test"
        if not test_dir.exists():
            pytest.skip("Test data directory not found")
        
        results = extract_all_patients(test_dir, stroke_profile)
        assert len(results) >= 1
        assert "patient_id" in results[0]
    
    @pytest.mark.skipif(not _CORE_AVAILABLE, reason="pipeline_core not available")
    def test_extract_all_empty_dir(self, stroke_profile, tmp_path):
        results = extract_all_patients(tmp_path, stroke_profile)
        assert results == []


# ================================================================
# INTEGRATION: Profile JSON validity
# ================================================================

class TestProfileJSON:
    """Validate all profile JSONs are well-formed."""
    
    def test_all_profiles_valid_json(self):
        for fp in PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            assert "name" in data, f"{fp.name}: missing 'name'"
            assert "categories" in data, f"{fp.name}: missing 'categories'"
            for cat_name, cat_def in data["categories"].items():
                assert "fields" in cat_def, f"{fp.name}/{cat_name}: missing 'fields'"
                assert "type" in cat_def, f"{fp.name}/{cat_name}: missing 'type'"
                assert cat_def["type"] in ("builtin", "regex", "keyword", "none"), \
                    f"{fp.name}/{cat_name}: invalid type '{cat_def['type']}'"
    
    def test_all_builtin_types_have_extractor(self):
        for fp in PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            for cat_name, cat_def in data["categories"].items():
                if cat_def.get("type") == "builtin":
                    assert "extractor" in cat_def, \
                        f"{fp.name}/{cat_name}: builtin type requires 'extractor' field"
    
    def test_all_regex_types_have_patterns(self):
        for fp in PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            for cat_name, cat_def in data["categories"].items():
                if cat_def.get("type") == "regex":
                    assert "patterns" in cat_def, \
                        f"{fp.name}/{cat_name}: regex type requires 'patterns' field"
    
    def test_all_keyword_types_have_keywords(self):
        for fp in PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            for cat_name, cat_def in data["categories"].items():
                if cat_def.get("type") == "keyword":
                    assert "keywords" in cat_def, \
                        f"{fp.name}/{cat_name}: keyword type requires 'keywords' field"


# ================================================================
# TASK 3: Negation Detection & Word Boundary
# ================================================================

class TestNegationDetection:
    """Test negation detection for keyword extraction."""
    
    def test_negasi_tidak_ada_demam(self):
        """'tidak ada demam' → negated (return 'tidak')"""
        files = [{"text": "Pasien tidak ada demam selama perawatan", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "tidak"
    
    def test_negasi_tanpa_demam(self):
        """'tanpa demam' → negated"""
        files = [{"text": "Tanpa demam, tanpa sesak", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "tidak"
    
    def test_positif_demam_plus(self):
        """'demam (+)' → positive"""
        files = [{"text": "Riwayat: Demam (+) sejak 3 hari", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "ada"
    
    def test_positif_bare_keyword(self):
        """'Pasien dengan demam tinggi' → positive (no negation)"""
        files = [{"text": "Pasien dengan demam tinggi 39.5°C", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "ada"
    
    def test_negasi_belum_ada(self):
        """'belum ada demam' → negated"""
        files = [{"text": "Sampai saat ini belum ada demam", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "tidak"
    
    def test_negasi_tidak_tampak_infiltrat(self):
        """'Tidak tampak infiltrat' → negated"""
        files = [{"text": "Foto Thorax: Tidak tampak infiltrat di kedua lapang paru", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_infiltrat"], "keywords": {"has_infiltrat": ["infiltrat"]}}
        result = _extract_keyword(files, cat)
        assert result["has_infiltrat"] == "tidak"
    
    def test_negasi_overridden_by_positive_later(self):
        """Multiple occurrences: first negated, second positive → ada"""
        files = [{"text": "Tidak ada demam saat masuk. Hari ke-2 demam (+)", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_demam"], "keywords": {"has_demam": ["demam"]}}
        result = _extract_keyword(files, cat)
        assert result["has_demam"] == "ada"


class TestWordBoundary:
    """Test that keyword matching uses word boundaries (no substring false positives)."""
    
    def test_no_substring_false_positive(self):
        """'stroke' should NOT match inside 'antistroke' or 'microstroke' etc."""
        files = [{"text": "Pasien mendapat terapi antistroke profilaksis", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_stroke"], "keywords": {"has_stroke": ["stroke"]}}
        result = _extract_keyword(files, cat)
        # "antistroke" contains "stroke" but \b should NOT match
        assert result["has_stroke"] == "tidak", \
            "False positive: 'stroke' matched inside 'antistroke'"
    
    def test_stroke_as_standalone_word(self):
        """'Stroke' as standalone word → match"""
        files = [{"text": "Diagnosis: Stroke Infark", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_stroke"], "keywords": {"has_stroke": ["stroke"]}}
        result = _extract_keyword(files, cat)
        assert result["has_stroke"] == "ada"
    
    def test_hipertensi_word_boundary(self):
        """'hipertensi' matches standalone, not in compound words"""
        files = [{"text": "Riwayat Hipertensi (+)", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["has_ht"], "keywords": {"has_ht": ["hipertensi"]}}
        result = _extract_keyword(files, cat)
        assert result["has_ht"] == "ada"
    
    def test_icu_word_boundary(self):
        """Short keyword 'icu' should still match standalone"""
        files = [{"text": "Pasien dirawat di ICU", "doc_type": "resume", "source_file": "r.txt"}]
        cat = {"fields": ["setting_icu"], "keywords": {"setting_icu": ["icu"]}}
        result = _extract_keyword(files, cat)
        assert result["setting_icu"] == "ada"


class TestRegexDotallOptIn:
    """Test that re.S (dotall) is now opt-in per pattern, not default."""
    
    def test_regex_default_no_dotall(self):
        """Without dotall flag, .* should NOT match across newlines."""
        text = "Diagnosis:\nStroke Infark\nKesimpulan: Baik"
        files = [{"text": text, "doc_type": "resume", "source_file": "r.txt"}]
        
        # Pattern uses .* to capture after "Diagnosis:" up to newline
        cat = {
            "fields": ["dx"],
            "patterns": {
                "dx": r"Diagnosis:\s*(.+)"
            }
        }
        result = _extract_regex(files, cat)
        # Without re.S, .* stops at newline → captures "Stroke Infark"
        assert "Stroke Infark" in result.get("dx", "")
        # Should NOT swallow the next line
        assert "Kesimpulan" not in result.get("dx", "")
    
    def test_regex_dotall_explicit_true(self):
        """With dotall=true, .* matches across newlines."""
        text = "Diagnosis:\nStroke Infark\nKesimpulan: Baik"
        files = [{"text": text, "doc_type": "resume", "source_file": "r.txt"}]
        
        cat = {
            "fields": ["dx"],
            "patterns": {
                "dx": {
                    "pattern": r"Diagnosis:\s*(.+)",
                    "dotall": True,
                }
            }
        }
        result = _extract_regex(files, cat)
        # With re.S, .* matches across newlines → captures everything after
        val = result.get("dx", "")
        assert "Stroke Infark" in val
        # Now it SHOULD swallow the next line
        assert "Kesimpulan" in val
    
    def test_regex_dotall_false_explicit(self):
        """With dotall=false (explicit), same as default."""
        text = "GCS E4M6V5 = 15\nTD 180/100"
        files = [{"text": text, "doc_type": "resume", "source_file": "r.txt"}]
        
        cat = {
            "fields": ["gcs"],
            "patterns": {
                "gcs": {
                    "pattern": r"GCS\s*E\d+M\d+V\d+\s*=\s*(\d{1,2})",
                    "dotall": False,
                }
            }
        }
        result = _extract_regex(files, cat)
        assert result["gcs"] == "15"
    
    def test_regex_string_format_backward_compatible(self):
        """Old string-format patterns still work (backward compatibility)."""
        text = "Diagnosis: Stroke Infark"
        files = [{"text": text, "doc_type": "resume", "source_file": "r.txt"}]
        
        cat = {
            "fields": ["dx"],
            "patterns": {
                "dx": r"(?i)Diagnosis:\s*(.+)"
            }
        }
        result = _extract_regex(files, cat)
        assert "Stroke Infark" in result.get("dx", "")
