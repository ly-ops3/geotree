# -*- coding: utf-8 -*-
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.database.pg import connect_pg

db = connect_pg()
out = io.open('scripts/geo/_survey_terms.out.txt', 'w', encoding='utf-8')

out.write('== ADM1: 每国英文名尾词（通名）分布，前 25 国 ==\n')
rows = db.execute(
    """SELECT iso_country, COUNT(*) c FROM geo_places
       WHERE source='geonames' AND level=2 GROUP BY iso_country ORDER BY c DESC LIMIT 25"""
).fetchall()
for r in rows:
    iso = r['iso_country']
    names = db.execute(
        "SELECT name_en FROM geo_places WHERE source='geonames' AND level=2 AND iso_country=?",
        (iso,)).fetchall()
    tails = {}
    for n in names:
        en = n['name_en'] or ''
        tail = en.split()[-1] if en else ''
        tails[tail] = tails.get(tail, 0) + 1
    top = sorted(tails.items(), key=lambda kv: -kv[1])[:6]
    out.write(f"  {iso} ({r['c']}): {top}\n")

out.write('\n== ADM2: 每国英文名尾词分布，前 25 国 ==\n')
rows = db.execute(
    """SELECT iso_country, COUNT(*) c FROM geo_places
       WHERE source='geonames' AND level=3 GROUP BY iso_country ORDER BY c DESC LIMIT 25"""
).fetchall()
for r in rows:
    iso = r['iso_country']
    names = db.execute(
        "SELECT name_en FROM geo_places WHERE source='geonames' AND level=3 AND iso_country=? LIMIT 300",
        (iso,)).fetchall()
    tails = {}
    for n in names:
        en = n['name_en'] or ''
        tail = en.split()[-1] if en else ''
        tails[tail] = tails.get(tail, 0) + 1
    top = sorted(tails.items(), key=lambda kv: -kv[1])[:6]
    out.write(f"  {iso} ({r['c']}): {top}\n")

out.close()
print('done')
