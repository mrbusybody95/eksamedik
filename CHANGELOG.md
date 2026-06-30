# 📜 Changelog — Pipeline RME Stroke

> Format: [ISO 8601] — Deskripsi perubahan

---

## 2026-06-27 — v2.1 "Field Details & Override"

### ✨ Ditambahkan
- **Lihat detail field per kategori** — hover checkbox untuk lihat daftar field, atau buka expander "📋 Lihat Detail Semua Field"
- **Override field list** — ubah field untuk kategori hardcoded (Demografi, CT Scan, dll) dari Tab Database Obat
- **Kelola Field per Kategori** — pilih kategori → lihat field → override → simpan ke JSON
- **Reset ke default** — kembalikan field yang sudah di-override

### ♻️ Diubah
- Help tooltip checkbox sekarang menampilkan nama-nama field (bukan hanya deskripsi)
- `get_extractor_categories()` mendukung override field dari JSON untuk kategori hardcoded

### ✨ Ditambahkan
- **Tombol "❌ Hapus Semua"** di pemilihan kategori ekstraksi (Tab 2)
- **Kategori data tambahan** via `extractor_categories_extra.json` — user bisa tambah kategori sendiri dari UI Tab Database Obat
- **Generic extractor** `extract_generic_fields()` untuk kategori user-defined (keyword-based)
- **Hot-reload** — kategori tambahan langsung muncul tanpa restart Streamlit
- **4 file dokumentasi fondasi:** `README.md`, `PIPELINE_STATUS.md`, `CHANGELOG.md`, `ACCURACY_LOG.md`

### 🐛 Diperbaiki
- **Drug filter `[]` vs `None`** — ketika semua obat di-uncheck, benar-benar tidak ada yang diekstrak (dulu fallback ke "semua")
- **Extractor categories dynamic** — `get_extractor_categories()` gantikan `EXTRACTOR_CATEGORIES` constant agar hot-reload berfungsi

### ♻️ Diubah
- `pipeline_core.py`: +~120 baris (load_extra_categories, get_extractor_categories, extract_generic_fields)
- `run_stroke_app.py`: +~80 baris (UI kategori tambahan, tombol Hapus Semua, get_extractor_categories)
- Ekstraksi Medikasi: `if selected_drug_keys:` → `if selected_drug_keys is not None:` (tidak ngefek kalau user tidak mengubah, tapi fix untuk edge case)

---

## 2026-06-26 — v1.9 "Streamlit App Final"

### ✨ Ditambahkan
- **6 tabs final:** Beranda, Anonimisasi & Ekstraksi, Data Staf RS, Database Obat, Laporan Audit, Pengaturan
- **Tab Database Obat**: tambah/edit/hapus kategori obat dari UI, simpan ke `drug_database.json`
- **Kategori protected**: kategori default tidak bisa dihapus dari UI
- **Template kategori**: med_antidiabetes, med_antivirus, med_antijamur, med_bronkodilator, dll
- **Preset kategori**: simpan kombinasi kategori data sebagai preset
- **Folder picker native Windows** — tombol Browse pake tkinter
- **Label batch** — beri nama unik tiap batch anonimisasi
- **Extraction log CSV** — riwayat batch tersimpan
- **Export terpilih** — pilih kolom tertentu sebelum download

### ♻️ Diubah
- UI dirombak: 2 langkah (anonimisasi + ekstraksi) dalam 1 tab
- Struktur output: `proyek/anonim_{label}_{timestamp}/` + `proyek/laporan/`
- Auto-detect folder anonim dari proyek & Penelitian 1 Daedalus

---

## 2026-06-25 — v1.5 "Database Obat & UI Rewrite"

### ✨ Ditambahkan
- **Drug database** dengan 16 kategori default + detail + dosis + durasi
- **Protected categories** — antiplatelet, aspirin, clopidogrel, dll tidak bisa dihapus
- **Template kategori obat** — 8 template siap pakai
- **Sub-kategori obat di UI** — centang golongan obat yang mau diekstrak
- **Batch selector** — pilih folder anonim dari dropdown (auto-detect)
- **Struktur NESTED & FLAT** — pipeline bisa baca subfolder per pasien atau file langsung

### 🐛 Diperbaiki
- Bug: drug checkbox tidak muncul di tab pertama (naming conflict `drug_sub_` vs `cat2_`)
- Bug: preset kategori tidak apply ke checkbox

---

## 2026-06-24 — v1.2 "Staff CSV & Profiling"

### ✨ Ditambahkan
- **Staff CSV** dengan 173 staf RS (49 role) — dokter umum hingga subspesialis
- **Fuzzy matching** untuk nama staf — variasi gelar, singkatan, typo minor
- **Role inference** — `infer_role()` untuk deteksi otomatis dari nama
- **Profile script** `_profile_anon.py` — ukur kecepatan & replacement per file

### 🐛 Diperbaiki
- Stage 5: false positive nama dokter di context klinis — tambah clinical stopwords
- Stage 6: leftover Sp. — hanya match Sp. dengan kode spesialis, bukan kata klinis

---

## 2026-06-22 — v1.0 "Anonimisasi v6 + Ekstraksi v7"

### ✨ Ditambahkan
- **Anonimisasi v6**: 6 stage × 2 iterasi — paling stabil hingga saat ini
  - Stage 1: NIK (16 digit), No HP, Email, Alamat
  - Stage 2: Nama staf RS (CSV matching)
  - Stage 3: Nama pasien + keluarga + No RM/SEP
  - Stage 4: Header CPPT + nomor dokumen
  - Stage 5: Nama dokter + gelar + role PPA
  - Stage 6: Leftover scan (ulang)
- **Ekstraksi v7**: Demografi, Diagnosis, GCS, Vital, CT Scan, Thorax, Lab, Medikasi, Faktor Risiko, Tindakan, Outcome
- **Leftover detection**: 8 pattern untuk deteksi sisa identitas
- **Self-test** (`--self-test` flag)

### 🗑️ Dihapus
- Script versi sebelumnya dipindah ke `10_scripts/gagal/`

---

## 2026-06-15 — v0.8 "Anonimisasi v5 & Ekstraksi v2"

### ✨ Ditambahkan
- Anonimisasi stage 5: staff CSV fuzzy recursive
- Ekstraksi via rule-based + regex (v2)
- Streamlit app pertama (1 tab)

---

## 2026-06-10 — v0.5 "Anonimisasi v3-v4"

### ✨ Ditambahkan
- Stage 3: leakfix recursive (header CPPT)
- Stage 4: staff & radiology phone recursive
- Label permanen `[PASIEN]`, `[NIK]`, `[NO_RM]`, dll

---

## 2026-06-05 — v0.3 "Anonimisasi v1-v2"

### ✨ Ditambahkan
- Stage 1: regex PII dasar (NIK, HP, Email)
- Stage 2: role PPA + nama dokter
- PDF text extraction via pypdf / PyMuPDF

---

## 2026-06-01 — v0.1 "Inisialisasi"

### ✨ Ditambahkan
- Project scaffold
- PDF text extraction pertama (`extract_pdf_text.py`)
- Eksperimen anonimisasi text (`anonymize_text.py`)
- Folder structure awal
