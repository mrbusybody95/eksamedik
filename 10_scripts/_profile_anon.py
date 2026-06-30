"""Quick profiling script for anonymization pipeline."""
import time, sys, os
from pathlib import Path

sys.path.insert(0, '.')
import anonymize_rme_pdf_text_v6 as anon

# Test 1: CPPT IGD (small file ~3.5KB)
root = Path('../00')
src_file = root / 'STROKE_001_194682' / 'cppt_igd.pdf'
src = anon.read_source(src_file, root, use_ocr=False)
print(f'[1] CPPT IGD | Status: {src.extraction_status} | Chars: {len(src.text)}')

# Test 2: CPPT Ranap (large file ~50KB)
src_file2 = root / 'STROKE_001_194682' / 'cppt_ranap.pdf'
src2 = anon.read_source(src_file2, root, use_ocr=False)
print(f'[2] CPPT Ranap | Status: {src2.extraction_status} | Chars: {len(src2.text)}')

# Build role patterns
variants = anon.load_staff_variants(Path('staff_doctors.csv'))
role_patterns = anon.compile_role_patterns(variants)
print(f'Staff variants: {len(variants)} → {len(role_patterns)} role patterns')

for label, s in [('CPPT IGD (3.5KB)', src.text), ('CPPT Ranap (50KB)', src2.text)]:
    print(f'\n--- {label} ---')
    
    # Full anonymize_text
    t0 = time.time()
    anon_text, counts, leftovers, examples = anon.anonymize_text(s, role_patterns)
    t1 = time.time()
    total_replacements = sum(counts.values())
    leftover_hits = {k: v for k, v in leftovers.items() if v}
    print(f'  Total: {t1-t0:.4f}s | Replacements: {total_replacements} | Leftover: {leftover_hits}')
    print(f'  Bytes: {len(s)} → {len(anon_text)} ({len(anon_text)-len(s):+d})')

print('\nDone.')
