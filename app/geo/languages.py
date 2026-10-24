"""语言代码：把 GeoNames isolanguage 收成稳定的 BCP 47 风格代码。

语种本身高度重复，不在每条地名里存「日语 / Japanese」。
代码（ja、zh-CN）就是枚举值，英文语言名只放在 geo_languages 里一次。
不用 PostgreSQL ENUM：码来自 dump，会新增，ENUM 每次都要 ALTER TYPE。
"""

from __future__ import annotations

import re

# GeoNames 用这些 isolanguage 表示邮编、机场码、外链，不是自然语言。
NON_LANGUAGE = frozenset({
    'post', 'iata', 'icao', 'faac', 'fr_1793', 'abbr', 'link', 'wkdt',
    'unlc', 'phon', 'lauc', 'uicn', 'geoid', 'nuts', 'piny', 'tcid',
})

# 国家主语言和 alternateNames 的码不完全一致（宏语言、书面语）。
# 只用于挑选 endonym，不合并 geo_place_names 里的行。
_LANG_ALIASES = {
    'no': ('nb', 'nn'),
    'nb': ('no',),
    'nn': ('no',),
    'zh': ('zh-CN', 'zh-Hans', 'zh-Hant', 'zh-TW'),
    'fil': ('tl',),
    'tl': ('fil',),
    'he': ('iw',),
    'iw': ('he',),
    'id': ('in',),
    'in': ('id',),
}

_TAG_RE = re.compile(r'^[a-z]{2,3}(-[a-zA-Z]{2,8}){0,2}$')


def canonicalize_lang(raw: str | None) -> str | None:
    """GeoNames isolanguage / 请求参数 → ja、zh-CN、zh-Hant。无法识别则 None。"""
    token = (raw or '').strip()
    if not token or token.lower() in NON_LANGUAGE:
        return None
    tag = token.replace('_', '-')
    if not _TAG_RE.match(tag):
        return None
    parts = tag.split('-')
    if any(part.isdigit() for part in parts):
        return None
    primary = parts[0].lower()
    if primary in NON_LANGUAGE or len(primary) not in (2, 3):
        return None
    out = [primary]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            out.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            out.append(part.title())
        elif part.isalnum():
            out.append(part.lower())
        else:
            return None
    return '-'.join(out)


def language_fallbacks(raw: str | None) -> list[str]:
    """请求语种的查找顺序。zh 先简体再繁体；zh-TW 相反；pt-BR 回落到 pt。"""
    code = canonicalize_lang(raw)
    if not code:
        return []
    primary = code.split('-')[0]
    if primary == 'zh':
        if code in ('zh-TW', 'zh-Hant', 'zh-HK', 'zh-MO'):
            chain = [code, 'zh-Hant', 'zh-TW', 'zh-HK', 'zh', 'zh-Hans', 'zh-CN']
        else:
            chain = [code, 'zh', 'zh-Hans', 'zh-CN', 'zh-Hant', 'zh-TW']
    elif code == primary:
        chain = [code]
    else:
        chain = [code, primary]
    seen: list[str] = []
    for item in chain:
        if item not in seen:
            seen.append(item)
    return seen


def primary_language_keys(languages_field: str | None) -> list[str]:
    """countryInfo.languages 的第一语种，精确标签在前，主标签和书面语别名在后。

    「de-CH,fr-CH,it-CH」→ ['de-CH', 'de']。只取第一语种：
    它是说话人口最多的语言，用来填 name_local。其余语言仍进 geo_place_names。
    """
    if not languages_field:
        return []
    first = languages_field.split(',')[0].strip()
    canon = canonicalize_lang(first)
    if not canon:
        return []
    base = canon.split('-')[0]
    ordered = [canon]
    if base != canon:
        ordered.append(base)
    for alt in _LANG_ALIASES.get(base, ()):
        if alt not in ordered:
            ordered.append(alt)
    return ordered


def name_score(*, is_preferred: bool, is_short: bool, is_colloquial: bool, is_historic: bool) -> int | None:
    """同一地点、同一语言只留一个展示名。历史名和俗称不入库。

    官方简称（Deutschland）高于正式全称（Bundesrepublik Deutschland），
    简称又必须带 preferred，避免「NYC」这种未标首选的缩写胜出。
    返回 None 表示丢弃。
    """
    if is_historic or is_colloquial:
        return None
    return (100 if is_preferred else 0) + (30 if is_short else 0)


def prefer_name(new_score: int, new_name: str, old_score: int, old_name: str) -> bool:
    if new_score != old_score:
        return new_score > old_score
    return len(new_name) < len(old_name)


def pick_endonym(by_lang: dict[str, str], keys: list[str]) -> tuple[str, str] | None:
    for key in keys:
        name = by_lang.get(key)
        if name:
            return key, name
    return None


def decide_local(
    *,
    name_local: str | None,
    name_en: str | None,
    by_lang: dict[str, str],
    keys: list[str],
) -> tuple[str | None, str | None]:
    """决定 (name_local, name_local_lang)。

    已有和英文不同的地名时保留原文，只补语种——GeoNames 的 utf8 name
    经常已经是当地写法。只有空值或与 name_en 相同才改用主语言的 alternate name。
    """
    current = (name_local or '').strip() or None
    en = (name_en or '').strip() or None
    picked = pick_endonym(by_lang, keys)
    if picked:
        lang, name = picked
        if current is None or current == en or current == name:
            return name, lang
        for code in keys:
            if by_lang.get(code) == current:
                return current, code
        for code, alt in by_lang.items():
            if alt == current:
                return current, code
        return current, (keys[0] if keys else None)
    if current and current != en and keys:
        return current, keys[0]
    if keys and keys[0].split('-')[0] == 'en' and en:
        lang = 'en' if 'en' in keys else keys[0]
        return en, lang
    return current, None


def _self_check() -> None:
    assert canonicalize_lang('JA') == 'ja'
    assert canonicalize_lang('zh_cn') == 'zh-CN'
    assert canonicalize_lang('zh-hant') == 'zh-Hant'
    assert canonicalize_lang('fr_1793') is None
    assert canonicalize_lang('link') is None
    assert canonicalize_lang('lauc') is None
    assert canonicalize_lang('') is None
    assert primary_language_keys('de-CH,fr-CH,it-CH,rm') == ['de-CH', 'de']
    assert primary_language_keys('fr-FR,frp,br') == ['fr-FR', 'fr']
    assert primary_language_keys('no,nb,nn') == ['no', 'nb', 'nn']
    assert primary_language_keys('en-US,es-US,haw')[:2] == ['en-US', 'en']
    assert language_fallbacks('zh')[0] == 'zh'
    assert 'zh-Hant' in language_fallbacks('zh-TW')
    assert name_score(is_preferred=True, is_short=True, is_colloquial=False, is_historic=False) == 130
    assert name_score(is_preferred=True, is_short=False, is_colloquial=False, is_historic=True) is None
    assert prefer_name(130, 'Deutschland', 100, 'Bundesrepublik Deutschland')
    assert decide_local(
        name_local=None, name_en='Germany',
        by_lang={'de': 'Deutschland', 'en': 'Germany'},
        keys=['de'],
    ) == ('Deutschland', 'de')
    assert decide_local(
        name_local='Tokyo', name_en='Tokyo',
        by_lang={'ja': '東京', 'en': 'Tokyo'},
        keys=['ja'],
    ) == ('東京', 'ja')
    assert decide_local(
        name_local='München', name_en='Munich',
        by_lang={'de': 'Muenchen'},
        keys=['de'],
    ) == ('München', 'de')
    assert decide_local(
        name_local='Springfield', name_en='Springfield',
        by_lang={},
        keys=['en-US', 'en'],
    ) == ('Springfield', 'en')
    assert decide_local(
        name_local=None, name_en='Antarctica', by_lang={'en': 'Antarctica'}, keys=[],
    ) == (None, None)


if __name__ == '__main__':
    _self_check()
    print('languages ok')
