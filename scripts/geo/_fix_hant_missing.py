# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg
from app.geo.names_zh import to_traditional

db = connect_pg()
rows = db.execute(
    """SELECT id, name_zh FROM geo_places
       WHERE name_zh IS NOT NULL AND TRIM(name_zh)<>''
         AND (name_zh_hant IS NULL OR TRIM(name_zh_hant)='')"""
).fetchall()
print('missing hant:', len(rows))
for r in rows:
    db.execute('UPDATE geo_places SET name_zh_hant=? WHERE id=?',
               (to_traditional(r['name_zh']), r['id']))
db.commit()
print('backfilled')
