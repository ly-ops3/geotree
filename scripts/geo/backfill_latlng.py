#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""allCountries.zip → geonames 行经纬度回填（latitude / longitude）。

只更新 source='geonames' 的行（ok_zh 无坐标源）。流式读 zip，
按 source_id(=geonameid) 匹配，分批 executemany。
用法: python -X utf8 scripts/geo/backfill_latlng.py [allCountries.zip 路径]
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg

DEFAULT_SRC = r'N:\项目\SV\geo\allCountries.zip'
BATCH = 5000


def main(path=DEFAULT_SRC):
    db = connect_pg()
    need = {
        r['source_id'] for r in db.execute(
            "SELECT source_id FROM geo_places WHERE source='geonames'"
        )
    }
    print(f'target geonames rows: {len(need)}')

    pending, hit = [], 0
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith('.txt')]
        assert names, 'zip 内没有 .txt'
        with zf.open(names[0]) as fh:
            for raw in fh:
                cols = raw.decode('utf-8', 'replace').rstrip('\n').split('\t')
                sid = cols[0]
                if sid not in need:
                    continue
                try:
                    pending.append((float(cols[4]), float(cols[5]), sid))
                except (ValueError, IndexError):
                    continue
                hit += 1
                if len(pending) >= BATCH:
                    db.executemany(
                        "UPDATE geo_places SET latitude=?, longitude=? WHERE source='geonames' AND source_id=?",
                        pending,
                    )
                    db.commit()
                    print(f'  ...{hit}')
                    pending.clear()
    if pending:
        db.executemany(
            "UPDATE geo_places SET latitude=?, longitude=? WHERE source='geonames' AND source_id=?",
            pending,
        )
        db.commit()
    print(f'updated {hit} rows')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
