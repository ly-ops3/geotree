#!/usr/bin/env python3
"""GeoNames 全球汉化修复（按国家参数）。

geo_places 在 geotree 库，请在本目录运行：
  cd geotree
  python -u scripts/geo/fix_geonames_name_zh.py --country ALL --wikipedia
  python -u scripts/geo/fix_geonames_name_zh.py --country US,CA,AU
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings

os.environ['PYTHONUNBUFFERED'] = '1'
warnings.filterwarnings('ignore', module='requests')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import create_app
from app.config import get_database_config
from app.db import ensure_geo_places_schema, get_db
from app.geo.geonames_zh_fixup import run_fixup


def _log(msg: str) -> None:
    print(msg, flush=True)


def _parse_countries(raw: str) -> list[str]:
    raw = (raw or 'US').strip()
    if raw.upper() == 'ALL':
        return ['ALL']
    return [c.strip().upper() for c in raw.split(',') if c.strip()]


def main():
    parser = argparse.ArgumentParser(description='GeoNames 中文名修复（按国家）')
    parser.add_argument(
        '--country',
        default='US',
        help='ISO2 国家码，逗号分隔，或 ALL（默认 US）',
    )
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写库')
    parser.add_argument('--skip-clear', action='store_true', help='跳过全局清除上级误填')
    parser.add_argument('--skip-wikidata', action='store_true', help='跳过 Wikidata')
    parser.add_argument('--skip-altnames', action='store_true', help='跳过 alternateNames')
    parser.add_argument(
        '--wikipedia',
        action='store_true',
        help='启用维基批量补全（慢，建议 --country 分批或 ALL 过夜跑）',
    )
    parser.add_argument('--skip-rule', action='store_true', help='跳过英文规则音译')
    parser.add_argument('--wikipedia-limit', type=int, default=None, help='每国维基上限（调试）')
    args = parser.parse_args()

    countries = _parse_countries(args.country)
    db_cfg = get_database_config()
    _log(f'连接 {db_cfg.get("host")}:{db_cfg.get("port")}/{db_cfg.get("name")} ...')

    app = create_app()
    with app.app_context():
        db = get_db()
        _log('数据库已连接')
        row = db.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=? LIMIT 1",
            ('geo_places',),
        ).fetchone()
        if not row:
            ensure_geo_places_schema(db)
        if not db.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=? LIMIT 1",
            ('geo_places',),
        ).fetchone():
            raise SystemExit('geo_places 不存在，请先 import_all.py')

        t0 = time.time()
        stats = run_fixup(
            db,
            countries=countries,
            dry_run=args.dry_run,
            skip_global_clear=args.skip_clear,
            skip_wikidata=args.skip_wikidata,
            skip_altnames=args.skip_altnames,
            skip_wikipedia=not args.wikipedia,
            skip_rule=args.skip_rule,
            wikipedia_limit=args.wikipedia_limit,
        )
        _log('')
        _log('JSON 汇总:')
        print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
        _log(f'退出 ({time.time() - t0:.1f}s)')


if __name__ == '__main__':
    main()
