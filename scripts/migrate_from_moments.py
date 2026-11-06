#!/usr/bin/env python3
"""将 moments_pro 中的地理表复制到 geo_registry（保留 id，供多应用共用）。

表：geo_places → ok_zh_level4

用法:
    cd geotree
    python scripts/migrate_from_moments.py --dry-run
    python scripts/migrate_from_moments.py
    python scripts/migrate_from_moments.py --force   # 清空目标库后重导

完成后在 Moments 侧运行:
    cd backend
    python scripts/migrations/drop_local_geo_data.py --dry-run
    python scripts/migrations/drop_local_geo_data.py --vacuum
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

import psycopg2

from app.config import load_config as load_geo_config

MOMENTS_CONFIG_PATH = os.path.join(PROJECT_DIR, 'config.json')

GEO_TABLES = (
    'geo_places',
    'ok_zh_level4',
)


def _load_moments_db_cfg():
    import json

    if not os.path.isfile(MOMENTS_CONFIG_PATH):
        raise SystemExit(f'未找到 Moments 配置: {MOMENTS_CONFIG_PATH}')
    with open(MOMENTS_CONFIG_PATH, encoding='utf-8') as fh:
        raw = json.load(f)
    db = raw.get('database', {})
    return {
        'host': str(db.get('host') or '127.0.0.1'),
        'port': int(db.get('port') or 5432),
        'name': str(db.get('name') or 'moments_pro'),
        'user': str(db.get('user') or 'postgres'),
        'password': str(db.get('password') or ''),
    }


def _connect(cfg):
    return psycopg2.connect(
        host=cfg['host'],
        port=cfg['port'],
        dbname=cfg['name'],
        user=cfg['user'],
        password=cfg.get('password') or '',
    )


def _count(conn, table):
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    n = cur.fetchone()[0]
    cur.close()
    return n


def _table_exists(conn, table):
    cur = conn.cursor()
    cur.execute(
        'SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s LIMIT 1',
        ('public', table),
    )
    ok = cur.fetchone() is not None
    cur.close()
    return ok


def _truncate_dest(dst_conn, force):
    if not force:
        for t in GEO_TABLES:
            if _count(dst_conn, t) > 0:
                raise SystemExit(
                    f'目标库已有数据 ({t}={_count(dst_conn, t)})，请加 --force 清空后重导'
                )
        return
    cur = dst_conn.cursor()
    cur.execute('TRUNCATE ok_zh_level4, geo_places CASCADE')
    dst_conn.commit()
    cur.close()
    print('  已 TRUNCATE 目标库地理表')


def _copy_table_binary(src_conn, dst_conn, table):
    tmp_path = tempfile.mktemp(suffix=f'.{table}.copy')
    try:
        src_cur = src_conn.cursor()
        with open(tmp_path, 'wb') as fh:
            src_cur.copy_expert(f'COPY {table} TO STDOUT WITH (FORMAT binary)', fh)
        src_cur.close()

        dst_cur = dst_conn.cursor()
        with open(tmp_path, 'rb') as fh:
            dst_cur.copy_expert(f'COPY {table} FROM STDIN WITH (FORMAT binary)', fh)
        dst_conn.commit()
        dst_cur.close()
        print(f'  COPY {table} OK')
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _reset_sequence(dst_conn, table, col='id'):
    cur = dst_conn.cursor()
    cur.execute(f'SELECT COALESCE(MAX({col}), 0) FROM {table}')
    max_id = cur.fetchone()[0]
    seq = f'{table}_{col}_seq'
    cur.execute('SELECT 1 FROM pg_class WHERE relname = %s', (seq,))
    if cur.fetchone():
        cur.execute('SELECT setval(%s, %s, true)', (seq, max_id))
    dst_conn.commit()
    cur.close()
    print(f'  sequence {seq} -> {max_id}')


def _validate_users_place_ids(src_conn):
    """检查 moments 用户的 place_id 是否都在 geo_places 中。"""
    cur = src_conn.cursor()
    cur.execute(
        '''
        SELECT COUNT(*) FROM users u
        WHERE u.location_place_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM geo_places g WHERE g.id = u.location_place_id)
        '''
    )
    bad = cur.fetchone()[0]
    cur.close()
    return bad


def main():
    parser = argparse.ArgumentParser(description='moments_pro → geo_registry 地理表迁移')
    parser.add_argument('--dry-run', action='store_true', help='只统计行数')
    parser.add_argument('--force', action='store_true', help='清空 geo_registry 地理表后重导')
    parser.add_argument('--skip-ok-zh', action='store_true', help='不复制 ok_zh_level4')
    args = parser.parse_args()

    src_cfg = _load_moments_db_cfg()
    dst_cfg = load_geo_config().get('database', {})

    print('源库 moments:', f'{src_cfg["host"]}:{src_cfg["port"]}/{src_cfg["name"]}')
    print('目标 geo_registry:', f'{dst_cfg["host"]}:{dst_cfg["port"]}/{dst_cfg["name"]}')

    src_conn = _connect(src_cfg)
    dst_conn = _connect(dst_cfg)

    for t in GEO_TABLES:
        if args.skip_ok_zh and t == 'ok_zh_level4':
            continue
        if not _table_exists(src_conn, t):
            print(f'  源库缺少表 {t}，跳过')
            continue
        print(f'  {t}: src={_count(src_conn, t)}')

    bad_users = _validate_users_place_ids(src_conn)
    if bad_users:
        print(f'  WARN: {bad_users} 个用户的 location_place_id 在 geo_places 中不存在')

    if args.dry_run:
        src_conn.close()
        dst_conn.close()
        print('dry-run 完成')
        return

    # 确保目标 schema
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.db import ensure_geo_places_schema, get_db

        ensure_geo_places_schema(get_db())

    _truncate_dest(dst_conn, args.force)

    tables_to_copy = [t for t in GEO_TABLES if not (args.skip_ok_zh and t == 'ok_zh_level4')]
    for table in tables_to_copy:
        if not _table_exists(src_conn, table):
            continue
        _copy_table_binary(src_conn, dst_conn, table)

    if _table_exists(dst_conn, 'geo_places'):
        _reset_sequence(dst_conn, 'geo_places', 'id')

    for table in tables_to_copy:
        src_n = _count(src_conn, table) if _table_exists(src_conn, table) else 0
        dst_n = _count(dst_conn, table) if _table_exists(dst_conn, table) else 0
        if src_n != dst_n:
            raise SystemExit(f'验收失败: {table} src={src_n} dst={dst_n}')
        print(f'  validate {table}: {dst_n} rows')

    src_conn.close()
    dst_conn.close()
    print('迁移完成。请验证 Geo 服务 /health 后，运行 backend/scripts/migrations/drop_local_geo_data.py 释放 moments 空间。')


if __name__ == '__main__':
    main()
