# 📊 Status Pipeline RME Stroke

**Terakhir diperbarui:** 27 Juni 2026

> Status terkini pipeline anonimisasi & ekstraksi untuk penelitian stroke infark.
> Dokumen ini adalah _living document_ — update setiap ada perubahan signifikan.

---

## 🟢 Status Umum: PRODUKSI — Berfungsi Normal

Pipeline siap dipakai untuk penelitian. Anonimisasi 100% lokal, tidak ada kebocoran data terdeteksi.

### Komponen Pipeline

| Komponen | Status | Versi | Catatan |
|---|---|---|---|
| Anonimisasi (Core) | ✅ **Produksi** | v6 (6 stage × 2 iterasi) | 100% offline, regex-based |
| Streamlit UI | ✅ **Produksi** | v2.0 | 6 tabs, native Windows dialog |
| Ekstraksi Data | ✅ **Produksi** | v8 | 15 kategori, 97 field |
| Database Obat | ✅ **Produksi** | v1 | 20 kategori, 258 keyword, editable via UI |
| Kategori Tambahan | ✅ **Produksi** | v1 | JSON-based, editable via UI |
| Staff CSV | ✅ **Produksi** | - | 173 staf, 49 role |
| Laporan Audit | ✅ **Produksi** | - | CSV + leftover detection |
| Self-Test | 🟡 **Ada** | v6 | Flag `--self-test` di script CLI |
| Unit Test | ✅ **Production** | pytest v1 | 113 test, 0.49s |

---

## 📈 Metrik Pipeline

### Anonimisasi

| Metrik | Nilai | Sumber |
|---|---|---|
| Kecepatan rata-rata | 0.07 dtk/file | Profiling 10 file (27 Juni) |
| File terkecil | 1.038 chars (lab_1.pdf) | STROKE_001 |
| File terbesar | 50.849 chars (cppt_ranap.pdf) | STROKE_001 |
| Rata-rata replacement/file | ~38 | Profiling |
| Sisa leftover (leak) | 0 | Semua file test |
| File total di pipeline | 37 | 5 pasien × ~7 file/pasien |

### Ekstraksi

| Metrik | Nilai |
|---|---|
| Total kategori data | 15 (13 hardcoded + 2 user-defined) |
| Total field | 97 |
| Kategori obat | 20 |
| Keyword obat | 258 |
| Pasien siap ekstraksi | 5 (6 jika termasuk anonim lama) |

### Kode

| File | Baris |
|---|---|
| `pipeline_core.py` | 1.955 |
| `run_stroke_app.py` | 1.605 |
| Total (core + UI) | ~3.560 |

---

## 🎯 Akurasi Anonimisasi

| Kategori PII | Method | Coverage | False Positive |
|---|---|---|---|
| NIK (16 digit) | `\b\d{16}\b` | ✅ | Hampir tidak ada |
| No HP/Telepon | Regex +62/08 | ✅ | Mungkin kena nomor RM numerik |
| Email | Regex email | ✅ | Sangat jarang |
| Nama pasien + keluarga | Context-based | ✅ | Risiko false positive di nama staf |
| No RM / SEP / Kunjungan | Regex + header | ✅ | - |
| Nama dokter + gelar | CSV fuzzy + title words | ✅ | Gelar "Sp." bisa kena istilah klinis (spontan, SPO2) |
| Alamat | Regex alamat | 🟡 Parsial | Tidak semua format alamat tertangkap |
| Nama RS | Regex | 🟡 Parsial | Hanya jika format konsisten |
| Nama staf non-dokter | CSV fuzzy | ✅ | Bergantung kelengkapan CSV |

**Catatan:** Anonimisasi menggunakan 2 iterasi — stage 1-5 lalu stage 1-5 lagi — untuk menangkap sisa yang terlewat di iterasi pertama.

---

## 🐛 Blocker & Risiko

| Blocker | Dampak | Prioritas | Rencana |
|---|---|---|---|
| ❌ Tidak ada unit test otomatis | Perlu manual test tiap perubahan | **Tinggi** | Buat test suite dengan pytest |
| 🟡 False positive "Sp." di stage 5 | Istilah klinis (spontan, SPO2) bisa kena | **Sedang** | Tambah clinical stopwords + context check |
| 🟡 Alamat tidak konsisten | Tidak semua format alamat tertangkap | **Sedang** | Tambah pola alamat Indonesia |
| 🟡 Nama RS hardcoded | Hanya RS tertentu yang dikenal | **Rendah** | Bikin regex RS Indonesia |
| ❌ Tidak ada backup otomatis | Data asli bisa kehilangan konteks setelah anonim | **Rendah** | Simpan source text di audit log |
| 🟡 Staff CSV perlu update manual | Staf baru tidak otomatis terdeteksi | **Sedang** | Tambah import dari SIM RS (future) |

---

## 📋 Improvement Plan

### Jangka Pendek (Next Session)

- [x] **Test suite** — pytest untuk unit test anonimisasi & ekstraksi ✅ (113 test, 0.49s)
- [ ] **False positive Sp.** — tambah clinical stopwords: spontan, SPO2, spesifik, spasme, spektrum, spinal
- [ ] **Pattern alamat Indonesia** — "Desa", "Kecamatan", "RT/RW", "Kelurahan"
- [ ] **Laporan Audit auto-connect** — dari folder proyek tanpa manual picker ✅

### Jangka Menengah

- [ ] **Self-test automatis** — `pytest` + GitHub Actions (offline, di mesin RS)
- [ ] **Regex profiler** — optimasi regex yang lambat (cppt_ranap 0.44 dtk)
- [ ] **Drug detection confidence** — tambah skor confidence untuk tiap obat
- [ ] **Export format** — tambah opsi SPSS (.sav) atau JSON

### Jangka Panjang

- [ ] **NLP-based extraction** — fallback NER untuk field yang tidak tertangkap regex
- [ ] **Dashboard statistik pasien** — visualisasi distribusi stroke, LOS, outcome
- [ ] **Multi-center support** — folder RS berbeda dengan mapping staf masing-masing

---

## 🔄 Riwayat Perubahan

Lihat [CHANGELOG.md](./CHANGELOG.md) untuk riwayat lengkap.

---

## 📁 File Terkait

- `README.md` — Panduan lengkap pipeline
- `CHANGELOG.md` — Riwayat versi
- `ACCURACY_LOG.md` — Log akurasi anonimisasi
