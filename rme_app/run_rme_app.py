"""
run_rme_app.py — Dashboard RME Multi-Penyakit
==============================================
App Streamlit disease-agnostic untuk anonimisasi & ekstraksi rekam medis.

Cara jalankan:
  cd rme_app
  streamlit run run_rme_app.py --server.port 8503
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ── Import extraction engine (disease-agnostic) ──
from extraction_engine import (
    list_profiles,
    load_profile,
    load_drug_profile,
    extract_one_patient,
    extract_all_patients,
    PROFILES_DIR,
    DRUG_PROFILES_DIR,
    _CORE_AVAILABLE,
)

# ── Import CP Variance analysis ──
from analytics.cp_variance import (
    list_cp_profiles,
    load_cp_profile,
    find_cp_for_disease,
    compare_patient,
    analyze_all_patients,
    AggregateReport,
    VarianceType,
)

# ── Import pipeline_core (anonimisasi + utilitas) ──
_CORE_DIR = Path(__file__).resolve().parent.parent / "cp_stroke_app"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

try:
    from pipeline_core import (
        AnonResult,
        ProgressState,
        anonymize_folder,
        anonymize_text,
        compile_role_patterns,
        load_staff_csv_data,
        load_staff_variants,
        read_source,
        save_audit_report,
        save_staff_csv_data,
        collect_source_files,
    )
    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False

# ================================================================
# KONFIGURASI
# ================================================================

st.set_page_config(
    page_title="Dashboard RME Penelitian",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
DEFAULT_STAFF_CSV = str((_CORE_DIR / "staff_doctors.csv").resolve())


# ================================================================
# FOLDER DIALOG
# ================================================================

DIALOG_SCRIPT = str((_CORE_DIR / "folder_dialog.py").resolve())

def browse_folder_dialog() -> str:
    try:
        result = subprocess.run(
            [sys.executable, DIALOG_SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        path = result.stdout.strip()
        return path if path else ""
    except Exception:
        return ""


def folder_picker(label: str, default_path: str, key: str, help_text: str = "") -> str:
    state_key = f"folder_{key}"
    current = st.session_state.get(state_key, "")
    if current != str(default_path):
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
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📂 Browse", key=f"btn_{key}", use_container_width=True):
            picked = browse_folder_dialog()
            if picked:
                st.session_state[state_key] = picked
                st.rerun()
    return st.session_state[state_key]


# ================================================================
# SESSION STATE
# ================================================================

if "progress" not in st.session_state:
    st.session_state.progress = ProgressState() if _CORE_AVAILABLE else None
if "anon_results" not in st.session_state:
    st.session_state.anon_results = []
if "extract_results" not in st.session_state:
    st.session_state.extract_results = []
if "staff_data" not in st.session_state:
    st.session_state.staff_data = load_staff_csv_data(DEFAULT_STAFF_CSV) if _CORE_AVAILABLE else []
if "staff_csv_path" not in st.session_state:
    st.session_state.staff_csv_path = DEFAULT_STAFF_CSV
if "active_profile" not in st.session_state:
    st.session_state.active_profile = None


# ================================================================
# SIDEBAR
# ================================================================

st.sidebar.markdown("## 🏥 Dashboard RME Penelitian")
st.sidebar.markdown("Disease-agnostic medical record extraction")
st.sidebar.markdown("---")

# ── Disease Profile Selector ──
st.sidebar.markdown("### 🔬 Profil Penyakit")
profiles = list_profiles()
profile_names = [p["name"] for p in profiles]

if not profile_names:
    st.sidebar.error("❌ Tidak ada profil penyakit ditemukan!")
    st.sidebar.markdown(f"📁 `{PROFILES_DIR}`")
else:
    selected_profile_name = st.sidebar.selectbox(
        "Pilih Penyakit",
        options=profile_names,
        index=0,
        key="profile_selector",
    )
    # Load profile
    try:
        active_profile = load_profile(selected_profile_name)
        st.session_state.active_profile = active_profile
        st.sidebar.caption(active_profile.get("description", ""))
        n_cats = len(active_profile.get("categories", {}))
        st.sidebar.markdown(f"📊 **{n_cats}** kategori data")
        if active_profile.get("drug_profile"):
            st.sidebar.markdown(f"💊 Profil obat: `{active_profile['drug_profile']}`")
    except Exception as e:
        st.sidebar.error(f"Error: {e}")
        active_profile = None

st.sidebar.markdown("---")

# ── Navigation ──
tabs = [
    "🏠 Beranda",
    "📂 Anonimisasi & Ekstraksi",
    "📋 Clinical Pathway",
    "👥 Data Staf RS",
    "💊 Database Obat",
    "📊 Laporan",
    "⚙️ Pengaturan",
]
active_tab = st.sidebar.radio("Menu", tabs, index=0)

st.sidebar.markdown("---")

# Status
p = st.session_state.progress
if p:
    st.sidebar.markdown("### Status Pipeline")
    if p.status == "idle":
        st.sidebar.info("⏸️ Siap")
    elif p.status == "running":
        st.sidebar.warning(f"⏳ {p.current}/{p.total} ({p.percent:.0f}%)")
    elif p.status == "done":
        st.sidebar.success(f"✅ {p.total} file selesai")
    elif p.status == "error":
        st.sidebar.error("❌ Error")

staff_count = len(st.session_state.staff_data) if st.session_state.staff_data else 0
st.sidebar.markdown(f"**Staf terdaftar:** {staff_count} orang")
st.sidebar.markdown("---")
st.sidebar.caption(f"v3.0 — Disease-Agnostic | {datetime.now().strftime('%d/%m/%Y %H:%M')}")


# ================================================================
# TAB: BERANDA
# ================================================================

if active_tab == "🏠 Beranda":
    st.title("🏥 Dashboard RME Penelitian")
    st.caption("Sistem Anonimisasi & Ekstraksi Data Rekam Medis Elektronik — Disease-Agnostic")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🔬 Profil Penyakit", len(profiles))
    with col2:
        if active_profile:
            cats = active_profile.get("categories", {})
            total_fields = sum(len(c.get("fields", [])) for c in cats.values())
            st.metric("📊 Total Field", total_fields)
        else:
            st.metric("📊 Total Field", 0)
    with col3:
        st.metric("👥 Staf RS", staff_count)

    st.markdown("---")

    st.markdown("""
    ### 📋 Alur Kerja
    1. **Pilih Profil Penyakit** di sidebar (Stroke, Pneumonia, dll)
    2. **Anonimisasi** → Hapus data pasien (PII) dari PDF rekam medis
    3. **Ekstraksi** → Ambil data klinis terstruktur dari teks anonim
    4. **Analisis** → Gunakan data terstruktur untuk penelitian

    ### 🔬 Profil Tersedia
    """)

    for p_info in profiles:
        with st.expander(f"**{p_info['name']}** — {p_info['description'][:80]}"):
            st.markdown(f"- **File:** `{p_info['file']}`")
            st.markdown(f"- **Kategori:** {p_info['category_count']}")
            st.markdown(f"- **Profil obat:** {p_info.get('drug_profile', 'none')}")
            if p_info['description']:
                st.markdown(f"- **Deskripsi:** {p_info['description']}")


# ================================================================
# TAB: ANONIMISASI & EKSTRAKSI
# ================================================================

elif active_tab == "📂 Anonimisasi & Ekstraksi":
    st.title("📂 Anonimisasi & Ekstraksi")

    if not active_profile:
        st.error("❌ Pilih profil penyakit di sidebar terlebih dahulu.")
        st.stop()

    profile_name = active_profile.get("name", "Unknown")
    categories = active_profile.get("categories", {})

    st.info(f"🔬 **Profil aktif:** {profile_name} — {len(categories)} kategori")

    anon_tab, extract_tab = st.tabs(["🔒 Anonimisasi", "📊 Ekstraksi"])

    # ── SUB-TAB: ANONIMISASI ──
    with anon_tab:
        st.subheader("🔒 Anonimisasi Data Pasien")
        st.caption("Hapus semua data identitas pasien (PII) dari PDF rekam medis. 100% offline.")

        if not _CORE_AVAILABLE:
            st.error("❌ Modul anonimisasi (pipeline_core) tidak tersedia. Cek instalasi.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                input_dir = folder_picker(
                    "📂 Folder PDF/TXT mentah", "", "anon_input",
                    help_text="Folder yang berisi file PDF/TXT rekam medis mentah"
                )
            with col2:
                output_dir = folder_picker(
                    "📂 Folder output anonim", "", "anon_output",
                    help_text="Folder untuk menyimpan teks anonim"
                )

            staf_col, ocr_col = st.columns(2)
            with staf_col:
                staff_csv = folder_picker(
                    "👥 Staff CSV", DEFAULT_STAFF_CSV, "staff_csv_path2",
                    help_text="CSV daftar nama staf RS untuk anonimisasi"
                )
            with ocr_col:
                use_ocr = st.checkbox("🔍 Gunakan OCR (untuk PDF scan)", value=False)

            if st.button("🚀 Mulai Anonimisasi", type="primary", use_container_width=True, key="run_anon"):
                if not input_dir or not Path(input_dir).exists():
                    st.error("❌ Folder input tidak valid.")
                else:
                    progress = ProgressState()
                    st.session_state.progress = progress

                    with st.status("🔒 Anonimisasi berjalan...", expanded=True) as status:
                        progress_bar = st.progress(0, text="⏳ Memulai...")
                        try:
                            results = anonymize_folder(
                                input_dir=input_dir,
                                output_dir=output_dir,
                                staff_csv=staff_csv if Path(staff_csv).exists() else None,
                                use_ocr=use_ocr,
                                progress=progress,
                            )
                            st.session_state.anon_results = results
                            progress.status = "done"
                            status.update(
                                label=f"✅ Anonimisasi selesai — {len(results)} file",
                                state="complete", expanded=True,
                            )
                        except Exception as e:
                            progress.status = "error"
                            progress.errors.append(str(e))
                            status.update(label="❌ Anonimisasi gagal", state="error")
                            results = []

                        progress_bar.progress(
                            1.0,
                            text=f"✅ {progress.current}/{progress.total} file selesai",
                        )

                    # Results persist across reruns via session_state
                    p = st.session_state.progress
                    if p.status == "done" and st.session_state.anon_results:
                        st.success(f"✅ Anonimisasi selesai! {p.total} file diproses.")
                        df = pd.DataFrame([r.__dict__ for r in st.session_state.anon_results])
                        st.dataframe(df, use_container_width=True)
                    elif p.status == "error":
                        st.error(f"❌ Error: {p.errors}")

    # ── SUB-TAB: EKSTRAKSI ──
    with extract_tab:
        st.subheader(f"📊 Ekstraksi Data — {profile_name}")
        st.caption(f"Ekstrak data terstruktur dari teks anonim menggunakan profil **{profile_name}**")

        # Folder anonim
        col1, col2 = st.columns(2)
        with col1:
            anon_dir = folder_picker(
                "📁 Folder Teks Anonim", "", "ext_anon_dir",
                help_text="Folder yang BERISI subfolder pasien dengan file .anon.txt"
            )
        with col2:
            extract_output = folder_picker(
                "📁 Output Ekstraksi", "", "ext_output_dir",
                help_text="Folder untuk menyimpan hasil CSV/Excel"
            )

        anon_path = Path(anon_dir)
        if anon_path.exists():
            patient_dirs = sorted([d.name for d in anon_path.iterdir() if d.is_dir()])
            flat_files = sorted([f for f in anon_path.glob("*.anon.txt") if f.is_file()])
            if patient_dirs:
                st.success(f"✅ **{len(patient_dirs)}** folder pasien ditemukan (struktur NESTED)")
            elif flat_files:
                st.success(f"✅ **{len(flat_files)}** file .anon.txt ditemukan (struktur FLAT)")
            else:
                st.warning("⚠️ Tidak ada file .anon.txt ditemukan di folder ini.")
                patient_dirs = []
        else:
            patient_dirs = []

        # ── Pilih Kategori ──
        st.markdown("---")
        st.subheader("📌 Pilih Kategori Data")

        # Quick select buttons
        qcol1, qcol2, qcol3, _ = st.columns([1, 1, 1, 3])
        with qcol1:
            if st.button("✅ Semua Kategori", key="qs_all"):
                for c in categories:
                    st.session_state[f"ecat_{c}"] = True
                st.rerun()
        with qcol2:
            if st.button("❌ Hapus Semua", key="qs_none"):
                for c in categories:
                    st.session_state[f"ecat_{c}"] = False
                st.rerun()
        with qcol3:
            if st.button("💊 Medikasi Saja", key="qs_med"):
                for c in categories:
                    st.session_state[f"ecat_{c}"] = (c == "Medikasi")
                st.rerun()

        # Category checkboxes
        col_left, col_right = st.columns(2)
        selected_categories = []
        selected_fields: dict[str, list[str]] = {}

        for i, (cat_name, cat_def) in enumerate(categories.items()):
            fields = cat_def.get("fields", [])
            cat_type = cat_def.get("type", "?")
            desc = cat_def.get("desc", "")
            col = col_left if i % 2 == 0 else col_right

            with col:
                default_val = st.session_state.get(f"ecat_{cat_name}", True)
                checked = st.checkbox(
                    f"**{cat_name}** ({len(fields)} field) `{cat_type}`",
                    value=default_val,
                    key=f"ecat_{cat_name}",
                    help=f"{desc}\n\nFields: {', '.join(fields)}",
                )
                if checked:
                    selected_categories.append(cat_name)

                    # Sub-field selection (non-Medikasi)
                    if cat_name != "Medikasi":
                        fcol1, fcol2 = st.columns(2)
                        cat_fields = []
                        for j, f in enumerate(fields):
                            fc = fcol1 if j % 2 == 0 else fcol2
                            with fc:
                                friendly = f.replace("demo_", "").replace("lab_", "") \
                                           .replace("med_", "").replace("rf_", "").replace("act_", "") \
                                           .replace("ct_", "").replace("thorax_", "").replace("setting_", "") \
                                           .replace("fisik_", "").replace("_", " ").title()
                                if friendly.upper() in ("GCS", "LOS", "HR", "RR", "HB", "IMT", "BB", "TB", "PPI", "NIHSS"):
                                    friendly = friendly.upper()

                                sf_key = f"sf_{cat_name}_{f}"
                                if sf_key not in st.session_state:
                                    st.session_state[sf_key] = True
                                if st.checkbox(friendly, value=st.session_state.get(sf_key, True), key=sf_key):
                                    cat_fields.append(f)
                        if cat_fields:
                            selected_fields[cat_name] = cat_fields
                        else:
                            selected_fields[cat_name] = fields

        # Drug sub-category selection
        selected_drug_keys = None
        if "Medikasi" in selected_categories:
            st.markdown("---")
            st.subheader("💊 Pilih Kategori Obat")
            drug_profile_name = active_profile.get("drug_profile")
            drug_data = load_drug_profile(drug_profile_name)
            if drug_data:
                drug_cols = st.columns(3)
                selected_drug_keys = []
                for idx, (drug_key, terms) in enumerate(drug_data.items()):
                    if not drug_key.startswith("med_"):
                        continue
                    with drug_cols[idx % 3]:
                        friendly = drug_key.replace("med_", "").replace("_", " ").title()
                        dk_key = f"dk_{drug_key}"
                        if dk_key not in st.session_state:
                            st.session_state[dk_key] = True
                        if st.checkbox(
                            f"{friendly} ({len(terms)} obat)",
                            value=st.session_state.get(dk_key, True),
                            key=dk_key,
                            help=f"Keywords: {', '.join(terms[:5])}...",
                        ):
                            selected_drug_keys.append(drug_key)

        # ── Run Extraction ──
        st.markdown("---")

        run_extract = st.button("🚀 Mulai Ekstraksi", type="primary", use_container_width=True)

        if run_extract:
            if not anon_path.exists() or (not patient_dirs and not flat_files):
                st.error("❌ Folder anonim tidak valid atau kosong.")
            elif not selected_categories:
                st.error("❌ Pilih minimal 1 kategori.")
            else:
                with st.spinner("⏳ Mengekstrak data..."):
                    results = extract_all_patients(
                        anon_dir=anon_path,
                        profile=active_profile,
                        selected_categories=selected_categories,
                        selected_fields=selected_fields if selected_fields else None,
                        selected_drug_keys=selected_drug_keys,
                    )
                st.session_state.extract_results = results

                if results:
                    st.success(f"✅ Ekstraksi selesai! **{len(results)}** pasien.")

                    # Build DataFrame
                    df = pd.DataFrame(results)
                    st.subheader(f"📊 Hasil Ekstraksi ({len(df)} pasien × {len(df.columns)} kolom)")
                    st.dataframe(df, use_container_width=True)

                    # Download buttons
                    st.markdown("---")
                    st.subheader("💾 Unduh Hasil")

                    dl_col1, dl_col2 = st.columns(2)
                    with dl_col1:
                        csv_data = df.to_csv(index=False).encode("utf-8")
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        safe_name = profile_name.lower().replace(" ", "_")
                        st.download_button(
                            "📥 Download CSV",
                            data=csv_data,
                            file_name=f"ekstraksi_{safe_name}_{ts}.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
                    with dl_col2:
                        # Excel export
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                                df.to_excel(writer, index=False, sheet_name="Ekstraksi")
                            st.download_button(
                                "📥 Download Excel",
                                data=buffer.getvalue(),
                                file_name=f"ekstraksi_{safe_name}_{ts}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                            )
                        except ImportError:
                            st.warning("openpyxl tidak tersedia — download CSV saja.")

                    # Stats
                    st.markdown("---")
                    st.subheader("📈 Statistik Singkat")
                    stat_cols = st.columns(4)
                    with stat_cols[0]:
                        st.metric("Pasien", len(results))
                    with stat_cols[1]:
                        st.metric("Kategori", len(selected_categories))
                    with stat_cols[2]:
                        st.metric("Kolom", len(df.columns))
                    with stat_cols[3]:
                        unknown_pct = (df == "unknown").sum().sum() / (df.shape[0] * df.shape[1]) * 100 if df.shape[1] > 0 else 0
                        st.metric("Unknown %", f"{unknown_pct:.0f}%")

                    # Detail per category
                    st.markdown("---")
                    st.subheader("📋 Detail per Kategori")
                    for cat_name in selected_categories:
                        cat_def = categories.get(cat_name, {})
                        cat_fields = cat_def.get("fields", [])
                        existing_fields = [f for f in cat_fields if f in df.columns]
                        if existing_fields:
                            with st.expander(f"**{cat_name}** — {len(existing_fields)} field"):
                                cat_df = df[["patient_id"] + existing_fields]
                                st.dataframe(cat_df, use_container_width=True)

                                # Summary for this category
                                for f in existing_fields:
                                    vc = df[f].value_counts()
                                    if len(vc) <= 5:
                                        st.caption(f"  **{f}**: {dict(vc)}")
                else:
                    st.warning("⚠️ Tidak ada data yang berhasil diekstrak.")


# ================================================================
# TAB: CLINICAL PATHWAY VARIANCE
# ================================================================

elif active_tab == "📋 Clinical Pathway":
    st.title("📋 Clinical Pathway — Deteksi Varians")
    st.caption("Bandingkan hasil ekstraksi aktual vs standar CP. Identifikasi varians + penyebab.")

    # ── CP Profile selector ──
    cp_profiles = list_cp_profiles()
    cp_names = [p["name"] for p in cp_profiles]

    if not cp_names:
        st.warning("⚠️ Tidak ada CP profiles ditemukan di `cp_profiles/`.")
        st.stop()

    col_cp, col_info = st.columns([1, 2])
    with col_cp:
        selected_cp_name = st.selectbox("📋 Standar CP", options=cp_names, key="cp_selector")
    with col_info:
        cp_meta = next((p for p in cp_profiles if p["name"] == selected_cp_name), None)
        if cp_meta:
            los = cp_meta.get("los_target", {})
            st.info(f"**{cp_meta['name']}** — {cp_meta['standard_count']} standar | LOS target: {los.get('min', '?')}-{los.get('max', '?')} hari")

    try:
        cp_profile = load_cp_profile(selected_cp_name)
    except Exception as e:
        st.error(f"❌ Error load CP profile: {e}")
        st.stop()

    # ── Data source: use extraction results from session_state ──
    results = st.session_state.get("extract_results", [])

    if not results:
        st.warning("⚠️ Belum ada data ekstraksi. Jalankan ekstraksi di tab **📂 Anonimisasi & Ekstraksi** terlebih dahulu.")
        st.markdown("---")
        st.markdown("### 📋 Standar CP yang Berlaku")
        for section, items in cp_profile.get("standards", {}).items():
            with st.expander(f"**{section}** ({len(items)} standar)"):
                for item in items:
                    sev_icon = "🔴" if item.get("severity") == "wajib" else "🟡"
                    st.markdown(f"- {sev_icon} **{item['label']}** — field: `{item['field']}`, expected: `{item['expected']}`")
        st.stop()

    # ── Run variance analysis ──
    st.success(f"📊 **{len(results)}** pasien tersedia dari hasil ekstraksi.")

    if st.button("🔍 Jalankan Analisis Varians", type="primary", use_container_width=True, key="run_cp_variance"):
        agg_report = analyze_all_patients(results, cp_profile)
        st.session_state["cp_agg_report"] = agg_report

    agg_report = st.session_state.get("cp_agg_report")
    if agg_report is None:
        st.info("Klik tombol di atas untuk menjalankan analisis varians.")
        st.stop()

    # ── Aggregate Dashboard ──
    st.markdown("---")
    st.subheader("📊 Dashboard Agregat")

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("👥 Pasien", agg_report.patient_count)
    with m2:
        st.metric("✅ Compliance Rata-rata", f"{agg_report.avg_compliance_rate:.1f}%")
    with m3:
        st.metric("⚠️ Total Deviasi", agg_report.total_deviations)
    with m4:
        st.metric("❌ Total Missing", agg_report.total_missing)
    with m5:
        los_sum = agg_report.los_summary()
        if los_sum["mean"] is not None:
            st.metric("📅 LOS Rata-rata", f"{los_sum['mean']} hari")
        else:
            st.metric("📅 LOS Rata-rata", "—")

    # ── LOS Summary ──
    if los_sum["count"] > 0:
        st.markdown("#### 📈 Distribusi LOS")
        los_c1, los_c2, los_c3, los_c4 = st.columns(4)
        with los_c1:
            st.metric("Dalam Target", los_sum["within_target"])
        with los_c2:
            st.metric("Di Atas Target", los_sum["above_target"])
        with los_c3:
            st.metric("Di Bawah Target", los_sum["below_target"])
        with los_c4:
            st.metric("Median LOS", f"{los_sum['median']} hari")

    # ── Per-Field Compliance Table ──
    st.markdown("---")
    st.subheader("📋 Compliance Per Field (Semua Pasien)")

    field_summary = agg_report.field_compliance_summary()
    if field_summary:
        rows = []
        for f, fs in sorted(field_summary.items(), key=lambda x: x[1]["compliance_pct"]):
            rows.append({
                "Field": fs["label"],
                "Severity": "🔴 wajib" if fs["severity"] == "wajib" else "🟡 rekomendasi",
                "Section": fs["section"],
                "Compliant": fs["compliant"],
                "Deviation": fs["deviation"],
                "Missing": fs["missing"],
                "Compliance %": fs["compliance_pct"],
            })
        df_fields = pd.DataFrame(rows)
        st.dataframe(df_fields, use_container_width=True, hide_index=True)

        # Highlight low compliance
        low_comp = df_fields[df_fields["Compliance %"] < 80]
        if not low_comp.empty:
            st.warning(f"⚠️ **{len(low_comp)}** field dengan compliance < 80%:")
            for _, row in low_comp.iterrows():
                st.caption(f"  • {row['Field']} ({row['Severity']}): {row['Compliance %']}%")

    # ── Per-Patient Detail ──
    st.markdown("---")
    st.subheader("👤 Detail Per Pasien")

    for pr in agg_report.patient_reports:
        wajib_missing = pr.wajib_missing
        status_icon = "✅" if not wajib_missing else "⚠️"

        with st.expander(f"{status_icon} **{pr.patient_id}** — Compliance: {pr.compliance_rate:.1f}% | Deviasi: {pr.deviation_count} | Missing: {pr.missing_count}"):
            # Summary metrics
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                st.metric("Compliant", pr.compliant_count)
            with pc2:
                st.metric("Deviation", pr.deviation_count)
            with pc3:
                st.metric("Missing", pr.missing_count)
            with pc4:
                if pr.los_actual is not None:
                    st.metric("LOS", f"{pr.los_actual:.0f} hari", delta=pr.los_variance)

            # Variance table
            if pr.variances:
                var_rows = [v.to_dict() for v in pr.variances]
                df_var = pd.DataFrame(var_rows)
                # Color-code by variance_type
                st.dataframe(
                    df_var[["label", "severity", "section", "expected", "actual", "variance_type", "note"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "label": "Standar",
                        "severity": "Severity",
                        "section": "Section",
                        "expected": "Expected",
                        "actual": "Actual",
                        "variance_type": st.column_config.TextColumn("Status", help="compliant/deviation/missing/not_assessable"),
                        "note": "Keterangan",
                    },
                )

            # Wajib missing alerts
            if wajib_missing:
                st.error(f"🔴 **{len(wajib_missing)}** standar WAJIB belum terpenuhi:")
                for w in wajib_missing:
                    st.caption(f"  • {w.label}: {w.note}")

    # ── Download Report ──
    st.markdown("---")
    st.subheader("💾 Unduh Laporan Varians")

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        # Per-patient summary CSV
        summary_rows = [pr.to_summary_dict() for pr in agg_report.patient_reports]
        df_summary = pd.DataFrame(summary_rows)
        csv_summary = df_summary.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Ringkasan Per Pasien (CSV)",
            data=csv_summary,
            file_name=f"cp_variance_summary_{selected_cp_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl_col2:
        # All variances detail CSV
        all_var_rows = []
        for pr in agg_report.patient_reports:
            for v in pr.variances:
                row = v.to_dict()
                row["patient_id"] = pr.patient_id
                all_var_rows.append(row)
        if all_var_rows:
            df_detail = pd.DataFrame(all_var_rows)
            csv_detail = df_detail.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Detail Semua Varians (CSV)",
                data=csv_detail,
                file_name=f"cp_variance_detail_{selected_cp_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )


# ================================================================
# TAB: DATA STAF RS
# ================================================================

elif active_tab == "👥 Data Staf RS":
    st.title("👥 Data Staf RS")
    st.caption("Daftar nama staf rumah sakit untuk anonimisasi (deteksi nama dokter/perawat).")

    if not _CORE_AVAILABLE:
        st.error("❌ Modul pipeline_core tidak tersedia.")
    else:
        staf_path = Path(st.session_state.staff_csv_path)
        if staf_path.exists():
            df = pd.read_csv(staf_path)
            st.info(f"📂 File: `{staf_path}` — **{len(df)}** staf")
            st.dataframe(df, use_container_width=True)
        else:
            st.warning(f"⚠️ File staf tidak ditemukan: `{staf_path}`")

        # Upload new
        uploaded = st.file_uploader("Upload CSV baru (kolom: name, role)", type=["csv"])
        if uploaded:
            try:
                df_new = pd.read_csv(uploaded)
                if "name" not in df_new.columns:
                    st.error("❌ CSV harus punya kolom 'name'")
                else:
                    st.success(f"✅ {len(df_new)} staf ditemukan")
                    st.dataframe(df_new, use_container_width=True)
                    if st.button("💾 Simpan sebagai staff CSV"):
                        save_path = APP_DIR / "staff_doctors.csv"
                        df_new.to_csv(save_path, index=False, encoding="utf-8-sig")
                        st.session_state.staff_csv_path = str(save_path)
                        st.session_state.staff_data = load_staff_csv_data(str(save_path))
                        st.success("✅ Staff CSV tersimpan!")
            except Exception as e:
                st.error(f"❌ Error: {e}")


# ================================================================
# TAB: DATABASE OBAT
# ================================================================

elif active_tab == "💊 Database Obat":
    st.title("💊 Database Obat")
    st.caption("Kelola daftar obat per profil penyakit.")

    if not active_profile:
        st.error("❌ Pilih profil penyakit di sidebar.")
    else:
        drug_profile_name = active_profile.get("drug_profile")
        drug_data = load_drug_profile(drug_profile_name)

        if not drug_data:
            st.warning("⚠️ Tidak ada profil obat untuk penyakit ini.")
        else:
            st.info(f"📂 File: `{drug_profile_name}` — **{len([k for k in drug_data if k.startswith('med_')])}** kategori obat")

            for drug_key, terms in drug_data.items():
                if not drug_key.startswith("med_"):
                    continue
                friendly = drug_key.replace("med_", "").replace("_", " ").title()
                with st.expander(f"**{friendly}** — {len(terms)} keyword"):
                    st.markdown(f"`{'`, `'.join(terms)}`")


# ================================================================
# TAB: LAPORAN
# ================================================================

elif active_tab == "📊 Laporan":
    st.title("📊 Laporan Ekstraksi")

    if not st.session_state.extract_results:
        st.info("ℹ️ Belum ada hasil ekstraksi. Jalankan ekstraksi di tab 'Anonimisasi & Ekstraksi' terlebih dahulu.")
    else:
        results = st.session_state.extract_results
        df = pd.DataFrame(results)

        st.success(f"✅ **{len(results)}** pasien, **{len(df.columns)}** kolom")
        st.dataframe(df, use_container_width=True)

        # Download
        csv_data = df.to_csv(index=False).encode("utf-8")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "📥 Download CSV",
            data=csv_data,
            file_name=f"laporan_ekstraksi_{ts}.csv",
            mime="text/csv",
        )


# ================================================================
# TAB: PENGATURAN
# ================================================================

elif active_tab == "⚙️ Pengaturan":
    st.title("⚙️ Pengaturan")

    st.subheader("📁 Path Konfigurasi")

    st.markdown(f"""
    | Item | Path |
    |------|------|
    | App Directory | `{APP_DIR}` |
    | Disease Profiles | `{PROFILES_DIR}` |
    | Drug Profiles | `{DRUG_PROFILES_DIR}` |
    | Pipeline Core | `{_CORE_DIR}` |
    | Staff CSV | `{st.session_state.staff_csv_path}` |
    """)

    st.markdown("---")

    st.subheader("🔬 Profil Penyakit")
    if st.button("🔄 Reload Profil", key="reload_profiles"):
        st.rerun()

    for p_info in profiles:
        with st.expander(f"**{p_info['name']}** — {p_info['file']}"):
            try:
                full = load_profile(p_info["name"])
                for cat_name, cat_def in full.get("categories", {}).items():
                    st.markdown(f"- **{cat_name}** ({cat_def.get('type', '?')}): {', '.join(cat_def.get('fields', []))}")
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("---")

    st.subheader("📝 Buat Profil Baru")
    st.caption("Copy template dari `disease_profiles/_template.json` dan edit sesuai kebutuhan.")

    template_path = PROFILES_DIR / "_template.json"
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
        st.download_button(
            "📥 Download Template JSON",
            data=template_content.encode("utf-8"),
            file_name="profil_baru.json",
            mime="application/json",
        )
