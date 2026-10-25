#!/usr/bin/env python3
"""从 GeoNames dump 导入 geo_places（B 档：ADM1–ADM5 + 全量居民点 PPL）。"""

from __future__ import annotations

import io
import os
import zipfile
from urllib.request import urlretrieve

from app.geo.admin1_zh import admin1_zh
from app.geo.country_zh import country_zh
from app.geo.names_zh import ZhNameResolver, admin1_name_zh, _load_cldr_admin1, to_traditional
from app.config import get_geo_dir

GEO_DIR = get_geo_dir()
GEONAMES_BASE = 'https://download.geonames.org/export/dump'

LEVEL_COUNTRY = 1
LEVEL_ADM1 = 2
LEVEL_ADM2 = 3
LEVEL_ADM3 = 4
LEVEL_ADM4 = 5
LEVEL_ADM5 = 6
LEVEL_PPL = 7
LEVEL_OTHER = 8  # 自然地理等（CN 对照探索）

NATURAL_FEATURE_CLASSES = frozenset({'H', 'T', 'L', 'V'})

ADM_FEATURE_CODES = frozenset({'ADM1', 'ADM2', 'ADM3', 'ADM4', 'ADM5'})
ADM_CODE_LEVEL = {
    'ADM1': LEVEL_ADM1,
    'ADM2': LEVEL_ADM2,
    'ADM3': LEVEL_ADM3,
    'ADM4': LEVEL_ADM4,
    'ADM5': LEVEL_ADM5,
}

COMMIT_EVERY = 100000
_fast_import = False

_zh_resolver: ZhNameResolver | None = None


def _log(msg: str):
    print(msg, flush=True)


_PARENT_FK = 'geo_places_parent_id_fkey'


def _drop_parent_fk(db):
    """临时去掉 parent_id 自引用 FK，避免 DELETE/UPDATE 在百万行上卡死。"""
    exists = db.execute(
        '''SELECT 1 FROM pg_constraint
           WHERE conname = ? AND conrelid = 'geo_places'::regclass''',
        (_PARENT_FK,),
    ).fetchone()
    if exists:
        _log('  drop parent_id self-FK (geo_places only) ...')
        db.execute(f'ALTER TABLE geo_places DROP CONSTRAINT {_PARENT_FK}')


def _restore_parent_fk(db):
    exists = db.execute(
        '''SELECT 1 FROM pg_constraint
           WHERE conname = ? AND conrelid = 'geo_places'::regclass''',
        (_PARENT_FK,),
    ).fetchone()
    if not exists:
        _log('  restore parent_id self-FK ...')
        db.execute(
            f'ALTER TABLE geo_places ADD CONSTRAINT {_PARENT_FK} '
            'FOREIGN KEY (parent_id) REFERENCES geo_places(id) NOT VALID'
        )
        db.execute(f'ALTER TABLE geo_places VALIDATE CONSTRAINT {_PARENT_FK}')


def _prepare_fast_import(db):
    """大批量导入前：降同步、卸次要索引。"""
    _log('  fast import: synchronous_commit=OFF, drop secondary indexes ...')
    db.execute('SET synchronous_commit = OFF')
    try:
        _load_cldr_admin1()
    except Exception as exc:
        _log(f'  WARN: CLDR preload failed: {exc}')
    for idx in (
        'idx_geo_places_parent',
        'idx_geo_places_iso_country',
        'idx_geo_places_name_zh',
        'idx_geo_places_admin1',
    ):
        db.execute(f'DROP INDEX IF EXISTS {idx}')
    db.commit()


def _finish_fast_import(db):
    """导入后：批量汉化 + 通名规范 + 重建索引。"""
    _apply_zh_names_batch(db)
    try:
        from app.geo.admin_terms import apply_admin_terms
        res = apply_admin_terms(db)
        _log(f'  admin terms: +{res["applied"]}')
    except Exception as exc:
        _log(f'  WARN: admin terms failed: {exc}')
    _log('  fast import: recreate indexes ...')
    db.execute('CREATE INDEX IF NOT EXISTS idx_geo_places_parent ON geo_places(parent_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_geo_places_iso_country ON geo_places(iso_country)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_geo_places_name_zh ON geo_places(name_zh)')
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_geo_places_admin1 ON geo_places(iso_country, admin1_code)'
    )
    db.execute('SET synchronous_commit = ON')
    db.commit()


def _apply_zh_names_batch(db):
    """从 zh_altnames.sqlite 批量回填 name_zh / name_zh_hant（避免导入期逐行 sqlite 查询）。"""
    import sqlite3

    db_path = os.path.join(GEO_DIR, 'zh_altnames.sqlite')
    if not os.path.isfile(db_path) or os.path.getsize(db_path) < 1024:
        _log('  skip batch zh names: zh_altnames.sqlite missing')
        return
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(zh_names)')}
    has_hant = 'name_zh_hant' in cols
    _log(f'  batch apply zh names from sqlite (hant={has_hant}) ...')
    db.execute(
        'CREATE TEMP TABLE zh_alt_import ('
        'geonameid BIGINT PRIMARY KEY, name_zh TEXT, name_zh_hant TEXT)'
    )
    batch = []
    total = 0

    def flush_batch():
        nonlocal batch, total
        if not batch:
            return
        db.executemany(
            'INSERT INTO zh_alt_import (geonameid, name_zh, name_zh_hant) VALUES (?, ?, ?) '
            'ON CONFLICT (geonameid) DO NOTHING',
            batch,
        )
        total += len(batch)
        batch = []
        if total % 200000 == 0:
            db.commit()
            _log(f'    ... zh_alt_import {total}')

    select_sql = (
        'SELECT geonameid, name_zh, name_zh_hant FROM zh_names'
        if has_hant else
        'SELECT geonameid, name_zh, NULL FROM zh_names'
    )
    for row in conn.execute(select_sql):
        batch.append(row)
        if len(batch) >= 50000:
            flush_batch()
    flush_batch()
    conn.close()
    db.commit()
    db.execute(
        '''UPDATE geo_places g
           SET name_zh = z.name_zh,
               name_zh_hant = COALESCE(z.name_zh_hant, g.name_zh_hant)
           FROM zh_alt_import z
           WHERE g.source = 'geonames' AND g.source_id = z.geonameid::text
             AND z.name_zh IS NOT NULL AND z.name_zh <> ''
             AND (g.name_zh IS NULL OR g.name_zh = '' OR g.name_zh = g.name_en
                  OR (z.name_zh_hant IS NOT NULL AND g.name_zh = z.name_zh_hant))'''
    )
    db.execute(
        '''UPDATE geo_places g
           SET name_zh_hant = z.name_zh_hant
           FROM zh_alt_import z
           WHERE g.source = 'geonames' AND g.source_id = z.geonameid::text
             AND z.name_zh_hant IS NOT NULL AND z.name_zh_hant <> ''
             AND g.name_zh_hant IS NULL'''
    )
    updated = db.execute(
        '''SELECT COUNT(*) AS c FROM geo_places g
           JOIN zh_alt_import z ON g.source_id = z.geonameid::text
           WHERE g.source = 'geonames' AND g.name_zh = z.name_zh
             AND z.name_zh IS NOT NULL AND z.name_zh <> ''
             AND z.name_zh <> COALESCE(g.name_en, '')'''
    ).fetchone()['c']
    db.commit()
    _log(f'  batch zh names done: loaded={total}, updated~={updated}')


def _resolve_name_zh(
    *,
    geonameid=None,
    alternatenames='',
    admin1_code=None,
    name_en=None,
    name_local=None,
    allow_admin1_fallback=False,
):
    if _zh_resolver and not _fast_import:
        zh = _zh_resolver.resolve(
            geonameid=geonameid,
            alternatenames=alternatenames,
            admin1_code=admin1_code,
            name_en=name_en,
            name_local=name_local,
            allow_admin1_fallback=allow_admin1_fallback,
        )
        if zh:
            return zh
    if allow_admin1_fallback and admin1_code:
        zh = admin1_name_zh(admin1_code)
        if zh:
            return zh
    picked = _pick_name_zh(alternatenames, name_en)
    if picked:
        return picked
    for candidate in (name_local, name_en):
        if candidate and any('\u4e00' <= ch <= '\u9fff' for ch in candidate):
            return candidate
    return None


def _resolve_name_zh_pair(
    *,
    geonameid=None,
    alternatenames='',
    admin1_code=None,
    name_en=None,
    name_local=None,
    allow_admin1_fallback=False,
):
    """返回 (简体名, 繁体名)。繁体优先别名表真实 hant，缺省 OpenCC s2t 补。"""
    from app.geo.names_zh import to_simplified, to_traditional

    hant = None
    hans = None
    if _zh_resolver and not _fast_import:
        hans, hant = _zh_resolver.resolve_pair(
            geonameid=geonameid,
            alternatenames=alternatenames,
            admin1_code=admin1_code,
            name_en=name_en,
            name_local=name_local,
            allow_admin1_fallback=allow_admin1_fallback,
        )
    if not hans and allow_admin1_fallback and admin1_code:
        hans = admin1_name_zh(admin1_code)
    if not hans:
        picked = _pick_name_zh(alternatenames, name_en)
        if picked:
            hans = to_simplified(picked)
    if not hans:
        for candidate in (name_local, name_en):
            if candidate and any('\u4e00' <= ch <= '\u9fff' for ch in candidate):
                hans = to_simplified(candidate)
                break
    if hans and not hant:
        hant = to_traditional(hans)
    return hans, hant



def _ensure_geo_dir():
    os.makedirs(GEO_DIR, exist_ok=True)


def _download(filename):
    _ensure_geo_dir()
    dest = os.path.join(GEO_DIR, filename)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    url = f'{GEONAMES_BASE}/{filename}'
    print(f'  downloading {url} ...')
    urlretrieve(url, dest)
    return dest


def _pick_name_zh(alternatenames, fallback_en=None):
    if alternatenames:
        for alt in alternatenames.split(','):
            alt = alt.strip()
            if alt and any('\u4e00' <= ch <= '\u9fff' for ch in alt):
                return alt
    return None


def _pop_sort_key(population, name_fallback=''):
    try:
        pop = max(0, int(population or 0))
    except (TypeError, ValueError):
        pop = 0
    inv = 999999999 - min(pop, 999999999)
    return f'{inv:09d}_{name_fallback or ""}'


def _name_sort_key(name_zh, name_en):
    return (name_zh or name_en or '').lower()


def _upsert_place(db, *, parent_id, level, source_id, iso_country, admin1_code, admin2_code,
                  name_en, name_zh, name_local, population, is_selectable, sort_key, source='geonames',
                  name_local_lang=None, name_zh_hant=None, feature_class=None, feature_code=None):
    cur = db.execute(
        '''INSERT INTO geo_places
           (parent_id, level, source, source_id, iso_country, admin1_code, admin2_code,
            feature_class, feature_code,
            name_en, name_zh, name_zh_hant, name_local, name_local_lang, population, is_selectable, sort_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET
             parent_id=EXCLUDED.parent_id,
             level=EXCLUDED.level,
             iso_country=EXCLUDED.iso_country,
             admin1_code=EXCLUDED.admin1_code,
             admin2_code=EXCLUDED.admin2_code,
             feature_class=EXCLUDED.feature_class,
             feature_code=EXCLUDED.feature_code,
             name_en=EXCLUDED.name_en,
             name_zh=EXCLUDED.name_zh,
             name_zh_hant=COALESCE(EXCLUDED.name_zh_hant, geo_places.name_zh_hant),
             name_local=COALESCE(EXCLUDED.name_local, geo_places.name_local),
             name_local_lang=COALESCE(EXCLUDED.name_local_lang, geo_places.name_local_lang),
             population=EXCLUDED.population,
             is_selectable=EXCLUDED.is_selectable,
             sort_key=EXCLUDED.sort_key
           RETURNING id''',
        (
            parent_id,
            level,
            source,
            str(source_id),
            iso_country,
            admin1_code,
            admin2_code,
            feature_class,
            feature_code,
            name_en,
            name_zh,
            name_zh_hant,
            name_local,
            name_local_lang,
            population,
            is_selectable,
            sort_key,
        ),
    )
    if cur.lastrowid is None:
        raise RuntimeError(f'geo_places upsert failed: source={source} source_id={source_id}')
    return cur.lastrowid


def _parse_country_info(path):
    countries = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            iso2 = parts[0]
            if len(iso2) != 2:
                continue
            geonameid = parts[16] if len(parts) > 16 and parts[16].isdigit() else None
            countries.append({'iso2': iso2, 'name_en': parts[4], 'geonameid': geonameid})
    return countries


def _parse_admin1(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            code, name, name_ascii, geonameid = (line.split('\t') + ['', '', '', ''])[:4]
            if '.' not in code:
                continue
            iso2, _admin1 = code.split('.', 1)
            rows.append({
                'code': code.upper(),
                'iso2': iso2.upper(),
                'name_en': name_ascii or name,
                'geonameid': geonameid,
            })
    return rows


def _parse_admin2(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            code, name, name_ascii, geonameid = (line.split('\t') + ['', '', '', ''])[:4]
            parts = code.split('.')
            if len(parts) < 3:
                continue
            rows.append({
                'code': code.upper(),
                'iso2': parts[0].upper(),
                'admin1_key': f'{parts[0]}.{parts[1]}'.upper(),
                'name_en': name_ascii or name,
                'geonameid': geonameid,
            })
    return rows


def _iter_all_countries(path):
    if path.endswith('.zip'):
        with zipfile.ZipFile(path) as zf:
            inner = [n for n in zf.namelist() if n.endswith('.txt')][0]
            with zf.open(inner) as raw:
                text = io.TextIOWrapper(raw, encoding='utf-8')
                for line in text:
                    yield line.rstrip('\n').split('\t')
    else:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                yield line.rstrip('\n').split('\t')


def _admin_keys(iso2, a1, a2='', a3='', a4=''):
    iso2 = (iso2 or '').upper()
    a1 = a1 or ''
    a2 = a2 or ''
    a3 = a3 or ''
    a4 = a4 or ''
    keys = {}
    if iso2 and a1:
        keys['adm1'] = f'{iso2}.{a1}'.upper()
    if iso2 and a1 and a2:
        keys['adm2'] = f'{iso2}.{a1}.{a2}'.upper()
    if iso2 and a1 and a2 and a3:
        keys['adm3'] = f'{iso2}.{a1}.{a2}.{a3}'.upper()
    if iso2 and a1 and a2 and a3 and a4:
        keys['adm4'] = f'{iso2}.{a1}.{a2}.{a3}.{a4}'.upper()
    return keys


def _resolve_admin_parent(feature_code, keys, iso_to_geo, admin1_to_geo, admin2_to_geo,
                          admin3_to_geo, admin4_to_geo):
    if feature_code == 'ADM1':
        return iso_to_geo.get((keys.get('adm1') or '').split('.')[0])
    if feature_code == 'ADM2':
        return admin1_to_geo.get(keys.get('adm1'))
    if feature_code == 'ADM3':
        return admin2_to_geo.get(keys.get('adm2')) or admin1_to_geo.get(keys.get('adm1'))
    if feature_code == 'ADM4':
        return admin3_to_geo.get(keys.get('adm3')) or admin2_to_geo.get(keys.get('adm2'))
    if feature_code == 'ADM5':
        return admin4_to_geo.get(keys.get('adm4')) or admin3_to_geo.get(keys.get('adm3'))
    return None


def _resolve_ppl_parent(keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo):
    for k, mapping in (
        ('adm4', admin4_to_geo),
        ('adm3', admin3_to_geo),
        ('adm2', admin2_to_geo),
        ('adm1', admin1_to_geo),
    ):
        code = keys.get(k)
        if code and code in mapping:
            return mapping[code]
    iso2 = (keys.get('adm1') or '').split('.')[0] if keys.get('adm1') else None
    if not iso2 and keys.get('adm2'):
        iso2 = keys['adm2'].split('.')[0]
    return iso_to_geo.get(iso2) if iso2 else None


def rebuild_geonames_places(db):
    """删除国外 geonames 节点（保留 ok_zh）。

    禁止 TRUNCATE geo_places CASCADE。
    """
    _log('  clearing geonames: remove overrides ...')
    _drop_parent_fk(db)
    _log('  clearing geonames: DELETE rows ...')
    db.execute("DELETE FROM geo_places WHERE source = 'geonames'")
    _restore_parent_fk(db)
    db.commit()
    _log('  cleared existing geonames rows')


def import_geonames(db, *, download=True, rebuild=False, fast=True, defer_finish=False):
    global _zh_resolver, _fast_import
    if rebuild:
        rebuild_geonames_places(db)

    _fast_import = fast
    if fast and not defer_finish:
        _prepare_fast_import(db)
    elif fast and defer_finish:
        _fast_import = True

    _zh_resolver = ZhNameResolver(download=download) if (not fast) else None
    try:
        result = _import_geonames_body(db, download=download)
        if fast and not defer_finish:
            _finish_fast_import(db)
        return result
    finally:
        if _zh_resolver:
            _zh_resolver.close()
        _zh_resolver = None
        if not defer_finish:
            _fast_import = False


def _import_geonames_body(db, *, download=True):

    if download:
        country_path = _download('countryInfo.txt')
        admin1_path = _download('admin1CodesASCII.txt')
        admin2_path = _download('admin2Codes.txt')
        all_countries_path = _download('allCountries.zip')
    else:
        country_path = os.path.join(GEO_DIR, 'countryInfo.txt')
        admin1_path = os.path.join(GEO_DIR, 'admin1CodesASCII.txt')
        admin2_path = os.path.join(GEO_DIR, 'admin2Codes.txt')
        all_countries_path = os.path.join(GEO_DIR, 'allCountries.zip')
        for p in (country_path, admin1_path, admin2_path, all_countries_path):
            if not os.path.isfile(p):
                raise FileNotFoundError(f'缺少 GeoNames 文件: {p}（请去掉 --no-download 或手动下载）')

    iso_to_geo = {}
    admin1_to_geo = {}
    admin2_to_geo = {}
    admin3_to_geo = {}
    admin4_to_geo = {}

    pending = 0

    def _commit_if_needed(force=False):
        nonlocal pending
        if force or pending >= COMMIT_EVERY:
            db.commit()
            pending = 0

    # 国家
    for c in _parse_country_info(country_path):
        iso2 = c['iso2'].upper()
        name_en = c['name_en']
        name_zh = country_zh(iso2, name_en)
        name_zh_hant = to_traditional(name_zh) if name_zh else None
        source_id = c['geonameid'] or f'country:{iso2}'
        geo_id = _upsert_place(
            db,
            parent_id=None,
            level=LEVEL_COUNTRY,
            source_id=source_id,
            iso_country=iso2,
            admin1_code=None,
            admin2_code=None,
            feature_class='A',
            feature_code='PCLI',
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=None,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        iso_to_geo[iso2] = geo_id
        pending += 1
        _commit_if_needed()

    # ADM1
    for row in _parse_admin1(admin1_path):
        if row['iso2'] == 'CN':
            continue
        parent_id = iso_to_geo.get(row['iso2'])
        if not parent_id:
            continue
        code = row['code']
        name_en = row['name_en']
        name_zh, name_zh_hant = _resolve_name_zh_pair(
            geonameid=row.get('geonameid'),
            admin1_code=code,
            name_en=name_en,
            allow_admin1_fallback=True,
        ) or admin1_zh(code, name_en)
        source_id = row['geonameid'] or f'admin1:{code}'
        geo_id = _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_ADM1,
            source_id=source_id,
            iso_country=row['iso2'],
            admin1_code=code,
            admin2_code=None,
            feature_class='A',
            feature_code='ADM1',
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=None,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        admin1_to_geo[code] = geo_id
        pending += 1
        _commit_if_needed()

    # ADM2
    adm2_count = 0
    for row in _parse_admin2(admin2_path):
        if row['iso2'] == 'CN':
            continue
        parent_id = admin1_to_geo.get(row['admin1_key'])
        if not parent_id:
            continue
        code = row['code']
        name_en = row['name_en']
        name_zh, name_zh_hant = _resolve_name_zh_pair(
            geonameid=row.get('geonameid'),
            admin1_code=row['admin1_key'],
            name_en=name_en,
        )
        source_id = row['geonameid'] or f'admin2:{code}'
        geo_id = _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_ADM2,
            source_id=source_id,
            iso_country=row['iso2'],
            admin1_code=row['admin1_key'],
            admin2_code=code,
            feature_class='A',
            feature_code='ADM2',
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=None,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        admin2_to_geo[code] = geo_id
        adm2_count += 1
        pending += 1
        _commit_if_needed()
    print(f'  admin2 from codes: {adm2_count}')

    # allCountries：ADM3–ADM5 + 全量 PPL
    adm_counts = {k: 0 for k in ADM_FEATURE_CODES}
    ppl_count = 0
    line_no = 0

    for parts in _iter_all_countries(all_countries_path):
        line_no += 1
        if len(parts) < 15:
            continue
        geonameid = parts[0]
        name = parts[1]
        ascii_name = parts[2]
        alternatenames = parts[3]
        feature_class = parts[6]
        feature_code = parts[7]
        iso2 = (parts[8] or '').upper()
        if iso2 == 'CN':
            continue
        a1, a2, a3, a4 = parts[10], parts[11], parts[12], parts[13]
        population_raw = parts[14]
        try:
            population = int(population_raw) if population_raw else 0
        except (TypeError, ValueError):
            population = 0
        keys = _admin_keys(iso2, a1, a2, a3, a4)
        name_en = ascii_name or name
        name_zh, name_zh_hant = _resolve_name_zh_pair(
            geonameid=geonameid,
            alternatenames=alternatenames,
            admin1_code=keys.get('adm1'),
            name_en=name_en,
            name_local=name,
        )

        if feature_class == 'A' and feature_code in ADM_FEATURE_CODES:
            if feature_code in ('ADM1', 'ADM2'):
                continue
            parent_id = _resolve_admin_parent(
                feature_code, keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo,
            )
            if not parent_id:
                continue
            level = ADM_CODE_LEVEL[feature_code]
            geo_id = _upsert_place(
                db,
                parent_id=parent_id,
                level=level,
                source_id=geonameid,
                iso_country=iso2,
                admin1_code=keys.get('adm1'),
                admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
                feature_class='A',
                feature_code=feature_code,
                name_en=name_en,
                name_zh=name_zh,
                name_zh_hant=name_zh_hant,
                name_local=name,
                population=None,
                is_selectable=True,
                sort_key=_name_sort_key(name_zh, name_en),
            )
            if feature_code == 'ADM3' and keys.get('adm3'):
                admin3_to_geo[keys['adm3']] = geo_id
            elif feature_code == 'ADM4' and keys.get('adm4'):
                admin4_to_geo[keys['adm4']] = geo_id
            adm_counts[feature_code] += 1
            pending += 1
            _commit_if_needed()
            continue

        if feature_class != 'P':
            continue

        parent_id = _resolve_ppl_parent(
            keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo,
        )
        if not parent_id:
            continue

        _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_PPL,
            source_id=geonameid,
            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            feature_class='P',
            feature_code=feature_code,
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=population,
            is_selectable=True,
            sort_key=_pop_sort_key(population, name_zh or name_en),
        )
        ppl_count += 1
        pending += 1
        if ppl_count % 50000 == 0:
            print(f'  ... PPL {ppl_count} (line {line_no})')
        _commit_if_needed()

    _commit_if_needed(force=True)

    cx = db.execute(
        "SELECT id FROM geo_places WHERE source='geonames' AND iso_country='CX' AND level=1 LIMIT 1"
    ).fetchone()
    if cx:
        db.execute(
            "UPDATE geo_places SET name_zh = ?, name_zh_hant = ? WHERE id = ?",
            ('圣诞岛', to_traditional('圣诞岛'), cx['id']),
        )
        db.commit()

    print(
        '  geonames B-tier: '
        f'countries={len(iso_to_geo)}, admin1={len(admin1_to_geo)}, admin2={len(admin2_to_geo)}, '
        f'adm3={adm_counts["ADM3"]}, adm4={adm_counts["ADM4"]}, adm5={adm_counts["ADM5"]}, ppl={ppl_count}'
    )
    return len(iso_to_geo) + len(admin1_to_geo) + len(admin2_to_geo) + sum(adm_counts.values()) + ppl_count


def rebuild_china_geonames(db):
    """仅删除 GeoNames 中国节点（保留 ok_zh 与国外 geonames）。"""
    _log('  clearing geonames CN: DELETE rows ...')
    _drop_parent_fk(db)
    db.execute("DELETE FROM geo_places WHERE source = 'geonames' AND iso_country = 'CN'")
    _restore_parent_fk(db)
    db.commit()
    _log('  cleared existing geonames CN rows')


def _import_geonames_row(
    db,
    *,
    geonameid,
    name,
    ascii_name,
    alternatenames,
    feature_class,
    feature_code,
    iso2,
    keys,
    population,
    iso_to_geo,
    admin1_to_geo,
    admin2_to_geo,
    admin3_to_geo,
    admin4_to_geo,
    adm_counts,
    include_natural=False,
    full_gazetteer=False,
    pending_ref,
    commit_fn,
):
    """处理 allCountries 单行；返回是否写入。"""
    name_en = ascii_name or name
    name_zh, name_zh_hant = _resolve_name_zh_pair(
        geonameid=geonameid,
        alternatenames=alternatenames,
        admin1_code=keys.get('adm1'),
        name_en=name_en,
        name_local=name,
    )

    if feature_class == 'A' and feature_code in ADM_FEATURE_CODES:
        if feature_code in ('ADM1', 'ADM2'):
            return False
        parent_id = _resolve_admin_parent(
            feature_code, keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo,
        )
        if not parent_id:
            return False
        level = ADM_CODE_LEVEL[feature_code]
        geo_id = _upsert_place(
            db,
            parent_id=parent_id,
            level=level,
            source_id=geonameid,
            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
            feature_class='A',
            feature_code=feature_code,
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        if feature_code == 'ADM3' and keys.get('adm3'):
            admin3_to_geo[keys['adm3']] = geo_id
        elif feature_code == 'ADM4' and keys.get('adm4'):
            admin4_to_geo[keys['adm4']] = geo_id
        adm_counts[feature_code] += 1
        pending_ref[0] += 1
        commit_fn()
        return True

    if feature_class == 'P':
        parent_id = _resolve_ppl_parent(
            keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo,
        )
        if not parent_id:
            return False
        _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_PPL,
            source_id=geonameid,
            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            feature_class='P',
            feature_code=feature_code,
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=population,
            is_selectable=True,
            sort_key=_pop_sort_key(population, name_zh or name_en),
        )
        pending_ref[0] += 1
        commit_fn()
        return True

    allow_other = full_gazetteer or (include_natural and feature_class in NATURAL_FEATURE_CLASSES)
    if not allow_other:
        return False

    parent_id = _resolve_ppl_parent(
        keys, iso_to_geo, admin1_to_geo, admin2_to_geo, admin3_to_geo, admin4_to_geo,
    ) or iso_to_geo.get(iso2)
    if not parent_id:
        return False
    label = name_zh or name_en
    _upsert_place(
        db,
        parent_id=parent_id,
        level=LEVEL_OTHER,
        source_id=geonameid,
        iso_country=iso2,
        admin1_code=keys.get('adm1'),
        admin2_code=None,
        feature_class=feature_class,
        feature_code=feature_code,
        name_en=name_en,
        name_zh=name_zh,
        name_zh_hant=name_zh_hant,
        name_local=name,
        population=population or None,
        is_selectable=False,
        sort_key=_name_sort_key(label, name_en),
    )
    pending_ref[0] += 1
    commit_fn()
    return True


def import_china_geonames(
    db,
    *,
    download=False,
    rebuild_china=True,
    include_natural=False,
    full_gazetteer=False,
    fast=True,
):
    """
    增量导入 GeoNames 中国对照层（不触碰国外 geonames / ok_zh）。
    默认：ADM3–ADM5 + 全量居民点 P。
    include_natural=True：额外导入 H/T/L/V 自然地理（约 4.5 万行）。
    full_gazetteer=True：allCountries 中 CN 全部 feature（不推荐）。
    """
    global _zh_resolver, _fast_import
    if rebuild_china:
        rebuild_china_geonames(db)

    if _zh_resolver is None and not fast:
        _zh_resolver = ZhNameResolver(download=download)
        close_resolver = True
    else:
        close_resolver = False
    prev_fast = _fast_import
    _fast_import = fast or prev_fast
    try:
        return _import_china_geonames_body(
            db,
            download=download,
            include_natural=include_natural,
            full_gazetteer=full_gazetteer,
        )
    finally:
        if close_resolver and _zh_resolver:
            _zh_resolver.close()
            _zh_resolver = None
        _fast_import = prev_fast


def _import_china_geonames_body(db, *, download=False, include_natural=False, full_gazetteer=False):

    if download:
        country_path = _download('countryInfo.txt')
        admin1_path = _download('admin1CodesASCII.txt')
        admin2_path = _download('admin2Codes.txt')
        all_countries_path = _download('allCountries.zip')
    else:
        country_path = os.path.join(GEO_DIR, 'countryInfo.txt')
        admin1_path = os.path.join(GEO_DIR, 'admin1CodesASCII.txt')
        admin2_path = os.path.join(GEO_DIR, 'admin2Codes.txt')
        all_countries_path = os.path.join(GEO_DIR, 'allCountries.zip')

    iso_to_geo = {}
    admin1_to_geo = {}
    admin2_to_geo = {}
    admin3_to_geo = {}
    admin4_to_geo = {}

    existing_cn = db.execute(
        "SELECT id FROM geo_places WHERE source='geonames' AND iso_country='CN' AND level=1 LIMIT 1"
    ).fetchone()
    if existing_cn:
        iso_to_geo['CN'] = existing_cn['id']
    else:
        for c in _parse_country_info(country_path):
            if c['iso2'].upper() != 'CN':
                continue
            geo_id = _upsert_place(
                db,
                parent_id=None,
                level=LEVEL_COUNTRY,
                source_id=c['geonameid'] or 'country:CN',
                iso_country='CN',
                admin1_code=None,
                admin2_code=None,
                feature_class='A',
                feature_code='PCLI',
                name_en=c['name_en'],
                name_zh=country_zh('CN', c['name_en']),
                name_zh_hant=to_traditional(country_zh('CN', c['name_en'])),
                name_local=None,
                population=None,
                is_selectable=True,
                sort_key=_name_sort_key(country_zh('CN', c['name_en']), c['name_en']),
            )
            iso_to_geo['CN'] = geo_id
            break

    for row in _parse_admin1(admin1_path):
        if row['iso2'] != 'CN':
            continue
        parent_id = iso_to_geo.get('CN')
        if not parent_id:
            continue
        code = row['code']
        name_en = row['name_en']
        name_zh, name_zh_hant = _resolve_name_zh_pair(
            geonameid=row.get('geonameid'),
            admin1_code=code,
            name_en=name_en,
            allow_admin1_fallback=True,
        )
        geo_id = _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_ADM1,
            source_id=row['geonameid'] or f'admin1:{code}',
            iso_country='CN',
            admin1_code=code,
            admin2_code=None,
            feature_class='A',
            feature_code='ADM1',
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=None,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        admin1_to_geo[code] = geo_id

    adm2_count = 0
    for row in _parse_admin2(admin2_path):
        if row['iso2'] != 'CN':
            continue
        parent_id = admin1_to_geo.get(row['admin1_key'])
        if not parent_id:
            continue
        code = row['code']
        name_en = row['name_en']
        name_zh, name_zh_hant = _resolve_name_zh_pair(
            geonameid=row.get('geonameid'),
            admin1_code=row['admin1_key'],
            name_en=name_en,
        )
        geo_id = _upsert_place(
            db,
            parent_id=parent_id,
            level=LEVEL_ADM2,
            source_id=row['geonameid'] or f'admin2:{code}',
            iso_country='CN',
            admin1_code=row['admin1_key'],
            admin2_code=code,
            feature_class='A',
            feature_code='ADM2',
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=None,
            population=None,
            is_selectable=True,
            sort_key=_name_sort_key(name_zh, name_en),
        )
        admin2_to_geo[code] = geo_id
        adm2_count += 1
    db.commit()
    print(f'  CN admin2 from codes: {adm2_count}')

    adm_counts = {k: 0 for k in ADM_FEATURE_CODES}
    ppl_count = 0
    other_count = 0
    line_no = 0
    pending_ref = [0]

    def _commit_if_needed(force=False):
        if force or pending_ref[0] >= COMMIT_EVERY:
            db.commit()
            pending_ref[0] = 0

    for parts in _iter_all_countries(all_countries_path):
        line_no += 1
        if len(parts) < 15:
            continue
        iso2 = (parts[8] or '').upper()
        if iso2 != 'CN':
            continue
        geonameid = parts[0]
        name = parts[1]
        ascii_name = parts[2]
        alternatenames = parts[3]
        feature_class = parts[6]
        feature_code = parts[7]
        a1, a2, a3, a4 = parts[10], parts[11], parts[12], parts[13]
        try:
            population = int(parts[14]) if parts[14] else 0
        except (TypeError, ValueError):
            population = 0
        keys = _admin_keys(iso2, a1, a2, a3, a4)

        want = (
            feature_class == 'P'
            or (feature_class == 'A' and feature_code in ADM_FEATURE_CODES)
            or full_gazetteer
            or (include_natural and feature_class in NATURAL_FEATURE_CLASSES)
        )
        if not want:
            continue

        ok = _import_geonames_row(
            db,
            geonameid=geonameid,
            name=name,
            ascii_name=ascii_name,
            alternatenames=alternatenames,
            feature_class=feature_class,
            feature_code=feature_code,
            iso2=iso2,
            keys=keys,
            population=population,
            iso_to_geo=iso_to_geo,
            admin1_to_geo=admin1_to_geo,
            admin2_to_geo=admin2_to_geo,
            admin3_to_geo=admin3_to_geo,
            admin4_to_geo=admin4_to_geo,
            adm_counts=adm_counts,
            include_natural=include_natural,
            full_gazetteer=full_gazetteer,
            pending_ref=pending_ref,
            commit_fn=_commit_if_needed,
        )
        if ok:
            if feature_class == 'P':
                ppl_count += 1
            elif feature_class == 'A' and feature_code in ADM_FEATURE_CODES:
                pass
            else:
                other_count += 1

        if line_no % 100000 == 0:
            print(f'  ... CN scan line {line_no}, ppl={ppl_count}, other={other_count}')

    _commit_if_needed(force=True)
    cn_total = db.execute(
        "SELECT COUNT(*) AS c FROM geo_places WHERE source='geonames' AND iso_country='CN'"
    ).fetchone()['c']
    print(
        '  geonames CN: '
        f'adm3={adm_counts["ADM3"]}, adm4={adm_counts["ADM4"]}, adm5={adm_counts["ADM5"]}, '
        f'ppl={ppl_count}, natural_other={other_count}, total_cn_rows={cn_total}, '
        f'include_natural={include_natural}, full_gazetteer={full_gazetteer}'
    )
    return cn_total
