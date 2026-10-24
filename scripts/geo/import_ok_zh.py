#!/usr/bin/env python3
"""从 ok_zh_level4 导入 geo_places（国内区划）。"""

from __future__ import annotations


def _ok_zh_parent_geo_id(db, ok_pid, ok_deep, ok_id_to_geo_id, ok_rows_by_id):
    if ok_deep == 0:
        return None
    parent_ok = ok_rows_by_id.get(ok_pid)
    if not parent_ok:
        return None
    if parent_ok['deep'] == -1:
        return None
    return ok_id_to_geo_id.get(ok_pid)


def import_ok_zh(db, selectable_max_deep=3):
    """
    从 ok_zh_level4 导入 geo_places。
    selectable_max_deep: 用户可选的最深 ok_zh deep（默认 3=街道/乡镇）。
    """
    rows = db.execute(
        'SELECT id, pid, deep, name, pinyin, ext_name FROM ok_zh_level4 WHERE deep >= 0 ORDER BY deep, id'
    ).fetchall()
    if not rows:
        print('  skip ok_zh: ok_zh_level4 表为空')
        return 0

    ok_rows_by_id = {r['id']: dict(r) for r in rows}
    ok_id_to_geo_id = {}
    inserted = 0

    for row in rows:
        row = dict(row)
        ok_id = row['id']
        deep = row['deep']
        level = deep + 2
        parent_id = _ok_zh_parent_geo_id(db, row['pid'], deep, ok_id_to_geo_id, ok_rows_by_id)
        name_zh = row['ext_name'] or row['name']
        sort_key = row.get('pinyin') or name_zh
        is_selectable = deep <= selectable_max_deep

        existing = db.execute(
            "SELECT id FROM geo_places WHERE source='ok_zh' AND source_id=?",
            (str(ok_id),),
        ).fetchone()
        cur = db.execute(
            '''INSERT INTO geo_places
               (parent_id, level, source, source_id, iso_country, name_zh, name_en, pinyin,
                deep_legacy, is_selectable, sort_key)
               VALUES (?, ?, 'ok_zh', ?, 'CN', ?, ?, ?, ?, ?, ?)
               ON CONFLICT (source, source_id) DO UPDATE SET
                 parent_id=EXCLUDED.parent_id,
                 level=EXCLUDED.level,
                 iso_country=EXCLUDED.iso_country,
                 name_zh=EXCLUDED.name_zh,
                 name_en=EXCLUDED.name_en,
                 pinyin=EXCLUDED.pinyin,
                 deep_legacy=EXCLUDED.deep_legacy,
                 is_selectable=EXCLUDED.is_selectable,
                 sort_key=EXCLUDED.sort_key
               RETURNING id''',
            (
                parent_id,
                level,
                str(ok_id),
                name_zh,
                row.get('name'),
                row.get('pinyin'),
                deep,
                is_selectable,
                sort_key,
            ),
        )
        geo_id = cur.lastrowid
        if geo_id is None:
            raise RuntimeError(f'ok_zh upsert failed for source_id={ok_id}')
        if not existing:
            inserted += 1
        ok_id_to_geo_id[ok_id] = geo_id

    db.commit()
    print(f'  ok_zh: {len(rows)} rows, {inserted} newly inserted')
    return len(rows)
