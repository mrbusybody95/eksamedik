"""
test_cp_variance.py — Tests for Clinical Pathway Variance Analysis
===================================================================
Acceptance criteria:
  1. CP profiles load correctly (all 5)
  2. COMPLIANT when actual matches expected
  3. VARIANCE_DEVIATION when actual differs from expected
  4. VARIANCE_MISSING when expected but not documented (None)
  5. NOT_ASSESSABLE when data absent for numeric comparison
  6. LOS target variance correctly detected
  7. Aggregate report computes correctly
  8. find_cp_for_disease matches by name/ref
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ── Setup path ──
RME_APP = Path(__file__).resolve().parent.parent
if str(RME_APP) not in sys.path:
    sys.path.insert(0, str(RME_APP))

from analytics.cp_variance import (
    AggregateReport,
    CP_PROFILES_DIR,
    FieldVariance,
    PatientVarianceReport,
    Severity,
    VarianceType,
    analyze_all_patients,
    compare_patient,
    find_cp_for_disease,
    list_cp_profiles,
    load_cp_profile,
)


# ================================================================
# FIXTURES
# ================================================================

@pytest.fixture
def stroke_cp():
    return load_cp_profile("stroke_infark")


@pytest.fixture
def pneumonia_cp():
    return load_cp_profile("pneumonia_dewasa")


@pytest.fixture
def nstemi_cp():
    return load_cp_profile("nstemi")


@pytest.fixture
def ckd_cp():
    return load_cp_profile("ckd")


@pytest.fixture
def pneumonia_anak_cp():
    return load_cp_profile("pneumonia_anak")


def _full_compliant_patient(patient_id: str = "FULL_001") -> dict:
    """Patient with all fields documented as 'ada' — should be 100% compliant."""
    return {
        "patient_id": patient_id,
        "ct_documented": "ada",
        "lab_hb": "13.2", "lab_leukosit": "12000", "lab_trombosit": "250000",
        "lab_gds": "150", "lab_kreatinin": "1.1", "gcs": 15,
        "thorax_documented": "ada",
        "med_antiplatelet": "ada", "med_statin": "ada",
        "med_antihipertensi": "ada", "med_ppi": "ada",
        "act_konsul_neurologi": "ada", "act_fisioterapi": "ada",
        "act_konsul_gizi": "ada", "act_edukasi_keluarga": "ada",
        "cara_keluar": "ada", "kondisi_pulang": "ada",
        "lama_rawat_hari": 7,
    }


def _empty_patient(patient_id: str = "EMPTY_001") -> dict:
    """Patient with no data — should be 100% missing."""
    return {"patient_id": patient_id}


def _mixed_patient(patient_id: str = "MIX_001") -> dict:
    """Patient with mix of compliant, deviation, missing."""
    return {
        "patient_id": patient_id,
        "ct_documented": "ada",
        "lab_hb": "10.5", "lab_leukosit": None,
        "thorax_documented": "tidak",
        "med_antiplatelet": "ada", "med_statin": None,
        "act_konsul_neurologi": "ada",
        "lama_rawat_hari": 15,
    }


# ================================================================
# CP PROFILE LOADING
# ================================================================

class TestCPProfileLoading:
    """Tests for CP profile loading and listing."""

    def test_list_cp_profiles_returns_all(self):
        profiles = list_cp_profiles()
        assert len(profiles) == 5
        names = {p["name"] for p in profiles}
        assert "Stroke Infark" in names
        assert "Pneumonia Dewasa" in names
        assert "Pneumonia Anak" in names
        assert "NSTEMI" in names
        assert "CKD" in names

    def test_load_cp_profile_by_name(self, stroke_cp):
        assert stroke_cp["name"] == "Stroke Infark"
        assert "standards" in stroke_cp
        assert "los_target" in stroke_cp
        assert stroke_cp["los_target"]["min"] == 5
        assert stroke_cp["los_target"]["max"] == 10

    def test_load_cp_profile_by_ref(self):
        cp = load_cp_profile("stroke_infark")
        assert cp["name"] == "Stroke Infark"

    def test_load_cp_profile_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_cp_profile("nonexistent_disease")

    def test_find_cp_for_disease_by_name(self):
        cp = find_cp_for_disease("Stroke Infark")
        assert cp is not None
        assert cp["name"] == "Stroke Infark"

    def test_find_cp_for_disease_by_ref(self):
        cp = find_cp_for_disease("stroke_infark")
        assert cp is not None

    def test_find_cp_for_disease_not_found(self):
        cp = find_cp_for_disease("Nonexistent Disease")
        assert cp is None

    def test_all_profiles_have_standards(self):
        for fp in CP_PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            assert "standards" in data, f"{fp.name} missing 'standards'"
            assert len(data["standards"]) > 0, f"{fp.name} has empty standards"
            for section, items in data["standards"].items():
                assert len(items) > 0, f"{fp.name}/{section} has no items"
                for item in items:
                    assert "field" in item
                    assert "expected" in item
                    assert "label" in item
                    assert "severity" in item
                    assert item["severity"] in ("wajib", "rekomendasi")

    def test_all_profiles_have_los_target(self):
        for fp in CP_PROFILES_DIR.glob("*.json"):
            if fp.name.startswith("_"):
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            assert "los_target" in data, f"{fp.name} missing 'los_target'"
            los = data["los_target"]
            assert "min" in los and "max" in los
            assert los["min"] <= los["max"]


# ================================================================
# FIELD-LEVEL COMPARISON
# ================================================================

class TestFieldComparison:
    """Tests for individual field variance detection."""

    def test_compliant_when_ada_and_present(self, stroke_cp):
        patient = {"patient_id": "T1", "ct_documented": "ada"}
        report = compare_patient(patient, stroke_cp)
        ct_var = next(v for v in report.variances if v.field == "ct_documented")
        assert ct_var.variance_type == VarianceType.COMPLIANT

    def test_compliant_when_numeric_value_present(self, stroke_cp):
        """Numeric field like lab_hb='12.5' should count as 'ada'."""
        patient = {"patient_id": "T1", "lab_hb": "12.5"}
        report = compare_patient(patient, stroke_cp)
        hb_var = next(v for v in report.variances if v.field == "lab_hb")
        assert hb_var.variance_type == VarianceType.COMPLIANT

    def test_deviation_when_negated(self, stroke_cp):
        patient = {"patient_id": "T1", "thorax_documented": "tidak"}
        report = compare_patient(patient, stroke_cp)
        th_var = next(v for v in report.variances if v.field == "thorax_documented")
        assert th_var.variance_type == VarianceType.VARIANCE_DEVIATION

    def test_deviation_when_negatif(self, stroke_cp):
        patient = {"patient_id": "T1", "ct_documented": "negatif"}
        report = compare_patient(patient, stroke_cp)
        ct_var = next(v for v in report.variances if v.field == "ct_documented")
        assert ct_var.variance_type == VarianceType.VARIANCE_DEVIATION

    def test_missing_when_none(self, stroke_cp):
        patient = {"patient_id": "T1", "lab_leukosit": None}
        report = compare_patient(patient, stroke_cp)
        lk_var = next(v for v in report.variances if v.field == "lab_leukosit")
        assert lk_var.variance_type == VarianceType.VARIANCE_MISSING

    def test_missing_when_field_absent(self, stroke_cp):
        patient = {"patient_id": "T1"}
        report = compare_patient(patient, stroke_cp)
        ct_var = next(v for v in report.variances if v.field == "ct_documented")
        assert ct_var.variance_type == VarianceType.VARIANCE_MISSING

    def test_wajib_severity_preserved(self, stroke_cp):
        patient = {"patient_id": "T1", "ct_documented": None}
        report = compare_patient(patient, stroke_cp)
        ct_var = next(v for v in report.variances if v.field == "ct_documented")
        assert ct_var.severity == Severity.WAJIB

    def test_rekomendasi_severity_preserved(self, stroke_cp):
        patient = {"patient_id": "T1", "thorax_documented": None}
        report = compare_patient(patient, stroke_cp)
        th_var = next(v for v in report.variances if v.field == "thorax_documented")
        assert th_var.severity == Severity.REKOMENDASI


# ================================================================
# LOS TARGET VARIANCE
# ================================================================

class TestLOSVariance:
    """Tests for LOS (Length of Stay) target variance."""

    def test_los_within_target(self, stroke_cp):
        patient = {"patient_id": "T1", "lama_rawat_hari": 7}
        report = compare_patient(patient, stroke_cp)
        assert report.los_actual == 7.0
        assert "Sesuai target" in report.los_variance

    def test_los_above_target(self, stroke_cp):
        patient = {"patient_id": "T1", "lama_rawat_hari": 15}
        report = compare_patient(patient, stroke_cp)
        assert report.los_actual == 15.0
        assert "Melebihi target" in report.los_variance or "Di atas target" in report.los_variance

    def test_los_below_target(self, stroke_cp):
        patient = {"patient_id": "T1", "lama_rawat_hari": 2}
        report = compare_patient(patient, stroke_cp)
        assert report.los_actual == 2.0
        assert "Di bawah target" in report.los_variance

    def test_los_none_when_not_documented(self, stroke_cp):
        patient = {"patient_id": "T1"}
        report = compare_patient(patient, stroke_cp)
        assert report.los_actual is None
        assert report.los_variance is None

    def test_los_variance_entry_added(self, stroke_cp):
        """LOS target variance should appear as explicit variance entry."""
        patient = {"patient_id": "T1", "lama_rawat_hari": 20}
        report = compare_patient(patient, stroke_cp)
        los_entries = [v for v in report.variances if "Target CP" in v.label]
        assert len(los_entries) == 1
        assert los_entries[0].variance_type == VarianceType.VARIANCE_DEVIATION


# ================================================================
# PATIENT REPORT
# ================================================================

class TestPatientReport:
    """Tests for PatientVarianceReport properties."""

    def test_compliance_rate_full(self, stroke_cp):
        patient = _full_compliant_patient()
        report = compare_patient(patient, stroke_cp)
        assert report.compliance_rate == 100.0

    def test_compliance_rate_empty(self, stroke_cp):
        patient = _empty_patient()
        report = compare_patient(patient, stroke_cp)
        assert report.compliance_rate == 0.0
        assert report.compliant_count == 0

    def test_wajib_missing_list(self, stroke_cp):
        patient = _empty_patient()
        report = compare_patient(patient, stroke_cp)
        assert len(report.wajib_missing) > 0
        for w in report.wajib_missing:
            assert w.severity == Severity.WAJIB
            assert w.variance_type == VarianceType.VARIANCE_MISSING

    def test_to_summary_dict(self, stroke_cp):
        patient = _mixed_patient()
        report = compare_patient(patient, stroke_cp)
        summary = report.to_summary_dict()
        assert "patient_id" in summary
        assert "compliance_rate_pct" in summary
        assert "wajib_missing_count" in summary
        assert isinstance(summary["compliance_rate_pct"], float)

    def test_to_dict_format(self, stroke_cp):
        patient = {"patient_id": "T1", "ct_documented": "ada"}
        report = compare_patient(patient, stroke_cp)
        for v in report.variances:
            d = v.to_dict()
            assert "field" in d
            assert "variance_type" in d
            assert "severity" in d


# ================================================================
# AGGREGATE REPORT
# ================================================================

class TestAggregateReport:
    """Tests for AggregateReport across multiple patients."""

    def test_analyze_all_patients(self, stroke_cp):
        patients = [
            _full_compliant_patient("P1"),
            _mixed_patient("P2"),
            _empty_patient("P3"),
        ]
        agg = analyze_all_patients(patients, stroke_cp)
        assert agg.patient_count == 3
        assert agg.avg_compliance_rate < 100.0
        assert agg.total_missing > 0

    def test_field_compliance_summary(self, stroke_cp):
        patients = [_full_compliant_patient("P1"), _empty_patient("P2")]
        agg = analyze_all_patients(patients, stroke_cp)
        fs = agg.field_compliance_summary()
        assert len(fs) > 0
        # ct_documented: P1=ada, P2=None → 50% compliance
        assert fs["ct_documented"]["compliant"] == 1
        assert fs["ct_documented"]["missing"] == 1
        assert fs["ct_documented"]["compliance_pct"] == 50.0

    def test_wajib_compliance_summary(self, stroke_cp):
        patients = [_full_compliant_patient("P1")]
        agg = analyze_all_patients(patients, stroke_cp)
        wajib = agg.wajib_compliance_summary()
        assert len(wajib) > 0
        for f, fs in wajib.items():
            assert fs["severity"] == "wajib"

    def test_los_summary(self, stroke_cp):
        patients = [
            {"patient_id": "P1", "lama_rawat_hari": 7},
            {"patient_id": "P2", "lama_rawat_hari": 12},
            {"patient_id": "P3", "lama_rawat_hari": 3},
        ]
        agg = analyze_all_patients(patients, stroke_cp)
        los_sum = agg.los_summary()
        assert los_sum["count"] == 3
        assert los_sum["mean"] == 7.3  # (7+12+3)/3
        assert los_sum["above_target"] == 1  # P2: 12 > 10
        assert los_sum["below_target"] == 1  # P3: 3 < 5
        assert los_sum["within_target"] == 1  # P1: 5-10

    def test_los_summary_empty(self, stroke_cp):
        agg = AggregateReport(cp_name="test")
        los_sum = agg.los_summary()
        assert los_sum["count"] == 0
        assert los_sum["mean"] is None

    def test_empty_results(self, stroke_cp):
        agg = analyze_all_patients([], stroke_cp)
        assert agg.patient_count == 0
        assert agg.avg_compliance_rate == 0.0


# ================================================================
# MULTIPLE DISEASE PROFILES
# ================================================================

class TestMultipleDiseases:
    """Verify CP analysis works across all disease profiles."""

    def test_pneumonia_dewasa(self, pneumonia_cp):
        patient = {"patient_id": "P1", "thorax_documented": "ada", "med_antibiotik": "ada", "lama_rawat_hari": 6}
        report = compare_patient(patient, pneumonia_cp)
        assert report.compliance_rate > 0
        assert len(report.variances) > 0

    def test_pneumonia_anak(self, pneumonia_anak_cp):
        patient = {"patient_id": "P1", "thorax_documented": "ada", "med_antibiotik": "ada", "lama_rawat_hari": 4}
        report = compare_patient(patient, pneumonia_anak_cp)
        assert report.compliance_rate > 0

    def test_nstemi(self, nstemi_cp):
        patient = {"patient_id": "P1", "troponin_t": "ada", "ecg_ada": "ada", "lama_rawat_hari": 5}
        report = compare_patient(patient, nstemi_cp)
        assert report.compliance_rate > 0

    def test_ckd(self, ckd_cp):
        patient = {"patient_id": "P1", "lab_kreatinin": "5.2", "egfr_value": "12", "lama_rawat_hari": 4}
        report = compare_patient(patient, ckd_cp)
        assert report.compliance_rate > 0
