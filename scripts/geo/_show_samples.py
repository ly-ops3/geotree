# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app.database.pg import connect_pg

db = connect_pg()

def show(title, sql, params=()):
    print('=== ' + title + ' ===')
    for r in db.execute(sql, params).fetchall():
        print(' ', ' | '.join(f'{k}={v}' for k, v in r.items()))
    print()

# 1) 通名追加效果：本次新增通名的行
show('通名追加样例（BR/CO municipio → 市镇）',
     """SELECT iso_country, level, name_en, name_zh, name_zh_hant
        FROM geo_places
        WHERE source='geonames' AND name_zh LIKE '%市镇'
          AND iso_country IN ('BR','CO','NO')
        ORDER BY iso_country LIMIT 8""")

show('通名追加样例（TR ilce → 县、KR 道、中亚 rayon → 区）',
     """SELECT iso_country, level, name_en, name_zh, name_zh_hant
        FROM geo_places
        WHERE source='geonames' AND level=3
          AND ((iso_country='TR' AND name_zh LIKE '%县')
            OR (iso_country IN ('KZ','UZ') AND name_zh LIKE '%区'))
        ORDER BY iso_country LIMIT 8""")

# 2) Wikidata 补的 ADM1
show('Wikidata 补的 ADM1（之前缺失的国家）',
     """SELECT iso_country, level, name_en, name_zh, name_zh_hant
        FROM geo_places
        WHERE source='geonames' AND level=2
          AND iso_country IN ('SI','MT','MK','AZ','MH')
          AND name_zh IS NOT NULL
        ORDER BY iso_country LIMIT 10""")

# 3) 繁简双字段
show('繁简双字段对照',
     """SELECT iso_country, level, name_en, name_zh, name_zh_hant
        FROM geo_places
        WHERE source='geonames' AND name_zh IS NOT NULL AND name_zh_hant IS NOT NULL
          AND iso_country IN ('US','JP','AT')
        ORDER BY level, iso_country LIMIT 10""")

# 3.5) 回填后的 hant 验证
c = db.execute(
    "SELECT COUNT(*) c FROM geo_places WHERE name_zh<>'' AND (name_zh_hant IS NULL OR name_zh_hant='')"
).fetchone()['c']
print('name_zh 有值但 hant 缺失:', c)
show('KZ 区样例（验证 hant 已回填）',
     """SELECT iso_country, level, name_en, name_zh, name_zh_hant FROM geo_places
        WHERE iso_country='KZ' AND level=3 AND name_zh LIKE '%区' LIMIT 3""")

# 4) 通名分布统计
show('name_zh 结尾通名 TOP20（level 2-5）',
     """SELECT substring(name_zh from '[一-龥]{1,4}$') AS tail, COUNT(*) c
        FROM geo_places WHERE source='geonames' AND level BETWEEN 2 AND 5 AND name_zh<>''
        GROUP BY 1 ORDER BY c DESC LIMIT 20""")
