# 📖 Petunjuk Penggunaan Dashboard RME Penelitian

> **Dashboard RME Penelitian** — Aplikasi desktop untuk anonimisasi & ekstraksi data rekam medis pasien stroke.
> 100% LOKAL — tidak ada data pasien yang dikirim ke internet.

---

## 📋 Daftar Isi
1. [Gambaran Umum](#-gambaran-umum)
2. [Persiapan Awal](#-persiapan-awal)
3. [Tab 1: Beranda](#-tab-1-beranda)
4. [Tab 2: Anonimisasi & Ekstraksi](#-tab-2-anonimisasi--ekstraksi)
5. [Tab 3: Data Staf RS](#-tab-3-data-staf-rs)
6. [Tab 4: Database Obat](#-tab-4-database-obat)
7. [Tab 5: Laporan Audit](#-tab-5-laporan-audit)
8. [Tab 6: Pengaturan](#-tab-6-pengaturan)
9. [Struktur Folder Output](#-struktur-folder-output)
10. [Troubleshooting](#-troubleshooting)
11. [FAQ](#-faq)

---

## 🎯 Gambaran Umum

Pipeline ini mengubah **PDF/TXT rekam medis mentah** menjadi **data terstruktur siap analisis** dalam 2 langkah besar:

```
📄 PDF/TXT Raw
    ↓
🔒 Anonimisasi (6 stage × 2 iterasi)
    ↓ Hapus: Nama, NIK, No RM, No HP, Email, Alamat, Nama Dokter/Staf
    ↓
📝 Teks Anonim
    ↓
📊 Ekstraksi Data Terstruktur
    ↓
📋 CSV/Excel siap analisis
```

### ✅ Yang Dilindungi Anonimisasi

| Data | Diganti Jadi |
|------|-------------|
| Nama Pasien + Keluarga | `[PASIEN]`, `[KELUARGA]` |
| NIK / No KTP (16 digit) | `[NIK]` |
| No. RM / Rekam Medis | `[NO_RM]` |
| No. SEP / Kunjungan | `[NO_SEP]`, `[NO_KUNJUNGAN]` |
| No. HP / Telepon | `[NO_HP]` |
| Email | `[EMAIL]` |
| Alamat | `[ALAMAT]` |
| Nama Dokter + Gelar | `[DOKTER_UMUM]`, `[DOKTER_SPESIALIS_NEUROLOGI]`, dll |
| Nama Perawat / Staf | `[PERAWAT_PELAKSANA]`, `[STAF]` |
| Nama Rumah Sakit | `[RUMAH_SAKIT]` |

---

## 📁 Persiapan Awal

### 1. Struktur Folder Input

Letakkan file PDF/TXT di folder `00/` dengan struktur:

```
📂 Pipeline_RME_Stroke/
├── 📂 00/
│   ├── 📂 PASIEN_001/
│   │   ├── resume.pdf
│   │   ├── cppt_igd.pdf
│   │   ├── cppt_ranap.pdf
│   │   ├── lab_1.pdf
│   │   └── ct_scan.pdf
│   ├── 📂 PASIEN_002/
│   │   └── ...
│   └── 📂 PASIEN_003/
│       └── ...
├── 📂 cp_stroke_app/
│   └── ...
└── ...
```

Setiap subfolder = 1 pasien. Nama subfolder bebas (ct: kode pasien, inisial, nomor urut).

### 2. Jalankan Aplikasi

**Klik 2x** `run.bat` atau jalankan di terminal:

```bash
cd cp_stroke_app
streamlit run run_stroke_app.py
```

Aplikasi terbuka di browser: `http://localhost:8502`

---

## 🏠 Tab 1: Beranda

Halaman selamat datang dengan ringkasan pipeline.

- **Kolom Input / Proses / Output** — gambaran alur kerja
- **Panduan Cepat** — tabel langkah-langkah
- **Status Pipeline** — sidebar kanan (siap / sedang proses / selesai / error)

> ℹ️ Tab ini hanya informasi — tidak ada aksi yang perlu dilakukan.

---

## 📂 Tab 2: Anonimisasi & Ekstraksi

**Tab utama** — tempat memproses data.

### Langkah 1: Konfigurasi

| Field | Fungsi |
|-------|--------|
| **📍 Folder Input** | Pilih folder berisi subfolder pasien (ct: `00/`) |
| **📁 Folder Proyek** | Folder output — semua hasil disimpan di sini |
| **🏷️ Label Batch** | Nama unik untuk sesi ini (ct: `gelombang_1`) |
| **🔍 Gunakan OCR** | Centang jika ada PDF scan (lebih lambat) |
| **📁 File Staf CSV** | Daftar staf RS (otomatis terisi) |

### Langkah 2: Pilih Ekstraksi

Setelah anonimisasi selesai, pilih kategori data yang ingin diekstrak:

| Kategori | Field yang Diekstrak |
|----------|---------------------|
| Demografi | Umur, Jenis Kelamin |
| Diagnosis | Diagnosis Utama, Diagnosis Kerja, Diagnosis Banding |
| GCS | Nilai GCS (Eyes, Verbal, Motorik) |
| Vital Sign | TD, Nadi, RR, Suhu, Spo2 |
| CT Scan | Letak Infark, Letak Perdarahan, Hidrosefalus |
| Thorax | Kesan Thorax |
| Tanggal Lab | Tanggal Pemeriksaan Lab |
| Demam | Status Demam |
| Medikasi | Semua golongan obat (antiplatelet, antikoagulan, dll) |
| Faktor Risiko | Hipertensi, DM, Dislipidemia, Atrial Fibrilasi, dll |
| Nilai Lab | Hb, Leukosit, Trombosit, GDS, LDL, dll |
| Tindakan | Trombolisis, Trombektomi, Drip, Operasi |
| Outcome | Status Pulang, MRS, Kematian, LOS |

### Langkah 3: Jalankan

1. Klik **"🚀 Mulai Anonimisasi"** — tunggu proses selesai
2. Centang kategori data yang diinginkan
3. Klik **"📋 Ekstrak Data"**
4. Klik **"⬇️ Download CSV"** atau **"📥 Download Excel"**

### Tombol Cepat

| Tombol | Fungsi |
|--------|--------|
| ✅ Semua Kategori | Centang semua kategori |
| ❌ Hapus Semua | Hapus centang semua kategori |
| 💊 Medikasi Saja | Centang hanya kategori Medikasi |

---

## 👥 Tab 3: Data Staf RS

Daftar dokter dan staf RS yang digunakan untuk anonimisasi.

### Kolom CSV

| Kolom | Contoh | Fungsi |
|-------|--------|--------|
| `nama` | Dr. Budi Santoso | Nama lengkap (akan dideteksi variasinya) |
| `gelar_depan` | dr | Gelar di depan nama |
| `gelar_belakang` | Sp.N, M.Kes | Gelar di belakang nama |
| `role` | DOKTER_SPESIALIS_NEUROLOGI | Role untuk label anonim |

### Cara Pakai

- **Tambah Staf**: klik "➕ Tambah Staf Baru"
- **Edit Staf**: klik staf di daftar → edit inline
- **Hapus Staf**: klik "🗑️ Hapus" di samping staf
- **Upload CSV**: upload file CSV staf dari RS lain
- **Download CSV**: download template atau data staf saat ini

> ⚠️ Semakin lengkap data staf, semakin akurat anonimisasi nama dokter/staf.

---

## 💊 Tab 4: Database Obat

Kelola database obat yang dideteksi saat ekstraksi.

### Dua Bagian

#### A. Kategori Obat (med_*)

| Aksi | Cara |
|------|------|
| **Tambah kategori baru** | Masukkan nama (ct: `med_antidiabetes`) → klik "➕ Tambah" |
| **Tambah dari template** | Pilih template → klik "📥 Tambah Template Ini" |
| **Edit keyword** | Pilih kategori → edit teks (satu keyword per baris) → klik "💾 Simpan" |
| **Hapus kategori** | Pilih kategori → klik "🗑️ Hapus" (hanya untuk kategori non-default) |

**Kategori default** (🔒 tidak bisa dihapus):
Anti血小板, Antikoagulan, Statin, Antihipertensi, Mannitol, Citicoline, PPI, Antibiotik, Antidiabetes, Antivirus, Antijamur, Bronkodilator, Kortikosteroid, Antiepilepsi, Analgesik, Obat Jantung

#### B. Kategori Data Tambahan

Untuk field di luar obat (ct: Pengaturan, Pemeriksaan Fisik):

1. Klik **"➕ Tambah Kategori Data Baru"**
2. Isi: nama kategori, nama field (pisah koma), kata kunci (opsional)
3. Klik **"✅ Tambah Kategori Data"**

**Override Field Kategori Hardcoded:**
- Pilih kategori dari dropdown (Demografi, CT Scan, dll)
- Klik "📝 Override Field List" → edit field → simpan
- Klik "🔄 Reset ke Default" untuk kembali ke bawaan

---

## 📊 Tab 5: Laporan Audit

Periksa hasil anonimisasi dan deteksi sisa kebocoran data.

### Cara Baca

| Kolom | Arti |
|-------|------|
| `source_file` | Nama file asli |
| `extraction_status` | Status ekstraksi teks (txt/pdf_ocr/dll) |
| `chars_in` / `chars_out` | Jumlah karakter sebelum/sesudah anonim |
| `needs_manual_review` | ⚠️ Perlu dicek manual |
| `leftover_*` | Sisa kebocoran yang terdeteksi |

### Filter

- **Cari file** — ketik nama file (ct: `cppt`, `resume`)
- **Hanya yang perlu review** — centang untuk lihat file bermasalah

### Sisa Kebocoran (Leftovers)

Jika ada file dengan `leftover_* > 0`:

| Tipe Leftover | Arti |
|---------------|------|
| `leftover_nik_16` | Mungkin ada NIK 16 digit yang terlewat |
| `leftover_phone` | Mungkin ada no HP yang terlewat |
| `leftover_email` | Mungkin ada email yang terlewat |
| `leftover_dr_name` | Mungkin ada nama dokter yang terlewat |
| `leftover_sp` | Mungkin ada gelar Sp. yang terlewat |

> ⚠️ **WARNING MERAH** = ada sisa data pasien! Buka file anonim dan hapus manual.

---

## ⚙️ Tab 6: Pengaturan

Pengaturan global aplikasi.

| Pengaturan | Fungsi |
|------------|--------|
| Path Staff CSV | Lokasi file staf RS |
| Auto-refresh | Frekuensi refresh otomatis |
| Theme | Tampilan gelap/terang |

---

## 📁 Struktur Folder Output

Setelah anonimisasi & ekstraksi, folder proyek akan berisi:

```
📂 {proyek}/
├── 📂 anonim_{label}_{timestamp}/
│   ├── 📂 PASIEN_001/
│   │   ├── resume.anon.txt
│   │   ├── cppt_igd.anon.txt
│   │   └── ...
│   └── 📂 PASIEN_002/
│       └── ...
├── 📂 laporan/
│   └── anonymization_report.csv
├── 📂 extracted_data/
│   └── hasil_ekstraksi_{timestamp}.csv
└── extraction_log.csv
```

---

## 🔧 Troubleshooting

### ❌ "Folder input tidak ditemukan"
**Solusi:** Pastikan folder `00/` ada di direktori yang benar. Klik Browse dan pilih manual.

### ❌ "Tidak ada file PDF/TXT ditemukan"
**Solusi:** Pastikan file berekstensi `.pdf` atau `.txt`. File `.docx`, `.jpg` tidak didukung.

### ❌ Anonimisasi lambat
**Solusi:** Matikan OCR (uncheck "🔍 Gunakan OCR") jika PDF bukan scan. OCR 10× lebih lambat.

### ❌ Ada sisa kebocoran (leftover) di laporan
**Solusi:** 
1. Buka file `.anon.txt` yang bermasalah
2. Cari teks yang terlewat (nama, NIK, dll)
3. Ganti manual dengan label yang sesuai `[NAMA]`, `[NIK]`, dll
4. Laporkan ke Daedalus untuk perbaikan pattern

### ❌ Hasil ekstraksi kosong
**Solusi:**
1. Pastikan anonimisasi sudah berhasil (cek Laporan Audit)
2. Centang kategori yang ingin diekstrak
3. Kalau masih kosong, mungkin format teks berbeda — tambah keyword di Database Obat

### ❌ Aplikasi error/tidak bisa jalan
**Solusi:**
1. Tutup terminal, buka baru
2. Jalankan: `cd cp_stroke_app && streamlit run run_stroke_app.py`
3. Kalau masih error, screenshot dan kirim ke Daedalus

---

## ❓ FAQ

### Apakah data pasien aman?
✅ **100% aman.** Semua proses di laptop sendiri. Tidak ada data dikirim ke internet.

### Bisa untuk penelitian multi-pusat?
✅ Bisa. Ganti file `staff_doctors.csv` dengan data staf RS masing-masing.

### Format PDF apa saja yang didukung?
- PDF text (hasil ketik komputer) — cepat
- PDF scan — perlu OCR (lebih lambat)
- PDF hasil screenshot — perlu OCR

### Bisa ekstrak data lama (retrospektif)?
✅ Bisa. Masukkan PDF tahun berapa pun — pipeline akan proses sama.

### Hasil ekstraksi bisa dibuka di SPSS / Excel?
✅ Bisa. Download CSV → buka di Excel atau import ke SPSS/Stata/R.

### Ada limit jumlah pasien?
Tidak ada. Pipeline sudah diuji dengan 1.000+ file tanpa masalah.

---

## 📝 Catatan Update

> **Dokumen ini otomatis terbaca dari `PETUNJUK.md`** — setiap ada perubahan di file ini, tampilan di tab "📖 Petunjuk" akan langsung terupdate tanpa perlu restart aplikasi.
>
> Terakhir diperbarui: 27 Juni 2026
