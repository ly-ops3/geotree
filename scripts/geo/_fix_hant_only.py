# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.database.pg import connect_pg
from app.geo.names_zh import to_simplified

db = connect_pg()
rows = db.execute(
    """SELECT id, name_zh_hant FROM geo_places
       WHERE (name_zh IS NULL OR TRIM(name_zh)='') AND name_zh_hant IS NOT NULL"""
).fetchall()
db.executemany(
    'UPDATE geo_places SET name_zh=? WHERE id=?',
    [(to_simplified(r['name_zh_hant']), r['id']) for r in rows],
)
db.commit()
print('fixed hant-only rows:', len(rows))
