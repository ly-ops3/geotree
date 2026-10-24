"""geo_places 查询、展示与用户资料地区逻辑。"""

from __future__ import annotations

import re

from app.db import _table_exists
from app.geo.admin1_zh import admin1_zh
from app.geo.country_zh import COUNTRY_ALIASES, COUNTRY_ZH, country_zh
from app.geo.macro_regions import LEVEL_MACRO, SOURCE_MACRO

ADMIN_SUFFIXES = (
    '特别行政区',
    '壮族自治区',
    '回族自治区',
    '维吾尔自治区',
    '自治区',
    '自治州',
    '地区',
    '林区',
    '盟',
    '省',
    '市',
    '区',
    '县',
)

SCOPE_CN = 'cn'
SCOPE_ABROAD = 'abroad'
SCOPE_CN_GN = 'cn_gn'  # GeoNames 中国全量 gazetteer（探索用，与 ok_zh 资料栏分离）


def geo_tables_ready(db) -> bool:
    return _table_exists(db, 'geo_places')


def place_display_name(row) -> str:
    if not row:
        return ''
    if row.get('source') == 'ok_zh':
        return row.get('name_zh') or row.get('name_en') or row.get('name_local') or ''
    if row.get('source') == SOURCE_MACRO and (row.get('iso_country') or '').upper() == 'CN':
        return (row.get('name_zh') or '').strip() or row.get('name_en') or row.get('name_local') or ''
    zh = (row.get('name_zh') or '').strip()
    en = (row.get('name_en') or row.get('name_local') or '').strip()
    if zh and en and zh != en:
        return f'{zh} ({en})'
    if zh:
        return zh
    return en or ''


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _fetch_place(db, place_id):
    if not place_id or not geo_tables_ready(db):
        return None
    row = db.execute('SELECT * FROM geo_places WHERE id = ?', (place_id,)).fetchone()
    return _row_to_dict(row)


def place_scope(row) -> str | None:
    if not row:
        return None
    if row.get('source') == 'ok_zh' or (row.get('level') == 1 and row.get('iso_country') == 'CN'):
        return SCOPE_CN
    if row.get('source') == SOURCE_MACRO and (row.get('iso_country') or '').upper() == 'CN':
        return SCOPE_CN
    return SCOPE_ABROAD


def _has_children(db, place_id):
    row = db.execute(
        'SELECT 1 FROM geo_places WHERE parent_id = ? LIMIT 1',
        (place_id,),
    ).fetchone()
    return row is not None


def _serialize_place_row(db, row):
    item = {
        'id': row['id'],
        'level': row['level'],
        'display_name': place_display_name(row),
        'name_zh': row.get('name_zh'),
        'name_en': row.get('name_en'),
        'name_local': row.get('name_local'),
        'iso_country': row.get('iso_country'),
        'population': row.get('population'),
        'feature': row.get('admin2_code') if (row.get('level') or 0) >= 8 else None,
        'has_children': _has_children(db, row['id']),
        'source': row.get('source'),
    }
    return item


def _cn_tree_children(db, parent_id=None, scope=None) -> bool:
    """两岸四地（ok_zh + CN 大区）级联子节点按 id 排序。"""
    if scope == SCOPE_CN:
        return True
    if parent_id is not None:
        return place_scope(_fetch_place(db, parent_id)) == SCOPE_CN
    return False


def get_children(db, parent_id=None, scope=None, limit=2000):
    if not geo_tables_ready(db):
        return []
    params = [SOURCE_MACRO]
    clauses = ['(p.is_selectable = TRUE OR p.source = ?)']
    if parent_id is None:
        clauses.append('p.parent_id IS NULL')
        if scope == SCOPE_CN:
            clauses.append("p.source = 'geonames'")
            clauses.append("p.iso_country = 'CN'")
            clauses.append('p.level = 1')
        elif scope == SCOPE_ABROAD:
            clauses.append("p.source = 'geonames'")
            clauses.append('p.level = 1')
        elif scope == SCOPE_CN_GN:
            clauses.append("p.source = 'geonames'")
            clauses.append("p.iso_country = 'CN'")
            clauses.append('p.level = 1')
        else:
            clauses.append('1=0')
    else:
        clauses.append('p.parent_id = ?')
        params.append(parent_id)
    if _cn_tree_children(db, parent_id, scope):
        order_by = 'p.id'
    else:
        order_by = f'''
            CASE WHEN p.level = {LEVEL_MACRO} THEN 0
                 WHEN p.level = 7 THEN 1
                 WHEN p.level >= 8 THEN 3
                 ELSE 2 END,
            CASE WHEN p.level < 7 THEN p.sort_key END NULLS LAST,
            p.population DESC NULLS LAST,
            p.sort_key NULLS LAST,
            p.name_zh NULLS LAST,
            p.name_en NULLS LAST,
            p.id
        '''
    sql = f'''
        SELECT p.* FROM geo_places p
        WHERE {' AND '.join(clauses)}
        ORDER BY {order_by}
        LIMIT {int(limit)}
    '''
    rows = db.execute(sql, params).fetchall()
    return [_serialize_place_row(db, dict(r)) for r in rows]


def get_place(db, place_id):
    """单条地区元数据（多应用共用）。"""
    if not place_id or not geo_tables_ready(db):
        return None
    row = _fetch_place(db, place_id)
    if not row:
        return None
    return _serialize_place_row(db, row)


def get_breadcrumb(db, place_id):
    if not place_id or not geo_tables_ready(db):
        return []
    chain = []
    cur_id = place_id
    seen = set()
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = _fetch_place(db, cur_id)
        if not row:
            break
        item = _serialize_place_row(db, row)
        item['parent_id'] = row.get('parent_id')
        # 查询完整地理树，不能用截断后的子节点列表推断「独生」。
        parent_id = row.get('parent_id')
        sibling = db.execute(
            '''SELECT 1 FROM geo_places
               WHERE parent_id = ? AND id <> ? LIMIT 1''',
            (parent_id, row['id']),
        ).fetchone() if parent_id is not None else True
        item['has_siblings'] = bool(sibling)
        chain.append(item)
        cur_id = row.get('parent_id')
    chain.reverse()
    return chain


def format_location_display(db, place_id, extra_text=None):
    path = get_breadcrumb(db, place_id)
    if not path:
        return (extra_text or '').strip()
    scope = place_scope(_fetch_place(db, place_id))
    parts = []
    if scope == SCOPE_CN:
        for node in path:
            if node.get('source') == SOURCE_MACRO or node.get('level') == LEVEL_MACRO:
                continue
            name = node['display_name'] or ''
            if name:
                parts.append(name)
    else:
        for node in path:
            if node.get('source') == SOURCE_MACRO or node.get('level') == LEVEL_MACRO:
                continue
            name = node['display_name']
            if name:
                parts.append(name)
    text = ' '.join(parts).strip()
    extra = (extra_text or '').strip()
    if extra:
        if text:
            text = f'{text} {extra}'
        else:
            text = extra
    return text


def validate_place_for_profile(db, place_id):
    row = _fetch_place(db, place_id)
    if not row:
        raise ValueError('地区不存在')
    if row.get('source') == SOURCE_MACRO or row.get('level') == LEVEL_MACRO:
        raise ValueError('请选择具体省/市/地区，不能只选地理大区')
    if not row.get('is_selectable'):
        raise ValueError('该地区不可选')
    return row


def apply_user_location_from_place(db, place_id, location_extra=None):
    row = validate_place_for_profile(db, place_id)
    scope = place_scope(row)
    location = format_location_display(db, place_id, location_extra)
    return {
        'location_place_id': place_id,
        'location_scope': scope,
        'location': location or None,
    }


def clear_user_location():
    return {
        'location_place_id': None,
        'location_scope': None,
        'location': None,
    }


def attach_location_to_user_dict(db, user_dict):
    if not user_dict or not geo_tables_ready(db):
        return user_dict
    place_id = user_dict.get('location_place_id')
    if place_id:
        user_dict['location_path'] = get_breadcrumb(db, place_id)
    else:
        user_dict['location_path'] = []
    return user_dict


def get_geo_stats(db):
    """地理库概览（探索用）。"""
    if not geo_tables_ready(db):
        return {'ready': False}
    total = db.execute('SELECT COUNT(*) AS c FROM geo_places').fetchone()['c']
    by_source = [
        dict(r)
        for r in db.execute(
            'SELECT source, COUNT(*) AS count FROM geo_places GROUP BY source ORDER BY source'
        ).fetchall()
    ]
    cn_gn_levels = [
        dict(r)
        for r in db.execute(
            '''SELECT level, COUNT(*) AS count FROM geo_places
               WHERE source = 'geonames' AND iso_country = 'CN'
               GROUP BY level ORDER BY level'''
        ).fetchall()
    ]
    cn_gn_features = [
        dict(r)
        for r in db.execute(
            '''SELECT admin2_code AS feature, COUNT(*) AS count FROM geo_places
               WHERE source = 'geonames' AND iso_country = 'CN' AND level = 8
               GROUP BY admin2_code ORDER BY count DESC LIMIT 20'''
        ).fetchall()
    ]
    samples = [
        dict(r)
        for r in db.execute(
            '''SELECT id, level, name_zh, name_en, name_local, population, admin2_code
               FROM geo_places
               WHERE source = 'geonames' AND iso_country = 'CN'
               ORDER BY RANDOM() LIMIT 15'''
        ).fetchall()
    ]
    top_ppl = [
        dict(r)
        for r in db.execute(
            '''SELECT id, name_zh, name_en, name_local, population
               FROM geo_places
               WHERE source = 'geonames' AND iso_country = 'CN' AND level = 7
               ORDER BY population DESC NULLS LAST LIMIT 15'''
        ).fetchall()
    ]
    return {
        'ready': True,
        'total': total,
        'by_source': by_source,
        'cn_geonames_by_level': cn_gn_levels,
        'cn_geonames_top_feature_types': cn_gn_features,
        'cn_geonames_random_samples': samples,
        'cn_geonames_top_cities_by_population': top_ppl,
    }


def _search_path_label(db, place_id):
    path = get_breadcrumb(db, place_id)
    if len(path) <= 1:
        return ''
    parts = []
    for node in path[:-1]:
        if node.get('source') == SOURCE_MACRO and node.get('level') == LEVEL_MACRO:
            continue
        name = (node.get('display_name') or '').strip()
        if name:
            parts.append(name)
    return ' · '.join(parts[-4:])


def search_places(db, q, scope=None, limit=20):
    """Compatibility entry point; use the same structured search as the HTTP API."""
    from app.geo.search_query import search
    return search(db, {'q': q, 'scope': scope, 'limit': limit}, place_display_name)['items']


def normalize_area_token(text):
    s = (text or '').strip()
    if not s:
        return s
    for suffix in ADMIN_SUFFIXES:
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


def _match_ok_zh_children(db, parent_geo_id, token):
    token_norm = normalize_area_token(token)
    rows = db.execute(
        '''
        SELECT p.* FROM geo_places p
        WHERE p.source = 'ok_zh'
          AND COALESCE(p.parent_id, -1) = COALESCE(?, -1)
          AND p.is_selectable = TRUE
        ''',
        (parent_geo_id,),
    ).fetchall()
    exact = []
    fuzzy = []
    for row in rows:
        row = dict(row)
        names = {
            (row.get('name_zh') or '').strip(),
            (row.get('name_en') or '').strip(),
            normalize_area_token(row.get('name_zh') or ''),
            normalize_area_token(row.get('name_en') or ''),
        }
        names.discard('')
        if token.strip() in names or token_norm in names:
            exact.append(row)
        elif token_norm and any(token_norm in n or n in token_norm for n in names):
            fuzzy.append(row)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    if len(fuzzy) == 1:
        return fuzzy[0]
    return None


def _find_country(db, token):
    token = (token or '').strip()
    if not token:
        return None
    alias = COUNTRY_ALIASES.get(token)
    if alias:
        row = db.execute(
            '''
            SELECT p.* FROM geo_places p
            WHERE p.source = 'geonames' AND p.level = 1 AND p.iso_country = ?
            LIMIT 1
            ''',
            (alias,),
        ).fetchone()
        if row:
            return dict(row)
    row = db.execute(
        '''
        SELECT p.* FROM geo_places p
        WHERE p.source = 'geonames' AND p.level = 1
          AND (p.name_zh = ? OR p.name_en ILIKE ? OR p.iso_country = ?)
        LIMIT 1
        ''',
        (token, token, token.upper() if len(token) == 2 else '___'),
    ).fetchone()
    return dict(row) if row else None


def _match_geonames_child(db, parent_row, token):
    parent_id = parent_row['id']
    token_norm = normalize_area_token(token)
    rows = db.execute(
        '''
        SELECT p.* FROM geo_places p
        WHERE p.parent_id = ? AND p.is_selectable = TRUE
        ''',
        (parent_id,),
    ).fetchall()
    for row in rows:
        row = dict(row)
        names = {
            (row.get('name_zh') or '').strip(),
            (row.get('name_en') or '').strip(),
            normalize_area_token(row.get('name_zh') or ''),
            normalize_area_token(row.get('name_en') or ''),
        }
        names.discard('')
        if token.strip() in names or token_norm in names:
            return row
        if token_norm and any(token_norm in n or n in token_norm for n in names):
            return row
    return None


def resolve_legacy_location_text(db, text):
    """将 users.location 自由文本解析为 geo_places 节点。返回 (place_id, scope, extra_text)。"""
    raw = (text or '').strip()
    if not raw or not geo_tables_ready(db):
        return None, None, None
    if raw in ('中国大陆', '中国'):
        return None, SCOPE_CN, None

    parts = [p for p in re.split(r'\s+', raw) if p]
    if not parts:
        return None, None, None

    # 国内：首段能匹配省级 ok_zh
    prov = _match_ok_zh_children(db, None, parts[0])
    if prov:
        cur = prov
        idx = 1
        while idx < len(parts):
            nxt = _match_ok_zh_children(db, cur['id'], parts[idx])
            if not nxt:
                break
            cur = nxt
            idx += 1
        extra = ' '.join(parts[idx:]).strip() or None
        return cur['id'], SCOPE_CN, extra

    # 国外
    country = _find_country(db, parts[0])
    if not country:
        return None, None, raw
    cur = country
    idx = 1
    while idx < len(parts):
        nxt = _match_geonames_child(db, cur, parts[idx])
        if not nxt:
            break
        cur = nxt
        idx += 1
    extra = ' '.join(parts[idx:]).strip() or None
    return cur['id'], SCOPE_ABROAD, extra


def lookup_country_zh(iso2, fallback_en=None):
    return country_zh(iso2, fallback_en)


def lookup_admin1_zh(admin1_code, fallback_en=None):
    return admin1_zh(admin1_code, fallback_en)
