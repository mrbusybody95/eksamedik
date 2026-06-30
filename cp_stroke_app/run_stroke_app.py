"""
run_stroke_app.py — Aplikasi Streamlit untuk Anonimisasi & Ekstraksi RME Stroke
=================================================================================
Target user: Seluruh staf RS (dokter, perawat, rekam medis, peneliti)
100% LOKAL — tidak ada data dikirim ke internet

Cara jalankan:
  cd cp_stroke_app
  streamlit run run_stroke_app.py

Atau klik 2x run.bat
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# Pipeline core — import semua fungsi
from pipeline_core import (
    AnonResult,
    ProgressState,
    anonymize_folder,
    anonymize_text,
    compile_role_patterns,
    extract_all_patients,
    load_staff_csv_data,
    load_staff_variants,
    read_source,
    save_audit_report,
    save_staff_csv_data,
    collect_source_files,
)

# ================================================================
# KONFIGURASI HALAMAN
# ================================================================

st.set_page_config(
    page_title="Dashboard RME Penelitian",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================================================================
# CONSTANTS
# ================================================================

APP_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = str((APP_DIR.parent / "00").resolve())
DEFAULT_OUTPUT = str((APP_DIR.parent / "03_anonymized_text_v6").resolve())
DEFAULT_REPORT = str((APP_DIR.parent / "04_anonymization_report_v6").resolve())
DEFAULT_STAFF_CSV = str((APP_DIR / "staff_doctors.csv").resolve())
DEFAULT_ANON_DIR = str((APP_DIR.parent / "03_anonymized_text_v6").resolve())
DEFAULT_EXTRACT_OUTPUT = str((APP_DIR.parent / "06_extracted_data").resolve())


# ================================================================
# HELPER: FOLDER DIALOG NATIVE WINDOWS
# ================================================================

import subprocess as _subprocess
import sys as _sys

DIALOG_SCRIPT = str((Path(__file__).resolve().parent / "folder_dialog.py").resolve())


def browse_folder_dialog() -> str:
    """
    Buka dialog folder native Windows (tkinter).
    Return path folder atau string kosong jika dibatalkan.
    """
    try:
        result = _subprocess.run(
            [_sys.executable, DIALOG_SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        path = result.stdout.strip()
        return path if path else ""
    except Exception as e:
        return ""


def folder_picker(label: str, default_path: str, key: str, help_text: str = "") -> str:
    """
    Folder picker dengan tombol Browse → dialog native Windows.
    Text input READ-ONLY — hanya berubah via tombol Browse.
    """
    state_key = f"folder_{key}"
    # Update session state kalau default_path berubah dan lebih cocok
    current = st.session_state.get(state_key, "")
    if current != str(default_path):
        # Update kalau: (a) session kosong, atau (b) path lama tidak ada foldernya
        if not current or not Path(current).exists():
            st.session_state[state_key] = str(default_path)

    if state_key not in st.session_state:
        st.session_state[state_key] = str(default_path)

    col1, col2 = st.columns([5, 1])
    with col1:
        st.text_input(
            label,
            value=st.session_state[state_key],
            key=f"txt_{key}",
            disabled=True,
            help=help_text,
            placeholder="Klik Browse untuk pilih folder...",
        )
    with col2:
        st.markdown("###")
        if st.button("📁 Browse", key=f"browse_{key}", use_container_width=True):
            folder = browse_folder_dialog()
            if folder:
                st.session_state[state_key] = folder
                st.rerun()

    return st.session_state[state_key]

# ================================================================
# SESSION STATE INIT
# ================================================================

if "progress" not in st.session_state:
    st.session_state.progress = ProgressState()
if "anon_results" not in st.session_state:
    st.session_state.anon_results = []
if "extract_results" not in st.session_state:
    st.session_state.extract_results = []
if "staff_data" not in st.session_state:
    st.session_state.staff_data = load_staff_csv_data(DEFAULT_STAFF_CSV)
if "staff_csv_path" not in st.session_state:
    st.session_state.staff_csv_path = DEFAULT_STAFF_CSV
if "processing" not in st.session_state:
    st.session_state.processing = False

# ================================================================
# SIDEBAR — NAVIGASI & STATUS
# ================================================================

st.sidebar.markdown("## 🛡️ Dashboard RME Penelitian")
st.sidebar.markdown("---")

# Navigation
tabs = [
    "🏠 Beranda",
    "📖 Petunjuk",
    "📂 Anonimisasi & Ekstraksi",
    "👥 Data Staf RS",
    "💊 Database Obat",
    "📊 Laporan Audit",
    "⚙️ Pengaturan",
]
active_tab = st.sidebar.radio("Menu", tabs, index=0)

st.sidebar.markdown("---")

# Status ringkas
p = st.session_state.progress
st.sidebar.markdown("### Status Pipeline")
if p.status == "idle":
    st.sidebar.info("⏸️ Siap")
elif p.status == "running":
    st.sidebar.warning(f"⏳ {p.current}/{p.total} ({p.percent:.0f}%)")
elif p.status == "done":
    st.sidebar.success(f"✅ {p.total} file selesai")
elif p.status == "error":
    st.sidebar.error("❌ Error")

# Staff count
staff_count = len(st.session_state.staff_data)
st.sidebar.markdown(f"**Staf terdaftar:** {staff_count} orang")

st.sidebar.markdown("---")
st.sidebar.caption("v2.0 — 100% Lokal & Offline")


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def refresh_staff_data():
    """Reload staff data from CSV."""
    st.session_state.staff_data = load_staff_csv_data(st.session_state.staff_csv_path)


def run_anon_pipeline(input_dir, output_dir, staff_csv, use_ocr, progress):
    """Jalankan pipeline di thread terpisah."""
    try:
        results = anonymize_folder(
            input_dir=input_dir,
            output_dir=output_dir,
            staff_csv=staff_csv,
            use_ocr=use_ocr,
            progress=progress,
        )
        st.session_state.anon_results = results

        # Simpan audit report
        report_path = Path(output_dir).parent / "04_anonymization_report_v6"
        if not report_path.exists():
            report_path = Path(output_dir) / "reports"
        save_audit_report(results, report_path)

        progress.status = "done"
    except Exception as e:
        progress.status = "error"
        progress.errors.append(str(e))
    finally:
        st.session_state.processing = False


# ================================================================
# TAB 1: BERANDA
# ================================================================

if active_tab == "🏠 Beranda":
    st.title("🛡️ Dashboard RME Penelitian")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 📥 Input")
        st.markdown("Folder **`00/`** berisi PDF/TXT rekam medis pasien stroke (per subfolder pasien).")
    with col2:
        st.markdown("### 🔒 Proses")
        st.markdown("Anonimisasi 6-tahap × 2 iterasi → Hapus **nama, NIK, RM, SEP, nama dokter, perawat, alamat**.")
    with col3:
        st.markdown("### 📊 Output")
        st.markdown("Teks anonim + laporan audit + data terstruktur untuk penelitian clinical pathway.")

    st.markdown("---")

    with st.expander("📖 Panduan Cepat", expanded=True):
        st.markdown("""
        ### 🎯 Cara Pakai

        | Langkah | Aksi | Keterangan |
        |---------|------|------------|
        | **1** | 📂 **Proses Anonimisasi** | Pilih folder PDF/TXT → klik "Mulai Anonimisasi" |
        | **2** | 👥 **Data Staf RS** | Tambah/edit daftar dokter & staf (opsional) |
        | **3** | 📊 **Laporan Audit** | Cek hasil: jumlah file, status, sisa kebocoran |
        | **4** | 📋 **Ekstraksi Data** | Ekstrak data terstruktur dari teks anonim |

        ### ✅ Yang Dilindungi
        - **Nama Pasien** → `[PASIEN]`
        - **NIK / No KTP** → `[NIK]`
        - **No RM / SEP / Kunjungan** → `[NO_RM]`, `[NO_SEP]`
        - **Nama Dokter & Staf** → `[DOKTER_UMUM]`, `[DOKTER_SPESIALIS]`, `[PERAWAT]`, dll
        - **No HP & Email** → `[NO_HP]`, `[EMAIL]`
        - **Alamat & RS** → `[ALAMAT]`, `[RUMAH_SAKIT]`

        ### ⚡ Hemat Waktu
        Pipeline sudah dioptimasi: ~0.1 detik per file (ratusan file dalam <1 menit).
        """)

    st.markdown("---")

    # Quick stats
    input_dir = Path(DEFAULT_INPUT)
    if input_dir.exists():
        pdf_files = list(input_dir.rglob("*.pdf"))
        txt_files = list(input_dir.rglob("*.txt"))
        total = len(pdf_files) + len(txt_files)
        st.metric("📄 Total file tersedia", total)

    # Riwayat terakhir
    if st.session_state.anon_results:
        st.success(f"**Riwayat terakhir:** {len(st.session_state.anon_results)} file diproses")
        safe = sum(1 for r in st.session_state.anon_results if not r.needs_manual_review)
        review = sum(1 for r in st.session_state.anon_results if r.needs_manual_review)
        c1, c2 = st.columns(2)
        c1.metric("✅ Aman", safe)
        c2.metric("⚠️ Perlu Review", review)


# ================================================================
# TAB 2: PETUNJUK PENGGUNAAN
# ================================================================

elif active_tab == "📖 Petunjuk":
    st.title("📖 Petunjuk Penggunaan Dashboard RME Penelitian")
    st.caption("Panduan lengkap — update otomatis dari file PETUNJUK.md")

    petunjuk_path = Path(__file__).parent / "PETUNJUK.md"
    if petunjuk_path.exists():
        content = petunjuk_path.read_text(encoding="utf-8")
        st.markdown(content)
        
        # Footer dengan info file
        st.markdown("---")
        st.caption(f"📁 Sumber: `{petunjuk_path.name}` | Terakhir dimuat: {datetime.now().strftime('%d %b %Y %H:%M')}")
        st.caption("💡 Untuk memperbarui panduan ini, edit file `PETUNJUK.md` — perubahan langsung tampil tanpa restart.")
    else:
        st.error(f"❌ File `PETUNJUK.md` tidak ditemukan.")
        st.info("Buat file `PETUNJUK.md` di folder `cp_stroke_app/` dengan panduan penggunaan dashboard.")


# ================================================================
# TAB 3: PROSES ANONIMISASI
# ================================================================

# ================================================================
# TAB 2: PROSES ANONIMISASI
# ================================================================

# ================================================================
# TAB 2: ANONIMISASI & EKSTRAKSI (1 tab, 2 langkah)
# ================================================================

elif active_tab == "📂 Anonimisasi & Ekstraksi":
    st.title("📂 Anonimisasi & Ekstraksi")
    st.caption("Langkah 1: Anonimisasi → Langkah 2: Ekstraksi — dalam satu tempat.")

    if "proyek_dir" not in st.session_state:
        st.session_state.proyek_dir = str(APP_DIR.parent)

    st.subheader("Konfigurasi")

    col1, col2 = st.columns(2)
    with col1:
        input_dir = folder_picker(
            "📍 Folder Input (PDF/TXT)", DEFAULT_INPUT, "input_dir_picker",
            help_text="Folder berisi subfolder pasien dengan file PDF/TXT"
        )
        proyek_dir = folder_picker(
            "📁 Folder Proyek (Output)", st.session_state.proyek_dir, "proyek_dir_picker",
            help_text="Semua hasil anonim, ekstraksi, laporan akan otomatis masuk sini"
        )
        st.session_state.proyek_dir = proyek_dir
        batch_label = st.text_input("🏷️ Label Batch (opsional)", placeholder="ct: gelombang_1", key="batch_label_input",
                                     help="Kosongkan = pakai timestamp saja")
    with col2:
        batch_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if batch_label.strip():
            batch_folder = f"anonim_{batch_label.strip()}_{batch_ts}"
        else:
            batch_folder = f"anonim_{batch_ts}"
        output_dir = str(Path(proyek_dir) / batch_folder)
        use_ocr = st.checkbox("🔍 Gunakan OCR (untuk PDF scan)", value=False,
                              help="Lebih lambat tapi menangkap teks dari dokumen scan")

    st.info(f"**Perkiraan:** ~0.1 dtk/file. Untuk 100 file ≈ 10 dtk.")
    st.caption(f"📁 Output → `{output_dir}`")
    st.caption(f"📁 Laporan → `{Path(proyek_dir) / 'laporan'}`")

    run_button = st.button("🚀 Mulai Anonimisasi", type="primary", use_container_width=True)

    if run_button:
        input_path = Path(input_dir)
        if not input_path.exists():
            st.error(f"❌ Folder input tidak ditemukan: {input_dir}")
        else:
            files = collect_source_files(input_path)
            if not files:
                st.error("❌ Tidak ada file PDF/TXT ditemukan di folder input.")
            else:
                staff_csv = Path(st.session_state.staff_csv_path) if st.session_state.staff_csv_path else None
                if staff_csv and not staff_csv.exists():
                    st.warning("⚠️ File staf tidak ditemukan. Anonimisasi tetap jalan tanpa data staf.")

                progress = ProgressState()
                st.session_state.progress = progress
                st.session_state.processing = True

                with st.spinner(f"Memproses {len(files)} file..."):
                    try:
                        results = anonymize_folder(
                            input_dir=input_dir,
                            output_dir=output_dir,
                            staff_csv=st.session_state.staff_csv_path,
                            use_ocr=use_ocr,
                            progress=progress,
                        )
                        st.session_state.anon_results = results

                        # Simpan laporan audit ke proyek/laporan/
                        report_dir = Path(proyek_dir) / "laporan"
                        save_audit_report(results, report_dir)

                        # Simpan extraction log
                        log_path = Path(proyek_dir) / "extraction_log.csv"
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        import csv as cm
                        log_entry = {
                            "timestamp": batch_ts,
                            "batch": batch_folder,
                            "pasien": len(set(r.patient_folder for r in results if r.patient_folder)),
                            "file": len(results),
                            "label": batch_label.strip() or "-",
                        }
                        existing_logs = []
                        if log_path.exists():
                            with log_path.open("r", encoding="utf-8-sig") as lf:
                                existing_logs = list(cm.DictReader(lf))
                        existing_logs.append(log_entry)
                        with log_path.open("w", encoding="utf-8-sig", newline="") as lf:
                            w = cm.DictWriter(lf, fieldnames=["timestamp", "batch", "pasien", "file", "label"])
                            w.writeheader()
                            w.writerows(existing_logs)

                        progress.status = "done"
                        st.success(f"✅ Selesai! {len(results)} file diproses.")
                        st.rerun()
                    except Exception as e:
                        progress.status = "error"
                        st.error(f"❌ Error: {e}")

    # ========== PROGRESS BAR ==========
    p = st.session_state.progress
    if p.status == "running":
        progress_bar = st.progress(0, text="Memulai...")
        progress_bar.progress(p.percent / 100, text=f"{p.current}/{p.total} — {p.current_file}")
        st.info(f"⏳ {p.current}/{p.total} file | ETA: {p.eta}")

    # ========== HASIL ==========
    if st.session_state.anon_results and p.status == "done":
        results = st.session_state.anon_results
        st.subheader("📊 Ringkasan Hasil")

        df = pd.DataFrame([{
            "File": r.source_file,
            "Status": r.extraction_status,
            "Karakter": r.chars_in,
            "Review": "⚠️ Ya" if r.needs_manual_review else "✅ Tidak",
        } for r in results])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📄 Total File", len(results))
        col2.metric("✅ Aman", sum(1 for r in results if not r.needs_manual_review))
        col3.metric("⚠️ Perlu Review", sum(1 for r in results if r.needs_manual_review))
        col4.metric("❌ Error", sum(1 for r in results if r.extraction_status == "error"))

        with st.expander("📋 Detail per File"):
            st.dataframe(df, use_container_width=True)

        # Download report
        report_dir = Path(st.session_state.get("proyek_dir", APP_DIR.parent)) / "laporan"
        report_csv = report_dir / "anonymization_report.csv"
        if report_csv.exists():
            with open(report_csv, "rb") as f:
                st.download_button(
                    label="⬇️ Download Laporan Audit (CSV)",
                    data=f,
                    file_name="anonymization_report.csv",
                    mime="text/csv",
                )

        # Error log
        if p.errors:
            with st.expander("❌ Error Log"):
                for err in p.errors:
                    st.code(err)

    # ── LANGKAH 2: EKSTRAKSI DATA ──
    st.markdown("---")
    st.subheader("📊 Langkah 2: Ekstraksi Data")
    st.caption("Dari hasil anonimisasi di atas, **atau dari folder anonim manapun** yang sudah pernah dibuat.")

    from pipeline_core import get_extractor_categories

    # Auto-detect batch terbaru dari proyek & beberapa lokasi umum
    proyek = Path(st.session_state.get("proyek_dir", APP_DIR.parent))
    scan_roots = set()
    scan_roots.add(proyek)
    scan_roots.add(APP_DIR.parent)
    scan_roots.add(APP_DIR.parent.parent)
    penelitian1 = APP_DIR.parent.parent / "Penelitian 1 Daedalus"
    if penelitian1.exists():
        scan_roots.add(penelitian1)
        data_dir = penelitian1 / "Data"
        if data_dir.exists():
            scan_roots.add(data_dir)
    found_anon = []
    for root in scan_roots:
        if root.exists():
            for d in root.iterdir():
                if d.is_dir() and d.name.startswith("anonim"):
                    found_anon.append(d)
                if d.is_dir() and d.name.lower() == "data":
                    for sub in d.iterdir():
                        if sub.is_dir() and sub.name.startswith("anonim"):
                            found_anon.append(sub)
    found_anon = sorted(set(found_anon))
    anon_options = [str(d) for d in found_anon]

    st.markdown("""
    ---
    **💡 Cara pakai:**
    1. **Auto-detect** → pilih folder anonim dari dropdown di bawah
    2. **Browse manual** → pilih "📁 Browse folder lain..." kalau folder anonim tidak muncul
    3. Folder anonim harus berisi **subfolder per pasien** + file **`.anon.txt`** di dalamnya
    """)

    col1, col2 = st.columns(2)
    with col1:
        if anon_options:
            anon_dir = st.selectbox(
                "📁 Pilih Batch Anonim",
                options=anon_options + ["📁 Browse folder lain..."],
                index=len(anon_options)-1,
                key="extract_batch_selector2",
            )
            if anon_dir == "📁 Browse folder lain...":
                anon_dir = folder_picker(
                    "📁 Folder Teks Anonim", str(proyek), "extract_anon_browse2",
                    help_text="Pilih folder yang BERISI subfolder pasien (bukan folder PDF mentah)"
                )
        else:
            st.info("🔍 Auto-detect tidak menemukan folder anonim. Browse manual di bawah:")
            anon_dir = folder_picker(
                "📁 Folder Teks Anonim", str(proyek), "extract_anon_browse2",
                help_text="Pilih folder yang BERISI subfolder pasien dengan file .anon.txt"
            )
    with col2:
        extract_output = folder_picker(
            "📁 Output Ekstraksi", str(proyek / "ekstraksi"), "extract_out_dir2",
            help_text="Folder untuk menyimpan hasil CSV/Excel ekstraksi"
        )

    anon_path = Path(anon_dir)
    if anon_path.exists():
        patients = sorted([d.name for d in anon_path.iterdir() if d.is_dir()])
    else:
        patients = []

    # ── VALIDASI: cek struktur folder ──
    if anon_path.exists() and patients:
        # Cek apakah ada file .anon.txt di subfolder pertama
        sample_dir = anon_path / patients[0]
        has_anon_files = len(list(sample_dir.glob("*.anon.txt"))) > 0
        total_anon_files = sum(1 for p in patients for _ in (anon_path / p).glob("*.anon.txt"))
        if has_anon_files:
            st.success(f"✅ **Struktur NESTED** — {len(patients)} folder pasien, **{total_anon_files}** file .anon.txt")
        else:
            st.warning(f"⚠️ Ditemukan {len(patients)} subfolder, tapi TIDAK ada file `.anon.txt` di dalamnya. "
                       "Folder ini mungkin bukan folder hasil anonimisasi.")
    elif anon_path.exists() and not patients:
        # Cek apakah ada file .anon.txt langsung (struktur FLAT)?
        flat_files = list(anon_path.glob("*.anon.txt"))
        if flat_files:
            patient_id = anon_path.name
            st.success(f"✅ **Struktur FLAT** — **{len(flat_files)}** file .anon.txt langsung di folder ini "
                       f"(akan diekstrak sebagai 1 pasien: `{patient_id}`)")
            patients = [patient_id]  # biar metric & tombol ekstrak jalan
        else:
            st.info(f"📂 Folder ditemukan, tapi **tidak ada file `.anon.txt`** di dalamnya. "
                    "Pastikan folder berisi file `.anon.txt` (hasil anonimisasi).")
    elif not anon_path.exists():
        st.error(f"❌ Folder tidak ditemukan: `{anon_dir}`")

    # ── PILIH KATEGORI ──
    st.subheader("📌 Pilih Kategori Data")
    st.caption("Centang kategori yang ingin diekstrak. Kosongkan untuk skip.")

    # ── FIELD MAP (untuk mapping nama field dari extractor) ──
    _FIELD_MAP = {
        "demo_age": "age",
        "demo_gender": "gender",
        "jenis_kelamin": "gender",
        "stroke_type": "stroke_type",
        "diagnosis_text": "diagnosis_text",
    }

    from pipeline_core import get_extractor_categories as _get_cats
    all_cats = list(_get_cats().keys())

    # Quick-select buttons
    qcol1, qcol2, qcol3, qcol4 = st.columns([1, 1, 1, 3])
    with qcol1:
        if st.button("💊 Medikasi Saja", use_container_width=True, key="qs_med_only2"):
            # Setel semua False dulu, lalu Medikasi True
            for c in all_cats:
                st.session_state[f"cat2_{c}"] = (c == "Medikasi")
            st.rerun()
    with qcol2:
        if st.button("✅ Semua Kategori", use_container_width=True, key="qs_all2"):
            for c in all_cats:
                st.session_state[f"cat2_{c}"] = True
            st.rerun()
    with qcol3:
        if st.button("❌ Hapus Semua", use_container_width=True, key="qs_none2"):
            for c in all_cats:
                st.session_state[f"cat2_{c}"] = False
            st.rerun()

    if "presets2" not in st.session_state:
        st.session_state.presets2 = {}
    if "preset_loaded2" not in st.session_state:
        st.session_state.preset_loaded2 = ""
    all_cats = list(_get_cats().keys())
    _cat_info = {c: _get_cats()[c] for c in all_cats}

    col_cats = st.columns(2)
    selected_cats = []
    selected_fields: dict[str, list[str]] = {}
    
    for i, cat in enumerate(all_cats):
        cat_info = _cat_info[cat]
        fields = cat_info['fields']
        with col_cats[i % 2]:
            if st.session_state.preset_loaded2:
                default_val = cat in st.session_state.presets2.get(st.session_state.preset_loaded2, [])
            else:
                default_val = st.session_state.get(f"cat2_{cat}", True)
            
            # Help tooltip yang menampilkan field names
            field_list = "`, `".join(fields)
            help_text = f"{cat_info['desc']}\n\n**Fields:** `{field_list}`"
            
            checked = st.checkbox(f"**{cat}** ({len(fields)} field)", value=default_val,
                                  help=help_text, key=f"cat2_{cat}")
            if checked:
                selected_cats.append(cat)
                
                # ── Sub-field selection untuk kategori ini (non-Medikasi) ──
                if cat != "Medikasi":
                    fcol1, fcol2 = st.columns(2)
                    cat_selected = []
                    for j, f in enumerate(fields):
                        col = fcol1 if j % 2 == 0 else fcol2
                        with col:
                            sf_key = f"sf_{cat}_{f}"
                            if sf_key not in st.session_state:
                                st.session_state[sf_key] = True
                            
                            # Label yang lebih ramah
                            friendly = f.replace("demo_", "").replace("lab_", "").replace("med_", "") \
                                        .replace("rf_", "").replace("act_", "").replace("ct_", "") \
                                        .replace("thorax_", "").replace("setting_", "").replace("fisik_", "")
                            friendly = friendly.replace("_", " ").title()
                            if friendly.upper() in ("PPI", "GCS", "LOS", "HR", "RR", "HB", "IMT", "BB", "TB"):
                                friendly = friendly.upper()
                            
                            sf_checked = st.checkbox(
                                f"{friendly}",
                                value=st.session_state.get(sf_key, True),
                                key=sf_key,
                                help=f"Field: `{f}`"
                            )
                            if sf_checked:
                                cat_selected.append(f)
                    
                    if cat_selected:
                        selected_fields[cat] = cat_selected
                    # Untuk Medikasi, gunakan selected_drug_keys sebagai selected_fields
                    # agar tidak dobel dengan drug sub-category yang sudah ada
                    else:
                        # Medikasi: field ikut drug sub-category selection
                        # selected_fields tidak diisi untuk Medikasi
                        # (drug sub-category sudah handle ini di extract_one_patient)
                        pass
            else:
                # Category unchecked — hapus dari selected_fields kalau ada
                if cat in selected_fields:
                    del selected_fields[cat]
                    # Hapus juga session state keys untuk kategori ini
                    for f in fields:
                        sf_key = f"sf_{cat}_{f}"
                        if sf_key in st.session_state:
                            del st.session_state[sf_key]

    if st.session_state.preset_loaded2:
        st.session_state.preset_loaded2 = ""

    # ── SUB-KATEGORI OBAT (kalau Medikasi dicentang) ──
    selected_drug_keys = None
    if "Medikasi" in selected_cats:
        st.markdown("##### 💊 Sub-kategori Obat")
        st.caption("Centang golongan obat yang ingin diekstrak. Kosongkan = semua.")
        from pipeline_core import get_drug_keywords
        all_drugs = get_drug_keywords()
        drug_keys = sorted([k for k in all_drugs if k.startswith("med_")])
        drug_labels = {
            k: k.replace("med_", "").replace("_", " ").title().replace("Ppi", "PPI")
            for k in drug_keys
        }

        # ── ACTION FLAG: tombol set flag, flag dieksekusi SEBELUM widget dirender ──
        if "drug_select_action" not in st.session_state:
            st.session_state.drug_select_action = None

        # Eksekusi flag (kalau ada) — SET state SEBELUM checkbox dirender
        if st.session_state.drug_select_action == "all":
            for dk in drug_keys:
                st.session_state[f"drug_sub_{dk}"] = True
            st.session_state.drug_select_action = None
        elif st.session_state.drug_select_action == "none":
            for dk in drug_keys:
                st.session_state[f"drug_sub_{dk}"] = False
            st.session_state.drug_select_action = None

        # Quick drug-select buttons — di ATAS checkbox
        dcol1, dcol2, dcol3 = st.columns([1, 1, 4])
        with dcol1:
            if st.button("🔘 Semua Obat", use_container_width=True, key="drug_all2"):
                st.session_state.drug_select_action = "all"
                st.rerun()
        with dcol2:
            if st.button("🔘 Hapus Semua", use_container_width=True, key="drug_none2"):
                st.session_state.drug_select_action = "none"
                st.rerun()

        # Render checkbox — state SUDAH siap dari flag di atas
        col_drugs = st.columns(3)
        selected_drug_keys = []
        for i, dk in enumerate(drug_keys):
            with col_drugs[i % 3]:
                # Init default (hanya sekali seumur hidup)
                if f"drug_sub_{dk}" not in st.session_state:
                    st.session_state[f"drug_sub_{dk}"] = True
                checked = st.checkbox(
                    f"{drug_labels.get(dk, dk)} ({len(all_drugs.get(dk, []))} keyword)",
                    value=st.session_state.get(f"drug_sub_{dk}", True),
                    key=f"drug_sub_{dk}"
                )
                if checked:
                    selected_drug_keys.append(dk)

        if not selected_drug_keys:
            st.info("ℹ️ Tidak ada golongan obat dipilih. Medikasi tidak akan diekstrak.")
            # [] → tidak ada obat yang diekstrak (beda dengan None = semua)

    with st.expander("💾 Preset Kategori", expanded=bool(st.session_state.presets2)):
        pc1, pc2 = st.columns([3, 1])
        with pc1:
            pname = st.text_input("Nama preset", placeholder="ct: stroke_lengkap", key="preset_name_input2")
        with pc2:
            st.markdown("###")
            if st.button("💾 Simpan preset", key="save_preset_btn2", use_container_width=True):
                if pname.strip() and selected_cats:
                    st.session_state.presets2[pname.strip()] = selected_cats
                    st.success(f"✅ Preset '{pname}' tersimpan ({len(selected_cats)} kategori)")
        if st.session_state.presets2:
            st.markdown("**Preset tersimpan:**")
            for pname, pcats in st.session_state.presets2.items():
                ca, cb = st.columns([1, 3])
                with ca:
                    if st.button(f"📂 {pname} ({len(pcats)})", key=f"load_preset2_{pname}", use_container_width=True):
                        st.session_state.preset_loaded2 = pname
                        st.rerun()
                with cb:
                    st.caption(", ".join(pcats))

    # Tombol ekstrak
    btn1, btn2 = st.columns([3, 1])
    with btn1:
        run_extract2 = st.button("🚀 Ekstrak Data", type="primary", use_container_width=True, key="extract_btn2")
    with btn2:
        st.metric("📂 Pasien", len(patients) if patients else 0)

    if run_extract2:
        if not patients:
            st.error("Tidak ada folder pasien ditemukan.")
        elif not selected_cats:
            st.warning("Pilih minimal satu kategori.")
        else:
            with st.spinner(f"Mengekstrak {len(patients)} pasien — {len(selected_cats)} kategori..."):
                try:
                    results = extract_all_patients(anon_dir, selected_cats, selected_drug_keys, selected_fields)
                    st.session_state.extract_results = results
                    st.success(f"✅ Ekstraksi selesai! {len(results)} pasien.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── HASIL EKSTRAKSI ──
    if st.session_state.extract_results:
        df = pd.DataFrame(st.session_state.extract_results)
        st.subheader(f"📊 Hasil Ekstraksi ({len(df)} pasien × {len(df.columns)} kolom)")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pasien", len(df))
        if "stroke_type" in df.columns:
            c2.metric("Stroke Infark", int((df["stroke_type"] == "INFARK").sum()))
        if "demo_age" in df.columns:
            ages = pd.to_numeric(df["demo_age"], errors="coerce")
            c3.metric("Rata-rata Usia", f"{ages.mean():.0f}" if ages.notna().any() else "-")
        if "lama_rawat_hari" in df.columns:
            los = pd.to_numeric(df["lama_rawat_hari"], errors="coerce")
            c4.metric("Rata-rata LOS (hari)", f"{los.mean():.1f}" if los.notna().any() else "-")

        invalid_cols = [c for c in df.columns if (df[c] == "invalid").any()]
        if invalid_cols:
            st.warning(f"⚠️ {len(invalid_cols)} kolom memiliki data invalid (di luar range):")
            for ic in invalid_cols:
                st.caption(f"  • `{ic}` — {int((df[ic]=='invalid').sum())} pasien")
            st.caption("Klik cell di tabel untuk mengedit.")

        edited_df = st.data_editor(df, use_container_width=True, num_rows="fixed",
                                    key="extract_data_editor2", hide_index=True)

        st.subheader("⬇️ Download Data")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            csv_data = edited_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📄 Download CSV", csv_data, f"stroke_infark_{ts}.csv", "text/csv", use_container_width=True)
        with dl2:
            try:
                out_path = Path(extract_output)
                out_path.mkdir(parents=True, exist_ok=True)
                excel_path = out_path / f"stroke_infark_{ts}.xlsx"
                edited_df.to_excel(excel_path, index=False)
                with open(excel_path, "rb") as f:
                    st.download_button("📊 Download Excel", f, f"stroke_infark_{ts}.xlsx",
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            except Exception as e:
                st.error(f"Excel error: {e}")
        with dl3:
            all_cols = list(edited_df.columns)
            sel = st.multiselect("Pilih kolom", all_cols, default=all_cols, key="col_select2")
            if sel:
                st.download_button("🎯 Export Terpilih", edited_df[sel].to_csv(index=False).encode("utf-8-sig"),
                                   f"stroke_infark_{ts}_selected.csv", "text/csv", use_container_width=True)


# ================================================================
# TAB 3: DATA STAF RS
# ================================================================

elif active_tab == "👥 Data Staf RS":
    st.title("👥 Data Staf RS")
    st.caption("Kelola daftar dokter dan staf untuk anonimisasi.")

    # ========== UPLOAD CSV ==========
    with st.expander("📤 Upload File Staf", expanded=False):
        uploaded = st.file_uploader("Pilih file CSV staf", type=["csv"])
        if uploaded:
            # Baca dan validasi
            try:
                content = uploaded.read().decode("utf-8-sig")
                reader = csv.DictReader(content.splitlines())
                rows = []
                for row in reader:
                    rows.append({
                        "name": (row.get("name") or "").strip(),
                        "role": (row.get("role") or "").strip(),
                    })
                if rows:
                    st.session_state.staff_data = rows
                    save_staff_csv_data(st.session_state.staff_csv_path, rows)
                    st.success(f"✅ {len(rows)} staf dimuat dari CSV")
                    st.rerun()
                else:
                    st.error("CSV kosong atau format salah. Pastikan kolom 'name' dan 'role'.")
            except Exception as e:
                st.error(f"Gagal membaca CSV: {e}")

        st.markdown("**Format CSV:**")
        st.code("name,role\ndr. Mugi Rahayu,DOKTER_UMUM\ndr. Hj. Dewi Nurhayati,DOKTER_UMUM", language="text")

    # ========== TABEL STAF ==========
    st.subheader(f"Daftar Staf ({len(st.session_state.staff_data)} orang)")

    if not st.session_state.staff_data:
        st.info("Belum ada data staf. Upload CSV atau tambah manual.")
    else:
        df_staff = pd.DataFrame(st.session_state.staff_data)
        st.dataframe(df_staff, use_container_width=True)

    # ========== TAMBAH STAF ==========
    with st.expander("➕ Tambah Staf Baru", expanded=False):
        with st.form("add_staff_form"):
            name = st.text_input("Nama Lengkap", placeholder="dr. Nama Dokter Sp.PD")
            role = st.text_input("Role (biarkan kosong untuk otomatis)", placeholder="DOKTER_SPESIALIS_PENYAKIT_DALAM")
            if st.form_submit_button("✅ Tambah"):
                if name.strip():
                    from pipeline_core import infer_role
                    final_role = role.strip() or infer_role(name)
                    st.session_state.staff_data.append({"name": name.strip(), "role": final_role})
                    save_staff_csv_data(st.session_state.staff_csv_path, st.session_state.staff_data)
                    st.success(f"✅ {name} → [{final_role}] ditambahkan")
                    st.rerun()

    # ========== HAPUS / EDIT ==========
    if st.session_state.staff_data:
        with st.expander("🗑️ Hapus Staf", expanded=False):
            names = [s["name"] for s in st.session_state.staff_data]
            to_remove = st.selectbox("Pilih staf yang akan dihapus:", names, index=None)
            if to_remove and st.button("🗑️ Hapus", type="secondary"):
                st.session_state.staff_data = [s for s in st.session_state.staff_data if s["name"] != to_remove]
                save_staff_csv_data(st.session_state.staff_csv_path, st.session_state.staff_data)
                st.success(f"✅ {to_remove} dihapus")
                st.rerun()

    # ========== DOWNLOAD ==========
    if st.session_state.staff_data:
        csv_output = "name,role\n" + "\n".join(
            f"{s['name']},{s['role']}" for s in st.session_state.staff_data
        )
        st.download_button(
            label="⬇️ Download CSV Staf",
            data=csv_output.encode("utf-8-sig"),
            file_name="staff_doctors.csv",
            mime="text/csv",
        )
        st.caption(f"Disimpan di: `{st.session_state.staff_csv_path}`")


# ================================================================
# TAB 4: DATABASE OBAT
# ================================================================

elif active_tab == "💊 Database Obat":
    st.title("💊 Database Obat")
    st.caption("Kelola daftar obat yang dideteksi saat ekstraksi. Bisa **tambah kategori baru**, edit, atau hapus — tanpa perlu edit kode.")

    # Load path
    IMPORT_DIR = Path(__file__).resolve().parent
    drug_json_path = IMPORT_DIR / "drug_database.json"

    # Load atau buat default
    if "drug_db_cache" not in st.session_state:
        if drug_json_path.exists():
            st.session_state.drug_db_cache = json.loads(drug_json_path.read_text(encoding="utf-8"))
        else:
            from pipeline_core import get_drug_keywords
            st.session_state.drug_db_cache = get_drug_keywords()

    db = st.session_state.drug_db_cache

    # ── Helper: generate display name dari key ──
    def key_to_label(key: str) -> str:
        name = key.replace("med_", "").replace("_", " ")
        if name.upper() in ("PPI",):
            return name.upper()
        return name.title().strip()

    # ── TAMBAH KATEGORI BARU ──
    st.subheader("➕ Tambah Kategori Obat Baru")
    col_new1, col_new2 = st.columns([3, 1])
    with col_new1:
        new_cat_key = st.text_input(
            "Nama kategori (contoh: med_antidiabetes, med_antivirus, med_bronkodilator)",
            placeholder="med_antidiabetes",
            key="drug_new_cat_key",
            help="Gunakan format 'med_nama_kategori'. Nanti dipakai sebagai kolom di CSV."
        )
    with col_new2:
        st.caption("")
        st.caption("")
        if st.button("➕ Tambah", type="primary", use_container_width=True, key="drug_add_cat"):
            key = new_cat_key.strip().lower()
            if not key:
                st.warning("⚠️ Masukkan nama kategori dulu.")
            elif not key.startswith("med_"):
                st.error("❌ Nama kategori harus diawali 'med_' — contoh: med_antidiabetes")
            elif key in db:
                st.warning("⚠️ Kategori ini sudah ada.")
            elif not key[4:]:
                st.error("❌ Nama kategori tidak boleh kosong setelah 'med_'.")
            else:
                db[key] = []
                st.session_state.drug_db_cache = db
                drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
                st.success(f"✅ Kategori '{key}' berhasil ditambahkan! Sekarang isi keyword-nya di bawah.")
                st.rerun()

    # ── Tambah cepat dari template ──
    with st.expander("📋 Template kategori yang sering dipakai"):
        template_options = {
            "med_antidiabetes": "antidiabetes, metformin, glibenclamide, glimepiride, insulin, glukofag, diabex",
            "med_antivirus": "antivirus, oseltamivir, tamiflu, asiklovir, acyclovir, favipiravir",
            "med_antijamur": "antijamur, flukonazol, fluconazole, ketokonazol, ketoconazole, miconazole, mikazol",
            "med_bronkodilator": "bronkodilator, salbutamol, ventolin, ipratropium, kombivent, teofilin",
            "med_kortikosteroid": "kortikosteroid, deksametason, dexamethasone, methylprednisolone, prednison, prednisone, hidrokortison",
            "med_antiepilepsi": "antiepilepsi, fenitoin, phenytoin, valproic acid, asam valproat, levetiracetam, keppra, karbamazepin, carbamazepine",
            "med_analgesik": "analgesik, parasetamol, paracetamol, acetaminophen, tramadol, pethidin, morphine, morfin, NSAID, ibuprofen, ketorolac, asam mefenamat",
            "med_obat_jantung": "obat jantung, digoxin, digoksin, nitrat, isosorbide dinitrate, ISDN, isosorbide mononitrate, ISMN"
        }
        selected_template = st.selectbox(
            "Pilih template untuk ditambahkan:", options=[""] + list(template_options.keys()),
            format_func=lambda k: key_to_label(k) if k else "— Pilih template —"
        )
        if selected_template and st.button("📥 Tambah Template Ini", key="drug_add_template"):
            if selected_template in db:
                st.warning(f"⚠️ Kategori '{selected_template}' sudah ada. Lewati.")
            else:
                keywords = [k.strip().lower() for k in template_options[selected_template].split(",")]
                db[selected_template] = keywords
                st.session_state.drug_db_cache = db
                drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
                st.success(f"✅ Template '{key_to_label(selected_template)}' ditambahkan ({len(keywords)} keyword)!")
                st.rerun()

    st.markdown("---")

    # ── Kategori yang TIDAK BISA DIHAPUS (default + template) ──
    PROTECTED_CATEGORIES = {
        "med_antiplatelet",
        "med_antikoagulan", "med_statin", "med_antihipertensi",
        "med_mannitol", "med_citicoline", "med_ppi", "med_antibiotik",
        "med_antidiabetes", "med_antivirus", "med_antijamur",
        "med_bronkodilator", "med_kortikosteroid", "med_antiepilepsi",
        "med_analgesik", "med_obat_jantung",
    }

    # ── EDIT / HAPUS KATEGORI ──
    drug_cats = {k: v for k, v in db.items() if k.startswith("med_")}
    if not drug_cats:
        st.info("💡 Belum ada kategori. Tambah kategori baru di atas.")
    else:
        cat_options = sorted(drug_cats.keys())
        kategori_terpilih = st.selectbox(
            "📌 Pilih Kategori Obat",
            options=cat_options,
            format_func=lambda k: f"{'🔒 ' if k in PROTECTED_CATEGORIES else '📝 '}{key_to_label(k)} ({len(db.get(k, []))} keyword)",
            key="drug_cat_selector"
        )

        if kategori_terpilih:
            is_protected = kategori_terpilih in PROTECTED_CATEGORIES
            st.subheader(f"✏️ {key_to_label(kategori_terpilih)}")
            if is_protected:
                st.caption("🔒 **Kategori default — tidak bisa dihapus.** Tambah / hapus keyword tetap bisa.")
            else:
                st.caption("Tambah / hapus keyword. Simpan setelah selesai.")

            col_hapus, _ = st.columns([1, 4])
            with col_hapus:
                if is_protected:
                    st.button(f"🔒 Tidak Bisa Dihapus (Default)", disabled=True, use_container_width=True, key="drug_del_cat_protected")
                else:
                    if st.button(f"🗑️ Hapus Kategori Ini", type="secondary", use_container_width=True, key="drug_del_cat"):
                        if kategori_terpilih in db:
                            del db[kategori_terpilih]
                        st.session_state.drug_db_cache = db
                        drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
                        st.warning(f"🗑️ Kategori '{kategori_terpilih}' dihapus.")
                        st.rerun()

            current_keywords = "\n".join(db.get(kategori_terpilih, []))
            new_keywords_text = st.text_area(
                "✏️ Satu keyword per baris",
                value=current_keywords,
                height=300,
                key=f"drug_ta_{kategori_terpilih}",
                help="Tambah, hapus, atau edit. Satu baris = satu keyword/varian obat."
            )

            col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
            with col_s1:
                if st.button("💾 Simpan Kategori Ini", type="primary", use_container_width=True, key="drug_save_cat"):
                    parsed = [k.strip().lower() for k in new_keywords_text.split("\n") if k.strip()]
                    db[kategori_terpilih] = parsed
                    st.session_state.drug_db_cache = db
                    drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
                    st.success(f"✅ {kategori_terpilih} tersimpan ({len(parsed)} keyword)")
                    st.rerun()
            with col_s2:
                if st.button("🔄 Reset ke Default", use_container_width=True, key="drug_reset_cat"):
                    if kategori_terpilih in db:
                        del db[kategori_terpilih]
                    st.session_state.drug_db_cache = db
                    drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
                    st.warning(f"⚠️ {kategori_terpilih} direset. Sisa kategori lain tetap tersimpan.")
                    st.rerun()

            parsed_preview = [k.strip().lower() for k in new_keywords_text.split("\n") if k.strip()]
            st.caption(f"📊 **{len(parsed_preview)}** keyword untuk kategori ini.")

    # ── RINGKASAN SEMUA ──
    st.markdown("---")
    st.subheader("📊 Ringkasan Semua Kategori")
    all_drug_cats = {k: v for k, v in db.items() if k.startswith("med_")}
    summary_data = []
    for k, v in sorted(all_drug_cats.items()):
        summary_data.append({"Kategori": key_to_label(k), "Key": k, "Jumlah Keyword": len(v)})
    if summary_data:
        st.dataframe(summary_data, use_container_width=True, hide_index=True)
        total_keywords = sum(len(v) for v in all_drug_cats.values())
        st.caption(f"📦 **{len(all_drug_cats)} kategori** | **{total_keywords} keyword** total")
    else:
        st.info("Belum ada kategori obat.")

    # Simpan semua sekaligus
    if st.button("💾 Simpan Semua Perubahan", type="primary", use_container_width=True, key="drug_save_all"):
        drug_json_path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
        drug_cats_count = len([k for k in db if k.startswith("med_")])
        total_kw = sum(len(v) for k, v in db.items() if k.startswith("med_"))
        st.success(f"✅ Database obat tersimpan ({drug_cats_count} kategori, {total_kw} keyword total)")
        st.rerun()

    st.markdown("---")
    st.subheader("📋 Kelola Field per Kategori Data")
    st.caption("Lihat daftar field untuk setiap kategori hardcoded. **Override field list** dengan menyimpannya ke JSON.")
    
    EXTRA_CAT_PATH = IMPORT_DIR / "extractor_categories_extra.json"
    
    from pipeline_core import get_extractor_categories as _get_cats_mgr
    all_hardcoded = sorted([k for k in _get_cats_mgr().keys()])
    
    # Load extra cats for override detection
    if "extra_cats_mgr" not in st.session_state:
        if EXTRA_CAT_PATH.exists():
            raw_mgr = json.loads(EXTRA_CAT_PATH.read_text(encoding="utf-8"))
            st.session_state.extra_cats_mgr = {k: v for k, v in raw_mgr.items() if not k.startswith("_")}
        else:
            st.session_state.extra_cats_mgr = {}
    extra_mgr = st.session_state.extra_cats_mgr
    
    # Cari kategori yang sudah di-override
    override_names = set()
    if extra_mgr:
        override_names = {k for k in extra_mgr if k in all_hardcoded}
    
    cat_to_edit = st.selectbox(
        "Pilih kategori untuk lihat / override field:",
        options=[""] + all_hardcoded,
        format_func=lambda k: f"{'🔄 ' if k in override_names else '📝 '}{k}" if k else "— Pilih kategori —",
        key="cat_field_selector"
    )
    
    if cat_to_edit:
        ci = _get_cats_mgr()[cat_to_edit]
        current_fields = ci['fields']
        is_overridden = cat_to_edit in override_names
        
        if is_overridden:
            st.info(f"🔄 Kategori ini sedang di-override oleh `extractor_categories_extra.json`")
        
        st.markdown(f"**Deskripsi:** {ci.get('desc', '-')}")
        st.markdown(f"**Field saat ini ({len(current_fields)}):**")
        for i, f in enumerate(current_fields):
            st.code(f"  {i+1}. {f}", language="text")
        
        # Tombol override
        col_o1, col_o2, col_o3 = st.columns([1, 1, 3])
        with col_o1:
            if st.button("📝 Override Field List", use_container_width=True, key="override_fields_btn"):
                # Buka form override
                st.session_state.show_override_form = cat_to_edit
                st.rerun()
        with col_o2:
            if is_overridden:
                if st.button("🔄 Reset ke Default", use_container_width=True, key="reset_override_btn"):
                    # Hapus dari extra_mgr
                    if cat_to_edit in extra_mgr:
                        del extra_mgr[cat_to_edit]
                    all_data = {"_comment": "Kategori data tambahan untuk ekstraksi RME Stroke."}
                    for k, v in sorted(extra_mgr.items()):
                        all_data[k] = v
                    EXTRA_CAT_PATH.write_text(json.dumps(all_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    st.session_state.extra_cats_mgr = extra_mgr
                    st.success(f"✅ '{cat_to_edit}' direset ke field default")
                    st.rerun()
        
        # Form override (kalau tombol ditekan)
        if st.session_state.get("show_override_form") == cat_to_edit:
            st.markdown("**✏️ Edit field list (satu field per baris):**")
            current_text = "\n".join(current_fields)
            new_fields_text = st.text_area(
                "Field baru:",
                value=current_text,
                height=250,
                key=f"override_ta_{cat_to_edit}",
                help="Satu nama field per baris. Field ini akan menggantikan field default."
            )
            
            col_s1, col_s2 = st.columns([1, 3])
            with col_s1:
                if st.button("💾 Simpan Override", type="primary", use_container_width=True, key="save_override_btn"):
                    parsed = [f.strip() for f in new_fields_text.split("\n") if f.strip()]
                    if parsed:
                        extra_mgr[cat_to_edit] = {
                            "fields": parsed,
                            "desc": ci.get("desc", cat_to_edit),
                            "extractor": "keyword" if cat_to_edit in extra_mgr and extra_mgr.get(cat_to_edit, {}).get("keywords") else "none",
                            "keywords": extra_mgr.get(cat_to_edit, {}).get("keywords", []),
                        }
                        all_data = {"_comment": "Kategori data tambahan untuk ekstraksi RME Stroke."}
                        for k, v in sorted(extra_mgr.items()):
                            all_data[k] = v
                        EXTRA_CAT_PATH.write_text(json.dumps(all_data, indent=2, ensure_ascii=False), encoding="utf-8")
                        st.session_state.extra_cats_mgr = extra_mgr
                        st.session_state.show_override_form = None
                        st.success(f"✅ Field '{cat_to_edit}' di-override ({len(parsed)} field)")
                        st.rerun()
            with col_s2:
                if st.button("❌ Batal", use_container_width=True, key="cancel_override_btn"):
                    st.session_state.show_override_form = None
                    st.rerun()
    
    st.markdown("---")
    st.subheader("📋 Kategori Data Tambahan (Baru)")
    st.caption("Kelola kategori data baru (selain obat) yang akan muncul di daftar centang ekstraksi. "
               "Gunakan pencocokan kata kunci sederhana.")
    
    EXTRA_CAT_PATH = IMPORT_DIR / "extractor_categories_extra.json"
    
    # Load extra categories
    if "extra_cats_cache" not in st.session_state:
        if EXTRA_CAT_PATH.exists():
            raw = json.loads(EXTRA_CAT_PATH.read_text(encoding="utf-8"))
            st.session_state.extra_cats_cache = {k: v for k, v in raw.items() if not k.startswith("_")}
        else:
            st.session_state.extra_cats_cache = {}
    
    extra_db = st.session_state.extra_cats_cache
    
    # ── TAMBAH KATEGORI BARU ──
    with st.expander("➕ Tambah Kategori Data Baru", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            new_cat_name = st.text_input("Nama kategori", placeholder="ct: Anamnesis, RPD, ...",
                                         key="extra_cat_new_name")
        with col2:
            new_cat_fields = st.text_input("Nama field (pisah koma)", placeholder="ct: anamnesis_utama, anamnesis_tambahan",
                                          key="extra_cat_new_fields",
                                          help="Nama kolom di output, dipisah koma")
        new_cat_keywords = st.text_input("Kata kunci (pisah koma, opsional)", 
                                        placeholder="ct: keluhan utama, riwayat penyakit, anamnesis",
                                        key="extra_cat_new_keywords",
                                        help="Kata kunci yang dicari di teks. Kosongkan = isi manual")
        new_cat_desc = st.text_input("Deskripsi singkat", placeholder="ct: Informasi anamnesis pasien",
                                    key="extra_cat_new_desc")
        
        if st.button("✅ Tambah Kategori Data", type="primary", use_container_width=True, key="extra_cat_add"):
            if not new_cat_name.strip():
                st.warning("⚠️ Masukkan nama kategori.")
            elif not new_cat_fields.strip():
                st.warning("⚠️ Masukkan minimal satu nama field.")
            else:
                fields = [f.strip() for f in new_cat_fields.split(",") if f.strip()]
                keywords = [k.strip().lower() for k in new_cat_keywords.split(",") if k.strip()] if new_cat_keywords.strip() else []
                extra_db[new_cat_name.strip()] = {
                    "fields": fields,
                    "desc": new_cat_desc.strip() or f"Kategori user: {new_cat_name.strip()}",
                    "extractor": "keyword" if keywords else "none",
                    "keywords": keywords,
                }
                # Simpan ke file
                all_data = {"_comment": "Kategori data tambahan untuk ekstraksi RME Stroke."}
                for k, v in sorted(extra_db.items()):
                    all_data[k] = v
                EXTRA_CAT_PATH.write_text(json.dumps(all_data, indent=2, ensure_ascii=False), encoding="utf-8")
                st.session_state.extra_cats_cache = extra_db
                st.success(f"✅ Kategori '{new_cat_name.strip()}' ditambahkan! ({len(fields)} field, {len(keywords)} keyword)")
                st.rerun()
    
    # ── DAFTAR KATEGORI TAMBAHAN ──
    if not extra_db:
        st.info("💡 Belum ada kategori tambahan. Tambah di atas.")
    else:
        st.subheader(f"Daftar Kategori Tambahan ({len(extra_db)})")
        for cat_name, cat_data in sorted(extra_db.items()):
            with st.expander(f"📝 {cat_name} ({len(cat_data.get('fields', []))} field)"):
                st.caption(f"*{cat_data.get('desc', '-')}*")
                st.markdown(f"**Fields:** `{', '.join(cat_data.get('fields', []))}`")
                st.markdown(f"**Keywords:** {', '.join(cat_data.get('keywords', [])) if cat_data.get('keywords') else '*tidak ada*'}")
                
                col_del, col_save = st.columns([1, 4])
                with col_del:
                    if st.button(f"🗑️ Hapus", key=f"extra_cat_del_{cat_name}"):
                        del extra_db[cat_name]
                        all_data = {"_comment": "Kategori data tambahan untuk ekstraksi RME Stroke."}
                        for k, v in sorted(extra_db.items()):
                            all_data[k] = v
                        EXTRA_CAT_PATH.write_text(json.dumps(all_data, indent=2, ensure_ascii=False), encoding="utf-8")
                        st.session_state.extra_cats_cache = extra_db
                        st.warning(f"🗑️ '{cat_name}' dihapus.")
                        st.rerun()


# ================================================================
# TAB 5: LAPORAN AUDIT
# ================================================================

elif active_tab == "📊 Laporan Audit":
    st.title("📊 Laporan Audit Anonimisasi")
    st.caption("Periksa hasil anonimisasi — deteksi sisa kebocoran data.")

    # Auto-connect dari folder proyek
    laporan_proyek = Path(st.session_state.get("proyek_dir", APP_DIR.parent)) / "laporan"
    report_path = laporan_proyek / "anonymization_report.csv"

    # Fallback: manual picker kalau file tidak ditemukan di auto-path
    if not report_path.exists():
        st.info(f"🔍 Laporan auto dari: `{laporan_proyek}` — file tidak ditemukan.")
        st.caption("Gunakan folder picker di bawah untuk cari manual, atau jalankan anonimisasi dulu.")
        report_dir = folder_picker(
            "📁 Cari Folder Laporan Manual", str(laporan_proyek), "report_dir_picker",
            help_text="Folder yang berisi anonymization_report.csv"
        )
        report_path = Path(report_dir) / "anonymization_report.csv"
    else:
        st.success(f"✅ Laporan auto-terhubung ke: `{laporan_proyek}`")
        st.caption("💡 Klik Browse jika ingin ganti folder laporan lain.")

    # Tampilkan data laporan (dari auto-path atau manual picker)
    if report_path.exists():
        df = pd.read_csv(report_path, encoding="utf-8-sig")
        st.success(f"✅ Ditemukan {len(df)} file dalam laporan.")

        # Summary stats
        col1, col2, col3 = st.columns(3)
        col1.metric("📄 Total File", len(df))
        if "needs_manual_review" in df.columns:
            review_count = int(df["needs_manual_review"].sum())
            col2.metric("⚠️ Perlu Review", review_count)
            col3.metric("✅ Aman", len(df) - review_count)

        # Filter
        st.subheader("🔍 Filter & Cari")
        col1, col2 = st.columns(2)
        with col1:
            search = st.text_input("Cari file:", placeholder="cppt_igd, resume, ...")
        with col2:
            show_only_review = st.checkbox("Hanya yang perlu review")

        filtered = df.copy()
        if search:
            filtered = filtered[filtered["source_file"].str.contains(search, case=False, na=False)]
        if show_only_review and "needs_manual_review" in filtered.columns:
            filtered = filtered[filtered["needs_manual_review"] == True]

        st.subheader(f"Detail ({len(filtered)} file)")
        st.dataframe(filtered, use_container_width=True)

        leftover_cols = [c for c in df.columns if c.startswith("leftover_")]
        if leftover_cols:
            st.subheader("🔐 Sisa Kebocoran (Leftovers)")
            leftover_df = df[["source_file"] + leftover_cols].copy()
            mask = (leftover_df[leftover_cols].apply(pd.to_numeric, errors='coerce') > 0).any(axis=1)
            if mask.any():
                st.warning("⚠️ Beberapa file memiliki sisa identitas yang mungkin belum teranoniimasi!")
                st.dataframe(leftover_df[mask], use_container_width=True)
            else:
                st.success("✅ Tidak ada sisa kebocoran terdeteksi.")

        csv_data = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="⬇️ Download Laporan (CSV)",
            data=csv_data,
            file_name="anonymization_report.csv",
            mime="text/csv",
        )


# ================================================================
# TAB 5: EKSTRAKSI DATA
# ================================================================
# TAB 5: (digabung ke Tab 2)
# ================================================================

if False:  # noqa
    st.title("📋 Ekstraksi Data Terstruktur")
    st.caption("Pilih folder anonim hasil anonimisasi, lalu ekstrak data penelitian.")

    from pipeline_core import get_extractor_categories as _get_cats2

    # Auto-scan: cari semua folder anonim di lokasi umum
    scan_roots = set()
    # Pipeline_RME_Stroke/cp_stroke_app/ -> parent = Pipeline_RME_Stroke
    scan_roots.add(APP_DIR.parent)
    # Penelitian/
    scan_roots.add(APP_DIR.parent.parent)
    # Penelitian 1 Daedalus/
    penelitian1 = APP_DIR.parent.parent / "Penelitian 1 Daedalus"
    if penelitian1.exists():
        scan_roots.add(penelitian1)
        # Data/ di dalamnya
        data_dir = penelitian1 / "Data"
        if data_dir.exists():
            scan_roots.add(data_dir)

    # Semua folder dengan nama "anonim" atau diawali "anonim_"
    found_anon = []
    for root in scan_roots:
        if root.exists():
            for d in root.iterdir():
                if d.is_dir() and d.name.startswith("anonim"):
                    found_anon.append(d)
                    # Include subfolder
                if d.is_dir() and d.name.lower() == "data":
                    for sub in d.iterdir():
                        if sub.is_dir() and sub.name.startswith("anonim"):
                            found_anon.append(sub)

    found_anon = sorted(set(found_anon))
    anon_options = [str(d) for d in found_anon]

    col1, col2 = st.columns(2)
    with col1:
        if anon_options:
            anon_dir = st.selectbox(
                "📁 Pilih Batch Anonim",
                options=anon_options + ["📁 Browse folder lain..."],
                index=len(anon_options)-1,
                key="extract_batch_selector",
            )
            if anon_dir == "📁 Browse folder lain...":
                anon_dir = folder_picker(
                    "📁 Folder Teks Anonim", str(APP_DIR.parent), "extract_anon_browse",
                    help_text="Folder berisi subfolder pasien dengan file .anon.txt"
                )
        else:
            anon_dir = folder_picker(
                "📁 Folder Teks Anonim", str(APP_DIR.parent), "extract_anon_browse",
                help_text="Folder berisi subfolder pasien dengan file .anon.txt"
            )
    with col2:
        extract_output = folder_picker(
            "📁 Output Ekstraksi", str(APP_DIR.parent / "ekstraksi"), "extract_out_dir",
            help_text="Folder untuk menyimpan hasil CSV/Excel ekstraksi"
        )

    # Cek folder
    anon_path = Path(anon_dir)
    if anon_path.exists():
        patients = sorted([d.name for d in anon_path.iterdir() if d.is_dir()])
    else:
        patients = []

    # ── 1. PILIH KATEGORI ──
    st.subheader("📌 Pilih Kategori Data")
    st.caption("Centang kategori yang ingin diekstrak. Kosongkan untuk skip.")

    if "presets" not in st.session_state:
        st.session_state.presets = {}
    if "preset_loaded" not in st.session_state:
        st.session_state.preset_loaded = ""

    all_cats = list(_get_cats2().keys())

    # ── RENDER CHECKBOX DULU (biar state-nya siap) ──
    col_cats = st.columns(2)
    selected_cats = []
    for i, cat in enumerate(all_cats):
        info = _get_cats2()[cat]
        with col_cats[i % 2]:
            # Apply preset: override default checkbox state
            if st.session_state.preset_loaded:
                default_val = cat in st.session_state.presets.get(st.session_state.preset_loaded, [])
            else:
                default_val = st.session_state.get(f"cat_{cat}", True)
            checked = st.checkbox(
                f"**{cat}** ({len(info['fields'])} field)",
                value=default_val,
                help=info["desc"],
                key=f"cat_{cat}",
            )
            if checked:
                selected_cats.append(cat)

    # Reset preset_loaded setelah diterapkan
    if st.session_state.preset_loaded:
        st.session_state.preset_loaded = ""

    # ── PRESET SAVE / LOAD ──
    with st.expander("💾 Preset Kategori", expanded=bool(st.session_state.presets)):
        preset_col1, preset_col2 = st.columns([3, 1])
        with preset_col1:
            preset_name = st.text_input("Nama preset", placeholder="ct: stroke_lengkap", key="preset_name_input")
        with preset_col2:
            st.markdown("###")
            if st.button("💾 Simpan preset", key="save_preset_btn", use_container_width=True):
                if preset_name.strip() and selected_cats:
                    st.session_state.presets[preset_name.strip()] = selected_cats
                    st.success(f"✅ Preset '{preset_name}' tersimpan ({len(selected_cats)} kategori)")

        if st.session_state.presets:
            st.markdown("**Preset tersimpan:**")
            # Tampilkan per preset dengan detail kategori
            for pname, pcats in st.session_state.presets.items():
                with st.container():
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        if st.button(f"📂 {pname} ({len(pcats)})", key=f"load_preset_{pname}", use_container_width=True):
                            st.session_state.preset_loaded = pname
                            st.rerun()
                    with col_b:
                        st.caption(", ".join(pcats))

    # Tombol ekstraksi
    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        run_extract = st.button("🚀 Mulai Ekstraksi", type="primary", use_container_width=True)
    with btn_col2:
        st.metric("📂 Pasien", len(patients) if patients else 0)

    # ── 2. JALANKAN EKSTRAKSI ──
    if run_extract:
        if not patients:
            st.error("Tidak ada folder pasien ditemukan.")
        elif not selected_cats:
            st.warning("Pilih minimal satu kategori.")
        else:
            with st.spinner(f"Mengekstrak {len(patients)} pasien — kategori: {', '.join(selected_cats)}..."):
                try:
                    results = extract_all_patients(anon_dir, selected_cats)
                    st.session_state.extract_results = results

                    st.success(f"✅ Ekstraksi selesai! {len(results)} pasien, {len(selected_cats)} kategori.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── 3. EDIT + DOWNLOAD ──
    if st.session_state.extract_results:
        df = pd.DataFrame(st.session_state.extract_results)

        # Ringkasan
        st.subheader(f"📊 Hasil Ekstraksi ({len(df)} pasien × {len(df.columns)} kolom)")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Pasien", len(df))
        if "stroke_type" in df.columns:
            infark = int((df["stroke_type"] == "INFARK").sum())
            col2.metric("Stroke Infark", infark)
        if "demo_age" in df.columns:
            ages = pd.to_numeric(df["demo_age"], errors="coerce")
            col3.metric("Rata-rata Usia", f"{ages.mean():.0f}" if ages.notna().any() else "-")
        if "lama_rawat_hari" in df.columns:
            los = pd.to_numeric(df["lama_rawat_hari"], errors="coerce")
            col4.metric("Rata-rata LOS (hari)", f"{los.mean():.1f}" if los.notna().any() else "-")

        # ── STATISTIK TAMBAHAN ──
        with st.expander("📈 Statistik Lanjutan", expanded=False):
            stats_cols = st.columns(3)
            with stats_cols[0]:
                if "demo_gender" in df.columns:
                    st.markdown("**Jenis Kelamin**")
                    st.dataframe(df["demo_gender"].value_counts(), use_container_width=True)
            with stats_cols[1]:
                if "ct_documented" in df.columns:
                    st.markdown("**CT Scan**")
                    ct_ada = int((df["ct_documented"] == "ada").sum())
                    st.metric("Pasien dengan CT", f"{ct_ada}/{len(df)} ({ct_ada/len(df)*100:.0f}%)")
                if "fisioterapi_ada" not in df.columns and "act_fisioterapi" in df.columns:
                    fte = int((df["act_fisioterapi"] == "ada").sum())
                    st.metric("Fisioterapi", f"{fte}/{len(df)} ({fte/len(df)*100:.0f}%)")
            with stats_cols[2]:
                if "med_antiplatelet" in df.columns:
                    ap = int((df["med_antiplatelet"] == "ada").sum())
                    st.metric("Antiplatelet", f"{ap}/{len(df)} ({ap/len(df)*100:.0f}%)")
                if "lama_rawat_hari" in df.columns:
                    los_vals = pd.to_numeric(df["lama_rawat_hari"], errors="coerce")
                    st.markdown(f"**LOS:** min={los_vals.min():.0f}, max={los_vals.max():.0f}, rata={los_vals.mean():.1f}")

        # ── VALIDASI WARNING ──
        invalid_cols = [c for c in df.columns if (df[c] == "invalid").any()]
        if invalid_cols:
            st.warning(f"⚠️ **{len(invalid_cols)} kolom** memiliki data invalid (di luar range wajar):")
            for ic in invalid_cols:
                bad = int((df[ic] == "invalid").sum())
                st.caption(f"  • `{ic}` — {bad} pasien dengan nilai tidak wajar")
            st.caption("Nilai 'invalid' bisa diedit langsung di tabel di bawah.")

        # ── DATA EDITOR — EDIT LANGSUNG ──
        st.subheader("✏️ Edit Data (klik langsung di tabel)")
        st.caption("Klik cell untuk mengubah nilai. Perubahan otomatis tersimpan selama sesi ini.")

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            num_rows="fixed",
            key="extract_data_editor",
            column_config={
                "patient_id": st.column_config.TextColumn("Pasien", width="small"),
                "demo_age": st.column_config.NumberColumn("Usia", width="small"),
                "demo_gender": st.column_config.TextColumn("JK", width="small"),
                "stroke_type": st.column_config.SelectboxColumn("Stroke", width="small",
                    options=["INFARK", "HEMORAGIK", "MIXED", "UNCLEAR", "unknown"]),
                "gcs": st.column_config.TextColumn("GCS", width="small"),
                "td_sistol": st.column_config.TextColumn("TD Sistol", width="small"),
                "td_diastol": st.column_config.TextColumn("TD Diastol", width="small"),
                "lama_rawat_hari": st.column_config.TextColumn("LOS (hari)", width="small"),
            },
            hide_index=True,
        )

        # ── DOWNLOAD ──
        st.subheader("⬇️ Download Data")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        col1, col2, col3 = st.columns(3)
        with col1:
            csv_data = edited_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📄 Download CSV",
                csv_data,
                f"stroke_infark_{ts}.csv",
                "text/csv",
                use_container_width=True,
            )
        with col2:
            try:
                output_path = Path(extract_output)
                output_path.mkdir(parents=True, exist_ok=True)
                excel_path = output_path / f"stroke_infark_{ts}.xlsx"
                edited_df.to_excel(excel_path, index=False)
                with open(excel_path, "rb") as f:
                    st.download_button(
                        "📊 Download Excel",
                        f,
                        f"stroke_infark_{ts}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
            except Exception as e:
                st.error(f"Gagal generate Excel: {e}")
        with col3:
            all_cols = list(edited_df.columns)
            selected_cols = st.multiselect("Pilih kolom (export)", all_cols, default=all_cols)
            if selected_cols:
                filtered_df = edited_df[selected_cols]
                filt_csv = filtered_df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "🎯 Export Kolom Terpilih",
                    filt_csv,
                    f"stroke_infark_{ts}_selected.csv",
                    "text/csv",
                    use_container_width=True,
                )

        # ── #12: LOG BATCH EXTRACTION ──
    # (diluar blok if extract_results — harus tetap bisa diakses)
    # Init log
    if "extraction_log" not in st.session_state:
        st.session_state.extraction_log = []

    # Catat log setiap kali extraction selesai
    if st.session_state.extract_results:
        # Cek apakah sudah tercatat (hindari duplikasi)
        ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
        n_pasien = len(st.session_state.extract_results)
        n_field = len(st.session_state.extract_results[0]) - 1 if st.session_state.extract_results and "patient_id" in st.session_state.extract_results[0] else 0

        log_entry = {
            "timestamp": ts_now,
            "pasien": n_pasien,
            "field": n_field,
            "kategori": ", ".join(selected_cats) if selected_cats else "semua",
        }
        # Cek apakah log ini sudah ada
        existing = [e for e in st.session_state.extraction_log if e["timestamp"] == ts_now]
        if not existing:
            st.session_state.extraction_log.append(log_entry)
            # Simpan ke file
            log_path = Path(extract_output) / "extraction_log.csv"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            import csv as csv_module
            with log_path.open("w", encoding="utf-8-sig", newline="") as lf:
                w = csv_module.DictWriter(lf, fieldnames=["timestamp", "pasien", "field", "kategori"])
                w.writeheader()
                w.writerows(st.session_state.extraction_log)

    # ── #12: TAMPILKAN LOG ──
    with st.expander("📜 Riwayat Extraction (Log Batch)", expanded=False):
        if st.session_state.extraction_log:
            log_df = pd.DataFrame(st.session_state.extraction_log)
            st.dataframe(log_df, use_container_width=True)
        else:
            st.info("Belum ada riwayat extraction.")
        if st.button("🗑️ Hapus Riwayat", key="clear_log"):
            st.session_state.extraction_log = []
            st.rerun()

    # ── #13: MERGE BATCH ──
    with st.expander("🔀 Merge Batch (Gabung Hasil Extraction)", expanded=False):
        st.markdown("Upload file CSV hasil extraction sebelumnya untuk digabung dengan hasil saat ini.")

        merge_files = st.file_uploader(
            "Upload CSV (bisa multiple)", 
            type=["csv"], 
            accept_multiple_files=True,
            key="merge_uploader"
        )

        if merge_files and st.button("🔀 Gabungkan", key="do_merge"):
            frames = []
            if st.session_state.extract_results:
                frames.append(pd.DataFrame(st.session_state.extract_results))
            for mf in merge_files:
                try:
                    df_m = pd.read_csv(mf, encoding="utf-8-sig")
                    if "patient_id" in df_m.columns:
                        frames.append(df_m)
                    else:
                        st.warning(f"{mf.name}: tidak punya kolom 'patient_id', dilewati")
                except Exception as e:
                    st.error(f"{mf.name}: gagal baca — {e}")

            if frames:
                merged = pd.concat(frames, ignore_index=True)
                merged = merged.drop_duplicates(subset=["patient_id"], keep="last")
                # Konversi balik ke list of dict
                merged_dicts = merged.to_dict(orient="records")
                st.session_state.extract_results = merged_dicts
                st.success(f"✅ {len(frames)} batch digabung → {len(merged_dicts)} pasien unik")
                st.rerun()

    # ── #14: UPLOAD PDF VIA UI ──
    with st.expander("📁 Upload PDF untuk Anonimisasi Cepat", expanded=False):
        st.markdown("Upload satu file PDF → anonimisasi langsung → lihat hasilnya.")
        uploaded_pdf = st.file_uploader("Pilih file PDF", type=["pdf"], key="pdf_uploader")
        if uploaded_pdf is not None:
            with st.spinner("Memproses PDF..."):
                try:
                    # Simpan ke temp
                    import tempfile as tf
                    with tf.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_pdf.getvalue())
                        tmp_path = tmp.name
                    # Baca + anonimisasi
                    from pipeline_core import read_source, anonymize_text, load_staff_variants, compile_role_patterns
                    root = Path(tmp_path).parent
                    src = read_source(Path(tmp_path), root, use_ocr=False)
                    variants = load_staff_variants(st.session_state.staff_csv_path)
                    role_patterns = compile_role_patterns(variants)
                    anon, counts, leftovers, examples = anonymize_text(src.text, role_patterns)
                    # Bersihin temp
                    try: Path(tmp_path).unlink()
                    except: pass
                    # Tampilkan
                    st.success("✅ Anonimisasi selesai!")
                    st.metric("Karakter input", len(src.text))
                    st.metric("Karakter output", len(anon))
                    leftover_count = sum(leftovers.values())
                    if leftover_count > 0:
                        st.warning(f"⚠️ {leftover_count} sisa kebocoran terdeteksi. Periksa manual.")
                    else:
                        st.info("✅ Tidak ada sisa kebocoran.")

                    with st.expander("📄 Teks Hasil Anonim", expanded=False):
                        st.text_area("Hasil", anon, height=400)
                    csv_pdf = pd.DataFrame([counts]).to_csv(index=False).encode("utf-8-sig")
                    st.download_button("⬇️ Download Report", csv_pdf, f"anon_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "text/csv")
                except Exception as e:
                    st.error(f"Error: {e}")


# ================================================================
# TAB 6: PENGATURAN
# ================================================================

elif active_tab == "⚙️ Pengaturan":
    st.title("⚙️ Pengaturan")
    st.caption("Konfigurasi pipeline anonimisasi.")

    st.subheader("📁 Path Default")
    st.text(f"Input:         {DEFAULT_INPUT}")
    st.text(f"Output Anonim: {DEFAULT_OUTPUT}")
    st.text(f"Laporan:       {DEFAULT_REPORT}")
    st.text(f"Staf CSV:      {DEFAULT_STAFF_CSV}")
    st.text(f"Anonim Dir:    {DEFAULT_ANON_DIR}")
    st.text(f"Ekstrak Output: {DEFAULT_EXTRACT_OUTPUT}")

    st.markdown("---")

    st.subheader("🔬 Self-Test Anonimisasi")
    if st.button("🧪 Jalankan Self-Test", type="secondary"):
        with st.spinner("Menjalankan self-test..."):
            from pipeline_core import self_test
            ok = self_test()
            if ok:
                st.success("✅ Self-Test LULUS — anonimisasi bekerja dengan benar.")
            else:
                st.error("❌ Self-Test GAGAL — ada kebocoran data. Periksa log di terminal.")

    st.markdown("---")

    st.subheader("📌 Informasi Sistem")
    st.text(f"Python: {__import__('sys').version}")
    try:
        st.text(f"Streamlit: {__import__('streamlit').__version__}")
    except Exception:
        pass
    try:
        st.text(f"PyMuPDF: {__import__('fitz').version}")
    except Exception:
        pass
    try:
        st.text(f"pypdf: {__import__('pypdf').__version__}")
    except Exception:
        st.text("pypdf: tidak terdeteksi")


# ================================================================
# FOOTER
# ================================================================

st.sidebar.markdown("---")
st.sidebar.caption(f"Terakhir: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
