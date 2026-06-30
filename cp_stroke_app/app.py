import streamlit as st
import pandas as pd
from pathlib import Path
from anonymizer import process_folder


st.set_page_config(
    page_title="MedAnon CP Assistant",
    page_icon="🛡️",
    layout="wide",
)


st.title("🛡️ MedAnon CP Assistant")
st.caption("Aplikasi lokal untuk anonimisasi teks rekam medis sebelum ekstraksi Clinical Pathway")


st.warning(
    "Gunakan aplikasi ini secara lokal. Jangan upload data rekam medis asli ke server/cloud tanpa izin etik dan kebijakan RS."
)


with st.sidebar:
    st.header("Pengaturan")

    mode = st.radio(
        "Mode anonimisasi",
        options=["standar", "ketat"],
        index=1,
        help="Mode ketat lebih agresif untuk menyamarkan baris identitas.",
    )

    st.divider()

    st.markdown("### Struktur folder yang disarankan")
    st.code(
        """
stroke_cp_app/
├── 02_text_extracted/
├── 03_anonymized_text/
└── 04_anonymization_report/
        """,
        language="text",
    )


st.subheader("1. Pilih Folder")

input_dir = st.text_input(
    "Folder input",
    value="02_text_extracted",
    help="Folder berisi subfolder pasien dan file .txt hasil ekstraksi.",
)

output_dir = st.text_input(
    "Folder output anonim",
    value="03_anonymized_text",
)

report_dir = st.text_input(
    "Folder laporan",
    value="04_anonymization_report",
)


col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Input", input_dir)

with col2:
    st.metric("Output", output_dir)

with col3:
    st.metric("Report", report_dir)


st.subheader("2. Jalankan Anonimisasi")

run_button = st.button("🚀 Jalankan Anonimisasi", type="primary")


if run_button:
    input_path = Path(input_dir)

    if not input_path.exists():
        st.error(f"Folder input tidak ditemukan: {input_dir}")
        st.stop()

    txt_files = list(input_path.rglob("*.txt"))

    if len(txt_files) == 0:
        st.error("Tidak ada file .txt ditemukan di folder input.")
        st.stop()

    st.info(f"Ditemukan {len(txt_files)} file .txt. Proses anonimisasi dimulai.")

    progress_bar = st.progress(0, text="Memproses file...")

    # Untuk MVP ini progress dibuat sederhana.
    # Proses utama dilakukan dalam satu fungsi.
    result = process_folder(
        input_dir=input_dir,
        output_dir=output_dir,
        report_dir=report_dir,
        mode=mode,
    )

    progress_bar.progress(100, text="Selesai")

    rows = result["rows"]
    df = pd.DataFrame(rows)

    total_files = result["total_files"]
    safe_files = int((df["status"] == "AMAN").sum())
    review_files = int((df["status"] == "PERLU_REVIEW").sum())
    error_files = int((df["status"] == "ERROR").sum())

    st.success("Anonimisasi selesai.")

    st.subheader("3. Ringkasan Hasil")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("Total file", total_files)

    with c2:
        st.metric("Aman", safe_files)

    with c3:
        st.metric("Perlu review", review_files)

    with c4:
        st.metric("Error", error_files)

    st.subheader("4. Laporan Detail")

    st.dataframe(df, use_container_width=True)

    st.subheader("5. Download Laporan")

    csv_data = df.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        label="⬇️ Download laporan CSV",
        data=csv_data,
        file_name="anonymization_report.csv",
        mime="text/csv",
    )

    st.info(f"File laporan juga disimpan di: {result['report_file']}")
    st.info(f"Hasil anonim disimpan di folder: {output_dir}")


else:
    st.info("Masukkan folder input dan klik tombol untuk mulai.")