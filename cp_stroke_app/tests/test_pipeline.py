"""
test_pipeline.py — Unit tests for core pipeline flow and integration.
"""

from pathlib import Path

import pytest

from pipeline_core import (
    extract_one_patient,
    extract_all_patients,
    get_extractor_categories,
    get_drug_keywords,
    save_audit_report,
    AnonResult,
    read_patient_files,
)


class TestExtractOnePatient:
    """Single-patient extraction — uses anon_dir + patient_folder args."""

    def test_folder_not_found(self, tmp_path):
        """Non-existent patient folder returns error."""
        result = extract_one_patient(
            anon_dir=tmp_path,
            patient_folder="NONEXISTENT",
        )
        assert result.get("error") == "folder_not_found"

    def test_no_valid_files(self, tmp_path):
        """Empty patient folder returns no_valid_files error."""
        patient_dir = tmp_path / "PASIEN_TEST"
        patient_dir.mkdir()
        # Empty .anon.txt file (< 20 chars) should be skipped
        (patient_dir / "resume.anon.txt").write_text("too short")
        result = extract_one_patient(
            anon_dir=tmp_path,
            patient_folder="PASIEN_TEST",
        )
        assert result.get("error") == "no_valid_files"

    def test_valid_patient(self, tmp_path):
        """Patient with valid files should extract successfully."""
        patient_dir = tmp_path / "PASIEN_001"
        patient_dir.mkdir()
        (patient_dir / "resume.anon.txt").write_text(
            "Umur: 45 tahun\n"
            "Jenis Kelamin: Laki-laki\n"
            "Diagnosa: Stroke Infark\n"
            "Terapi: Aspirin 80 mg\n"
        )

        result = extract_one_patient(
            anon_dir=tmp_path,
            patient_folder="PASIEN_001",
        )
        assert isinstance(result, dict)
        assert result.get("patient_id") == "PASIEN_001"
        assert "error" not in result


class TestExtractAllPatients:
    """Multi-patient extraction."""

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent directory returns empty list."""
        results = extract_all_patients(
            anon_dir=tmp_path / "nope",
        )
        assert isinstance(results, list)
        assert len(results) == 0

    def test_empty_dir(self, tmp_path):
        """Empty directory with no patient subdirs returns empty list."""
        empty_dir = tmp_path / "no_patients"
        empty_dir.mkdir()
        results = extract_all_patients(
            anon_dir=empty_dir,
        )
        assert isinstance(results, list)
        assert len(results) == 0

    def test_one_patient(self, tmp_path):
        """Directory with one patient subfolder."""
        patient_dir = tmp_path / "P001"
        patient_dir.mkdir()
        (patient_dir / "resume.anon.txt").write_text(
            "Umur: 45 tahun\n"
            "Jenis Kelamin: Laki-laki\n"
        )

        results = extract_all_patients(
            anon_dir=tmp_path,
        )
        assert len(results) == 1
        assert results[0].get("patient_id") == "P001"


class TestSaveAuditReport:
    """Audit report generation."""

    def test_saves_csv(self, tmp_path):
        """Audit report should create a CSV file."""
        from datetime import datetime
        results = [
            AnonResult(
                source_file="test.pdf",
                output_file="test.anon.txt",
                patient_folder="p1",
                extraction_status="txt",
                ocr_used=False,
                chars_in=100,
                chars_out=95,
                processed_at=datetime.now().isoformat(),
                needs_manual_review=False,
                counts={"nik": 2, "phone": 1},
                leftovers={},
                leftover_examples={},
            )
        ]

        report_dir = tmp_path / "laporan"
        report_path = save_audit_report(results, report_dir)

        assert report_path.exists()
        assert report_path.suffix == ".csv"
        content = report_path.read_text(encoding="utf-8-sig")
        assert "test.pdf" in content


class TestDrugDatabaseConsistency:
    """Verify drug database internal consistency."""

    def test_no_orphan_references(self):
        """EXTRACTOR_CATEGORIES['Medikasi']['fields'] references exist in drug DB."""
        db = get_drug_keywords()
        cats = get_extractor_categories()

        if "Medikasi" not in cats:
            pytest.skip("Medikasi category not found")

        med_fields = cats["Medikasi"]["fields"]
        db_keys = set(db.keys())

        for field in med_fields:
            if field.endswith("_detail"):
                continue
            assert field in db_keys, (
                f"Field '{field}' in EXTRACTOR_CATEGORIES missing from drug_database.json"
            )

    def test_no_empty_keyword_lists(self):
        db = get_drug_keywords()
        for key, keywords in db.items():
            if key.startswith("med_"):
                assert len(keywords) > 0, f"{key} has empty keyword list"

    def test_keywords_not_case_sensitive_required(self):
        """Keywords are lowercase except known acronyms (NSAID, ISDN). Acceptable."""
        db = get_drug_keywords()
        acronym_allowlist = {"nsaid", "isdn", "ismn"}
        for key, keywords in db.items():
            if key.startswith("med_"):
                for kw in keywords:
                    if kw != kw.lower() and kw.lower() not in acronym_allowlist:
                        pytest.fail(f"Unexpected uppercase: {key}: '{kw}'")


class TestCategoryConfigConsistency:
    """Verify extractor categories configuration."""

    def test_field_names_no_spaces(self):
        cats = get_extractor_categories()
        for name, conf in cats.items():
            for field in conf["fields"]:
                assert " " not in field, (
                    f"Category '{name}' has field with space: '{field}'"
                )

    def test_no_duplicate_fields(self):
        cats = get_extractor_categories()
        all_fields = []
        for name, conf in cats.items():
            all_fields.extend(conf["fields"])
        duplicates = [f for f in set(all_fields) if all_fields.count(f) > 1]
        assert len(duplicates) == 0, f"Duplicate fields: {duplicates}"


class TestReadPatientFiles:
    """read_patient_files utility."""

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        files = read_patient_files(d)
        assert files == []

    def test_skips_short_files(self, tmp_path):
        d = tmp_path / "patient"
        d.mkdir()
        (d / "resume.anon.txt").write_text("short")
        files = read_patient_files(d)
        assert files == []

    def test_reads_valid_file(self, tmp_path):
        d = tmp_path / "patient"
        d.mkdir()
        (d / "resume.anon.txt").write_text("x" * 30)
        files = read_patient_files(d)
        assert len(files) == 1
        assert files[0]["source_file"] == "resume.anon.txt"
        assert files[0]["doc_type"] == "resume"
        assert files[0]["char_count"] == 30
