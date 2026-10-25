#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zh.wikipedia sitelink 反查补中文名：对缺 name_zh 的行，用 P1566 找到实体，
再取其在 zh.wikipedia 上的条目标题（比 rdfs:label 覆盖更广）。

用法: python scripts/geo/fill_zh_via_zhwiki.py --level=7 --min-pop=10000 [--level=4] [--dry-run]
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests

from app.database.pg import connect_pg
from app.geo.names_zh import to_traditional

WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
UA = 'wechat-moments-pro/2.1 geo-fixup (local batch; https://www.mediawiki.org/wiki/API:Etiquette)'
BATCH = 400

# 标题清洗：去掉消歧后缀 "(城市)" / "(美国)" 和 ", 某国" 逗号尾注
_DISAMB_PAREN = re.compile(r'[（(][^（）()]*[)）]\s*$')
_DISAMB_COMMA = re.compile(r'[,，].*$')
_BAD_TITLE = re.compile(r'^(Category|Template|Wikipedia|Help|Portal|分类|模板|模块|帮助|主题|列表)[:：]')


def clean_title(t: str) -> str:
    t = (t or '').strip()
    if not t or _BAD_TITLE.search(t):
        return ''
    t = _DISAMB_PAREN.sub('', t).strip()
    t = _DISAMB_COMMA.sub('', t).strip()
    # 必须含汉字，且不能是残留的全英文/拉丁串
    if not any('一' <= ch <= '鿿' for ch in t):
        return ''
    # 排除重定向页式的"A就是B"标题
    if '→' in t or len(t) > 30:
        return ''
    return t


def fetch_zh_batch(geonameids):
    values = ' '.join(f'"{g}"' for g in geonameids)
    query = f"""
SELECT ?geonameId ?title WHERE {{
  VALUES ?geonameId {{ {values} }}
  ?item wdt:P1566 ?geonameId .
  ?article schema:about ?item ;
           schema:isPartOf <https://zh.wikipedia.org/> ;
           schema:name ?title .
}}"""
    resp = requests.get(
        WIKIDATA_SPARQL,
        params={'query': query, 'format': 'json'},
        headers={'Accept': 'application/sparql-results+json', 'User-Agent': UA},
        timeout=180,
    )
    resp.raise_for_status()
    out = {}
    for b in resp.json().get('results', {}).get('bindings', []):
        gid = b.get('geonameId', {}).get('value')
        zh = clean_title(b.get('title', {}).get('value') or '')
        if gid and zh:
            out[str(gid)] = zh
    return out


def main():
    dry = '--dry-run' in sys.argv
    levels = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--level=')] or [7]
    min_pop = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--min-pop=')), 0)
    db = connect_pg()

    for level in levels:
        rows = db.execute(
            '''SELECT id, source_id FROM geo_places
               WHERE source='geonames' AND level=?
                 AND (name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)
                 AND source_id ~ '^[0-9]+$'
                 AND COALESCE(population, 0) >= ?
               ORDER BY iso_country, id''',
            (level, min_pop),
        ).fetchall()
        print(f'level {level}: {len(rows)} missing zh', flush=True)
        if not rows:
            continue

        updated = 0
        errors = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            gids = [r['source_id'] for r in chunk]
            try:
                mapping = fetch_zh_batch(gids)
            except Exception as exc:
                errors += 1
                print(f'  batch {i//BATCH}: FAIL {exc}', flush=True)
                time.sleep(15)
                continue
            if mapping and not dry:
                db.executemany(
                    'UPDATE geo_places SET name_zh=?, name_zh_hant=? WHERE id=? AND '
                    "(name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)",
                    [(zh, to_traditional(zh), r['id']) for r in chunk for zh in [mapping.get(r['source_id'])] if zh],
                )
                db.commit()
            updated += len(mapping)
            print(f'  batch {i//BATCH}: +{len(mapping)} (cum {updated})', flush=True)
            time.sleep(1.5)
        print(f'level {level} done: resolved {updated}, batch_errors={errors}', flush=True)


if __name__ == '__main__':
    main()
