#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wikidata P300 (ISO 3166-2) 反查补 ADM1/ADM2 中文名。
对缺 name_zh 的行政区，把 admin1_code/admin2_code 转成 ISO 码（US.CA -> US-CA）批量查 zh label。

用法: python scripts/geo/fill_zh_via_p300.py [--level=2] [--level=3] [--dry-run]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests

from app.database.pg import connect_pg
from app.geo.geonames_zh_fixup import normalize_place_zh
from app.geo.names_zh import to_traditional

WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
UA = 'wechat-moments-pro/2.1 geo-fixup (local batch; https://www.mediawiki.org/wiki/API:Etiquette)'
BATCH = 400


def iso_code(row):
    """GeoNames 区划码 -> ISO 3166-2。admin1_code='US.CA' -> 'US-CA'；
    admin2_code='US.CA.001' -> 'US-CA-001' 不存在，ISO 只到二级 US-XX，故 ADM2 用 admin2_code 原文。"""
    level = row['level']
    code = row['admin1_code'] if level == 2 else row['admin2_code']
    if not code:
        return None
    return code.replace('.', '-', 1)


def fetch_zh_batch(codes):
    values = ' '.join(f'"{c}"' for c in codes)
    query = f"""
SELECT ?code ?nameZh WHERE {{
  VALUES ?code {{ {values} }}
  ?item wdt:P300 ?code ;
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
        code = b.get('code', {}).get('value')
        zh = normalize_place_zh(b.get('nameZh', {}).get('value') or '')
        if code and zh and any('一' <= ch <= '鿿' for ch in zh):
            out[code] = zh
    return out


def main():
    dry = '--dry-run' in sys.argv
    levels = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--level=')] or [2]
    db = connect_pg()

    for level in levels:
        code_col = 'admin1_code' if level == 2 else 'admin2_code'
        rows = db.execute(
            f'''SELECT id, level, {code_col} AS admin1_code, admin2_code FROM geo_places
                WHERE source='geonames' AND level=?
                  AND (name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)
                  AND {code_col} IS NOT NULL AND {code_col} <> ''
                ORDER BY iso_country, id''',
            (level,),
        ).fetchall()
        print(f'level {level}: {len(rows)} missing zh', flush=True)
        if not rows:
            continue

        updated = 0
        errors = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            codes = [iso_code(r) for r in chunk]
            codes = [c for c in codes if c]
            try:
                mapping = fetch_zh_batch(codes)
            except Exception as exc:
                errors += 1
                print(f'  batch {i//BATCH}: FAIL {exc}', flush=True)
                time.sleep(15)
                continue
            if mapping and not dry:
                db.executemany(
                    'UPDATE geo_places SET name_zh=?, name_zh_hant=? WHERE id=? AND '
                    "(name_zh IS NULL OR TRIM(name_zh)='' OR name_zh=name_en)",
                    [(mapping[c], to_traditional(mapping[c]), r['id'])
                     for r in chunk for c in [iso_code(r)] if c in mapping],
                )
                db.commit()
            updated += len(mapping)
            print(f'  batch {i//BATCH}: +{len(mapping)} (cum {updated})', flush=True)
            time.sleep(1.5)
        print(f'level {level} done: resolved {updated}, batch_errors={errors}', flush=True)


if __name__ == '__main__':
    main()
