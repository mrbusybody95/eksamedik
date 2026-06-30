from pathlib import Path
import fitz  # PyMuPDF

BASE_DIR = Path(__file__).resolve().parents[1]

IN_DIR = BASE_DIR / "01_raw_pdf"
OUT_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR.mkdir(exist_ok=True)

pdf_files = list(IN_DIR.rglob("*.pdf"))

if not pdf_files:
    print(f"Tidak ada file PDF di folder {IN_DIR}.")
    print("Pastikan file PDF berada di dalam 01_raw_pdf atau subfoldernya, misalnya 01_raw_pdf/STROKE_001/")
    raise SystemExit

for pdf_path in pdf_files:
    relative_path = pdf_path.relative_to(IN_DIR)
    patient_folder = relative_path.parts[0] if len(relative_path.parts) > 1 else pdf_path.stem

    patient_out_dir = OUT_DIR / patient_folder
    patient_out_dir.mkdir(exist_ok=True)

    out_txt = patient_out_dir / f"{pdf_path.stem}.txt"

    print(f"Mengekstrak: {pdf_path}")

    doc = fitz.open(pdf_path)
    text_all = []

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        text_all.append(f"\n\n===== HALAMAN {page_num} =====\n\n{text}")

    out_txt.write_text("\n".join(text_all), encoding="utf-8")

    print(f"Berhasil disimpan ke: {out_txt}")

print("\nSelesai.")