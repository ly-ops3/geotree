#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""name_base 存量回填：
- ok_zh：name_base ← name_en（现存的专名），name_en 置 NULL（它本不该放中文）
- geonames：name_base ← name_zh 剥掉已知通名后缀；剥不出留 NULL（本就是裸名）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.pg import connect_pg
from app.geo.admin_terms import strip_known_term


def main():
    db = connect_pg()

    # ok_zh: name_en 里存的是专名，搬到 name_base，name_en 清空
    n1 = db.execute(
        """UPDATE geo_places SET name_base=name_en, name_en=NULL
           WHERE source='ok_zh' AND name_en IS NOT NULL AND name_en<>''"""
    ).rowcount
    db.commit()
    print(f'ok_zh: moved proper name to name_base, nulled name_en: {n1}')

    # geonames: name_zh 剥通名
    # geonames: 先清空再重剥（修正音译撞通名误剥）
    db.execute("UPDATE geo_places SET name_base=NULL WHERE source='geonames'")
    rows = db.execute(
        """SELECT id, iso_country, name_zh FROM geo_places
           WHERE source='geonames' AND name_zh IS NOT NULL AND name_zh<>''"""
    ).fetchall()
    n2 = 0
    for r in rows:
        base = strip_known_term(r['name_zh'], r['iso_country'])
        if base:
            db.execute('UPDATE geo_places SET name_base=? WHERE id=?', (base, r['id']))
            n2 += 1
    db.commit()
    print(f'geonames: stripped term -> name_base: {n2}')

    c = db.execute("SELECT COUNT(*) c FROM geo_places WHERE name_base IS NOT NULL AND name_base<>''").fetchone()
    print('name_base total:', c['c'])


if __name__ == '__main__':
    main()
