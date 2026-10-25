# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg
from app.geo.admin_terms import apply_admin_terms, term_for, has_known_term

db = connect_pg()
res = apply_admin_terms(db, dry_run=True)
print('applied:', res['applied'], 'scanned:', res['scanned'])
for t, c in sorted(res['by_term'].items(), key=lambda x: -x[1]):
    print(' ', t, c)

rows = db.execute(
    """SELECT id, iso_country, level, name_en, name_zh FROM geo_places
       WHERE source='geonames' AND level BETWEEN 2 AND 5
         AND name_zh IS NOT NULL AND TRIM(name_zh)<>''"""
).fetchall()
n = 0
for r in rows:
    if has_known_term(r['name_zh']):
        continue
    rule = term_for(r['iso_country'], r['level'], r['name_en'])
    if not rule:
        continue
    print(r['iso_country'], 'L' + str(r['level']), r['name_en'], '->', r['name_zh'] + rule['term'])
    n += 1
    if n >= 30:
        break
