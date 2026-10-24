#!/usr/bin/env python3
"""终止卡死的 geo_places 相关 PG 会话（不动业务表数据）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import create_app
from app.db import get_db

LOCK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'database',
    'geo',
    '.geo_import.lock',
)


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        zombies = db.execute(
            '''SELECT pid, left(query, 120) AS q, now() - query_start AS dur
               FROM pg_stat_activity
               WHERE datname = current_database()
                 AND pid <> pg_backend_pid()
                 AND state = 'active'
                 AND query ILIKE '%geo_places%'
               ORDER BY query_start'''
        ).fetchall()
        if not zombies:
            print('no active geo_places queries')
        for row in zombies:
            pid = row['pid']
            print(f'terminate pid={pid} dur={row["dur"]} q={row["q"]!r}')
            db.execute('SELECT pg_terminate_backend(?)', (pid,))
        db.commit()

    if os.path.isfile(LOCK_PATH):
        os.remove(LOCK_PATH)
        print(f'removed stale lock: {LOCK_PATH}')


if __name__ == '__main__':
    main()
