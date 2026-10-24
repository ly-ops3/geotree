"""GeoNames 中文地名解析：CLDR 行政区 + alternateNames/zh 别名表。"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile
from urllib.request import urlretrieve

from app.config import get_geo_dir

GEO_DIR = get_geo_dir()
GEONAMES_BASE = 'https://download.geonames.org/export/dump'
CLDR_SUBDIVISIONS_URL = (
    'https://raw.githubusercontent.com/unicode-org/cldr-json/main/'
    'cldr-json/cldr-subdivisions-full/subdivisions/zh/zh.json'
)

_cldr_admin1: dict[str, str] | None = None
_zh_sqlite_path: str | None = None


def _ensure_geo_dir():
    os.makedirs(GEO_DIR, exist_ok=True)


def _cldr_key_to_geonames(cldr_key: str) -> str | None:
    """CLDR 键 → GeoNames admin1 码（usca / US-CA → US.CA）。"""
    key = (cldr_key or '').strip()
    if not key or key.endswith('-alt-variant'):
        return None
    if '-' in key:
        iso, rest = key.split('-', 1)
        if len(iso) == 2 and rest:
            return f'{iso.upper()}.{rest.upper()}'
        return None
    if len(key) >= 3:
        return f'{key[:2].upper()}.{key[2:].upper()}'
    return None


def _load_cldr_admin1() -> dict[str, str]:
    global _cldr_admin1
    if _cldr_admin1 is not None:
        return _cldr_admin1
    _ensure_geo_dir()
    cache_path = os.path.join(GEO_DIR, 'cldr_subdivisions_zh.json')
    if not os.path.isfile(cache_path) or os.path.getsize(cache_path) < 100:
        print('  downloading CLDR subdivisions (zh) ...')
        try:
            urlretrieve(CLDR_SUBDIVISIONS_URL, cache_path)
        except Exception as exc:
            print(f'  WARN: CLDR download failed ({exc}); admin1 仅用手工表')
            _cldr_admin1 = {}
            return _cldr_admin1
    with open(cache_path, encoding='utf-8') as fh:
        raw = json.load(fh)
    subdivisions = (
        raw.get('subdivisions', {})
        .get('localeDisplayNames', {})
        .get('subdivisions', {})
    )
    if not subdivisions:
        subdivisions = (
            raw.get('main', {})
            .get('zh', {})
            .get('localeDisplayNames', {})
            .get('subdivisions', {})
        )
    mapping: dict[str, str] = {}
    for cldr_key, name in subdivisions.items():
        if not name:
            continue
        gn_key = _cldr_key_to_geonames(cldr_key)
        if gn_key:
            mapping[gn_key] = name
    _cldr_admin1 = mapping
    print(f'  CLDR admin1 loaded: {len(mapping)} entries')
    return mapping


def admin1_name_zh(admin1_code: str | None) -> str | None:
    from app.geo.admin1_zh import ADMIN1_ZH

    key = (admin1_code or '').upper()
    if not key:
        return None
    if key in ADMIN1_ZH:
        return ADMIN1_ZH[key]
    cldr = _load_cldr_admin1()
    return cldr.get(key)


def _build_zh_altnames_sqlite(zip_path: str, db_path: str) -> None:
    """从 alternateNames.zip 流式筛选 zh/zh-CN 构建 geonameid 索引 sqlite。"""
    if os.path.isfile(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        'CREATE TABLE zh_names (geonameid INTEGER PRIMARY KEY, name_zh TEXT NOT NULL, preferred INTEGER NOT NULL DEFAULT 0)'
    )
    conn.execute('PRAGMA journal_mode=OFF')
    conn.execute('PRAGMA synchronous=OFF')
    zh_langs = frozenset({'zh', 'zh-cn', 'zh-hans', 'zh-tw', 'zh-hant'})
    batch = []
    count = 0

    def flush():
        nonlocal batch
        if not batch:
            return
        conn.executemany(
            '''INSERT INTO zh_names (geonameid, name_zh, preferred) VALUES (?, ?, ?)
               ON CONFLICT(geonameid) DO UPDATE SET
                 name_zh=CASE WHEN excluded.preferred=1 OR zh_names.preferred=0 THEN excluded.name_zh ELSE zh_names.name_zh END,
                 preferred=MAX(zh_names.preferred, excluded.preferred)''',
            batch,
        )
        conn.commit()
        batch = []

    def ingest_line(line: str):
        nonlocal count, batch
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 3:
            return
        # alternateNamesV2: nameId, geonameId, isolang, name, isPreferred, ...
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit():
            gid = parts[1]
            isolang = (parts[2] or '').lower()
            name = parts[3]
            pref = (parts[4] if len(parts) > 4 else '0') == '1'
        else:
            gid = parts[0]
            isolang = (parts[1] or '').lower()
            name = parts[2]
            pref = (parts[3] if len(parts) > 3 else '0') == '1'
        if not gid.isdigit():
            return
        if isolang and isolang not in zh_langs:
            return
        if not isolang:
            return
        if not name or not any('\u4e00' <= ch <= '\u9fff' for ch in name):
            return
        batch.append((int(gid), name, 1 if pref else 0))
        count += 1
        if len(batch) >= 50000:
            flush()

    if zip_path.endswith('.zip'):
        with zipfile.ZipFile(zip_path) as zf:
            inner_names = [n for n in zf.namelist() if n.endswith('alternateNames.txt')]
            if not inner_names:
                raise FileNotFoundError(f'{zip_path} 内无 alternateNames.txt')
            with zf.open(inner_names[0]) as raw:
                text = io.TextIOWrapper(raw, encoding='utf-8')
                for line in text:
                    ingest_line(line)
    else:
        with open(zip_path, encoding='utf-8') as fh:
            for line in fh:
                ingest_line(line)
    flush()
    conn.execute('CREATE INDEX IF NOT EXISTS idx_zh_names_id ON zh_names(geonameid)')
    conn.commit()
    conn.close()
    print(f'  zh alternateNames sqlite: {count} rows -> {db_path}')


def ensure_zh_altnames_db(*, download: bool = True) -> str:
    """返回 zh 别名 sqlite 路径（从 alternateNames.zip 筛选中文）。"""
    global _zh_sqlite_path
    _ensure_geo_dir()
    db_path = os.path.join(GEO_DIR, 'zh_altnames.sqlite')
    zip_path = os.path.join(GEO_DIR, 'alternateNames.zip')
    if os.path.isfile(db_path) and os.path.getsize(db_path) > 1024:
        _zh_sqlite_path = db_path
        return db_path
    if download:
        if not os.path.isfile(zip_path) or os.path.getsize(zip_path) < 1_000_000:
            url = f'{GEONAMES_BASE}/alternateNames.zip'
            print(f'  downloading {url} (~200MB, 首次较慢) ...')
            urlretrieve(url, zip_path)
    elif not os.path.isfile(zip_path):
        print('  skip zh alternateNames: alternateNames.zip missing (--no-download)')
        _zh_sqlite_path = db_path
        return db_path
    print('  building zh_altnames.sqlite from alternateNames.zip ...')
    _build_zh_altnames_sqlite(zip_path, db_path)
    _zh_sqlite_path = db_path
    return db_path


class ZhNameResolver:
    """导入期中文名解析（geonameid 别名表 + CLDR admin1）。"""

    def __init__(self, *, download: bool = True):
        self._conn: sqlite3.Connection | None = None
        db_path = ensure_zh_altnames_db(download=download)
        if os.path.isfile(db_path) and os.path.getsize(db_path) > 1024:
            self._conn = sqlite3.connect(db_path)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def lookup_geonameid(self, geonameid) -> str | None:
        if not self._conn or not geonameid:
            return None
        row = self._conn.execute(
            'SELECT name_zh FROM zh_names WHERE geonameid=?',
            (int(geonameid),),
        ).fetchone()
        return row[0] if row else None

    def resolve(
        self,
        *,
        geonameid=None,
        alternatenames: str = '',
        admin1_code: str | None = None,
        name_en: str | None = None,
        name_local: str | None = None,
        allow_admin1_fallback: bool = False,
    ) -> str | None:
        if geonameid:
            zh = self.lookup_geonameid(geonameid)
            if zh:
                return zh
        if allow_admin1_fallback and admin1_code:
            zh = admin1_name_zh(admin1_code)
            if zh:
                return zh
        if alternatenames:
            for alt in alternatenames.split(','):
                alt = alt.strip()
                if alt and any('\u4e00' <= ch <= '\u9fff' for ch in alt):
                    return alt
        for candidate in (name_local, name_en):
            if candidate and any('\u4e00' <= ch <= '\u9fff' for ch in candidate):
                return candidate
        return None
