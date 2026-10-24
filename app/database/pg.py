"""PostgreSQL 连接包装（sqlite3 风格 execute/fetch）。"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from app.config import get_database_config


class PGRow(dict):
    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        super().__init__(zip(keys, values))
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class PGCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return PGRow([d[0] for d in self._cursor.description], row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        keys = [d[0] for d in self._cursor.description]
        return [PGRow(keys, row) for row in rows]

    def __iter__(self):
        keys = [d[0] for d in self._cursor.description] if self._cursor.description else []
        for row in self._cursor:
            yield PGRow(keys, row)


class PGConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        adapted, params = adapt_sql_and_params(sql, params)
        cur = self._conn.cursor()
        cur.execute(adapted, tuple(params or ()))

        lastrowid = None
        upper = adapted.strip().upper()
        if upper.startswith('INSERT') and 'RETURNING' in upper:
            row = cur.fetchone()
            if row:
                lastrowid = row[0]
        return PGCursor(cur, lastrowid)

    def executemany(self, sql: str, seq_of_params):
        adapted, _ = adapt_sql_and_params(sql, ())
        cur = self._conn.cursor()
        cur.executemany(adapted, [tuple(p) for p in seq_of_params])
        return PGCursor(cur)

    def executescript(self, script: str):
        cur = self._conn.cursor()
        for stmt in split_sql_script(script):
            if not stmt.strip():
                continue
            adapted, _ = adapt_sql_and_params(stmt, ())
            cur.execute(adapted)
        return PGCursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


TABLES_WITH_RETURNING_ID = frozenset({
    'geo_places',
})


def _insert_table_name(sql: str):
    m = re.search(r'INSERT\s+INTO\s+"?(\w+)"?', sql, re.IGNORECASE)
    return m.group(1).lower() if m else None


def split_sql_script(script: str):
    parts = []
    buf = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        buf.append(line)
        if ';' in line:
            parts.append('\n'.join(buf))
            buf = []
    if buf:
        parts.append('\n'.join(buf))
    return parts


def adapt_sql_and_params(sql: str, params: Iterable[Any] | None = None):
    params = list(params or ())
    text = sql

    text = re.sub(
        r'INSERT\s+OR\s+IGNORE\s+INTO',
        'INSERT INTO',
        text,
        flags=re.IGNORECASE,
    )

    if 'last_insert_rowid()' in text.lower():
        raise ValueError('last_insert_rowid() is not supported on PostgreSQL; use RETURNING id')

    upper = text.strip().upper()
    if upper.startswith('INSERT') and 'RETURNING' not in upper:
        tbl = _insert_table_name(text)
        if tbl in TABLES_WITH_RETURNING_ID and ' ON CONFLICT ' not in upper:
            text = text.rstrip().rstrip(';') + ' RETURNING id'

    if '?' in text:
        text = text.replace('?', '%s')

    text = _escape_literal_percent(text)
    return text, params


def _escape_literal_percent(sql: str) -> str:
    out = []
    i = 0
    n = len(sql)
    while i < n:
        if sql[i:i + 2] == '%s':
            out.append('%s')
            i += 2
        elif sql[i] == '%':
            out.append('%%')
            i += 1
        else:
            out.append(sql[i])
            i += 1
    return ''.join(out)


def connect_pg():
    cfg = get_database_config()
    conn = psycopg2.connect(
        host=cfg['host'],
        port=cfg['port'],
        dbname=cfg['name'],
        user=cfg['user'],
        password=cfg.get('password') or '',
    )
    conn.autocommit = False
    psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
    return PGConnection(conn)
