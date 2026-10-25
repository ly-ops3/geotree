# -*- coding: utf-8 -*-
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.database.pg import connect_pg

db = connect_pg()
out = io.open('scripts/geo/_verify_hant.out.txt', 'w', encoding='utf-8')

out.write('== AT 样本 ==\n')
for r in db.execute("""SELECT name_en, name_zh, name_zh_hant FROM geo_places
    WHERE source='geonames' AND iso_country='AT' AND name_zh IS NOT NULL LIMIT 10""").fetchall():
    out.write(f"  {r['name_en']} | {r['name_zh']} | {r['name_zh_hant']}\n")

out.write('== 仍疑似繁体的 name_zh 数 ==\n')
r = db.execute("""SELECT COUNT(*) c FROM geo_places
    WHERE name_zh SIMILAR TO '%[縣區島奧爾灣東達華薩貝國際倫亞羅馬諾臺韓]%'""").fetchone()
out.write(f"  {r['c']}\n")

out.write('== hant 有但 hans 空的行 ==\n')
for r in db.execute("""SELECT iso_country, level, name_en, name_zh_hant FROM geo_places
    WHERE (name_zh IS NULL OR TRIM(name_zh)='') AND name_zh_hant IS NOT NULL LIMIT 15""").fetchall():
    out.write(f"  {r['iso_country']} L{r['level']} {r['name_en']} -> {r['name_zh_hant']}\n")

out.write('== ok_zh 繁体样本 ==\n')
for r in db.execute("""SELECT name_zh, name_zh_hant FROM geo_places
    WHERE source='ok_zh' AND name_zh_hant IS NOT NULL LIMIT 8""").fetchall():
    out.write(f"  {r['name_zh']} | {r['name_zh_hant']}\n")

out.close()
print('done')
