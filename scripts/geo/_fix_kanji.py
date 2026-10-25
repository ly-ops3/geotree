# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg
from app.geo.names_zh import to_simplified

db = connect_pg()
rows = db.execute(
    "SELECT id, name_zh FROM geo_places WHERE name_zh IS NOT NULL AND name_zh <> ''"
).fetchall()
fixed = 0
for r in rows:
    s = to_simplified(r['name_zh'])
    if s and s != r['name_zh']:
        db.execute('UPDATE geo_places SET name_zh=? WHERE id=?', (s, r['id']))
        print(r['name_zh'], '->', s)
        fixed += 1
db.commit()
print('fixed:', fixed)
