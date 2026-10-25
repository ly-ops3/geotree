# -*- coding: utf-8 -*-
import io, os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.database.pg import connect_pg
from app.geo.names_zh import _zh_names_has_hant

db = connect_pg()
out = io.open('scripts/geo/_check_kanji_leak.out.txt', 'w', encoding='utf-8')

out.write('== name_zh==name_local 且含汉字，按国按级 ==\n')
rows = db.execute(
    """SELECT iso_country, level, COUNT(*) c FROM geo_places
       WHERE source='geonames' AND name_zh IS NOT NULL
         AND name_zh = name_local AND name_local ~ '[一-鿿]'
       GROUP BY iso_country, level ORDER BY c DESC LIMIT 30"""
).fetchall()
for r in rows:
    out.write(f"  {r['iso_country']} L{r['level']} {r['c']}\n")

# sqlite zh 覆盖检查：这些"zh==local"的行有多少其实不在 zh 别名表（疑似本地名直充）
conn = sqlite3.connect(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'database', 'geo', 'zh_altnames.sqlite'))
sus = db.execute(
    """SELECT id, source_id, iso_country, level, name_local, name_zh FROM geo_places
       WHERE source='geonames' AND name_zh IS NOT NULL
         AND name_zh = name_local AND name_local ~ '[一-鿿]'
         AND iso_country IN ('JP','KR','KP','VN')"""
).fetchall()
out.write(f"\n== JP/KR/VN 中 zh==local 行: {len(sus)} ==\n")
miss = 0
samples = []
for r in sus:
    try:
        gid = int(r['source_id'])
    except (TypeError, ValueError):
        continue
    hit = conn.execute('SELECT 1 FROM zh_names WHERE geonameid=?', (gid,)).fetchone()
    if not hit:
        miss += 1
        if len(samples) < 40:
            samples.append(r)
out.write(f"不在 zh 别名表（疑似直充本地名）: {miss}\n")
for r in samples:
    out.write(f"  {r['iso_country']} L{r['level']} gid={r['source_id']} {r['name_local']!r}\n")
out.close()
print('done')
