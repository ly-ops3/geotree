"""GeoNames 中文名修复：全球清除错误上级回退 + 按国家 Wikidata / 维基 / 规则补全。"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any

import requests

from app.geo.geo_fixup_profiles import (
    SKIP_ISO2,
    CountryFixupProfile,
    get_profile,
    list_fixup_countries,
)
from app.geo.names_zh import admin1_name_zh

LEVEL_ADM1 = 2

_LOG_EVERY_RULE = 200
_COMMIT_EVERY = 5000
_WIKI_BATCH_SIZE = 50
_WIKI_BATCH_INTERVAL = 1.2

WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
_WIKI_USER_AGENT = (
    'wechat-moments-pro/2.1 geo-fixup '
    '(local batch; https://www.mediawiki.org/wiki/API:Etiquette)'
)
_WIKI_REACH_CACHE: dict[str, tuple[bool, int, str]] = {}


class WikipediaAccessError(RuntimeError):
    """Wikipedia API 不可达（含 GFW 403）。"""

_EN_ADMIN_SUFFIXES: tuple[tuple[str, str], ...] = (
    (' Census Area', '人口普查区'),
    (' Municipality', '市镇'),
    (' Borough', '自治市镇'),
    (' Parish', '堂区'),
    (' Shire', '郡'),
    (' County', '县'),
    (' District', '区'),
    (' Division', '区'),
)

_GEO_TOKENS: dict[str, str] = {
    'saint': '圣', 'st': '圣', 'st.': '圣', 'fort': '福特', 'mount': '芒特',
    'north': '北', 'south': '南', 'east': '东', 'west': '西', 'new': '新',
    'san': '圣', 'santa': '圣', 'los': '洛斯', 'las': '拉斯', 'grand': '大',
}

_STEM_ZH: dict[str, str] = {
    'baker': '贝克', 'benton': '本顿', 'columbia': '哥伦比亚', 'douglas': '道格拉斯',
    'franklin': '富兰克林', 'hamilton': '汉密尔顿', 'jackson': '杰克逊',
    'jefferson': '杰斐逊', 'lincoln': '林肯', 'madison': '麦迪逊', 'marion': '马里昂',
    'montgomery': '蒙哥马利', 'washington': '华盛顿', 'wayne': '韦恩', 'york': '约克',
}

_SYLLABLE_ZH: dict[str, str] = {
    'ba': '巴', 'be': '贝', 'ber': '伯', 'bo': '博', 'ca': '卡', 'co': '科',
    'da': '达', 'de': '德', 'el': '埃尔', 'en': '恩', 'er': '尔', 'es': '斯',
    'fr': '弗', 'ga': '加', 'gr': '格', 'ha': '哈', 'in': '因', 'la': '拉',
    'le': '勒', 'li': '利', 'lo': '洛', 'ma': '马', 'me': '梅', 'mi': '米',
    'mo': '莫', 'na': '纳', 'ne': '内', 'no': '诺', 'or': '奥', 'pa': '帕',
    'ri': '里', 'ro': '罗', 'sa': '萨', 'se': '塞', 'sh': '什', 'si': '西',
    'st': '斯特', 'ta': '塔', 'te': '特', 'to': '托', 'un': '尤', 'va': '瓦',
    'wa': '瓦', 'wi': '威', 'ton': '顿', 'son': '逊', 'ville': '维尔',
    'baker': '贝克', 'ford': '福德', 'port': '波特', 'land': '兰',
}

_TRAD_TO_SIMP = str.maketrans({
    '縣': '县', '區': '区', '島': '岛', '奧': '奥', '爾': '尔', '灣': '湾',
    '東': '东', '達': '达', '華': '华', '薩': '萨', '貝': '贝', '國': '国',
    '際': '际', '倫': '伦', '亞': '亚', '羅': '罗', '馬': '马', '諾': '诺',
})


def _log(msg: str) -> None:
    print(msg, flush=True)


def to_simplified_zh(text: str) -> str:
    text = (text or '').translate(_TRAD_TO_SIMP)
    try:
        from app.geo.names_zh import to_simplified
        return to_simplified(text)
    except ImportError:
        return text


def normalize_place_zh(label: str) -> str:
    label = to_simplified_zh((label or '').strip())
    for sep in ('（', '('):
        if sep in label:
            label = label.split(sep, 1)[0].strip()
    return label


def is_bad_admin1_fallback(row: dict[str, Any]) -> bool:
    level = row.get('level') or 0
    if level <= LEVEL_ADM1:
        return False
    name_zh = (row.get('name_zh') or '').strip()
    if not name_zh:
        return False
    a1zh = admin1_name_zh(row.get('admin1_code'))
    if not a1zh or name_zh != a1zh:
        return False
    return (row.get('name_en') or '').strip() != a1zh


def clear_bad_parent_fallbacks(db, *, dry_run: bool = False) -> int:
    """清除 name_zh 与直接上级相同、但与英文名不符的节点（全球 geonames）。"""
    row = db.execute(
        """SELECT COUNT(*) AS c
           FROM geo_places g
           INNER JOIN geo_places par ON par.id = g.parent_id
           WHERE g.source = 'geonames'
             AND g.level > par.level
             AND g.name_zh IS NOT NULL AND TRIM(g.name_zh) <> ''
             AND g.name_zh = par.name_zh
             AND COALESCE(TRIM(g.name_en), '') <> g.name_zh"""
    ).fetchone()
    n = int(row['c'] if row else 0)
    _log(f'  直接上级误填: {n} 条')
    if n == 0 or dry_run:
        return n
    cur = db.execute(
        """UPDATE geo_places g SET name_zh = NULL
           FROM geo_places par
           WHERE par.id = g.parent_id
             AND g.source = 'geonames'
             AND g.level > par.level
             AND g.name_zh IS NOT NULL AND TRIM(g.name_zh) <> ''
             AND g.name_zh = par.name_zh
             AND COALESCE(TRIM(g.name_en), '') <> g.name_zh"""
    )
    db.commit()
    return int(cur.rowcount or n)


def clear_bad_admin1_fallbacks(db, *, dry_run: bool = False) -> int:
    """清除 name_zh 与 ADM1 省州名相同的情况（全球 geonames）。"""
    row = db.execute(
        """SELECT COUNT(*) AS c
           FROM geo_places g
           INNER JOIN geo_places a1
             ON a1.source = 'geonames' AND a1.level = ?
            AND a1.iso_country = g.iso_country AND a1.admin1_code = g.admin1_code
           WHERE g.source = 'geonames' AND g.level > ?
             AND g.admin1_code IS NOT NULL
             AND g.name_zh IS NOT NULL AND TRIM(g.name_zh) <> ''
             AND g.name_zh = a1.name_zh
             AND COALESCE(TRIM(g.name_en), '') <> g.name_zh""",
        (LEVEL_ADM1, LEVEL_ADM1),
    ).fetchone()
    n = int(row['c'] if row else 0)
    _log(f'  ADM1 省州误填: {n} 条')
    if n == 0 or dry_run:
        return n
    cur = db.execute(
        """UPDATE geo_places g SET name_zh = NULL
           FROM geo_places a1
           WHERE a1.source = 'geonames' AND a1.level = ?
             AND a1.iso_country = g.iso_country AND a1.admin1_code = g.admin1_code
             AND g.source = 'geonames' AND g.level > ?
             AND g.admin1_code IS NOT NULL
             AND g.name_zh IS NOT NULL AND TRIM(g.name_zh) <> ''
             AND g.name_zh = a1.name_zh
             AND COALESCE(TRIM(g.name_en), '') <> g.name_zh""",
        (LEVEL_ADM1, LEVEL_ADM1),
    )
    db.commit()
    return int(cur.rowcount or n)


def clear_all_bad_fallbacks(db, *, dry_run: bool = False) -> dict[str, int]:
    _log('[全局] 清除误用上级行政区中文名 ...')
    t0 = time.time()
    p = clear_bad_parent_fallbacks(db, dry_run=dry_run)
    a = clear_bad_admin1_fallbacks(db, dry_run=dry_run)
    _log(f'  合计清除 {p + a} 条 ({time.time() - t0:.1f}s)')
    return {'parent': p, 'admin1': a, 'total': p + a}


def fetch_wikidata_zh_for_country(
    wikidata_q: str,
    *,
    timeout: int = 180,
    retries: int = 4,
) -> dict[str, str]:
    query = f"""
SELECT ?geonameId ?nameZh WHERE {{
  ?item wdt:P17 wd:{wikidata_q} ;
        wdt:P1566 ?geonameId .
  ?item rdfs:label ?nameZh .
  FILTER(LANG(?nameZh) = "zh")
}}
"""
    headers = {
        'Accept': 'application/sparql-results+json',
        'User-Agent': _WIKI_USER_AGENT,
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                WIKIDATA_SPARQL,
                params={'query': query, 'format': 'json'},
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            out: dict[str, str] = {}
            for binding in resp.json().get('results', {}).get('bindings', []):
                gid = binding.get('geonameId', {}).get('value')
                zh = binding.get('nameZh', {}).get('value')
                if not gid or not zh:
                    continue
                zh = normalize_place_zh(zh)
                if zh and any('\u4e00' <= ch <= '\u9fff' for ch in zh):
                    out[str(gid)] = zh
            return out
        except Exception as exc:
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise last_err or RuntimeError(f'Wikidata failed for {wikidata_q}')


def check_wikipedia_langlinks(wiki_api: str, *, timeout: int = 15) -> tuple[bool, int, str]:
    """探测 langlinks 查询是否可用（比 siteinfo 更能反映实际补全能力）。"""
    cached = _WIKI_REACH_CACHE.get(wiki_api)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            wiki_api,
            params={
                'action': 'query',
                'titles': 'China',
                'prop': 'langlinks',
                'lllang': 'zh',
                'format': 'json',
            },
            headers={'User-Agent': _WIKI_USER_AGENT},
            timeout=timeout,
        )
        if resp.status_code == 403:
            result = (False, 403, 'HTTP 403，疑似 GFW/网络限制，可配置代理或境外运行')
        elif resp.status_code != 200:
            result = (False, resp.status_code, (resp.text or '')[:160])
        elif resp.json().get('error'):
            err = resp.json()['error']
            result = (False, resp.status_code, str(err.get('info') or err))
        else:
            result = (True, 200, '')
    except requests.RequestException as exc:
        result = (False, 0, str(exc))
    _WIKI_REACH_CACHE[wiki_api] = result
    return result


def _wiki_request(wiki_api: str, params: dict, *, timeout: int = 45, retries: int = 6) -> requests.Response:
    headers = {'User-Agent': _WIKI_USER_AGENT}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(wiki_api, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(min(60, 2 ** attempt))
            continue
        if resp.status_code == 429:
            wait = int(resp.headers.get('Retry-After') or min(90, 10 * (attempt + 1)))
            _log(f'    Wikipedia 429，等待 {wait}s ...')
            time.sleep(wait)
            continue
        if resp.status_code == 403:
            raise WikipediaAccessError(
                f'Wikipedia HTTP 403（{wiki_api}），疑似 GFW/网络限制'
            )
        if resp.status_code >= 500:
            time.sleep(min(30, 2 ** attempt))
            continue
        resp.raise_for_status()
        return resp
    raise last_exc or RuntimeError('Wikipedia API failed')


def fetch_wikipedia_zh_batch(titles: list[str], *, wiki_api: str) -> dict[str, str]:
    if not titles:
        return {}
    title_set = {t: t for t in titles}
    resp = _wiki_request(wiki_api, {
        'action': 'query',
        'titles': '|'.join(titles),
        'prop': 'langlinks',
        'lllang': 'zh',
        'format': 'json',
        'redirects': 1,
    })
    out: dict[str, str] = {}
    lower_map = {t.lower(): t for t in titles}
    for page in resp.json().get('query', {}).get('pages', {}).values():
        if page.get('missing'):
            continue
        title = page.get('title') or ''
        orig = title_set.get(title) or lower_map.get(title.lower())
        if not orig:
            continue
        links = page.get('langlinks') or []
        if not links:
            continue
        zh = normalize_place_zh(links[0].get('*', ''))
        if zh and any('\u4e00' <= ch <= '\u9fff' for ch in zh):
            out[orig] = zh
    return out


def _greedy_syllables(word: str) -> str | None:
    word = re.sub(r'[^a-z]', '', word.lower())
    if not word:
        return None
    if word in _STEM_ZH:
        return _STEM_ZH[word]
    out, i = [], 0
    while i < len(word):
        matched = ''
        for size in range(min(8, len(word) - i), 0, -1):
            piece = word[i : i + size]
            if piece in _SYLLABLE_ZH:
                matched = _SYLLABLE_ZH[piece]
                i += size
                break
        if not matched:
            return None
        out.append(matched)
    return ''.join(out)


def rule_english_admin_zh(name_en: str | None) -> str | None:
    name_en = (name_en or '').strip()
    if not name_en or not re.match(r"^[A-Za-z][A-Za-z .'\-]+$", name_en):
        return None
    stem, suffix_zh = name_en, ''
    for en_suffix, zh_suffix in _EN_ADMIN_SUFFIXES:
        if name_en.endswith(en_suffix):
            stem = name_en[: -len(en_suffix)].strip()
            suffix_zh = zh_suffix
            break
    if not suffix_zh or not stem:
        return None
    raw = stem.lower().replace('-', ' ').replace('.', ' ').strip()
    raw = re.sub(r'\s+', ' ', raw)
    if raw in _STEM_ZH:
        return _STEM_ZH[raw] + suffix_zh
    parts = []
    for part in raw.split():
        token = _GEO_TOKENS.get(part.rstrip('.'))
        if token:
            parts.append(token)
            continue
        piece = _greedy_syllables(part)
        if not piece:
            return None
        parts.append(piece)
    joined = ''.join(parts)
    if joined and any('\u4e00' <= ch <= '\u9fff' for ch in joined):
        return joined + suffix_zh
    return None


def _candidates(db, iso2: str, level: int):
    return db.execute(
        """SELECT id, source_id, name_en, name_zh, admin1_code, parent_id, level
           FROM geo_places
           WHERE source = 'geonames' AND iso_country = ? AND level = ?
             AND (name_zh IS NULL OR TRIM(name_zh) = '')""",
        (iso2.upper(), level),
    ).fetchall()


def _count_missing(db, iso2: str, levels: tuple[int, ...]) -> int:
    if not levels:
        return 0
    placeholders = ','.join('?' * len(levels))
    row = db.execute(
        f"""SELECT COUNT(*) AS c FROM geo_places
            WHERE source = 'geonames' AND iso_country = ?
              AND level IN ({placeholders})
              AND (name_zh IS NULL OR TRIM(name_zh) = '')""",
        (iso2.upper(), *levels),
    ).fetchone()
    return int(row['c'] if row else 0)


def _admin1_en_map(db, iso2: str) -> dict[str, str]:
    rows = db.execute(
        """SELECT admin1_code, name_en FROM geo_places
           WHERE source = 'geonames' AND iso_country = ? AND level = ?""",
        (iso2.upper(), LEVEL_ADM1),
    ).fetchall()
    return {r['admin1_code']: r['name_en'] for r in rows if r.get('admin1_code')}


def _parent_en(db, row, profile: CountryFixupProfile, admin1_map: dict[str, str]) -> str:
    if profile.wiki_parent_level == LEVEL_ADM1:
        return admin1_map.get(row.get('admin1_code') or '', '') or ''
    pid = row.get('parent_id')
    if not pid:
        return ''
    p = db.execute('SELECT name_en FROM geo_places WHERE id = ?', (pid,)).fetchone()
    return (p['name_en'] or '') if p else ''


def _wiki_name_stem(name_en: str) -> str:
    name_en = (name_en or '').strip()
    if name_en.endswith(' City'):
        return name_en[:-5].strip()
    return name_en


def _format_wiki_title(template: str, name_en: str, parent_en: str) -> str | None:
    if '{parent_en}' in template and not parent_en:
        if '{name_en}' not in template and '{name_stem}' not in template:
            return None
    name_stem = _wiki_name_stem(name_en)
    title = template.format(name_en=name_en, parent_en=parent_en, name_stem=name_stem)
    return title.strip() or None


def _wiki_title_variants(profile: CountryFixupProfile, name_en: str, parent_en: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for template in profile.wiki_title_templates:
        title = _format_wiki_title(template, name_en, parent_en)
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(title)
    return out


def apply_altnames(db, iso2: str, levels: tuple[int, ...], *, dry_run: bool = False) -> int:
    from app.geo.names_zh import ensure_zh_altnames_db

    db_path = ensure_zh_altnames_db(download=False)
    if not os.path.isfile(db_path) or os.path.getsize(db_path) < 1024:
        return 0
    conn = sqlite3.connect(db_path)
    updated = pending = 0
    try:
        for level in levels:
            rows = _candidates(db, iso2, level)
            for row in rows:
                try:
                    gid = int(row['source_id'])
                except (TypeError, ValueError):
                    continue
                alt = conn.execute(
                    'SELECT name_zh FROM zh_names WHERE geonameid = ?', (gid,)
                ).fetchone()
                if not alt or not alt[0]:
                    continue
                zh = normalize_place_zh(alt[0])
                if not zh:
                    continue
                updated += 1
                if not dry_run:
                    db.execute(
                        'UPDATE geo_places SET name_zh = ? WHERE id = ?', (zh, row['id'])
                    )
                    pending += 1
                    if pending >= _COMMIT_EVERY:
                        db.commit()
                        pending = 0
    finally:
        conn.close()
    if not dry_run and pending:
        db.commit()
    return updated


def apply_wikidata(db, iso2: str, profile: CountryFixupProfile, mapping: dict[str, str], *, dry_run: bool) -> int:
    updated = pending = 0
    for level in profile.target_levels:
        rows = _candidates(db, iso2, level)
        for i, row in enumerate(rows, 1):
            zh = mapping.get(str(row['source_id']))
            if not zh:
                continue
            updated += 1
            if not dry_run:
                db.execute('UPDATE geo_places SET name_zh = ? WHERE id = ?', (zh, row['id']))
                pending += 1
                if pending >= _COMMIT_EVERY:
                    db.commit()
                    pending = 0
            if i % _LOG_EVERY_RULE == 0:
                _log(f'    Wikidata L{level} {i}/{len(rows)} +{updated}')
    if not dry_run and pending:
        db.commit()
    return updated


def apply_wikipedia(
    db,
    iso2: str,
    profile: CountryFixupProfile,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    ok, status, hint = check_wikipedia_langlinks(profile.wiki_api)
    if not ok:
        _log(f'    Wikipedia 跳过: HTTP {status} {hint}')
        return 0

    admin1_map = _admin1_en_map(db, iso2)
    work: list[tuple[dict, list[str]]] = []
    for level in profile.target_levels:
        for row in _candidates(db, iso2, level):
            name_en = row.get('name_en') or ''
            if not name_en:
                continue
            parent_en = _parent_en(db, row, profile, admin1_map)
            variants = _wiki_title_variants(profile, name_en, parent_en)
            if not variants:
                continue
            work.append((dict(row), variants))
    if limit is not None:
        work = work[:limit]
    total = len(work)
    if not total:
        return 0

    templates_n = max(len(v) for _, v in work)
    _log(
        f'    Wikipedia {total} 条 / 最多 {templates_n} 轮标题 '
        f'({profile.wiki_api.split("/")[2]})'
    )
    resolved: dict[int, str] = {}
    updated = pending = 0

    for pass_idx in range(templates_n):
        pass_work = [
            (row, variants[pass_idx])
            for row, variants in work
            if row['id'] not in resolved and pass_idx < len(variants)
        ]
        if not pass_work:
            break
        if pass_idx > 0:
            _log(f'    标题回退 第 {pass_idx + 1}/{templates_n} 轮 ({len(pass_work)} 条)')

        batches = (len(pass_work) + _WIKI_BATCH_SIZE - 1) // _WIKI_BATCH_SIZE
        processed = 0
        pass_updated = 0
        blocked = False
        for batch_no, start in enumerate(range(0, len(pass_work), _WIKI_BATCH_SIZE), 1):
            chunk = pass_work[start : start + _WIKI_BATCH_SIZE]
            titles = [t for _, t in chunk]
            try:
                mapping = fetch_wikipedia_zh_batch(titles, wiki_api=profile.wiki_api)
            except WikipediaAccessError as exc:
                _log(f'    Wikipedia 中止: {exc}')
                blocked = True
                break
            except Exception as exc:
                _log(f'    批次 {batch_no}/{batches} 失败: {exc}')
                time.sleep(_WIKI_BATCH_INTERVAL * 5)
                continue
            for row, title in chunk:
                processed += 1
                zh = mapping.get(title)
                if not zh:
                    continue
                resolved[row['id']] = zh
                pass_updated += 1
                updated += 1
                if not dry_run:
                    db.execute('UPDATE geo_places SET name_zh = ? WHERE id = ?', (zh, row['id']))
                    pending += 1
                    if pending >= _COMMIT_EVERY:
                        db.commit()
                        pending = 0
            if pass_idx == 0 and (batch_no == 1 or batch_no % 10 == 0 or batch_no == batches):
                _log(f'    批次 {batch_no}/{batches} | {processed}/{len(pass_work)} | +{updated}')
            if batch_no < batches:
                time.sleep(_WIKI_BATCH_INTERVAL)
        if blocked:
            break
        if pass_idx > 0 and pass_updated:
            _log(f'    第 {pass_idx + 1} 轮 +{pass_updated}（累计 +{updated}）')

    if not dry_run and pending:
        db.commit()
    return updated


def apply_rule(db, iso2: str, profile: CountryFixupProfile, *, dry_run: bool = False) -> int:
    if not profile.rule_english:
        return 0
    updated = pending = 0
    for level in profile.target_levels:
        rows = _candidates(db, iso2, level)
        for i, row in enumerate(rows, 1):
            zh = rule_english_admin_zh(row.get('name_en'))
            if not zh:
                continue
            updated += 1
            if not dry_run:
                db.execute('UPDATE geo_places SET name_zh = ? WHERE id = ?', (zh, row['id']))
                pending += 1
                if pending >= _COMMIT_EVERY:
                    db.commit()
                    pending = 0
            if i % _LOG_EVERY_RULE == 0:
                _log(f'    规则 L{level} {i}/{len(rows)} +{updated}')
    if not dry_run and pending:
        db.commit()
    return updated


def run_country_fixup(
    db,
    iso2: str,
    *,
    dry_run: bool = False,
    skip_wikidata: bool = False,
    skip_altnames: bool = False,
    skip_wikipedia: bool = False,
    skip_rule: bool = False,
    wikipedia_limit: int | None = None,
) -> dict[str, int]:
    iso2 = iso2.upper()
    if iso2 in SKIP_ISO2:
        _log(f'[{iso2}] 跳过（大中华区用 ok_zh）')
        return {}
    profile = get_profile(iso2)
    missing = _count_missing(db, iso2, profile.target_levels)
    _log(f'[{iso2}] levels={profile.target_levels} 缺中文={missing}')
    if missing == 0:
        return {'altnames': 0, 'wikidata': 0, 'wikipedia': 0, 'rule': 0, 'remaining': 0}

    stats = {'altnames': 0, 'wikidata': 0, 'wikipedia': 0, 'rule': 0}
    if not skip_altnames:
        stats['altnames'] = apply_altnames(db, iso2, profile.target_levels, dry_run=dry_run)
        if stats['altnames']:
            _log(f'  alternateNames +{stats["altnames"]}')

    if not skip_wikidata and profile.wikidata_q:
        try:
            t0 = time.time()
            mapping = fetch_wikidata_zh_for_country(profile.wikidata_q)
            _log(f'  Wikidata 词典 {len(mapping)} ({time.time() - t0:.1f}s)')
            stats['wikidata'] = apply_wikidata(db, iso2, profile, mapping, dry_run=dry_run)
            _log(f'  Wikidata +{stats["wikidata"]}')
        except Exception as exc:
            _log(f'  Wikidata 跳过: {exc}')
    elif not skip_wikidata:
        _log('  Wikidata 跳过: 无国家 Q  id')

    if not skip_wikipedia:
        stats['wikipedia'] = apply_wikipedia(
            db, iso2, profile, dry_run=dry_run, limit=wikipedia_limit,
        )
        _log(f'  Wikipedia +{stats["wikipedia"]}')

    if not skip_rule:
        stats['rule'] = apply_rule(db, iso2, profile, dry_run=dry_run)
        _log(f'  规则 +{stats["rule"]}')

    stats['remaining'] = _count_missing(db, iso2, profile.target_levels)
    _log(f'[{iso2}] 仍缺中文 {stats["remaining"]}')
    return stats


def run_fixup(
    db,
    *,
    countries: list[str] | None = None,
    dry_run: bool = False,
    skip_wikidata: bool = False,
    skip_altnames: bool = False,
    skip_wikipedia: bool = True,
    skip_rule: bool = False,
    wikipedia_limit: int | None = None,
    skip_global_clear: bool = False,
) -> dict[str, Any]:
    t_all = time.time()
    _log('=' * 60)
    _log('geo name_zh fixup')
    _log(
        f'  dry_run={dry_run} wikidata={not skip_wikidata} '
        f'wikipedia={not skip_wikipedia} rule={not skip_rule}'
    )

    if countries is None or len(countries) == 0:
        countries = ['US']
    elif len(countries) == 1 and countries[0].upper() == 'ALL':
        countries = list_fixup_countries(db)
        _log(f'  国家 ALL: {len(countries)} 个')

    _log(f'  国家: {", ".join(countries[:20])}' + (' ...' if len(countries) > 20 else ''))
    _log('=' * 60)

    result: dict[str, Any] = {'cleared': {}, 'countries': {}}
    if not skip_global_clear:
        result['cleared'] = clear_all_bad_fallbacks(db, dry_run=dry_run)

    for iso in countries:
        result['countries'][iso.upper()] = run_country_fixup(
            db,
            iso,
            dry_run=dry_run,
            skip_wikidata=skip_wikidata,
            skip_altnames=skip_altnames,
            skip_wikipedia=skip_wikipedia,
            skip_rule=skip_rule,
            wikipedia_limit=wikipedia_limit,
        )

    _log('=' * 60)
    _log(f'全部完成 ({time.time() - t_all:.1f}s)')
    return result


# 兼容旧 import
fetch_wikidata_us_county_zh = lambda **kw: fetch_wikidata_zh_for_country('Q30', **kw)
rule_us_admin2_zh = rule_english_admin_zh
normalize_county_zh = normalize_place_zh
