
from pathlib import Path
import re
import csv
from datetime import datetime

# ============================================================
# ANONIMISASI STAGE 4 - CPPT HEADER / SIGNATURE LEAKFIX
# Struktur:
# 02_text_extracted/STROKE_001/*.txt
# 03_anonymized_text/STROKE_001/*.txt
#
# Jalankan dari folder 06_scripts:
#   python anonymize_stage4_cppt_header_leakfix_recursive.py
#
# Pastikan staff_doctors.csv ada di folder 06_scripts.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
IN_DIR = BASE_DIR / "02_text_extracted"
OUT_DIR = BASE_DIR / "03_anonymized_text"
REPORT_DIR = BASE_DIR / "04_anonymization_report"
DOCTOR_CSV = Path(__file__).resolve().parent / "staff_doctors.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

SPECIALIST_MAP = {
    "sp.n": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.s": "DOKTER_SPESIALIS_NEUROLOGI",
    "sp.rad": "DOKTER_SPESIALIS_RADIOLOGI",
    "sp.pk": "DOKTER_SPESIALIS_PATOLOGI_KLINIK",
    "sp.pa": "DOKTER_SPESIALIS_PATOLOGI_ANATOMI",
    "sp.pd": "DOKTER_SPESIALIS_PENYAKIT_DALAM",
    "sp.pd-kger": "DOKTER_SUBSPESIALIS_GERIATRI",
    "sp.pd-kgh": "DOKTER_SUBSPESIALIS_GINJAL_HIPERTENSI",
    "sp.pd-kgeh": "DOKTER_SUBSPESIALIS_GASTROENTERO_HEPATOLOGI",
    "sp.pd-khom": "DOKTER_SUBSPESIALIS_HEMATO_ONKOLOGI",
    "sp.pd-kai": "DOKTER_SUBSPESIALIS_ALERGI_IMUNOLOGI",
    "sp.pd-kpsi": "DOKTER_SUBSPESIALIS_PSIKOSOMATIK",
    "sp.pd-kpti": "DOKTER_SUBSPESIALIS_PENYAKIT_TROPIS_INFEKSI",
    "sp.pd-kemd": "DOKTER_SUBSPESIALIS_ENDOKRIN_METABOLIK_DIABETES",
    "sp.pd-kr": "DOKTER_SUBSPESIALIS_REUMATOLOGI",
    "sp.pd-kkv": "DOKTER_SUBSPESIALIS_KARDIOVASKULAR",
    "sp.jp": "DOKTER_SPESIALIS_JANTUNG",
    "sp.jp(k)": "DOKTER_SUBSPESIALIS_JANTUNG",
    "sp.an": "DOKTER_SPESIALIS_ANESTESI",
    "sp.an-kic": "DOKTER_SUBSPESIALIS_INTENSIVE_CARE",
    "sp.b": "DOKTER_SPESIALIS_BEDAH",
    "sp.bs": "DOKTER_SPESIALIS_BEDAH_SARAF",
    "sp.ot": "DOKTER_SPESIALIS_ORTOPEDI",
    "sp.u": "DOKTER_SPESIALIS_UROLOGI",
    "sp.a": "DOKTER_SPESIALIS_ANAK",
    "sp.a(k)": "DOKTER_SUBSPESIALIS_ANAK",
    "sp.og": "DOKTER_SPESIALIS_OBGYN",
    "sp.og(k)": "DOKTER_SUBSPESIALIS_OBGYN",
    "sp.p": "DOKTER_SPESIALIS_PARU",
    "sp.kfr": "DOKTER_SPESIALIS_REHAB_MEDIK",
    "sp.kj": "DOKTER_SPESIALIS_KEDOKTERAN_JIWA",
    "sp.tht-kl": "DOKTER_SPESIALIS_THT",
    "sp.m": "DOKTER_SPESIALIS_MATA",
    "sp.kk": "DOKTER_SPESIALIS_KULIT_KELAMIN",
    "sp.dv": "DOKTER_SPESIALIS_DERMATOLOGI_VENEREOLOGI",
}

HOSPITAL_NAMES = [
    # Tambahkan bila perlu:
    # "RS AL ISLAM BANDUNG",
    # "RUMAH SAKIT AL ISLAM BANDUNG",
]

CLINICAL_STOPWORDS = {
    "keluhan", "diagnosa", "diagnosis", "terapi", "planning", "sesuai", "observasi",
    "pasien", "nyeri", "lemah", "sesak", "muntah", "demam", "stroke", "infark",
    "pneumonia", "hematemesis", "anamnesis", "pemeriksaan", "tekanan", "darah",
    "suhu", "spo2", "gcs", "ews", "hasil", "nilai", "rujukan", "satuan", "klinik",
    "poliklinik", "penjamin", "alamat", "umur", "tgl", "lahir", "perempuan", "laki",
}

def norm(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))

def merge(*dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out

def safe_name(name: str) -> str:
    e = re.escape(name.strip())
    return e.replace(r"\ ", r"\s+").replace(r"\.", r"\.?")

def infer_role(s: str) -> str:
    low = s.lower()
    compact = re.sub(r"[\s,\.]+", "", low)
    for degree, role in sorted(SPECIALIST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if degree.replace(".", "").replace(" ", "").lower() in compact:
            return role
    if re.search(r"\bsp\.?\s*[a-z]", low, flags=re.I):
        return "DOKTER_SPESIALIS"
    if re.search(r"\bdrg\.?\b", low, flags=re.I):
        return "DOKTER_GIGI"
    if re.search(r"\bdr\.?\b|\bdr\s*,", low, flags=re.I):
        return "DOKTER_UMUM"
    return "DOKTER"

def load_doctors():
    doctors = []
    if not DOCTOR_CSV.exists():
        print(f"PERINGATAN: staff_doctors.csv tidak ditemukan: {DOCTOR_CSV}")
        return doctors
    with DOCTOR_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip() or infer_role(name)
            if not name:
                continue
            doctors.append((name, role))
            bare = re.sub(r"(?i)\bdrg?\.?\s*", "", name).strip()
            bare = re.sub(r"(?i),?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?", "", bare).strip(" ,.")
            bare = re.sub(r"\s+", " ", bare)
            if bare and len(bare.split()) >= 2:
                doctors.append((bare, role))
    unique = []
    seen = set()
    for n, r in doctors:
        key = (n.lower(), r)
        if key not in seen:
            seen.add(key)
            unique.append((n, r))
    print(f"Daftar dokter + varian terbaca: {len(unique)} nama")
    return unique

def patient_rs(text):
    counts = {}
    patterns = [
        ("NO_RM", r"\b(?:No\.?\s*RM|Nomor\s*RM|MRN|Rekam\s*Medis|No\.?\s*Rekam\s*Medis)\s*[:\-]?\s*[A-Za-z0-9\-\/\.]+", "[NO_RM]"),
        ("NIK", r"\b(?:NIK|No\.?\s*KTP|Nomor\s*KTP)\s*[:\-]?\s*\d{12,20}\b", "[NIK]"),
        ("NIK_16", r"\b\d{16}\b", "[NIK]"),
        ("NO_HP", r"\b(?:0|\+62|62)8[1-9][0-9\s\-]{6,15}\b", "[NO_HP]"),
        ("EMAIL", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        ("NAMA_PASIEN", r"\b(?:Nama\s*Pasien|Nama)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}", "Nama Pasien: [PASIEN]"),
        ("ALAMAT", r"\b(?:Alamat)\s*[:\-]?\s*.{5,120}", "Alamat: [ALAMAT]"),
    ]
    for k, p, r in patterns:
        text, n = re.subn(p, r, text, flags=re.I)
        counts[k] = n
    total = 0
    for name in HOSPITAL_NAMES:
        if name.strip():
            text, n = re.subn(safe_name(name), "[RUMAH_SAKIT]", text, flags=re.I)
            total += n
    for p, r in [
        (r"\b(?:Rumah\s*Sakit|RS|R\.?S\.?)\s+[A-Z][A-Za-z0-9&.'` -]{2,80}", "[RUMAH_SAKIT]"),
        (r"\b(?:Jl\.?|Jalan)\s+[A-Z][A-Za-z0-9&.'` ,\-\/]{5,120}", "[ALAMAT_RS]"),
        (r"\b(?:Telp\.?|Telepon|Fax)\s*[:\-]?\s*[0-9\-\s\(\)]{5,30}", "[TELEPON_RS]"),
    ]:
        text, n = re.subn(p, r, text, flags=re.I)
        total += n
    counts["RUMAH_SAKIT_ALAMAT_RS"] = total
    return text, counts

def csv_doctors(text, doctors):
    counts = {}
    for name, role in sorted(doctors, key=lambda x: len(x[0]), reverse=True):
        if len(name) < 5:
            continue
        text, n = re.subn(safe_name(name), f"[{role}]", text, flags=re.I)
        counts[f"CSV_{role}"] = counts.get(f"CSV_{role}", 0) + n
    return text, counts

def doctor_regex(text):
    counts = {}
    degree = r"(?:drg?\.?|Drg?\.?)"
    sp = r"(?:Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?)"
    honor = r"(?:H\.?|Hj\.?)"
    suffix = r"(?:\s*,?\s*(?:H\.?|Hj\.?|KIC|FINASIM|FIHA|M\.?Kes|MH\.?Kes|M\.?Sc|MM|SH|MH))*"

    def repl(m):
        old = m.group(0)
        role = infer_role(old)
        counts[role] = counts.get(role, 0) + 1
        pref = re.match(r"(?is)\b(DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?", old.strip())
        if pref:
            return f"{pref.group(1)}: [{role}]"
        if re.search(r"(?i)diverifikasi\s+oleh", old):
            return re.sub(r"(?is)(diverifikasi\s+oleh\s*:?).*", rf"\1 [{role}]", old)
        if re.search(r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:", old):
            return re.sub(r"(?is)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:).*", rf"\1 [{role}]", old)
        return f"[{role}]"

    patterns = [
        rf"(?is)\bdiverifikasi\s+oleh\s*:?\s*[A-Z][A-Za-z.'` -]{{2,60}}(?:\n\s*[A-Z][A-Za-z.'` -]{{1,60}}){{0,3}}\s*,?\s*{honor}?\.?\s*\n?\s*{degree}\s*,?\s*{sp}?{suffix}\.?",
        rf"\b(?:DPJP|Dokter\s+IGD|Dokter\s+Jaga|Dokter|Konsulen|Operator|Anestesi|Radiolog|Pemeriksa|Verifikator|Pengirim)\s*[:\-]?\s*(?:\(?\s*)?(?:{degree}\s*)?[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?(?:{degree})?(?:,\s*)?{sp}?{suffix}\.?\)?",
        rf"\b{degree}\s*[A-Z][A-Za-z.'` -]{{2,80}}(?:,\s*)?{sp}?{suffix}\.?",
        rf"\b[A-Z][A-Za-z.'` -]{{2,80}}\s*,\s*{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"(?m)^[A-Z][A-Za-z.'` -]{{2,60}},?\s*\n\s*(?:[A-Z][A-Za-z.'` -]{{1,60}},?\s*\n\s*){{0,3}}{honor}?\.?\s*{degree}\.?(?:\s*,?\s*{sp})?{suffix}\.?",
        rf"\([A-Z][A-Za-z.'` -]{{2,120}},\s*{honor}?\.?\s*{degree}\.?\s*,?\s*{sp}?{suffix}\.?\)",
        rf"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{{2,80}}\s*,?\s*(?:{degree}|\[DOKTER(?:_[A-Z_]+)?\])(?:\s*:\s*\d{{1,2}}\s+\w+\s+\d{{4}},?)?",
    ]
    for p in patterns:
        text = re.sub(p, repl, text, flags=re.I | re.S)
    return text, counts

def cleanup_context(text):
    counts = {}
    cleanups = [
        ("dokter_label_name", r"(?is)(Dokter\s*:\s*)\[DOKTER\]\s*\n\s*:\s*[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
        ("colon_name_doctorlabel", r"(?m)^(\s*:\s*)[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
        ("print_copy_name", r"(?i)(print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*)[A-Z][A-Za-z.'` -]{2,80},?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1\2"),
        ("parentheses_after_doctor_label", r"\(\s*[A-Z][A-Za-z.'` -]{2,120},\s*(?:H\.?|Hj\.?)?\.?\s*drg?\.?\s*,?\s*Sp\.?\s*[A-Za-z]+[^)]*\)", "[DOKTER_SPESIALIS]"),
    ]
    for k, p, r in cleanups:
        text, n = re.subn(p, r, text, flags=re.I)
        counts[k] = n
    return text, counts

def cppt_provider(text):
    counts = {}
    date_pat = r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    time_pat = r"\d{1,2}:\d{2}(?::\d{2})?"

    def repl(m):
        header, block, soap = m.group("header"), m.group("block"), m.group("soap")
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        joined = " ".join(lines)
        low = joined.lower()
        if any(w in low for w in CLINICAL_STOPWORDS) or len(lines) > 4 or len(joined) > 120:
            return m.group(0)
        role = "PPA"
        if re.search(r"\bdrg?\.?\b|\bdr\b|\bsp\.?", joined, flags=re.I):
            role = infer_role(joined)
        elif re.search(r"\bners\b|\bns\.?\b|\bamd\.?\s*kep\b|\bs\.?\s*kep\b", joined, flags=re.I):
            role = "PERAWAT"
        counts[f"CPPT_HEADER_{role}"] = counts.get(f"CPPT_HEADER_{role}", 0) + 1
        return f"{header}[{role}]\n{soap}"

    pat = rf"(?ms)(?P<header>^\s*{date_pat}\s*\n\s*{time_pat}\s*\n)(?P<block>(?:\s*[A-Z][A-Za-z.'` -]{{1,60}}\s*\n){{1,4}})(?P<soap>\s*[SOAP]\s*(?:\n|$))"
    text = re.sub(pat, repl, text)
    return text, counts

def other_ppa(text):
    counts = {}
    patterns = [
        ("PERAWAT", r"\b(?:Ns\.?|Ners)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Kep\.?|S\.?\s*Kep\s*,?\s*Ners|Ners)\b"),
        ("PERAWAT", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?|AMK)\b"),
        ("PERAWAT", r"\[PERAWAT\]\s*,?\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\b"),
        ("BIDAN", r"\b(?:Bd\.?|Bdn\.?|Bidan)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("BIDAN", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Keb\.?|A\.?Md\.?\s*Keb\.?|S\.?\s*Tr\.?\s*Keb\.?)\b"),
        ("APOTEKER", r"\b(?:apt\.?|Apt\.?|Apoteker)\s+[A-Z][A-Za-z.'` -]{2,80}"),
        ("APOTEKER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:S\.?\s*Farm\.?|M\.?\s*Farm\.?|Apt\.?|apt\.?)\b"),
        ("ANALIS_LAB", r"\b(?:Analis|ATLM|Petugas\s+Lab|Laboratorium)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("ANALIS_LAB", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*AK\.?|A\.?Md\.?\s*AK\.?|S\.?\s*Tr\.?\s*Kes\.?)\b"),
        ("RADIOGRAFER", r"\b(?:Radiografer|Petugas\s+Radiologi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("RADIOGRAFER", r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        ("RADIOGRAFER", r"\[RADIOGRAFER\]\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\b"),
        ("FISIOTERAPIS", r"\b(?:Ftr\.?|Fisioterapis|Fisioterapi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
        ("NUTRISIONIS", r"\b(?:Ahli\s+Gizi|Nutrisionis|Dietisien|Gizi)\s*[:\-]?\s*[A-Z][A-Za-z.'` -]{2,80}"),
    ]
    for role, p in patterns:
        text, n = re.subn(p, f"[{role}]", text, flags=re.I)
        counts[role] = counts.get(role, 0) + n
    return text, counts

def final_cleanup(text):
    counts = {}
    cleanups = [
        ("LABEL_DOCTOR_DR", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*,?\s*drg?\.?", r"\1"),
        ("LABEL_DOCTOR_SP", r"(\[DOKTER(?:_[A-Z_]+)?\])\s*,?\s*Sp\.?\s*[A-Za-z]+(?:[\.\-\s]?[A-Za-z]+)*(?:\([Kk]\))?\.?", r"\1"),
        ("LABEL_PERAWAT_NERS", r"(\[PERAWAT\])\s*,?\s*(?:Ners|Ns\.?|S\.?\s*Kep\.?|Amd\.?\s*Kep\.?|A\.?Md\.?\s*Kep\.?)\.?", r"\1"),
        ("LABEL_RAD_AMD", r"(\[RADIOGRAFER\])\s*,?\s*(?:Amd\.?\s*Rad\.?|A\.?Md\.?\s*Rad\.?|S\.?\s*Tr\.?\s*Rad\.?)\.?", r"\1"),
        ("DOUBLE_DOKTER", r"\[DOKTER\]\s*,?\s*(\[DOKTER(?:_[A-Z_]+)?\])", r"\1"),
    ]
    for k, p, r in cleanups:
        text, n = re.subn(p, r, text, flags=re.I)
        counts[k] = n
    return text, counts

def detect(text):
    patterns = {
        "possible_multiline_dr_leftover": r"(?m)^[A-Z][A-Za-z.'` -]{2,60},?\s*\n\s*(?:H\.?|Hj\.?)?\.?\s*Dr?\.?,?\s*Sp",
        "possible_colon_name_doctorlabel_leftover": r"(?m)^\s*:\s*[A-Z][A-Za-z.'` -]{2,80},?\s*\[DOKTER",
        "possible_comma_dr_leftover": r"\b[A-Z][A-Za-z.'` -]{2,80}\s*,\s*(?:H\.?|Hj\.?)?\.?\s*drg?\.?",
        "possible_dr_leftover": r"\bdrg?\.?\s+[A-Z][A-Za-z.'` -]{2,80}",
        "possible_sp_leftover": r"\bSp\.?\s*[A-Za-z]+",
        "possible_ners_leftover": r"\b(?:Ns\.?|Ners)\b",
        "possible_amd_kep_leftover": r"\bA\.?Md\.?\s*Kep\.?\b|\bAmd\.?\s*Kep\.?\b",
        "possible_amd_rad_leftover": r"\bA\.?Md\.?\s*Rad\.?\b|\bAmd\.?\s*Rad\.?\b",
        "possible_print_copy_by_leftover": r"(?i)print\s+copy\s+(?:ke-\d+\s+)?by\s*:\s*[A-Z][A-Za-z.'` -]{2,80}",
    }
    return {k: len(re.findall(p, text, flags=re.I)) for k, p in patterns.items()}

def anonymize_text(text, doctors):
    text = norm(text)
    text, c1 = patient_rs(text)
    text, c2 = csv_doctors(text, doctors)
    text, c3 = doctor_regex(text)
    text, c4 = cleanup_context(text)
    text, c5 = cppt_provider(text)
    text, c6 = other_ppa(text)
    text, c7 = final_cleanup(text)
    c8 = detect(text)
    return text, merge(c1, c2, c3, c4, c5, c6, c7, c8)

def main():
    print("BASE_DIR:", BASE_DIR)
    print("IN_DIR  :", IN_DIR)
    print("OUT_DIR :", OUT_DIR)

    if not IN_DIR.exists():
        raise FileNotFoundError(f"Folder input tidak ditemukan: {IN_DIR}")

    doctors = load_doctors()
    txt_files = sorted(IN_DIR.rglob("*.txt"))

    if not txt_files:
        print(f"Tidak ada file .txt di {IN_DIR} maupun subfoldernya.")
        return

    print(f"Total file .txt ditemukan: {len(txt_files)}")
    rows = []

    for fp in txt_files:
        rel = fp.relative_to(IN_DIR)
        out = OUT_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)

        raw = fp.read_text(encoding="utf-8", errors="ignore")
        anon, counts = anonymize_text(raw, doctors)
        out.write_text(anon, encoding="utf-8")

        row = {
            "patient_folder": rel.parts[0] if len(rel.parts) > 1 else "",
            "file": str(rel),
            "output_file": str(out.relative_to(BASE_DIR)),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        row.update(counts)
        rows.append(row)

        print(f"Anonimisasi: {rel}")
        print(f"Berhasil disimpan ke: {out}")

    keys = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)

    report = REPORT_DIR / "anonymization_report.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    print("\nSelesai.")
    print(f"Hasil anonim: {OUT_DIR}")
    print(f"Report audit: {report}")
    print("\nCek manual dengan Ctrl+F:")
    print("dr | Dr | Sp. | Ners | Amd.Kep | Amd.Rad | Print copy by")
    print("Cek juga kolom possible_*_leftover di anonymization_report.csv")

if __name__ == "__main__":
    main()
