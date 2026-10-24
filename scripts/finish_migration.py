#!/usr/bin/env python3
"""迁移收尾：geo_registry 删 overrides 表；核对 moments_pro 状态。"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

import psycopg2


def _connect_db(cfg):
    return psycopg2.connect(
        host=cfg['host'],
        port=cfg['port'],
        dbname=cfg['name'],
        user=cfg['user'],
        password=cfg.get('password') or '',
    )


def main():
    geo_cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))['database']
    moments_cfg = json.load(open(os.path.join(PROJECT, 'config.json'), encoding='utf-8'))['database']

    print('=== geo_registry ===')
    gconn = _connect_db(geo_cfg)
    gconn.autocommit = True
    gcur = gconn.cursor()
    gcur.execute('SELECT COUNT(*) FROM geo_places')
    print('geo_places rows:', gcur.fetchone()[0])
    gcur.execute("SELECT to_regclass('public.geo_place_label_overrides')")
    overrides = gcur.fetchone()[0]
    print('geo_place_label_overrides:', overrides or '(none)')
    if overrides:
        gcur.execute('DROP TABLE geo_place_label_overrides')
        print('  -> dropped geo_place_label_overrides')
    gcur.execute(
        "SELECT setval(pg_get_serial_sequence('geo_places', 'id'), COALESCE((SELECT MAX(id) FROM geo_places), 1), true)"
    )
    print('geo_places id sequence synced')
    gconn.close()

    print('=== moments_pro ===')
    mconn = _connect_db(moments_cfg)
    mcur = mconn.cursor()
    for t in ('geo_places', 'ok_zh_level4', 'geo_place_label_overrides'):
        mcur.execute('SELECT to_regclass(%s)', (f'public.{t}',))
        print(f'{t}:', mcur.fetchone()[0] or '(gone)')
    mcur.execute(
        """
        SELECT conname FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'users' AND c.contype = 'f'
          AND pg_get_constraintdef(c.oid) LIKE '%geo_places%'
        """
    )
    fks = [r[0] for r in mcur.fetchall()]
    if fks:
        print('WARN users still has geo FK:', fks)
    else:
        print('users.location_place_id: no geo_places FK (OK)')
    mconn.close()
    print('done')


if __name__ == '__main__':
    main()
