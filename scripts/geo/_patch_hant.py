# -*- coding: utf-8 -*-
"""一次性补丁：_resolve_name_zh 拆成 pair 版 + _upsert_place 写 name_zh_hant。"""
import io

p = 'scripts/geo/import_geonames.py'
src = io.open(p, encoding='utf-8').read()

old_tail = None
for cand in ("\\u4e00", "一"):
    tail = "if candidate and any('%s' <= ch <= '%s' for ch in candidate):\n            return candidate\n    return None" % (
        '一' if cand == '一' else '\\u4e00',
        '鿿' if cand == '一' else '\\u9fff',
    )
    old = """    picked = _pick_name_zh(alternatenames, name_en)
    if picked:
        return picked
    for candidate in (name_local, name_en):
        %s""" % tail
    if old in src:
        old_tail = old
        break

assert old_tail, 'resolve tail not found'

new = """    picked = _pick_name_zh(alternatenames, name_en)
    if picked:
        return picked
    for candidate in (name_local, name_en):
        if candidate and any('\\u4e00' <= ch <= '\\u9fff' for ch in candidate):
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
    \"\"\"返回 (简体名, 繁体名)。繁体优先别名表真实 hant，缺省 OpenCC s2t 补。\"\"\"
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
            if candidate and any('\\u4e00' <= ch <= '\\u9fff' for ch in candidate):
                hans = to_simplified(candidate)
                break
    if hans and not hant:
        hant = to_traditional(hans)
    return hans, hant
"""

src = src.replace(old_tail, new, 1)

# _upsert_place: add name_zh_hant column
old_sig = """def _upsert_place(db, *, parent_id, level, source_id, iso_country, admin1_code, admin2_code,
                  name_en, name_zh, name_local, population, is_selectable, sort_key, source='geonames',
                  name_local_lang=None):"""
new_sig = """def _upsert_place(db, *, parent_id, level, source_id, iso_country, admin1_code, admin2_code,
                  name_en, name_zh, name_local, population, is_selectable, sort_key, source='geonames',
                  name_local_lang=None, name_zh_hant=None):"""
assert old_sig in src
src = src.replace(old_sig, new_sig, 1)

old_cols = """        '''INSERT INTO geo_places
           (parent_id, level, source, source_id, iso_country, admin1_code, admin2_code,
            name_en, name_zh, name_local, name_local_lang, population, is_selectable, sort_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET
             parent_id=EXCLUDED.parent_id,
             level=EXCLUDED.level,
             iso_country=EXCLUDED.iso_country,
             admin1_code=EXCLUDED.admin1_code,
             admin2_code=EXCLUDED.admin2_code,
             name_en=EXCLUDED.name_en,
             name_zh=EXCLUDED.name_zh,
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
            name_en,
            name_zh,
            name_local,
            name_local_lang,
            population,
            is_selectable,
            sort_key,
        ),"""
new_cols = """        '''INSERT INTO geo_places
           (parent_id, level, source, source_id, iso_country, admin1_code, admin2_code,
            name_en, name_zh, name_zh_hant, name_local, name_local_lang, population, is_selectable, sort_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET
             parent_id=EXCLUDED.parent_id,
             level=EXCLUDED.level,
             iso_country=EXCLUDED.iso_country,
             admin1_code=EXCLUDED.admin1_code,
             admin2_code=EXCLUDED.admin2_code,
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
            name_en,
            name_zh,
            name_zh_hant,
            name_local,
            name_local_lang,
            population,
            is_selectable,
            sort_key,
        ),"""
assert old_cols in src
src = src.replace(old_cols, new_cols, 1)

# call sites: name_zh = _resolve_name_zh(...) -> pair; add name_zh_hant to upserts
# pattern A: "name_zh = _resolve_name_zh(\n ... )" multiline calls
import re
count_calls = 0
def repl_call(m):
    global count_calls
    count_calls += 1
    return 'name_zh, name_zh_hant = _resolve_name_zh_pair(' + m.group(1) + ')'

src = re.sub(r'name_zh = _resolve_name_zh\((.*?)\)', repl_call, src, flags=re.S)

# now add name_zh_hant=name_zh_hant to every _upsert_place call lacking it
def repl_upsert(m):
    body = m.group(0)
    if 'name_zh_hant' in body:
        return body
    return body.replace('name_zh=name_zh,', 'name_zh=name_zh,\n                name_zh_hant=name_zh_hant,')
    # indentation varies; fix below

count_upsert = 0
out = []
idx = 0
for m in re.finditer(r'_upsert_place\(\n(?:.*?)sort_key=', src, flags=re.S):
    pass

# simpler: insert "name_zh_hant=name_zh_hant," right after every "name_zh=name_zh," inside _upsert_place calls
# there are also lines "name_zh=name_zh," used elsewhere; restrict to upsert args (they follow 'name_en=name_en,')
count_upsert = src.count('name_zh=name_zh,')
src = src.replace('name_zh=name_zh,\n            name_local=name,', 'name_zh=name_zh,\n            name_zh_hant=name_zh_hant,\n            name_local=name,')
src = src.replace('name_zh=name_zh,\n                name_local=name,', 'name_zh=name_zh,\n                name_zh_hant=name_zh_hant,\n                name_local=name,')
# country/admin rows pass name_local=None
src = src.replace('name_zh=name_zh,\n            name_local=None,', 'name_zh=name_zh,\n            name_zh_hant=name_zh_hant,\n            name_local=None,')

io.open(p, 'w', encoding='utf-8').write(src)
print('patched. resolve calls:', count_calls, 'name_zh=name_zh occurrences:', count_upsert)
