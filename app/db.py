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


def _column_exists(db, table, column):
    row = db.execute(
        '''SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
           LIMIT 1''',
        (table, column),
    ).fetchone()
    return row is not None


def _ensure_local_name_schema(db):
    """已有库补上语种表、name_local_lang、多语言名称表。新库的 canonical DDL 已包含。"""
    db.execute(
        '''CREATE TABLE IF NOT EXISTS geo_languages (
            code TEXT PRIMARY KEY,
            iso639 TEXT NOT NULL,
            name_en TEXT
        )'''
    )
    if _table_exists(db, 'geo_places') and not _column_exists(db, 'geo_places', 'name_local_lang'):
        db.execute('ALTER TABLE geo_places ADD COLUMN name_local_lang TEXT')
    if _table_exists(db, 'geo_places') and not _column_exists(db, 'geo_places', 'name_zh_hant'):
        db.execute('ALTER TABLE geo_places ADD COLUMN name_zh_hant TEXT')
    if _table_exists(db, 'geo_places') and not _column_exists(db, 'geo_places', 'feature_class'):
        db.execute('ALTER TABLE geo_places ADD COLUMN feature_class CHAR(1)')
    if _table_exists(db, 'geo_places') and not _column_exists(db, 'geo_places', 'feature_code'):
        db.execute('ALTER TABLE geo_places ADD COLUMN feature_code TEXT')
    if _table_exists(db, 'geo_places') and not _column_exists(db, 'geo_places', 'name_base'):
        db.execute('ALTER TABLE geo_places ADD COLUMN name_base TEXT')
        db.execute('CREATE INDEX IF NOT EXISTS idx_geo_places_name_base ON geo_places(name_base)')
    db.execute(
        '''CREATE TABLE IF NOT EXISTS geo_place_names (
            place_id BIGINT NOT NULL REFERENCES geo_places(id) ON DELETE CASCADE,
            lang_code TEXT NOT NULL REFERENCES geo_languages(code),
            name TEXT NOT NULL,
            is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (place_id, lang_code)
        )'''
    )
    fk = db.execute(
        '''SELECT 1
           FROM pg_constraint c
           JOIN pg_class t ON c.conrelid = t.oid
           JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
           WHERE t.relname = 'geo_places'
             AND a.attname = 'name_local_lang'
             AND c.contype = 'f'
           LIMIT 1'''
    ).fetchone()
    if not fk and _column_exists(db, 'geo_places', 'name_local_lang'):
        db.execute(
            '''ALTER TABLE geo_places
               ADD CONSTRAINT geo_places_name_local_lang_fkey
               FOREIGN KEY (name_local_lang) REFERENCES geo_languages(code)'''
        )
    db.execute(
        '''INSERT INTO geo_languages (code, iso639, name_en) VALUES
           ('zh', 'zh', 'Chinese'),
           ('en', 'en', 'English')
           ON CONFLICT (code) DO NOTHING'''
    )
    db.commit()


def ensure_geo_places_schema(db):
    """确保 geo 字典表存在（导入脚本与启动时调用）。"""
    if not _table_exists(db, 'geo_places'):
        apply_schema(db)
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
    _ensure_local_name_schema(db)


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
