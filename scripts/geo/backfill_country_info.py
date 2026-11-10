#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""countryInfo.txt → 国家级字段回填：population / area_km2 / capital / continent。

人口为 GeoNames 维护的各国普查/估算混合快照（约 2018-2020 年份），
仅作排序参考；面积基本不变可当事实数据。
用法: python -X utf8 scripts/geo/backfill_country_info.py [countryInfo.txt 路径]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg

DEFAULT_SRC = r'N:\项目\SV\geo\countryInfo.txt'


def main(path=DEFAULT_SRC):
    db = connect_pg()
    updated = matched = 0
    skipped = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if line.startswith('#') or not line.strip():
                continue
            c = line.rstrip('\n').split('\t')
            if len(c) < 17:
                continue
            geonameid, capital, area, pop, cont = c[16], c[5], c[6], c[7], c[8]
            cur = db.execute(
                """UPDATE geo_places SET
                     population = ?,
                     area_km2   = ?,
                     capital    = NULLIF(?, ''),
                     continent  = NULLIF(?, '')
                   WHERE source='geonames' AND level=1 AND source_id=?""",
                (
                    int(pop) if pop else None,
                    int(float(area)) if area else None,
                    capital,
                    cont,
                    geonameid,
                ),
            )
            if cur.rowcount:
                updated += cur.rowcount
            else:
                skipped.append((c[0], c[4]))
            matched += 1
    db.commit()
    print(f'country rows in file: {matched}, updated: {updated}')
    if skipped:
        print('未匹配（库里无此 geonameid）:', ', '.join(f'{i} {n}' for i, n in skipped[:20]))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
