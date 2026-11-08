import sys
sys.path.insert(0, '.')
from core.parsers.docx_parser import extract_tables_from_docx
from core.parsers.header_profiles import parse_table

for t in extract_tables_from_docx(sys.argv[1]):
    p = parse_table(t)
    print('cols in doc:', max(len(r) for r in t), 'profile:', getattr(p, 'profile', None))
    print('headers:', p.headers)
    print('dropped:', p.dropped)
    for r in t[:6]:
        print(r)
    print('rows:', len(t))
