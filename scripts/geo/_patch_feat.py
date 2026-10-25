# -*- coding: utf-8 -*-
"""给 _upsert_place 各调用点补 feature_class/feature_code。"""
import io

p = 'scripts/geo/import_geonames.py'
src = io.open(p, encoding='utf-8').read()

def rep(old, new, cnt=1):
    global src
    assert src.count(old) >= 1, 'missing: ' + old[:60]
    src = src.replace(old, new, cnt)

# ADM3-5 & PPL & level8 paths（allCountries 行内已有 feature_class/feature_code 变量）
rep("""            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
            name_en=name_en,""",
    """            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
            feature_class='A',
            feature_code=feature_code,
            name_en=name_en,""")

rep("""            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            name_en=name_en,""",
    """            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            feature_class='P',
            feature_code=feature_code,
            name_en=name_en,""")

# _import_geonames_row 内同样的两个块（缩进 8）
rep("""            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=None,""",
    """            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2') or keys.get('adm3') or keys.get('adm4'),
            feature_class='A',
            feature_code=feature_code,
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=None,""")

rep("""            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=population,""",
    """            iso_country=iso2,
            admin1_code=keys.get('adm1'),
            admin2_code=keys.get('adm2'),
            feature_class='P',
            feature_code=feature_code,
            name_en=name_en,
            name_zh=name_zh,
            name_zh_hant=name_zh_hant,
            name_local=name,
            population=population,""")

io.open(p, 'w', encoding='utf-8').write(src)
print('ok')
