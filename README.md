# Pipeline RME — Disease-Agnostic Medical Record Extraction

Sistem anonimisasi & ekstraksi data rekam medis elektronik (RME) yang mendukung **berbagai jenis penyakit**, bukan hanya stroke.

## 🚀 Quick Start

```bash
cd rme_app
streamlit run run_rme_app.py --server.port 8503
```

Atau klik 2x `rme_app/run.bat`.

Buka browser: **http://localhost:8503**

## 📁 Struktur Folder

```
Pipeline_RME/
├── rme_app/                          ← APP UTAMA (disease-agnostic)
│   ├── run_rme_app.py                ← Streamlit UI
│   ├── extraction_engine.py          ← Generic extraction engine
│   ├── disease_profiles/             ← Definisi per penyakit
│   │   ├── stroke_infark.json        ← 15 kategori (migrasi dari hardcode)
│   │   └── _template.json            ← Template buat profil baru
│   ├── drug_profiles/                ← Database obat per penyakit
│   │   └── stroke.json
│   ├── tests/                        ← Unit tests
│   │   ├── test_extraction_engine.py ← 31 tests ✅
│   │   └── conftest.py
│   └── run.bat                       ← 1-klik start
├── cp_stroke_app/                    ← LAMA (tidak dimodifikasi)
├── 10_scripts/                       ← LAMA (tidak dimodifikasi)
└── 03_anonymized_text_v6_test/       ← Test data
```

## 🔬 Arsitektur

### Pipeline Flow
```
PDF/TXT mentah → [Anonimisasi] → teks anonim → [Extraction Engine] → data terstruktur
```

### Disease Profile System
Setiap penyakit = 1 file JSON. User pilih profil → pipeline ekstrak sesuai definisi.

**3 tipe extractor:**
- `builtin` — fungsi Python existing (demografi, vital, lab, dll)
- `regex` — pattern per field → capture group
- `keyword` — keyword list per field → ada/tidak

### Contoh: Buat Profil Pneumonia
```json
{
  "name": "Pneumonia",
  "categories": {
    "Diagnosis": {
      "fields": ["diagnosis_utama"],
      "type": "regex",
      "patterns": {"diagnosis_utama": "(?i)pneumonia"}
    },
    "CURB-65": {
      "fields": ["curb_confusion", "curb_ureum"],
      "type": "keyword",
      "keywords": {"curb_confusion": ["confusion", "bingung"]}
    }
  }
}
```

## 🧪 Testing

```bash
cd rme_app
python -m pytest tests/ -v
```

Hasil: **31 tests passed** (1.55s)

## 📊 Profil Tersedia

| Penyakit | File | Kategori | Fields |
|----------|------|----------|--------|
| Stroke Infark | stroke_infark.json | 15 | 80+ |

## 🛡️ Keamanan

- **100% Offline** — tidak ada data dikirim ke internet
- Anonimisasi sebelum ekstraksi — PII dihapus dari teks
- Tidak ada PII di output CSV/Excel
- Semua proses di lokal komputer

## 📋 Perbedaan dari Pipeline_RME_Stroke

| Aspek | Pipeline_RME_Stroke (lama) | Pipeline_RME (baru) |
|-------|---------------------------|---------------------|
| Penyakit | Stroke saja | Multi-penyakit |
| Ekstraksi | Hardcode di pipeline_core.py | JSON profile + engine |
| Tambah penyakit | Edit kode Python | Buat file JSON |
| UI | Dashboard RME Penelitian | Dashboard RME Penelitian v3.0 |
| Port | 8502 | 8503 |
| Anonimisasi | Sama | Sama (reuse pipeline_core) |

## 🔧 Dependencies

Sama dengan Pipeline_RME_Stroke:
- streamlit, pandas, openpyxl
- pypdf, pymupdf (fitz)
- pytesseract, Pillow (opsional, untuk OCR)
