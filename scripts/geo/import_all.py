#!/usr/bin/env python3
"""一键导入 geo_places（审定方案：ok_zh + 国外 ADM/PPL + 中国对照 + 可选自然地理）。

清理 geonames 仅用脚本内 DELETE；禁止 TRUNCATE geo_places CASCADE。
"""

from __future__ import annotations

import argparse
import atexit
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from app import create_app
from app.db import ensure_geo_places_schema, get_db
from import_geonames import GEO_DIR, _finish_fast_import, _prepare_fast_import, import_china_geonames, import_geonames
from import_ok_zh import import_ok_zh

LOCK_PATH = os.path.join(GEO_DIR, '.geo_import.lock')


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_import_lock():
    os.makedirs(GEO_DIR, exist_ok=True)
    if os.path.isfile(LOCK_PATH):
        try:
            with open(LOCK_PATH, encoding='utf-8') as fh:
                old_pid = int((fh.read() or '0').strip())
        except (ValueError, OSError):
            old_pid = 0
        if old_pid and _pid_alive(old_pid):
            raise SystemExit(
                f'已有 geo 导入进程在运行 (pid={old_pid})。请等待结束或删除锁文件：{LOCK_PATH}'
            )
        try:
            os.remove(LOCK_PATH)
        except OSError:
            pass
    with open(LOCK_PATH, 'w', encoding='utf-8') as fh:
        fh.write(str(os.getpid()))


def release_import_lock():
    try:
        if os.path.isfile(LOCK_PATH):
            with open(LOCK_PATH, encoding='utf-8') as fh:
                if fh.read().strip() == str(os.getpid()):
                    os.remove(LOCK_PATH)
    except OSError:
        pass


def validate_geo_places(db, *, expect_natural: bool) -> None:
    dup = db.execute(
        '''SELECT source, source_id, COUNT(*) AS n FROM geo_places
           GROUP BY source, source_id HAVING COUNT(*) > 1 LIMIT 1'''
    ).fetchone()
    if dup:
        raise SystemExit(
            f'验收失败：重复键 source={dup["source"]} source_id={dup["source_id"]} n={dup["n"]}'
        )

    total = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
    if total < 3_000_000 or total > 7_000_000:
        raise SystemExit(f'验收失败：总行数 {total} 不在预期 300万–700万')

    level8 = db.execute('SELECT COUNT(*) AS c FROM geo_places WHERE level = 8').fetchone()['c']
    if expect_natural:
        if level8 < 10_000:
            raise SystemExit(f'验收失败：level=8 自然地理仅 {level8} 行（预期约 4 万+）')
    elif level8 > 0:
        raise SystemExit(f'验收失败：不应有 level=8，当前 {level8}')

    s_count = db.execute(
        """SELECT COUNT(*) AS c FROM geo_places
           WHERE level = 8 AND admin2_code LIKE 'S.%'"""
    ).fetchone()['c']
    if s_count > 0:
        raise SystemExit(f'验收失败：level=8 含人工设施 S.* 共 {s_count} 行')

    print(f'  validate OK: total={total}, level8={level8}')


def main():
    parser = argparse.ArgumentParser(description='导入 geo_places 地理字典（审定方案）')
    parser.add_argument('--profile', choices=('standard',), help='standard=ok_zh+国外重建+中国lite+自然')
    parser.add_argument('--skip-geonames', action='store_true', help='不导入/重建国外 GeoNames')
    parser.add_argument('--import-china-only', action='store_true', help='仅导入 GeoNames 中国对照层')
    parser.add_argument('--no-download', action='store_true', help='GeoNames 不自动下载')
    parser.add_argument('--rebuild-geonames', action='store_true', help='删除现有 geonames 后重建国外')
    parser.add_argument(
        '--china-natural',
        action='store_true',
        help='中国对照层额外导入自然地理 H/T/L/V（约 4.5 万行）',
    )
    parser.add_argument(
        '--china-full-gazetteer',
        action='store_true',
        help='中国 allCountries 全 feature（不推荐，含酒店车站等）',
    )
    parser.add_argument('--selectable-deep', type=int, default=3, help='国内 ok_zh 可选最深 deep（默认 3=街道）')
    parser.add_argument('--skip-ok-zh', action='store_true', help='跳过 ok_zh 刷新')
    parser.add_argument('--skip-validate', action='store_true', help='跳过导入后验收')
    args = parser.parse_args()

    if args.profile == 'standard':
        args.rebuild_geonames = True
        args.china_natural = True
        if args.import_china_only:
            parser.error('--profile standard 不可与 --import-china-only 同用')

    acquire_import_lock()
    atexit.register(release_import_lock)

    app = create_app()
    with app.app_context():
        db = get_db()
        ensure_geo_places_schema(db)

        download = not args.no_download
        expect_natural = False

        if args.import_china_only:
            print('Import GeoNames China (lite + optional natural) → geo_places ...')
            import_china_geonames(
                db,
                download=download,
                rebuild_china=True,
                include_natural=args.china_natural,
                full_gazetteer=args.china_full_gazetteer,
            )
            expect_natural = args.china_natural and not args.china_full_gazetteer
        else:
            if not args.skip_ok_zh:
                print('Import ok_zh_level4 → geo_places ...', flush=True)
                import_ok_zh(db, selectable_max_deep=args.selectable_deep)
            fast = args.profile == 'standard'
            if fast:
                _prepare_fast_import(db)
            if not args.skip_geonames:
                print('Import GeoNames abroad (ADM + full PPL) → geo_places ...', flush=True)
                import_geonames(
                    db,
                    download=download,
                    rebuild=args.rebuild_geonames,
                    fast=fast,
                    defer_finish=fast,
                )
            if args.profile == 'standard':
                print('Import GeoNames China (lite + natural) → geo_places ...', flush=True)
                import_china_geonames(
                    db,
                    download=download,
                    rebuild_china=True,
                    include_natural=True,
                    full_gazetteer=False,
                    fast=fast,
                )
                expect_natural = True
            if fast:
                _finish_fast_import(db)

        count = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
        cn = db.execute(
            "SELECT COUNT(*) AS c FROM geo_places WHERE source='geonames' AND iso_country='CN'"
        ).fetchone()['c']
        print(f'Done. geo_places total={count}, geonames_CN={cn}')

        if not args.skip_validate and (args.profile == 'standard' or args.import_china_only):
            validate_geo_places(db, expect_natural=expect_natural)


if __name__ == '__main__':
    main()
