"""
conftest.py — Test fixtures for extraction engine tests.
"""
import json
import pytest
from pathlib import Path

# Paths
RME_APP_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"


@pytest.fixture
def profiles_dir():
    """Path to disease_profiles directory."""
    return RME_APP_DIR / "disease_profiles"


@pytest.fixture
def stroke_profile():
    """Load stroke_infark.json profile."""
    fp = RME_APP_DIR / "disease_profiles" / "stroke_infark.json"
    return json.loads(fp.read_text(encoding="utf-8"))


@pytest.fixture
def sample_resume_file():
    """Synthetic resume medis file for testing."""
    return {
        "source_file": "resume.txt",
        "doc_type": "resume",
        "text": """
RUMAH SAKIT UMUM DAERAH
RESUME MEDIS

Nama Pasien: [PASIEN]
No RM: [NO_RM]
Tanggal Lahir: 15 Januari 1960
Jenis Kelamin: Laki-laki
Umur: 66 Tahun

Diagnosis:
Stroke Infark / Cerebral Infarct

Riwayat Penyakit Dahulu:
Hipertensi (+), Diabetes Melitus (+), Dislipidemia (+)
Merokok (+) sejak 20 tahun

Pemeriksaan Fisik:
TD 180/100 mmHg, HR 88 /mnt, RR 20 /mnt, S 36.8°C, SpO2 98%
GCS E4M6V5 = 15

CT Scan Kepala:
Kesimpulan: Infark di daerah capsula interna kanan. Tidak tampak perdarahan intrakranial.

Foto Thorax:
Kesan: Cor normal, Pulmo tidak tampak infiltrat.

Laboratorium:
Hb 13.2 g/dL, Leukosit 11.200 /uL, Trombosit 250.000 /uL
GDS 180 mg/dL, Ureum 32 mg/dL, Kreatinin 1.1 mg/dL

Terapi:
Aspirin 1x100mg, Clopidogrel 1x75mg, Atorvastatin 1x40mg
Amlodipine 1x10mg, Mannitol 3x125cc, Pantoprazole 2x40mg

Fisioterapi: Ya
Edukasi keluarga: Ya

Cara Keluar: Atas persetujuan dokter
Kondisi Pulang: Perbaikan
Lama Rawat: 5 hari
Rencana Kontrol: 1 minggu di poli saraf
""",
        "char_count": 800,
    }


@pytest.fixture
def sample_igd_file():
    """Synthetic CPPT IGD file for testing."""
    return {
        "source_file": "cppt_igd.txt",
        "doc_type": "cppt_igd",
        "text": """
Catatan Perkembangan Pasien Terintegrasi
06-05-2026 08:30:00
IGD

O: Pasien datang dengan keluhan lemah sisi kiri tubuh sejak 3 jam yang lalu
Anamnesis: onset jam 05.00
A: Stroke Infark
P: CT Scan Kepala, Lab darah lengkap

TTV: TD 170/95mmHg, HR 82x/mnt, RR 18x/mnt, Suhu 36.5°C, SpO2 97%
GCS E4M5V4 = 13

Demam: Tidak
""",
        "char_count": 400,
    }


@pytest.fixture
def sample_lab_file():
    """Synthetic lab result file for testing."""
    return {
        "source_file": "lab_igd.txt",
        "doc_type": "lab",
        "text": """
HASIL PEMERIKSAAN LABORATORIUM

Tgl. Sampling: 06 Mei 2026
Tgl. Selesai: 06 Mei 2026

HEMATOLOGI
Hemoglobin 12.8 g/dL
Leukosit 12.500 /uL
Trombosit 220.000 /uL
Hematokrit 38.0 %
Eritrosit 4.50 10*6/uL

KIMIA KLINIK
Glukosa Darah Sewaktu 165 mg/dL
Ureum 28 mg/dL
Kreatinin 1.0 mg/dL
Natrium (Na) 140 mmol/L
Kalium (K) 3.8 mmol/L
HbA1c 7.2 %
Kolesterol Total 220 mg/dL
LDL 140 mg/dL
Trigliserida 180 mg/dL
""",
        "char_count": 500,
    }


@pytest.fixture
def sample_radiology_file():
    """Synthetic radiology report for testing."""
    return {
        "source_file": "rad_ct_kepala.txt",
        "doc_type": "radiology",
        "text": """
LAPORAN HASIL PEMERIKSAAN RADIOLOGI

TANGGAL SELESAI: 06 Mei 2026

Pemeriksaan: CT Scan Kepala

KESIMPULAN:
- Infark subakut di daerah capsula interna kanan dan corona radiata
- ASPECTS: 7
- Tidak tampak tanda-tanda perdarahan intrakranial
- Tidak tampak midline shift
- Tidak tampak hidrosefalus
- Atrofi kortikal ringan

IMPRESSION:
CT Scan kepala menunjukkan infark subakut di capsula interna kanan.
""",
        "char_count": 500,
    }


@pytest.fixture
def patient_files(sample_resume_file, sample_igd_file, sample_lab_file, sample_radiology_file):
    """Combined list of all sample patient files."""
    return [sample_resume_file, sample_igd_file, sample_lab_file, sample_radiology_file]
