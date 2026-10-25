# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg

db = connect_pg()
for pop in (10000, 20000, 50000, 100000, 500000):
    r = db.execute(
        """SELECT COUNT(*) total,
                  COUNT(*) FILTER (WHERE name_zh<>'') has_zh
           FROM geo_places
           WHERE source='geonames' AND level=7
             AND population >= ? AND source_id ~ '^[0-9]+$'""",
        (pop,)).fetchone()
    print(f"pop>={pop}: total={r['total']}, missing={r['total']-r['has_zh']}")
sel = db.execute(
    """SELECT COUNT(*) total, COUNT(*) FILTER (WHERE name_zh<>'') has_zh
       FROM geo_places WHERE source='geonames' AND level=7 AND is_selectable=TRUE""").fetchone()
print(f"is_selectable: total={sel['total']}, missing={sel['total']-sel['has_zh']}")
