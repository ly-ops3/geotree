"""地理大区（国家与一级行政区之间的导航层）静态映射。"""

from __future__ import annotations

LEVEL_MACRO = 15
SOURCE_MACRO = 'macro'

# 已启用大区分组的国家（增量扩展时在此登记 ISO2）
MACRO_COUNTRIES = frozenset({'CN', 'US', 'JP'})

# (macro_id, name_zh, name_en, sort_key)
CN_MACROS: tuple[tuple[str, str, str, str], ...] = (
    ('huabei', '华北地区', 'North China', '01'),
    ('dongbei', '东北地区', 'Northeast China', '02'),
    ('huadong', '华东地区', 'East China', '03'),
    ('zhongnan', '中南地区', 'Central-South China', '04'),
    ('xinan', '西南地区', 'Southwest China', '05'),
    ('xibei', '西北地区', 'Northwest China', '06'),
    ('gangaotai', '港澳地区', 'Hong Kong & Macau', '07'),
    ('taiwan', '台湾地区', 'Taiwan', '08'),
)

CN_MACRO_PROVINCES: dict[str, tuple[str, ...]] = {
    'huabei': ('北京市', '天津市', '河北省', '山西省', '内蒙古自治区'),
    'dongbei': ('辽宁省', '吉林省', '黑龙江省'),
    'huadong': ('上海市', '江苏省', '浙江省', '安徽省', '福建省', '江西省', '山东省'),
    'zhongnan': ('河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区', '海南省'),
    'xinan': ('重庆市', '四川省', '贵州省', '云南省', '西藏自治区'),
    'xibei': ('陕西省', '甘肃省', '青海省', '宁夏回族自治区', '新疆维吾尔自治区'),
    'gangaotai': ('香港特别行政区', '澳门特别行政区'),
    'taiwan': ('台湾省', '台湾'),
}

# US Census Bureau 9 divisions → GeoNames admin1 后缀（ISO 3166-2）
US_MACROS: tuple[tuple[str, str, str, str], ...] = (
    ('new_england', '新英格兰', 'New England', '01'),
    ('mid_atlantic', '中大西洋', 'Middle Atlantic', '02'),
    ('east_north_central', '东中西部', 'East North Central', '03'),
    ('west_north_central', '中西部平原', 'West North Central', '04'),
    ('south_atlantic', '南大西洋', 'South Atlantic', '05'),
    ('east_south_central', '东中南部', 'East South Central', '06'),
    ('west_south_central', '西中南部', 'West South Central', '07'),
    ('mountain', '山地', 'Mountain', '08'),
    ('pacific', '太平洋', 'Pacific', '09'),
    ('territories', '海外领地', 'U.S. Territories', '10'),
)

US_MACRO_ADMIN1: dict[str, tuple[str, ...]] = {
    'new_england': ('CT', 'ME', 'MA', 'NH', 'RI', 'VT'),
    'mid_atlantic': ('NJ', 'NY', 'PA'),
    'east_north_central': ('IL', 'IN', 'MI', 'OH', 'WI'),
    'west_north_central': ('IA', 'KS', 'MN', 'MO', 'NE', 'ND', 'SD'),
    'south_atlantic': ('DE', 'FL', 'GA', 'MD', 'NC', 'SC', 'VA', 'WV', 'DC'),
    'east_south_central': ('AL', 'KY', 'MS', 'TN'),
    'west_south_central': ('AR', 'LA', 'OK', 'TX'),
    'mountain': ('AZ', 'CO', 'ID', 'MT', 'NV', 'NM', 'UT', 'WY'),
    'pacific': ('AK', 'CA', 'HI', 'OR', 'WA'),
    'territories': ('PR', 'GU', 'VI', 'AS', 'MP', 'UM', 'FM', 'MH', 'PW'),
}

# 日本 8 地方区分 → GeoNames admin1 数字码（JP.01 …）
JP_MACROS: tuple[tuple[str, str, str, str], ...] = (
    ('hokkaido', '北海道', 'Hokkaido', '01'),
    ('tohoku', '东北', 'Tohoku', '02'),
    ('kanto', '关东', 'Kanto', '03'),
    ('chubu', '中部', 'Chubu', '04'),
    ('kinki', '近畿', 'Kinki', '05'),
    ('chugoku', '中国', 'Chugoku', '06'),
    ('shikoku', '四国', 'Shikoku', '07'),
    ('kyushu_okinawa', '九州·冲绳', 'Kyushu & Okinawa', '08'),
)

JP_MACRO_ADMIN1: dict[str, tuple[str, ...]] = {
    'hokkaido': ('01',),
    'tohoku': ('02', '03', '04', '05', '06', '07'),
    'kanto': ('08', '09', '10', '11', '12', '13', '14'),
    'chubu': ('15', '16', '17', '18', '19', '20', '21', '22', '23'),
    'kinki': ('24', '25', '26', '27', '28', '29', '30'),
    'chugoku': ('31', '32', '33', '34', '35'),
    'shikoku': ('36', '37', '38', '39'),
    'kyushu_okinawa': ('40', '41', '42', '43', '44', '45', '46', '47'),
}


def macro_source_id(iso2: str, macro_key: str) -> str:
    return f'{iso2.upper()}.{macro_key}'


def country_macros(iso2: str):
    iso2 = iso2.upper()
    if iso2 == 'CN':
        return CN_MACROS
    if iso2 == 'US':
        return US_MACROS
    if iso2 == 'JP':
        return JP_MACROS
    return ()


def admin1_to_macro_key(iso2: str, admin1_suffix: str) -> str | None:
    """GeoNames admin1 后缀 → macro key（US: CA, JP: 13）。"""
    iso2 = iso2.upper()
    suffix = (admin1_suffix or '').upper()
    if iso2 == 'US':
        mapping = US_MACRO_ADMIN1
        for key, codes in mapping.items():
            if suffix in codes:
                return key
    elif iso2 == 'JP':
        num = suffix.zfill(2) if suffix.isdigit() else suffix
        for key, codes in JP_MACRO_ADMIN1.items():
            if num in codes:
                return key
    return None


def cn_province_to_macro_key(name_zh: str) -> str | None:
    name = (name_zh or '').strip()
    for key, names in CN_MACRO_PROVINCES.items():
        if name in names:
            return key
    return None
