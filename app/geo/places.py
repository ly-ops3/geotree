"""geo_places 查询、展示与用户资料地区逻辑。"""

from __future__ import annotations

import re

from app.db import _table_exists
from app.geo.admin1_zh import admin1_zh
from app.geo.country_zh import COUNTRY_ALIASES, COUNTRY_ZH, country_zh
from app.geo.languages import language_fallbacks
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

from app.geo.un_m49 import (CONTINENTS, SUBREGIONS, isos_of_subregion,
                            region_of, region_names, subregions_of_continent)


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
        'parent_id': row.get('parent_id'),
        'level': row.get('level'),
        'display_name': place_display_name(row),
        'name_zh': row.get('name_zh'),
        'name_zh_hant': row.get('name_zh_hant'),
        'name_base': row.get('name_base'),
        'name_en': row.get('name_en'),
        'name_local': row.get('name_local'),
        'name_local_lang': row.get('name_local_lang'),
        'iso_country': row.get('iso_country'),
        'source': row.get('source'),
        'source_id': row.get('source_id'),
        'admin1_code': row.get('admin1_code'),
        'admin2_code': row.get('admin2_code'),
        'feature_class': row.get('feature_class'),
        'feature_code': row.get('feature_code'),
        'feature': row.get('feature_code') or (row.get('admin2_code') if (row.get('level') or 0) >= 8 else None),
        'pinyin': row.get('pinyin'),
        'population': row.get('population'),
        'latitude': row.get('latitude'),
        'longitude': row.get('longitude'),
        'area_km2': row.get('area_km2'),
        'capital': row.get('capital'),
        'continent': row.get('continent'),
        'deep_legacy': row.get('deep_legacy'),
        'is_selectable': row.get('is_selectable'),
        'sort_key': row.get('sort_key'),
        'has_children': _has_children(db, row['id']),
    }
    if row.get('level') == 1:
        cont, sub = region_of(row.get('iso_country'))
        item['continent_zh'], item['continent_en'] = region_names(cont, CONTINENTS)
        item['subregion_zh'], item['subregion_en'] = region_names(sub, SUBREGIONS)
    return item


def _cn_tree_children(db, parent_id=None, scope=None) -> bool:
    """两岸四地（ok_zh + CN 大区）级联子节点按 id 排序。"""
    if scope == SCOPE_CN:
        return True
    if parent_id is not None:
        return place_scope(_fetch_place(db, parent_id)) == SCOPE_CN
    return False


def _virtual_region_item(code, table, has_children=True):
    zh, en = region_names(code, table)
    return {
        'id': -code,
        'level': 0,
        'display_name': f'{zh} ({en})' if zh != en else zh,
        'name_zh': zh,
        'name_en': en,
        'name_local': None,
        'iso_country': None,
        'source': 'region',
        'feature': 'region',
        'has_children': has_children,
        'virtual': True,
    }


def get_children(db, parent_id=None, scope=None, limit=2000, flat=False):
    if not geo_tables_ready(db):
        return []
    # 虚拟层级：abroad 根 → 大洲 → 地理区 → 国家（flat 时跳过，直接给国家列表）
    if parent_id is None and scope == SCOPE_ABROAD and not flat:
        return [_virtual_region_item(c, CONTINENTS) for c in CONTINENTS]
    if parent_id is not None and parent_id < 0:
        code = -parent_id
        if code in CONTINENTS:
            return [_virtual_region_item(s, SUBREGIONS)
                    for s in subregions_of_continent(code)]
        if code in SUBREGIONS:
            isos = isos_of_subregion(code)
            if not isos:
                return []
            marks = ','.join('?' for _ in isos)
            rows = db.execute(
                f"""SELECT p.* FROM geo_places p
                    WHERE p.parent_id IS NULL AND p.source = 'geonames'
                      AND p.level = 1 AND p.iso_country IN ({marks})
                    ORDER BY p.sort_key NULLS LAST, p.name_zh NULLS LAST,
                             p.name_en NULLS LAST, p.id""",
                isos,
            ).fetchall()
            return [_serialize_place_row(db, dict(r)) for r in rows]
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
            '''SELECT COALESCE(feature_code, admin2_code) AS feature, COUNT(*) AS count FROM geo_places
               WHERE source = 'geonames' AND iso_country = 'CN' AND level = 8
               GROUP BY 1 ORDER BY count DESC LIMIT 20'''
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


def _match_ok_zh_children(db, parent_geo_id, token, fuzzy=True):
    token_norm = normalize_area_token(token)
    if parent_geo_id is None:
        # ok_zh 省级节点挂在大区（macro）下，顶层匹配按 level=2 取
        rows = db.execute(
            '''
            SELECT p.* FROM geo_places p
            WHERE p.source = 'ok_zh' AND p.level = 2 AND p.is_selectable = TRUE
            ''',
        ).fetchall()
    else:
        rows = db.execute(
            '''
            SELECT p.* FROM geo_places p
            WHERE p.source = 'ok_zh'
              AND p.parent_id = ?
              AND p.is_selectable = TRUE
            ''',
            (parent_geo_id,),
        ).fetchall()
    exact = []
    fuzzy_hits = []
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
        elif fuzzy and token_norm and any(token_norm in n or n in token_norm for n in names):
            fuzzy_hits.append(row)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    if len(fuzzy_hits) == 1:
        return fuzzy_hits[0]
    return None


# 中国省级行政区英文名 → 标准中文名（ok_zh 无英文名，GeoNames CN gazetteer 未入库时的桥）
CN_PROVINCE_EN = {
    'beijing': '北京市', 'tianjin': '天津市', 'hebei': '河北省', 'shanxi': '山西省',
    'inner mongolia': '内蒙古自治区', 'nei mongol': '内蒙古自治区', 'liaoning': '辽宁省',
    'jilin': '吉林省', 'heilongjiang': '黑龙江省', 'shanghai': '上海市', 'jiangsu': '江苏省',
    'zhejiang': '浙江省', 'anhui': '安徽省', 'fujian': '福建省', 'jiangxi': '江西省',
    'shandong': '山东省', 'henan': '河南省', 'hubei': '湖北省', 'hunan': '湖南省',
    'guangdong': '广东省', 'guangxi': '广西壮族自治区', 'hainan': '海南省',
    'chongqing': '重庆市', 'sichuan': '四川省', 'guizhou': '贵州省', 'yunnan': '云南省',
    'tibet': '西藏自治区', 'xizang': '西藏自治区', 'shaanxi': '陕西省', 'gansu': '甘肃省',
    'qinghai': '青海省', 'ningxia': '宁夏回族自治区', 'xinjiang': '新疆维吾尔自治区',
    'hong kong': '香港特别行政区', 'macau': '澳门特别行政区', 'macao': '澳门特别行政区',
    'taiwan': '台湾省',
}


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


def _resolve_leading_node(db, parts):
    """首段解析：多词实体（New Zealand / Inner Mongolia）按最长前缀分组试配。
    返回 (row, consumed, scope)，未命中返回 (None, 0, None)。
    多词段只允许精确匹配——避免 '内蒙古 通辽' 被模糊吸收进省级。"""
    for size in range(len(parts), 0, -1):
        seg = ' '.join(parts[:size])
        prov = _match_ok_zh_children(db, None, seg, fuzzy=(size == 1))
        if prov:
            return prov, size, SCOPE_CN
        country = _find_country(db, seg)
        if country:
            return country, size, SCOPE_ABROAD
        # 英文省名桥：Inner Mongolia 通辽 → 内蒙古自治区 → ok_zh 下行
        en_prov = CN_PROVINCE_EN.get(seg.lower())
        if en_prov:
            prov = _match_ok_zh_children(db, None, en_prov, fuzzy=False)
            if prov:
                return prov, size, SCOPE_CN
    return None, 0, None


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

    cur, idx, scope = _resolve_leading_node(db, parts)
    if not cur:
        return None, None, raw
    matcher = _match_ok_zh_children if scope == SCOPE_CN else _match_geonames_child
    while idx < len(parts):
        nxt = matcher(db, cur['id'] if scope == SCOPE_CN else cur, parts[idx])
        if not nxt:
            break
        cur = nxt
        idx += 1
    extra = ' '.join(parts[idx:]).strip() or None
    return cur['id'], scope, extra


def lookup_country_zh(iso2, fallback_en=None):
    return country_zh(iso2, fallback_en)


def lookup_admin1_zh(admin1_code, fallback_en=None):
    return admin1_zh(admin1_code, fallback_en)


def list_languages(db):
    if not _table_exists(db, 'geo_languages'):
        return []
    rows = db.execute(
        'SELECT code, iso639, name_en FROM geo_languages ORDER BY code'
    ).fetchall()
    return [
        {'code': row['code'], 'iso639': row['iso639'], 'name_en': row['name_en']}
        for row in rows
    ]


def list_place_names(db, place_id):
    if not place_id or not _table_exists(db, 'geo_place_names'):
        return []
    rows = db.execute(
        '''SELECT n.lang_code, n.name, n.is_preferred, l.name_en AS language_en
           FROM geo_place_names n
           LEFT JOIN geo_languages l ON l.code = n.lang_code
           WHERE n.place_id = ?
           ORDER BY n.lang_code''',
        (place_id,),
    ).fetchall()
    return [
        {
            'lang': row['lang_code'],
            'name': row['name'],
            'preferred': bool(row['is_preferred']),
            'language_en': row['language_en'],
        }
        for row in rows
    ]


def _apply_localized_display(item):
    localized = (item.get('name_in_lang') or '').strip()
    if not localized:
        return
    anchor = (item.get('name_local') or item.get('name_en') or '').strip()
    if anchor and anchor != localized:
        item['display_name'] = f'{localized} ({anchor})'
    else:
        item['display_name'] = localized


_ZH_HANT_REQUEST = frozenset({'zh-tw', 'zh-hk', 'zh-mo', 'zh-hant'})


def _wants_hant(lang) -> bool:
    return (lang or '').lower().replace('_', '-') in _ZH_HANT_REQUEST


def _hant_fallback(items):
    """zh-TW 等请求：geo_place_names 没命中时用 name_zh_hant 列兜底。"""
    nodes = []
    for item in items:
        if not item:
            continue
        nodes.append(item)
        nodes.extend(n for n in (item.get('path') or []) if n is not item)
    for node in nodes:
        if node.get('name_in_lang'):
            continue
        hant = (node.get('name_zh_hant') or '').strip()
        if hant:
            node['name_in_lang'] = hant
            node['name_in_lang_code'] = 'zh-Hant'
            _apply_localized_display(node)


def localize_items(db, items, lang):
    """按请求语种填 name_in_lang，并只在传入 lang 时改 display_name。"""
    if not lang or not items:
        return items
    if not _table_exists(db, 'geo_place_names'):
        if _wants_hant(lang):
            _hant_fallback(items)
        return items
    codes = language_fallbacks(lang)
    if not codes:
        if _wants_hant(lang):
            _hant_fallback(items)
        return items
    nodes = []
    for item in items:
        if not item:
            continue
        nodes.append(item)
        for node in item.get('path') or []:
            if node is not item:
                nodes.append(node)
    ids = list({node['id'] for node in nodes if node.get('id')})
    if not ids:
        return items
    id_marks = ','.join('?' for _ in ids)
    code_marks = ','.join('?' for _ in codes)
    rows = db.execute(
        f'''SELECT place_id, lang_code, name FROM geo_place_names
            WHERE place_id IN ({id_marks}) AND lang_code IN ({code_marks})''',
        [*ids, *codes],
    ).fetchall()
    rank = {code: index for index, code in enumerate(codes)}
    best = {}
    for row in rows:
        prev = best.get(row['place_id'])
        if prev is None or rank[row['lang_code']] < rank[prev[0]]:
            best[row['place_id']] = (row['lang_code'], row['name'])
    for node in nodes:
        hit = best.get(node.get('id'))
        if not hit:
            continue
        node['name_in_lang'] = hit[1]
        node['name_in_lang_code'] = hit[0]
        _apply_localized_display(node)
    if _wants_hant(lang):
        _hant_fallback(items)
    for item in items:
        path = item.get('path') if item else None
        if not path:
            continue
        item['path_label'] = ' · '.join(
            node['display_name'] for node in path[:-1]
            if node.get('source') != 'macro'
            and not (node.get('is_administrative') and node.get('has_siblings') is False)
        )
    return items
