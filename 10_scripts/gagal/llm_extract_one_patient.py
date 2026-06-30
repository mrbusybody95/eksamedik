"""
llm_extract_one_patient.py

Tujuan:
- Membaca semua file .txt dari 03_anonymized_text/STROKE_001/
- Mengirim teks anonim ke Gemini API
- Meminta output JSON terstruktur untuk variabel stroke
- Menyimpan hasil ke 04_llm_extracted/STROKE_001.json

Cara pakai:
1. Install:
   pip install -U google-genai

2. Set API key di PowerShell:
   $env:GEMINI_API_KEY="ISI_API_KEY_KAMU"

3. Jalankan dari folder utama project:
   python scripts/llm_extract_one_patient.py
"""

from pathlib import Path
import os
import json
import re
from google import genai


# =========================
# PENGATURAN UTAMA
# =========================

PATIENT_ID = "STROKE_001"

# Model murah/cepat untuk ekstraksi awal.
# Jika model ini error karena tidak tersedia di akunmu, ganti ke model yang tersedia di Google AI Studio.
MODEL_NAME = "gemini-2.5-flash"

BASE_DIR = Path(__file__).resolve().parents[1]

INPUT_DIR = BASE_DIR / "03_anonymized_text" / PATIENT_ID
OUTPUT_DIR = BASE_DIR / "04_llm_extracted"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_JSON = OUTPUT_DIR / f"{PATIENT_ID}.json"
OUTPUT_RAW = OUTPUT_DIR / f"{PATIENT_ID}_raw.txt"


# =========================
# FUNGSI BANTUAN
# =========================

def read_patient_text(patient_dir: Path) -> str:
    """
    Membaca semua .txt dalam folder pasien.
    Nama file ikut dimasukkan agar Gemini tahu sumber informasinya.
    """
    if not patient_dir.exists():
        raise FileNotFoundError(f"Folder tidak ditemukan: {patient_dir}")

    txt_files = sorted(patient_dir.glob("*.txt"))

    if not txt_files:
        raise FileNotFoundError(f"Tidak ada file .txt di folder: {patient_dir}")

    parts = []

    for file_path in txt_files:
        text = file_path.read_text(encoding="utf-8", errors="ignore").strip()

        if not text:
            continue

        parts.append(
            f"\n\n===== SUMBER FILE: {file_path.name} =====\n{text}"
        )

    if not parts:
        raise ValueError(f"Semua file .txt kosong di folder: {patient_dir}")

    return "\n".join(parts)


def extract_json_from_text(text: str) -> dict:
    """
    Mengambil JSON dari respons Gemini.
    Kadang respons terbungkus ```json ... ```, jadi dibersihkan dulu.
    """
    cleaned = text.strip()

    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Coba ambil bagian antara kurung kurawal terluar
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1 and end > start:
            possible_json = cleaned[start:end + 1]
            return json.loads(possible_json)

        raise


def build_prompt(patient_id: str, patient_text: str) -> str:
    return f"""
Anda adalah asisten ekstraksi data rekam medis stroke untuk penelitian.

Konteks:
- Teks berasal dari rekam medis elektronik yang SUDAH DIANONIMKAN.
- Tugas Anda hanya mengekstrak data yang tertulis di teks.
- Jangan membuat diagnosis baru.
- Jangan mengarang informasi yang tidak ada.
- Jika data tidak ditemukan, isi value dengan null.
- Jawab hanya dalam JSON valid, tanpa markdown, tanpa penjelasan tambahan.

Aturan evidence:
- Setiap variabel harus memiliki:
  1. value
  2. evidence
  3. confidence
- evidence adalah potongan kalimat asli dari teks.
- Jika value null, evidence juga null.
- confidence hanya boleh: "high", "medium", "low", atau null.

Definisi ringkas:
- jenis_stroke: iskemik, hemoragik, TIA, SAH, ICH, atau lainnya sesuai teks.
- onset: waktu awal gejala atau last known well bila tertulis.
- gcs_awal: GCS awal di IGD/awal masuk.
- tekanan_darah_awal: tekanan darah awal di IGD/awal masuk.
- gula_darah_awal: GDS/GDP/gula darah awal bila ada.
- ct_scan_result: hasil CT scan kepala/radiologi yang paling relevan.
- komorbid_ht: hipertensi atau riwayat darah tinggi.
- komorbid_dm: diabetes mellitus.
- komorbid_af: atrial fibrillation/fibrilasi atrium/AF.
- terapi_antiplatelet: aspirin, clopidogrel, cilostazol, atau antiplatelet lain.
- terapi_antikoagulan: warfarin, heparin, enoxaparin, rivaroxaban, apixaban, dabigatran, atau antikoagulan lain.
- trombolisis: alteplase/rtPA/trombolisis IV bila tertulis.
- mrs_masuk: modified Rankin Scale saat masuk bila tertulis.
- mrs_pulang: modified Rankin Scale saat pulang bila tertulis.
- discharge_status: pulang, rujuk, meninggal, APS, rawat lanjut, atau status akhir perawatan.

Format JSON wajib:
{{
  "patient_id": "{patient_id}",
  "jenis_stroke": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "onset": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "gcs_awal": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "tekanan_darah_awal": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "gula_darah_awal": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "ct_scan_result": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "komorbid_ht": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "komorbid_dm": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "komorbid_af": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "terapi_antiplatelet": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "terapi_antikoagulan": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "trombolisis": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "mrs_masuk": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "mrs_pulang": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }},
  "discharge_status": {{
    "value": null,
    "evidence": null,
    "confidence": null
  }}
}}

TEKS REKAM MEDIS:
{patient_text}
"""


def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY belum ditemukan.\n"
            "Di PowerShell jalankan:\n"
            '$env:GEMINI_API_KEY="ISI_API_KEY_KAMU"'
        )

    print(f"Membaca data pasien: {PATIENT_ID}")
    print(f"Folder input: {INPUT_DIR}")

    patient_text = read_patient_text(INPUT_DIR)

    print("Menghubungi Gemini API...")

    client = genai.Client(api_key=api_key)

    prompt = build_prompt(PATIENT_ID, patient_text)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    raw_text = response.text or ""
    OUTPUT_RAW.write_text(raw_text, encoding="utf-8")

    print("Respons mentah disimpan.")
    print(f"File raw: {OUTPUT_RAW}")

    try:
        result = extract_json_from_text(raw_text)
    except Exception as e:
        print("\nGAGAL parsing JSON.")
        print("Cek file raw untuk melihat respons Gemini:")
        print(OUTPUT_RAW)
        raise e

    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\nSelesai.")
    print(f"Output JSON: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
