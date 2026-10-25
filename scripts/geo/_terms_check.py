# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg
from app.geo.admin_terms import has_known_term

db = connect_pg()
# 1) spot check rows from earlier sample
for en in ('Cass County', 'Uki Shi', 'Kehtna vald', 'Comuna Tomesti'):
    r = db.execute(
        "SELECT iso_country, level, name_en, name_zh, name_zh_hant FROM geo_places "
        "WHERE name_en=? AND source='geonames' LIMIT 1", (en,)).fetchone()
    print(dict(r) if r else en + ' NOT FOUND')

# 2) how many zh names have NO known term but a rule exists?
rows = db.execute(
    """SELECT iso_country, level, name_en, name_zh FROM geo_places
       WHERE source='geonames' AND level BETWEEN 2 AND 5
         AND name_zh IS NOT NULL AND TRIM(name_zh)<>''"""
).fetchall()
no_term = [r for r in rows if not has_known_term(r['name_zh'])]
print('no_known_term:', len(no_term))
for r in no_term[:30]:
    print(' ', r['iso_country'], 'L'+str(r['level']), r['name_en'], '->', r['name_zh'])
