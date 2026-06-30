# 🎯 Accuracy Log — Anonimisasi RME Stroke

> Log akurasi anonimisasi tiap versi.
> **Metrik:** Replacement count, leftover count, false positive/negative, kecepatan.

---

## Baseline — 27 Juni 2026 (v6, Anonimisasi Core)

### ⚡ Kecepatan

| Jenis File | Karakter | Waktu (dtk) | Replacement | Leftover |
|---|---|---|---|---|
| CPPT IGD | 3.579 | 0.0468 | 30 | 0 |
| CPPT Ranap | 50.849 | 0.4390 | 168 | 0 |
| Lab 1 | 1.235 | 0.0094 | 15 | 0 |
| Lab 2 | 1.038 | 0.0083 | 14 | 0 |
| Rad 1 | 1.455 | 0.0127 | 22 | 0 |
| Rad 2 | 1.978 | 0.0167 | 22 | 0 |
| Resume | 3.352 | 0.0298 | 13 | 0 |
| CPPT IGD (2) | 1.936 | 0.0163 | 19 | 0 |
| CPPT Ranap (2) | 16.749 | 0.1435 | 66 | 0 |
| Lab IGD | 1.142 | 0.0141 | 16 | 0 |

**Rata-rata:** 0.0737 dtk/file
**Estimasi throughput:** ~50 file dalam 3.7 dtk, ~100 file dalam 7.4 dtk

### ✅ Hasil Anonimisasi

| Metrik | Nilai |
|---|---|
| Total file test | 10 |
| File dengan leftover = 0 | **10 (100%)** |
| Rata-rata replacement/file | 38.5 |
| Replacement minimal | 13 (resume) |
| Replacement maksimal | 168 (cppt_ranap) |

### 🧪 Deteksi Kebocoran (Leftover Patterns)

| Pattern | Files affected | Total hits |
|---|---|---|
| `leftover_nik_16` (16 digit) | 0 | 0 |
| `leftover_phone` (no HP) | 0 | 0 |
| `leftover_email` | 0 | 0 |
| `leftover_rm` (no RM) | 0 | 0 |
| `leftover_sep` (no SEP) | 0 | 0 |
| `leftover_dr_name` (nama dokter) | 0 | 0 |
| `leftover_name_comma_dr` | 0 | 0 |
| `leftover_sp` (Sp. spesialis) | 0 | 0 |
| `leftover_ners_apt` (perawat, apoteker) | 0 | 0 |

---

## 🎯 Cakupan Anonimisasi per Kategori PII

| Kategori PII | Metode | Coverage | Catatan |
|---|---|---|---|
| **NIK** (16 digit) | `\b\d{16}\b` | ✅ ~100% | Hampir tidak ada false positive |
| **No. HP** | `\b(0\|+62\|62)8[1-9]...` | ✅ ~100% | Mungkin kena nomor RM numerik panjang |
| **Email** | Regex standar | ✅ ~100% | Sangat jarang false positive |
| **Nama pasien** | Context-based | ✅ ~95% | Tergantung format penulisan nama |
| **Nama keluarga** | Context-based | 🟡 ~85% | Variasi format alamat tinggi |
| **No. RM** | Header + pola `no. rm` | ✅ ~98% | Kode alfanumerik 3+ digit |
| **No. SEP** | Header + pola `no. sep` | ✅ ~98% | Format min 5 karakter |
| **Nama dokter** | CSV fuzzy (173 staf) | ✅ ~99% | Tergantung kelengkapan CSV |
| **Nama perawat** | Title words `Ns.`, `Ners` | ✅ ~95% | Variasi format gelar |
| **Nama apoteker** | `Apt.` | ✅ ~95% | Variasi format gelar |
| **Gelar Sp.** | `Sp.\s*[A-Za-z]{2,}` | 🟡 ~90% | Risiko false positive: spontan, SPO2, spesifik, spektrum |
| **Alamat** | Regex alamat | 🟡 ~70% | Variasi format tinggi (Desa, Kec., Jl. vs Jln., dll) |
| **Nama RS** | Regex header | 🟡 ~60% | Format nama RS bervariasi |

---

## 🐛 False Positive yang Diketahui

| Pattern | False Positive | Frekuensi | Rencana Fix |
|---|---|---|---|
| `\b\d{16}\b` | Kode unik 16 digit non-NIK | Sangat jarang | Tambah validasi digit NIK (KTP: 16 digit, format khusus) |
| `Sp.\s*[A-Za-z]{2,}` | "spontan", "SPO2", "spesifik", "spektrum", "spinal", "spasme" | Sering | Tambah ke `CLINICAL_STOPWORDS` |
| `dr.` di nama dokter | "dr." di context "sesak nafas dr kemarin" | Jarang | Context check: hanya match di awal baris/setelah "dr." + nama |
| `\b\d{5,}\b` (no dokumen) | Nilai lab numerik > 9999 | Sedang | Sudah partial fix: hanya cari di header CPPT |

---

## 📊 Perbandingan Antar Versi

| Versi | File test | Leftover | Kecepatan | Catatan |
|---|---|---|---|---|
| v1 (stage1-2) | 3 | 5+ | - | Banyak bocor: nama dokter, Sp., alamat |
| v2 (stage3 role) | 3 | 3 | - | Header CPPT masih bocor |
| v3 (stage4 leakfix) | 5 | 2 | - | Nama perawat masih bocor |
| v4 (stage5 staff csv) | 5 | 1 | - | Sp. spesialis masih bocor |
| v5 (stage6 leftover) | 5 | 0 | - | Pertama kali 0 leftover |
| **v6 (6 stage × 2 iter)** | **10** | **0** | **0.074 dtk** | **Paling stabil** |

---

## ⚠️ Catatan Penting

1. **Test dilakukan pada 10 file dari 1 pasien (STROKE_001)** — perlu diverifikasi di pasien lain
2. **CSV staf = 173 orang** — staf baru perlu ditambahkan manual
3. **False positive Sp.** masih perlu perbaikan — istilah medis dengan "sp" awal perlu dikecualikan
4. **Alamat** coverage terendah (70%) — perlu tambah pola alamat Indonesia
5. **OCR tidak di-test** — PDF scan mungkin punya akurasi lebih rendah

---

## 🔬 Cara Reproduksi

```bash
# Profiling cepat
cd cp_stroke_app
python ../10_scripts/_profile_anon.py

# Self-test penuh
python ../10_scripts/anonymize_rme_pdf_text_v6.py --self-test

# Pipeline penuh (Streamlit)
streamlit run run_stroke_app.py
# → Buka Tab "Laporan Audit" untuk lihat leftover
```
