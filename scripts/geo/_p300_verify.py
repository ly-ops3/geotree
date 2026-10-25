# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg

db = connect_pg()
rows = db.execute(
    """SELECT iso_country, COUNT(*) c FROM geo_places
       WHERE source='geonames' AND level=2
         AND (name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)
       GROUP BY iso_country ORDER BY c DESC LIMIT 15"""
).fetchall()
print('still missing by country:', [(r['iso_country'], r['c']) for r in rows])
print('total missing:', db.execute(
    """SELECT COUNT(*) c FROM geo_places WHERE source='geonames' AND level=2
       AND (name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)"""
).fetchone()['c'])
print()
smp = db.execute(
    """SELECT iso_country, name_en, name_zh, name_zh_hant FROM geo_places
       WHERE source='geonames' AND level=2
         AND iso_country IN ('PR','IM','MH','AI','VN','MA','GU','YT')
         AND name_zh<>''
       ORDER BY iso_country, name_en LIMIT 30"""
).fetchall()
for r in smp:
    print(r)
