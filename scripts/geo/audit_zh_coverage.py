#!/usr/bin/env python3
"""审计 geo_places：每国每级 name_zh / name_local 覆盖率。结果写 UTF-8 文件。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audit_zh_coverage.out.txt')
LEVEL_NAMES = {1: 'COUNTRY', 2: 'ADM1', 3: 'ADM2', 4: 'ADM3', 5: 'ADM4', 6: 'ADM5', 7: 'PPL', 8: 'OTHER'}
TRAD_CHARS = '縣區島奧爾灣東達華薩貝國際倫亞羅馬諾臺韓嶽廣門蘭總體蘇亀龍點裡麼這為麼國學經緯營莊薩爾濱鎮鄉邊遠選'
_lines = []


def out(s=''):
    _lines.append(str(s))


def main():
    db = connect_pg()
    out('=== 全局（geonames）按 level ===')
    out(f"{'lvl':>4} {'name':>7} {'total':>8} {'has_zh':>8} {'zh=en':>7} {'local':>8} {'lang':>6}")
    for r in db.execute(
        '''SELECT level, COUNT(*) AS total,
                  COUNT(NULLIF(TRIM(name_zh), '')) AS has_zh,
                  COUNT(*) FILTER (WHERE name_zh = name_en) AS zh_eq_en,
                  COUNT(NULLIF(TRIM(name_local), '')) AS has_local,
                  COUNT(NULLIF(TRIM(name_local_lang), '')) AS has_lang
           FROM geo_places WHERE source='geonames'
           GROUP BY level ORDER BY level'''
    ).fetchall():
        out(f"{r['level']:>4} {LEVEL_NAMES.get(r['level'],'?'):>7} {r['total']:>8} "
            f"{r['has_zh']:>8} {r['zh_eq_en']:>7} {r['has_local']:>8} {r['has_lang']:>6}")

    out('\n=== source/level 分布 ===')
    for r in db.execute(
        'SELECT source, level, COUNT(*) c FROM geo_places GROUP BY source, level ORDER BY source, level'
    ).fetchall():
        out(f"  {r['source']:<10} L{r['level']} {r['c']}")

    out('\n=== 缺中文最多的国家（level 2-4，前 40）===')
    for r in db.execute(
        '''SELECT iso_country, level, COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE name_zh IS NULL OR TRIM(name_zh)='') AS missing
           FROM geo_places WHERE source='geonames' AND level BETWEEN 2 AND 4
           GROUP BY iso_country, level
           HAVING COUNT(*) FILTER (WHERE name_zh IS NULL OR TRIM(name_zh)='') > 0
           ORDER BY missing DESC LIMIT 40'''
    ).fetchall():
        out(f"  {r['iso_country']} L{r['level']} 缺 {r['missing']}/{r['total']}")

    out('\n=== ADM1 缺中文统计（level=2，按国）===')
    for r in db.execute(
        '''SELECT iso_country, COUNT(*) c FROM geo_places
           WHERE source='geonames' AND level=2
             AND (name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)
           GROUP BY iso_country ORDER BY c DESC'''
    ).fetchall():
        out(f"  {r['iso_country']} 缺 {r['c']} 个 ADM1")

    out('\n=== 繁体字符样本（name_zh 命中常见繁体字，前 50）===')
    for r in db.execute(
        '''SELECT iso_country, level, name_en, name_zh FROM geo_places
           WHERE source='geonames' AND name_zh SIMILAR TO %s
           LIMIT 50''',
        (f'%[{TRAD_CHARS}]%',),
    ).fetchall():
        out(f"  {r['iso_country']} L{r['level']} en={r['name_en']!r} zh={r['name_zh']!r}")

    out('\n=== name_zh 非中文样本（zh 无汉字，前 30）===')
    for r in db.execute(
        '''SELECT iso_country, level, name_en, name_zh FROM geo_places
           WHERE source='geonames' AND name_zh IS NOT NULL AND TRIM(name_zh)<>''
             AND name_zh !~ '[一-鿿]'
           LIMIT 30'''
    ).fetchall():
        out(f"  {r['iso_country']} L{r['level']} en={r['name_en']!r} zh={r['name_zh']!r}")

    out('\n=== level=8 自然地理样本 ===')
    for r in db.execute(
        '''SELECT iso_country, admin2_code AS feat, name_en, name_zh
           FROM geo_places WHERE source='geonames' AND level=8 LIMIT 15'''
    ).fetchall():
        out(f"  {r['iso_country']} {r['feat']} en={r['name_en']!r} zh={r['name_zh']!r}")

    with open(OUT_PATH, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_lines))
    print(f'wrote {OUT_PATH} ({len(_lines)} lines)')


if __name__ == '__main__':
    main()
