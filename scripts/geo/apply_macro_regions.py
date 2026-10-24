#!/usr/bin/env python3
"""增量插入地理大区并重挂一级行政区 parent_id（仅 geo_places，不 TRUNCATE）。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import create_app
from app.db import get_db
from app.geo.macro_regions import (
    CN_MACRO_PROVINCES,
    LEVEL_MACRO,
    MACRO_COUNTRIES,
    SOURCE_MACRO,
    admin1_to_macro_key,
    cn_province_to_macro_key,
    country_macros,
    macro_source_id,
)

LEVEL_ADM1 = 2
LEVEL_COUNTRY = 1


def _upsert_macro(db, *, parent_id, iso2, macro_key, name_zh, name_en, sort_key, dry_run):
    sid = macro_source_id(iso2, macro_key)
    if dry_run:
        print(f'  [dry] macro {sid} parent={parent_id} {name_zh}')
        row = db.execute(
            "SELECT id FROM geo_places WHERE source=? AND source_id=?",
            (SOURCE_MACRO, sid),
        ).fetchone()
        return row['id'] if row else -1
    if iso2 == 'CN':
        name_local, name_local_lang = name_zh, 'zh'
    elif iso2 == 'US':
        name_local, name_local_lang = name_en, 'en'
    else:
        # 日本大区目前只有中文译名和罗马字，不是假名，不假装它是当地名称。
        name_local, name_local_lang = None, None
    cur = db.execute(
        '''INSERT INTO geo_places
           (parent_id, level, source, source_id, iso_country, name_zh, name_en,
            name_local, name_local_lang, is_selectable, sort_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET
             parent_id=EXCLUDED.parent_id,
             level=EXCLUDED.level,
             iso_country=EXCLUDED.iso_country,
             name_zh=EXCLUDED.name_zh,
             name_en=EXCLUDED.name_en,
             name_local=COALESCE(EXCLUDED.name_local, geo_places.name_local),
             name_local_lang=COALESCE(EXCLUDED.name_local_lang, geo_places.name_local_lang),
             is_selectable=EXCLUDED.is_selectable,
             sort_key=EXCLUDED.sort_key
           RETURNING id''',
        (
            parent_id, LEVEL_MACRO, SOURCE_MACRO, sid, iso2, name_zh, name_en,
            name_local, name_local_lang, sort_key,
        ),
    )
    geo_id = cur.lastrowid
    if geo_id is None:
        raise RuntimeError(f'macro upsert failed: {sid}')
    return geo_id


def _country_place_id(db, iso2: str):
    row = db.execute(
        '''SELECT id FROM geo_places
           WHERE source='geonames' AND iso_country=? AND level=?
           ORDER BY id LIMIT 1''',
        (iso2.upper(), LEVEL_COUNTRY),
    ).fetchone()
    return row['id'] if row else None


def _apply_country_macros(db, iso2: str, *, dry_run: bool) -> dict[str, int]:
    iso2 = iso2.upper()
    macro_ids: dict[str, int] = {}
    parent_id = _country_place_id(db, iso2)
    if parent_id is None:
        raise SystemExit(f'未找到国家节点: {iso2} (geonames level=1)')
    for macro_key, name_zh, name_en, sort_key in country_macros(iso2):
        macro_ids[macro_key] = _upsert_macro(
            db,
            parent_id=parent_id,
            iso2=iso2,
            macro_key=macro_key,
            name_zh=name_zh,
            name_en=name_en,
            sort_key=sort_key,
            dry_run=dry_run,
        )
    return macro_ids


def _reparent_cn_provinces(db, macro_ids: dict[str, int], *, dry_run: bool) -> tuple[int, list]:
    rows = db.execute(
        '''SELECT id, name_zh, source_id FROM geo_places
           WHERE source='ok_zh' AND level=? AND deep_legacy=0''',
        (LEVEL_ADM1,),
    ).fetchall()
    updated = 0
    unmapped = []
    for row in rows:
        key = cn_province_to_macro_key(row['name_zh'])
        if not key:
            unmapped.append(dict(row))
            continue
        mid = macro_ids.get(key)
        if mid is None:
            unmapped.append(dict(row))
            continue
        if dry_run:
            print(f'  [dry] ok_zh {row["name_zh"]} -> macro {key}')
        else:
            db.execute('UPDATE geo_places SET parent_id=? WHERE id=?', (mid, row['id']))
        updated += 1
    return updated, unmapped


def _reparent_geonames_admin1(db, iso2: str, macro_ids: dict[str, int], *, dry_run: bool) -> tuple[int, list]:
    iso2 = iso2.upper()
    rows = db.execute(
        '''SELECT id, admin1_code, name_en, name_zh FROM geo_places
           WHERE source='geonames' AND iso_country=? AND level=?''',
        (iso2, LEVEL_ADM1),
    ).fetchall()
    updated = 0
    unmapped = []
    for row in rows:
        code = row['admin1_code'] or ''
        suffix = code.split('.', 1)[-1] if '.' in code else code
        key = admin1_to_macro_key(iso2, suffix)
        if not key:
            unmapped.append(dict(row))
            continue
        mid = macro_ids.get(key)
        if mid is None:
            unmapped.append(dict(row))
            continue
        if dry_run:
            print(f'  [dry] {code} -> macro {key}')
        else:
            db.execute('UPDATE geo_places SET parent_id=? WHERE id=?', (mid, row['id']))
        updated += 1
    return updated, unmapped


def _ensure_macro_index(db, *, dry_run: bool):
    if dry_run:
        print('  [dry] CREATE INDEX idx_geo_places_macro_source ...')
        return
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_geo_places_macro_source '
        "ON geo_places (iso_country, sort_key) WHERE source = 'macro'"
    )


def main():
    parser = argparse.ArgumentParser(description='应用地理大区映射（CN/US/JP）')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划，不写库')
    parser.add_argument('--countries', default='CN,US,JP', help='逗号分隔 ISO2，默认 CN,US,JP')
    args = parser.parse_args()
    countries = [c.strip().upper() for c in args.countries.split(',') if c.strip()]
    for c in countries:
        if c not in MACRO_COUNTRIES:
            parser.error(f'暂不支持大区: {c}，已登记: {sorted(MACRO_COUNTRIES)}')

    app = create_app()
    with app.app_context():
        db = get_db()
        print(f'apply macro regions (dry_run={args.dry_run}) ...')
        total_macros = 0
        total_reparent = 0
        all_unmapped = []

        for iso2 in countries:
            print(f'--- {iso2} ---')
            macro_ids = _apply_country_macros(db, iso2, dry_run=args.dry_run)
            total_macros += len(macro_ids)
            if iso2 == 'CN':
                n, unmapped = _reparent_cn_provinces(db, macro_ids, dry_run=args.dry_run)
            else:
                n, unmapped = _reparent_geonames_admin1(db, iso2, macro_ids, dry_run=args.dry_run)
            total_reparent += n
            all_unmapped.extend([(iso2, u) for u in unmapped])
            print(f'  macros={len(macro_ids)}, reparented={n}, unmapped={len(unmapped)}')

        _ensure_macro_index(db, dry_run=args.dry_run)
        if not args.dry_run:
            db.commit()
        print(f'Done. macros={total_macros}, reparented={total_reparent}')
        if all_unmapped:
            print('WARN unmapped:')
            for iso2, u in all_unmapped[:30]:
                label = u.get('name_zh') or u.get('admin1_code') or u.get('name_en')
                print(f'  {iso2}: {label}')
            if len(all_unmapped) > 30:
                print(f'  ... and {len(all_unmapped) - 30} more')


if __name__ == '__main__':
    main()
