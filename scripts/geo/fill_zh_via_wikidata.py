#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wikidata 批量补中文名：对缺 name_zh 的 geonames 行，用 P1566=geonameid 反查 zh label。

用法: python scripts/geo/fill_zh_via_wikidata.py [--level 2] [--level 3] [--dry-run]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests

from app.database.pg import connect_pg
from app.geo.geonames_zh_fixup import normalize_place_zh

WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
UA = 'wechat-moments-pro/2.1 geo-fixup (local batch; https://www.mediawiki.org/wiki/API:Etiquette)'
BATCH = 400


def fetch_zh_batch(geonameids: list[str]) -> dict[str, str]:
    values = ' '.join(f'"{g}"' for g in geonameids)
    query = f"""
SELECT ?geonameId ?nameZh WHERE {{
  VALUES ?geonameId {{ {values} }}
  ?item wdt:P1566 ?geonameId ;
        rdfs:label ?nameZh .
  FILTER(LANG(?nameZh) = "zh")
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
        zh = normalize_place_zh(b.get('nameZh', {}).get('value') or '')
        if gid and zh and any('一' <= ch <= '鿿' for ch in zh):
            out[str(gid)] = zh
    return out


def main():
    dry = '--dry-run' in sys.argv
    levels = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--level=')] or [2]
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
                from app.geo.names_zh import to_traditional
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
