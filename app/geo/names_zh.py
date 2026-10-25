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

_ZH_HANS_LANGS = frozenset({'zh', 'zh-cn', 'zh-sg', 'zh-hans', 'zh-my'})
_ZH_HANT_LANGS = frozenset({'zh-tw', 'zh-hk', 'zh-mo', 'zh-hant'})

_s2t = None
_t2s = None


def _opencc(kind):
    global _s2t, _t2s
    if kind == 's2t':
        if _s2t is None:
            from opencc import OpenCC
            _s2t = OpenCC('s2t')
        return _s2t
    if _t2s is None:
        from opencc import OpenCC
        _t2s = OpenCC('t2s')
    return _t2s


def to_simplified(text: str) -> str:
    return _opencc('t2s').convert(text or '')


def to_traditional(text: str) -> str:
    return _opencc('s2t').convert(text or '')


def _zh_bucket(isolang: str) -> str | None:
    lang = (isolang or '').lower().replace('_', '-')
    if lang in _ZH_HANS_LANGS:
        return 'hans'
    if lang in _ZH_HANT_LANGS:
        return 'hant'
    return None


def _zh_names_has_hant(conn) -> bool:
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(zh_names)')}
    except sqlite3.Error:
        return False
    return 'name_zh_hant' in cols


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


def _build_zh_altnames_sqlite(src_path: str, db_path: str) -> None:
    """从 alternateNames(.zip/.txt) 流式筛选中文构建 geonameid 索引 sqlite。

    简繁分桶：简体坑 zh/zh-CN/zh-SG/zh-Hans/zh-MY，繁体坑 zh-TW/zh-HK/zh-MO/zh-Hant，
    各自独立评 preferred，不再互相抢 name_zh。
    """
    if os.path.isfile(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''CREATE TABLE zh_names (
               geonameid INTEGER PRIMARY KEY,
               name_zh TEXT,
               preferred INTEGER NOT NULL DEFAULT 0,
               name_zh_hant TEXT,
               preferred_hant INTEGER NOT NULL DEFAULT 0
           )'''
    )
    conn.execute('PRAGMA journal_mode=OFF')
    conn.execute('PRAGMA synchronous=OFF')
    batch_hans: list[tuple] = []
    batch_hant: list[tuple] = []
    count = 0

    _UPSERT_HANS = '''INSERT INTO zh_names (geonameid, name_zh, preferred) VALUES (?, ?, ?)
        ON CONFLICT(geonameid) DO UPDATE SET
          name_zh=CASE WHEN excluded.preferred=1 OR zh_names.preferred=0 THEN excluded.name_zh ELSE zh_names.name_zh END,
          preferred=MAX(zh_names.preferred, excluded.preferred)'''
    _UPSERT_HANT = '''INSERT INTO zh_names (geonameid, name_zh_hant, preferred_hant) VALUES (?, ?, ?)
        ON CONFLICT(geonameid) DO UPDATE SET
          name_zh_hant=CASE WHEN excluded.preferred_hant=1 OR zh_names.preferred_hant=0 THEN excluded.name_zh_hant ELSE zh_names.name_zh_hant END,
          preferred_hant=MAX(zh_names.preferred_hant, excluded.preferred_hant)'''

    def flush():
        nonlocal batch_hans, batch_hant
        if batch_hans:
            conn.executemany(_UPSERT_HANS, batch_hans)
            batch_hans = []
        if batch_hant:
            conn.executemany(_UPSERT_HANT, batch_hant)
            batch_hant = []
        conn.commit()

    def ingest_line(line: str):
        nonlocal count, batch_hans, batch_hant
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 3:
            return
        # alternateNamesV2: nameId, geonameId, isolang, name, isPreferred, ...
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit():
            gid = parts[1]
            isolang = parts[2]
            name = parts[3]
            pref = (parts[4] if len(parts) > 4 else '0') == '1'
        else:
            gid = parts[0]
            isolang = parts[1]
            name = parts[2]
            pref = (parts[3] if len(parts) > 3 else '0') == '1'
        if not gid.isdigit():
            return
        bucket = _zh_bucket(isolang)
        if not bucket:
            return
        if not name or not any('一' <= ch <= '鿿' for ch in name):
            return
        rec = (int(gid), name, 1 if pref else 0)
        if bucket == 'hans':
            batch_hans.append(rec)
        else:
            batch_hant.append(rec)
        count += 1
        if len(batch_hans) + len(batch_hant) >= 50000:
            flush()

    if src_path.endswith('.zip'):
        with zipfile.ZipFile(src_path) as zf:
            inner_names = [n for n in zf.namelist() if n.endswith('alternateNames.txt')]
            if not inner_names:
                raise FileNotFoundError(f'{src_path} 内无 alternateNames.txt')
            with zf.open(inner_names[0]) as raw:
                text = io.TextIOWrapper(raw, encoding='utf-8')
                for line in text:
                    ingest_line(line)
    else:
        with open(src_path, encoding='utf-8') as fh:
            for line in fh:
                ingest_line(line)
    flush()
    conn.execute('CREATE INDEX IF NOT EXISTS idx_zh_names_id ON zh_names(geonameid)')
    conn.commit()
    conn.close()
    print(f'  zh alternateNames sqlite: {count} rows -> {db_path}')


def _find_altnames_source() -> str | None:
    """找 alternateNames 源：GEO_DIR 下 zip，或 GEO_NAMES_ZIP_DIR/N 盘常见路径。"""
    candidates = [
        os.path.join(GEO_DIR, 'alternateNames.zip'),
        os.path.join(GEO_DIR, 'alternateNames.txt'),
        os.path.join(GEO_DIR, 'alternateNames', 'alternateNames.txt'),
    ]
    extra_dir = (os.environ.get('GEO_NAMES_ZIP_DIR') or '').strip()
    if extra_dir:
        candidates.append(os.path.join(extra_dir, 'alternateNames.zip'))
        candidates.append(os.path.join(extra_dir, 'alternateNames', 'alternateNames.txt'))
        candidates.append(os.path.join(extra_dir, 'alternateNames.txt'))
    for path in candidates:
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            return path
    return None


def zh_altnames_needs_rebuild(db_path: str) -> bool:
    """旧版 sqlite 没有繁体列时需要重建。"""
    if not os.path.isfile(db_path) or os.path.getsize(db_path) < 1024:
        return True
    conn = sqlite3.connect(db_path)
    try:
        return not _zh_names_has_hant(conn)
    finally:
        conn.close()


def ensure_zh_altnames_db(*, download: bool = True, rebuild: bool = False) -> str:
    """返回 zh 别名 sqlite 路径（从 alternateNames 筛选中文，简繁双列）。"""
    global _zh_sqlite_path
    _ensure_geo_dir()
    db_path = os.path.join(GEO_DIR, 'zh_altnames.sqlite')
    if os.path.isfile(db_path) and os.path.getsize(db_path) > 1024 and not rebuild:
        if not zh_altnames_needs_rebuild(db_path):
            _zh_sqlite_path = db_path
            return db_path
        print('  zh_altnames.sqlite 为旧版单列结构，重建 ...')
    src = _find_altnames_source()
    if src is None and download:
        zip_path = os.path.join(GEO_DIR, 'alternateNames.zip')
        url = f'{GEONAMES_BASE}/alternateNames.zip'
        print(f'  downloading {url} (~200MB, 首次较慢) ...')
        urlretrieve(url, zip_path)
        src = zip_path
    if src is None:
        print('  skip zh alternateNames: 未找到 alternateNames 源文件')
        _zh_sqlite_path = db_path
        return db_path
    print(f'  building zh_altnames.sqlite from {src} ...')
    _build_zh_altnames_sqlite(src, db_path)
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
        pair = self.lookup_geonameid_pair(geonameid)
        return pair[0] if pair else None

    def lookup_geonameid_pair(self, geonameid) -> tuple[str | None, str | None] | None:
        """返回 (简体, 繁体)；sqlite 无该行返回 None。"""
        if not self._conn or not geonameid:
            return None
        if not _zh_names_has_hant(self._conn):
            row = self._conn.execute(
                'SELECT name_zh FROM zh_names WHERE geonameid=?',
                (int(geonameid),),
            ).fetchone()
            return (row[0], None) if row else None
        row = self._conn.execute(
            'SELECT name_zh, name_zh_hant FROM zh_names WHERE geonameid=?',
            (int(geonameid),),
        ).fetchone()
        return (row[0], row[1]) if row else None

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
        return self.resolve_pair(
            geonameid=geonameid,
            alternatenames=alternatenames,
            admin1_code=admin1_code,
            name_en=name_en,
            name_local=name_local,
            allow_admin1_fallback=allow_admin1_fallback,
        )[0]

    def resolve_pair(
        self,
        *,
        geonameid=None,
        alternatenames: str = '',
        admin1_code: str | None = None,
        name_en: str | None = None,
        name_local: str | None = None,
        allow_admin1_fallback: bool = False,
    ) -> tuple[str | None, str | None]:
        """返回 (简体名, 繁体名)。繁体优先取别名表真实 hant，否则 None（由调用方 OpenCC 补）。"""
        hant = None
        if geonameid:
            pair = self.lookup_geonameid_pair(geonameid)
            if pair:
                zh, hant = pair
                if zh:
                    return zh, hant
        if allow_admin1_fallback and admin1_code:
            zh = admin1_name_zh(admin1_code)
            if zh:
                return zh, hant
        if alternatenames:
            for alt in alternatenames.split(','):
                alt = alt.strip()
                if alt and any('一' <= ch <= '鿿' for ch in alt):
                    return to_simplified(alt), hant
        for candidate in (name_local, name_en):
            if candidate and any('一' <= ch <= '鿿' for ch in candidate):
                return to_simplified(candidate), hant
        return None, hant
