"""数据库连接与 geo 表 schema。"""

import os

from flask import g

from app.config import BASE_DIR
from app.database.pg import connect_pg

SCHEMA_PG_PATH = os.path.join(BASE_DIR, 'database', 'schema.postgresql.sql')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_pg()
    return db


def _table_exists(db, name):
    row = db.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def apply_schema(db):
    if _table_exists(db, 'geo_places'):
        return False
    if not os.path.isfile(SCHEMA_PG_PATH):
        raise FileNotFoundError(f'缺少 schema: {SCHEMA_PG_PATH}')
    with open(SCHEMA_PG_PATH, encoding='utf-8') as fh:
        db.executescript(fh.read())
    db.commit()
    return True


def ensure_geo_places_schema(db):
    """确保 geo 字典表存在（导入脚本与启动时调用）。"""
    if not _table_exists(db, 'geo_places'):
        apply_schema(db)
        return
    if not _table_exists(db, 'ok_zh_level4'):
        db.execute(
            '''CREATE TABLE ok_zh_level4 (
                id INTEGER PRIMARY KEY,
                pid INTEGER,
                deep INTEGER NOT NULL,
                name TEXT,
                pinyin_prefix TEXT,
                pinyin TEXT,
                ext_name TEXT NOT NULL
            )'''
        )
        db.commit()
    _ensure_geo_places_unique(db)


def _ensure_geo_places_unique(db):
    if not _table_exists(db, 'geo_places'):
        return
    try:
        row = db.execute(
            '''SELECT 1 FROM pg_constraint c
               JOIN pg_class t ON c.conrelid = t.oid
               WHERE t.relname = 'geo_places' AND c.contype = 'u'
                 AND pg_get_constraintdef(c.oid) LIKE '%source%source_id%'
               LIMIT 1'''
        ).fetchone()
    except Exception:
        return
    if row:
        return
    dup = db.execute(
        '''SELECT source, source_id, COUNT(*) AS n FROM geo_places
           GROUP BY source, source_id HAVING COUNT(*) > 1 LIMIT 1'''
    ).fetchone()
    if dup:
        raise RuntimeError(
            f'geo_places 存在重复键 source={dup["source"]} source_id={dup["source_id"]}'
        )
    db.execute(
        'ALTER TABLE geo_places ADD CONSTRAINT geo_places_source_source_id_key UNIQUE (source, source_id)'
    )
    db.commit()
