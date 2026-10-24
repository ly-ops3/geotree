"""GeoNames 各国汉化修复配置（可复用到其他项目）。"""

from __future__ import annotations

from dataclasses import dataclass

# 大中华区用 ok_zh，不走 geonames 批量汉化
SKIP_ISO2 = frozenset({'CN', 'HK', 'MO', 'TW', 'CX'})

# ISO 3166-1 alpha-2 → Wikidata 国家实体（用于 P17 查询）
ISO_WIKIDATA_Q: dict[str, str] = {
    'US': 'Q30', 'CA': 'Q16', 'AU': 'Q408', 'GB': 'Q145', 'IE': 'Q27',
    'DE': 'Q183', 'FR': 'Q142', 'IT': 'Q38', 'ES': 'Q29', 'PT': 'Q45',
    'NL': 'Q55', 'BE': 'Q31', 'CH': 'Q39', 'AT': 'Q40', 'SE': 'Q34',
    'NO': 'Q20', 'DK': 'Q35', 'FI': 'Q33', 'PL': 'Q36', 'CZ': 'Q213',
    'SK': 'Q214', 'HU': 'Q28', 'RO': 'Q218', 'BG': 'Q219', 'GR': 'Q41',
    'RU': 'Q159', 'UA': 'Q212', 'TR': 'Q43', 'JP': 'Q17', 'KR': 'Q884',
    'IN': 'Q668', 'PK': 'Q843', 'BD': 'Q902', 'TH': 'Q869', 'VN': 'Q881',
    'MY': 'Q833', 'SG': 'Q334', 'ID': 'Q252', 'PH': 'Q928', 'NZ': 'Q664',
    'MX': 'Q96', 'BR': 'Q155', 'AR': 'Q414', 'CL': 'Q298', 'CO': 'Q739',
    'PE': 'Q419', 'ZA': 'Q258', 'EG': 'Q79', 'NG': 'Q1033', 'KE': 'Q114',
    'IL': 'Q801', 'SA': 'Q851', 'AE': 'Q878', 'IR': 'Q794',
}


# Wikipedia 标题模板，按顺序尝试；占位符：name_en / parent_en / name_stem（去 City 后缀）
WIKI_TITLE_NAME_ONLY = ('{name_en}',)
WIKI_TITLE_NAME_THEN_PARENT = ('{name_en}', '{name_en}, {parent_en}')
WIKI_TITLE_PARENT_THEN_NAME = ('{name_en}, {parent_en}', '{name_en}')
WIKI_TITLE_IE = ('{name_en}', '{name_stem}', '{name_en}, {parent_en}')


@dataclass(frozen=True)
class CountryFixupProfile:
    iso2: str
    target_levels: tuple[int, ...]
    wikidata_q: str | None
    wiki_title_templates: tuple[str, ...] = WIKI_TITLE_NAME_THEN_PARENT
    wiki_parent_level: int = 2
    wiki_api: str = 'https://en.wikipedia.org/w/api.php'
    rule_english: bool = True


def _profile(iso2: str, levels: tuple[int, ...], **kw) -> CountryFixupProfile:
    iso2 = iso2.upper()
    return CountryFixupProfile(
        iso2=iso2,
        target_levels=levels,
        wikidata_q=ISO_WIKIDATA_Q.get(iso2),
        **kw,
    )


# 显式配置优先；未列出的国家用 default_profile(iso2)
COUNTRY_PROFILES: dict[str, CountryFixupProfile] = {
    'US': _profile('US', (3,), wiki_title_templates=WIKI_TITLE_PARENT_THEN_NAME),
    'CA': _profile('CA', (3,), wiki_title_templates=WIKI_TITLE_PARENT_THEN_NAME),
    'AU': _profile('AU', (3,), wiki_title_templates=WIKI_TITLE_PARENT_THEN_NAME),
    'GB': _profile('GB', (3, 4), wiki_title_templates=WIKI_TITLE_PARENT_THEN_NAME),
    'IE': _profile('IE', (3,), wiki_title_templates=WIKI_TITLE_IE),
    'DE': _profile('DE', (3, 4)),
    'FR': _profile('FR', (3, 4)),
    'IT': _profile('IT', (3, 4)),
    'ES': _profile('ES', (3, 4)),
    'JP': _profile('JP', (3, 4), rule_english=False),
    'KR': _profile('KR', (3, 4), rule_english=False),
    'IN': _profile('IN', (3, 4), wiki_title_templates=WIKI_TITLE_NAME_THEN_PARENT),
    'ID': _profile(
        'ID', (3, 4),
        wiki_title_templates=WIKI_TITLE_NAME_THEN_PARENT,
        wiki_api='https://id.wikipedia.org/w/api.php',
    ),
    'BR': _profile('BR', (3,)),
    'MX': _profile('MX', (3,)),
    'RU': _profile('RU', (3, 4)),
    'NZ': _profile('NZ', (3,)),
}


def default_profile(iso2: str) -> CountryFixupProfile:
    """未单独配置的国家：ADM2 + ADM3，先试地名再试「地名, 上级」。"""
    iso2 = iso2.upper()
    return CountryFixupProfile(
        iso2=iso2,
        target_levels=(3, 4),
        wikidata_q=ISO_WIKIDATA_Q.get(iso2),
        wiki_title_templates=WIKI_TITLE_NAME_THEN_PARENT,
        wiki_parent_level=2,
        rule_english=True,
    )


def get_profile(iso2: str) -> CountryFixupProfile:
    iso2 = iso2.upper()
    return COUNTRY_PROFILES.get(iso2) or default_profile(iso2)


def list_fixup_countries(db) -> list[str]:
    """返回待处理 ISO2 列表（有缺中文的 geonames 节点）。"""
    rows = db.execute(
        """SELECT DISTINCT iso_country AS c
           FROM geo_places
           WHERE source = 'geonames'
             AND iso_country IS NOT NULL
             AND level BETWEEN 3 AND 5
             AND (name_zh IS NULL OR TRIM(name_zh) = '')
           ORDER BY iso_country"""
    ).fetchall()
    out = []
    for r in rows:
        iso = (r['c'] or '').upper()
        if not iso or iso in SKIP_ISO2:
            continue
        out.append(iso)
    return out
