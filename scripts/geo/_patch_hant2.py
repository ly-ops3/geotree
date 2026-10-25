# -*- coding: utf-8 -*-
import io

p = 'scripts/geo/import_geonames.py'
src = io.open(p, encoding='utf-8').read()

old = """        name_en = c['name_en']
        name_zh = country_zh(iso2, name_en)
        source_id = c['geonameid'] or f'country:{iso2}'"""
new = """        name_en = c['name_en']
        name_zh = country_zh(iso2, name_en)
        name_zh_hant = to_traditional(name_zh) if name_zh else None
        source_id = c['geonameid'] or f'country:{iso2}'"""
assert src.count(old) == 1, 'country loop'
src = src.replace(old, new, 1)

old = "from app.geo.names_zh import ZhNameResolver, admin1_name_zh, _load_cldr_admin1"
new = "from app.geo.names_zh import ZhNameResolver, admin1_name_zh, _load_cldr_admin1, to_traditional"
assert old in src, 'import line'
src = src.replace(old, new, 1)

old = """        name_en=display_en,
        name_zh=name_zh,
        name_local=name,"""
new = """        name_en=display_en,
        name_zh=name_zh,
        name_zh_hant=name_zh_hant,
        name_local=name,"""
assert src.count(old) == 1, 'level8 upsert'
src = src.replace(old, new, 1)

old = """            "UPDATE geo_places SET name_zh = ? WHERE id = ?",
            ('圣诞岛', cx['id']),"""
new = """            "UPDATE geo_places SET name_zh = ?, name_zh_hant = ? WHERE id = ?",
            ('圣诞岛', to_traditional('圣诞岛'), cx['id']),"""
assert src.count(old) == 1, 'cx fix'
src = src.replace(old, new, 1)

old = """                name_en=c['name_en'],
                name_zh=country_zh('CN', c['name_en']),
                name_local=None,"""
new = """                name_en=c['name_en'],
                name_zh=country_zh('CN', c['name_en']),
                name_zh_hant=to_traditional(country_zh('CN', c['name_en'])),
                name_local=None,"""
assert src.count(old) == 1, 'CN country upsert'
src = src.replace(old, new, 1)

io.open(p, 'w', encoding='utf-8').write(src)
print('ok')
