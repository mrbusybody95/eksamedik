"""
conftest.py — Shared fixtures for Pipeline RME Stroke tests.
All test data is SYNTHETIC — no real patient data.
"""

import re
import sys
from pathlib import Path

# Add parent dir so imports work
_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import pytest
from pipeline_core import (
    compile_role_patterns,
    load_staff_variants,
)


# ── Fake staff CSV (inline, no filesystem dependency) ──

FAKE_STAFF_CSV_CONTENT = """\
nama,gelar_depan,gelar_belakang,role
Dr. Budi Santoso,dr,Sp.N,DOKTER_SPESIALIS_NEUROLOGI
Dr. Siti Rahmawati,dr,Sp.Rad,DOKTER_SPESIALIS_RADIOLOGI
Dr. Andi Pratama,dr,Sp.PD,DOKTER_SPESIALIS_PENYAKIT_DALAM
Ns. Dewi Sartika,Ns,,PERAWAT_PELAKSANA
Ns. Rina Fitriani,Ns,,PERAWAT_PELAKSANA
Apt. Hendra Gunawan,Apt,,APOTEKER
Dr. Maya Indah,dr,Sp.A,DOKTER_SPESIALIS_ANAK
"""


@pytest.fixture(scope="session")
def role_patterns():
    """Compile role patterns from inline fake staff data."""
    # We need to simulate load_staff_variants → compile_role_patterns
    # Create a temporary CSV file
    import tempfile
    import csv
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write(FAKE_STAFF_CSV_CONTENT)
    tmp_path = tmp.name
    tmp.close()

    variants = load_staff_variants(tmp_path)
    patterns = compile_role_patterns(variants)

    # Clean up
    Path(tmp_path).unlink(missing_ok=True)
    return patterns


# ── Synthetic RME text samples ──

@pytest.fixture
def sample_rme_text():
    """Synthetic RME text with various PII for anonymization testing."""
    return """
    RUMAH SAKIT SEHAT SELALU
    Jl. Kesehatan No. 123, Jakarta
    
    REKAM MEDIS PASIEN
    No. RM: RM-2024-05-6789
    No. SEP: 0123SEP4567890
    
    Nama Pasien: Ahmad Fauzi
    Tanggal Lahir: 15-05-1978
    NIK: 3273011505780001
    Alamat: Jl. Merdeka No. 45, Kelurahan Kebon Jeruk, Kecamatan Palmerah
    No. HP: 081234567890
    Email: ahmad.fauzi@email.com
    
    DOKTER PENANGGUNG JAWAB:
    Dr. Budi Santoso, Sp.N
    Ns. Dewi Sartika
    
    RESUME:
    Pasien datang dengan keluhan nyeri kepala hebat.
    Diagnosa kerja: Stroke Infark.
    Terapi: Aspirin 80 mg, Clopidogrel 75 mg, Atorvastatin 20 mg.
    """


@pytest.fixture
def sample_staff_csv():
    """Path to a temporary fake staff CSV."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write(FAKE_STAFF_CSV_CONTENT)
    tmp_path = tmp.name
    tmp.close()
    yield tmp_path
    Path(tmp_path).unlink(missing_ok=True)


# ── Drug database fixture ──

@pytest.fixture(autouse=True)
def reset_drug_cache():
    """Reset drug keyword cache before each test (if cached)."""
    from pipeline_core import get_drug_keywords
    if hasattr(get_drug_keywords, "cache_clear"):
        get_drug_keywords.cache_clear()
    yield


# ── Sample drug database ──

@pytest.fixture
def fake_drug_db(tmp_path):
    """Create a temporary drug_database.json with sample data."""
    db = {
        "_note": "Fake drug DB for testing",
        "med_antiplatelet": ["aspirin", "clopidogrel", "ticagrelor", "cilostazol"],
        "med_antikoagulan": ["warfarin", "notisil", "rivaroxaban"],
        "med_statin": ["atorvastatin", "simvastatin", "rosuvastatin"],
    }
    import json
    path = tmp_path / "drug_database.json"
    path.write_text(json.dumps(db, indent=2), encoding="utf-8")
    return path
