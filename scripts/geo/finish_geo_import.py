#!/usr/bin/env python3
"""geo 导入收尾：批量汉化 + 确认索引 + 验收（不重建 geonames 数据）。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from app import create_app
from app.db import get_db
from import_all import validate_geo_places
from import_geonames import _finish_fast_import

LOCK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'database',
    'geo',
    '.geo_import.lock',
)

EXPECTED_INDEXES = (
    'idx_geo_places_parent',
    'idx_geo_places_iso_country',
    'idx_geo_places_name_zh',
    'idx_geo_places_admin1',
)


def _report(db):
    total = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
    idx = [
        r['indexname']
        for r in db.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='geo_places'"
        ).fetchall()
    ]
    missing_idx = [n for n in EXPECTED_INDEXES if n not in idx]
    gn = db.execute("SELECT COUNT(*) AS c FROM geo_places WHERE source='geonames'").fetchone()['c']
    need_zh = db.execute(
        """SELECT COUNT(*) AS c FROM geo_places
           WHERE source='geonames'
             AND (name_zh IS NULL OR name_zh = '' OR name_zh = name_en)"""
    ).fetchone()['c']
    print(f'  total={total}, geonames={gn}, geonames_need_zh={need_zh}')
    print(f'  indexes missing: {missing_idx or "none"}')
    return missing_idx, need_zh


def main():
    parser = argparse.ArgumentParser(description='geo 导入收尾（汉化+索引+验收）')
    parser.add_argument('--skip-zh', action='store_true', help='跳过批量汉化')
    parser.add_argument('--skip-validate', action='store_true', help='跳过验收')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()
        print('Before:')
        missing_idx, need_zh = _report(db)

        if not args.skip_zh and need_zh > 0:
            print('Running batch zh names + index ensure ...')
            _finish_fast_import(db)
        elif missing_idx:
            print('Ensuring indexes only ...')
            _finish_fast_import(db)
        else:
            print('Indexes OK; skip zh batch' if args.skip_zh else 'No zh work needed')

        print('After:')
        _report(db)

        if not args.skip_validate:
            print('Validating ...')
            validate_geo_places(db, expect_natural=True)

    if os.path.isfile(LOCK_PATH):
        try:
            os.remove(LOCK_PATH)
            print(f'Removed stale lock: {LOCK_PATH}')
        except OSError as exc:
            print(f'WARN: could not remove lock: {exc}')

    print('Finish complete.')


if __name__ == '__main__':
    main()
