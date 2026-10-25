#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""name_zh_hant 存量回填 + 繁体泄漏归一。

步骤：
1. 确保 geo_places.name_zh_hant 列存在
2. zh_altnames.sqlite 若为旧版单列结构，从 alternateNames 重建（简体/繁体分桶）
3. sqlite 批量回填：name_zh 用简体名覆盖泄漏的繁体；name_zh_hant 用真实繁体
4. OpenCC 兜底：name_zh 全量 t2s 归一；name_zh_hant 缺失时 s2t 补

用法：python scripts/geo/backfill_zh_hant.py [--dry-run]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg
from app.geo.names_zh import (
    ensure_zh_altnames_db,
    zh_altnames_needs_rebuild,
    to_simplified,
    to_traditional,
)

GEO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'database', 'geo',
)


def main():
    dry = '--dry-run' in sys.argv
    db = connect_pg()

    col = db.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema='public' AND table_name='geo_places' AND column_name='name_zh_hant'"""
    ).fetchone()
    if not col:
        print('add column name_zh_hant ...')
        if not dry:
            db.execute('ALTER TABLE geo_places ADD COLUMN name_zh_hant TEXT')
            db.commit()

    db_path = os.path.join(GEO_DIR, 'zh_altnames.sqlite')
    os.environ.setdefault('GEO_NAMES_ZIP_DIR', r'N:\项目\SV\geo')
    if zh_altnames_needs_rebuild(db_path):
        print('rebuilding zh_altnames.sqlite (dual hans/hant) ...')
        ensure_zh_altnames_db(download=True, rebuild=True)
    else:
        print('zh_altnames.sqlite already dual-column')

    # ---- step 3: sqlite 回填 ----
    import sqlite3
    conn = sqlite3.connect(db_path)
    db.execute(
        'CREATE TEMP TABLE zh_alt_import ('
        'geonameid BIGINT PRIMARY KEY, name_zh TEXT, name_zh_hant TEXT)')
    batch, total = [], 0
    for row in conn.execute('SELECT geonameid, name_zh, name_zh_hant FROM zh_names'):
        batch.append(row)
        if len(batch) >= 50000:
            db.executemany(
                'INSERT INTO zh_alt_import (geonameid, name_zh, name_zh_hant) '
                'VALUES (?, ?, ?) ON CONFLICT (geonameid) DO NOTHING', batch)
            total += len(batch)
            batch = []
            if not dry:
                db.commit()
            print(f'  loaded {total}', flush=True)
    if batch:
        db.executemany(
            'INSERT INTO zh_alt_import (geonameid, name_zh, name_zh_hant) '
            'VALUES (?, ?, ?) ON CONFLICT (geonameid) DO NOTHING', batch)
        total += len(batch)
    conn.close()
    if not dry:
        db.commit()
    print(f'sqlite names loaded: {total}')

    if not dry:
        cur = db.execute(
            '''UPDATE geo_places g
               SET name_zh = z.name_zh,
                   name_zh_hant = COALESCE(z.name_zh_hant, g.name_zh_hant)
               FROM zh_alt_import z
               WHERE g.source = 'geonames' AND g.source_id = z.geonameid::text
                 AND z.name_zh IS NOT NULL AND z.name_zh <> ''
                 AND (g.name_zh IS NULL OR g.name_zh = '' OR g.name_zh = g.name_en
                      OR (z.name_zh_hant IS NOT NULL AND g.name_zh = z.name_zh_hant))'''
        )
        print(f'name_zh from sqlite: {cur.rowcount}')
        cur = db.execute(
            '''UPDATE geo_places g
               SET name_zh_hant = z.name_zh_hant
               FROM zh_alt_import z
               WHERE g.source = 'geonames' AND g.source_id = z.geonameid::text
                 AND z.name_zh_hant IS NOT NULL AND z.name_zh_hant <> ''
                 AND g.name_zh_hant IS NULL'''
        )
        print(f'name_zh_hant from sqlite: {cur.rowcount}')
        db.commit()

    # ---- step 4: OpenCC 兜底 ----
    print('OpenCC pass: normalize name_zh -> simplified, fill name_zh_hant ...')
    last_id = 0
    changed = 0
    while True:
        rows = db.execute(
            '''SELECT id, name_zh, name_zh_hant FROM geo_places
               WHERE id > ? AND name_zh IS NOT NULL AND TRIM(name_zh) <> ''
               ORDER BY id LIMIT 50000''',
            (last_id,),
        ).fetchall()
        if not rows:
            break
        last_id = rows[-1]['id']
        updates = []
        for r in rows:
            zh = r['name_zh']
            simp = to_simplified(zh)
            hant = r['name_zh_hant'] or to_traditional(simp)
            if simp != zh or hant != r['name_zh_hant']:
                updates.append((simp, hant, r['id']))
        if updates and not dry:
            db.executemany(
                'UPDATE geo_places SET name_zh=?, name_zh_hant=? WHERE id=?', updates)
        changed += len(updates)
        if not dry:
            db.commit()
        print(f'  scanned to id={last_id}, changed={changed}', flush=True)
    print(f'OpenCC pass done: {changed} rows updated')

    for r in db.execute(
        '''SELECT level, COUNT(*) AS total,
                  COUNT(NULLIF(TRIM(name_zh),'')) AS hans,
                  COUNT(NULLIF(TRIM(name_zh_hant),'')) AS hant
           FROM geo_places GROUP BY level ORDER BY level'''
    ).fetchall():
        print(f"  L{r['level']} total={r['total']} hans={r['hans']} hant={r['hant']}")


if __name__ == '__main__':
    main()
