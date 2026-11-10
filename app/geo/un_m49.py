"""UN M49 大洲 / 地理区映射（浏览层虚拟层级，不落库）。

虚拟节点 id 编码规则：place_id = -M49代码。
  大洲：-142 (Asia)、-150 (Europe)…
  地理区：-30 (东亚)、-155 (西欧)…
负数与真实 BIGSERIAL id 不冲突；解码直接取负。
"""

CONTINENTS = {
    142: ('亚洲', 'Asia'),
    150: ('欧洲', 'Europe'),
    2: ('非洲', 'Africa'),
    19: ('美洲', 'Americas'),
    9: ('大洋洲', 'Oceania'),
    999: ('南极洲及其他', 'Antarctica & Other'),
}

SUBREGIONS = {
    # 亚洲
    30: ('东亚', 'Eastern Asia'),
    143: ('中亚', 'Central Asia'),
    35: ('东南亚', 'South-eastern Asia'),
    34: ('南亚', 'Southern Asia'),
    145: ('西亚', 'Western Asia'),
    # 欧洲
    151: ('东欧', 'Eastern Europe'),
    154: ('北欧', 'Northern Europe'),
    39: ('南欧', 'Southern Europe'),
    155: ('西欧', 'Western Europe'),
    # 非洲
    15: ('北非', 'Northern Africa'),
    11: ('西非', 'Western Africa'),
    17: ('中非', 'Middle Africa'),
    14: ('东非', 'Eastern Africa'),
    18: ('南部非洲', 'Southern Africa'),
    # 美洲
    21: ('北美', 'Northern America'),
    13: ('中美', 'Central America'),
    29: ('加勒比', 'Caribbean'),
    5: ('南美', 'South America'),
    # 大洋洲
    53: ('澳大利亚和新西兰', 'Australia and New Zealand'),
    54: ('美拉尼西亚', 'Melanesia'),
    57: ('密克罗尼西亚', 'Micronesia'),
    61: ('波利尼西亚', 'Polynesia'),
    # 兜底
    998: ('其他', 'Other'),
}

_CONTINENT_OF_SUBREGION = {
    30: 142, 143: 142, 35: 142, 34: 142, 145: 142,
    151: 150, 154: 150, 39: 150, 155: 150,
    15: 2, 11: 2, 17: 2, 14: 2, 18: 2,
    21: 19, 13: 19, 29: 19, 5: 19,
    53: 9, 54: 9, 57: 9, 61: 9,
    998: 999,
}

# iso → subregion M49 code
_ISO_SUBREGION = {iso: sub for sub, isos in {
    # 东亚
    30: 'CN HK JP KP KR MN MO TW',
    # 中亚
    143: 'KZ KG TJ TM UZ',
    # 东南亚
    35: 'BN KH ID LA MY MM PH SG TH TL VN',
    # 南亚
    34: 'AF BD BT IN IR MV NP PK LK IO',
    # 西亚
    145: 'AM AZ BH CY GE IQ IL JO KW LB OM PS QA SA SY TR AE YE',
    # 东欧
    151: 'BY BG CZ HU PL MD RO RU SK UA',
    # 北欧
    154: 'AX DK EE FO FI GG IM IE IS JE LV LT NO SJ SE GB',
    # 南欧
    39: 'AL AD BA HR GI GR IT MT ME MK PT SM RS SI ES VA XK CS',
    # 西欧
    155: 'AT BE FR DE LI LU MC NL CH',
    # 北非
    15: 'DZ EG LY MA SD TN EH',
    # 西非
    11: 'BJ BF CV CI GM GH GN GW LR ML MR NE NG SH SN SL TG',
    # 中非
    17: 'AO CM CF TD CG CD GQ GA ST',
    # 东非
    14: 'BI KM DJ ER ET KE MG MW MU YT MZ RE RW SC SO SS TZ UG ZM ZW TF',
    # 南部非洲
    18: 'BW SZ LS NA ZA',
    # 北美
    21: 'BM CA GL PM US',
    # 中美
    13: 'BZ CR SV GT HN MX NI PA',
    # 加勒比
    29: 'AI AG AW BS BB BQ VG CU CW DM DO GD GP HT JM MQ MS PR KN LC VC SX TT TC VI AN',
    # 南美
    5: 'AR BO BV BR CL CO EC FK GF GY PY PE GS SR UY VE',
    # 澳新
    53: 'AU NZ NF',
    # 美拉尼西亚
    54: 'FJ NC PG SB VU',
    # 密克罗尼西亚
    57: 'GU KI MH FM NR MP PW UM',
    # 波利尼西亚
    61: 'AS CK PF NU PN WS TK TO TV WF',
    # 其他（南极洲等）
    998: 'AQ HM',
}.items() for iso in isos.split()}


def region_of(iso_country):
    """iso → (continent_code, subregion_code)；未知归 999/998。"""
    sub = _ISO_SUBREGION.get((iso_country or '').upper(), 998)
    return _CONTINENT_OF_SUBREGION[sub], sub


def continent_of_subregion(sub_code):
    return _CONTINENT_OF_SUBREGION.get(sub_code, 999)


def region_names(code, table):
    zh, en = table.get(code, ('未知', 'Unknown'))
    return zh, en


def isos_of_subregion(sub_code):
    return sorted(iso for iso, s in _ISO_SUBREGION.items() if s == sub_code)


def subregions_of_continent(cont_code):
    return sorted(c for c, cont in _CONTINENT_OF_SUBREGION.items() if cont == cont_code)


def subregion_of_iso(iso_country):
    return _ISO_SUBREGION.get((iso_country or '').upper(), 998)
