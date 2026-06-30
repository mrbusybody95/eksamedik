import sys
sys.path.insert(0, '.')
from anonymize_rme_pdf_text_v6 import read_source, load_staff_variants, anonymize_text
from pathlib import Path

pdf_path = Path(r'C:\Users\milha\OneDrive\Documents\RSAI\Penelitian\Pipeline_RME_Stroke\00\STROKE_003_317082\cppt_ranap.pdf')
root = pdf_path.parent
src = read_source(pdf_path, root, use_ocr=False)
print(f'Extraction status: {src.extraction_status}, chars: {len(src.text)}')
if len(src.text) == 0:
    print('No text extracted')
    sys.exit(1)

staff_variants = load_staff_variants(Path('staff_doctors.csv'))
print(f'Loaded {len(staff_variants)} staff variants')

anon, counts, leftovers, examples = anonymize_text(src.text, staff_variants)
print(f'Anonymized chars: {len(anon)}')
needs = any(v > 0 for v in leftovers.values())
print(f'Needs manual review: {needs}')
if needs:
    import json
    print(f'Leftovers: {json.dumps({k:v for k,v in leftovers.items() if v>0})}')

out_dir = Path(r'C:\Users\milha\OneDrive\Documents\RSAI\Penelitian\Pipeline_RME_Stroke\03_anonymized_text_v6_test')
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / (pdf_path.stem + '.anon.txt')
out_path.write_text(anon, encoding='utf-8')
print(f'Written to: {out_path}')
print('--- First 500 chars of anonymized text ---')
print(anon[:500])
