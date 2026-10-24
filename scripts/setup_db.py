#!/usr/bin/env python3
"""创建 geo_registry PostgreSQL 数据库（若不存在）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

from app.config import load_config


def main():
    cfg = load_config().get('database', {})
    host = cfg.get('host', '127.0.0.1')
    port = int(cfg.get('port') or 5432)
    user = cfg.get('user', 'postgres')
    password = cfg.get('password') or ''
    name = cfg.get('name', 'geo_registry')

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname='postgres')
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
    if cur.fetchone():
        print(f'Database {name!r} already exists')
    else:
        cur.execute(f'CREATE DATABASE {name}')
        print(f'Created database {name!r}')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
