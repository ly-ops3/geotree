# -*- coding: utf-8 -*-
import io
p = 'app/geo/admin_terms.py'
src = io.open(p, encoding='utf-8').read()
for bad in [
    "    _rule('RU', 2, None, '州'),\n",
    "    _rule('VN', 2, None, '省'),\n",
    "    _rule('UA', 2, None, '州'),\n",
    "    _rule('BY', 2, None, '州'),\n",
    "    _rule('KZ', 2, None, '州'),\n",
    "    _rule('UZ', 2, None, '州'),\n",
    "    _rule('MH', 2, r' Island$', '岛', '島'),\n",
    "    _rule('AE', 2, r'(Emirate|Abu|Dubai|Sharjah|Ajman|Fujairah|Khaimah|Quwain)$', '酋长国', '酋長國'),\n",
    "    _rule('AM', 2, None, '州'),\n",
    "    _rule('TO', 2, r\"(Division|Ha'apai|Tongatapu|Vava'u|Eua|Niuas)$\", '区', '區'),\n",
    "    _rule('TV', 2, r'(Atoll|Island|Funafuti|Niutao|Nanumea|Nanumaga|Niulakita|Nukufetau|Nukulaelae|Vaitupu|Nui)$', '环礁', '環礁'),\n",
    "    _rule('BS', 2, r'(District|Island|Cay|Andros|Abaco|Eleuthera|Exuma|Bimini|Inagua|Acklins|Mayaguana|Ragged|Long Island|Rum Cay|San Salvador|Black Point|Central|Crooked|Grand|Mangrove|Moore|New Providence|North|South|Spanish Wells|Harbour|West Grand|Freeport|Hope Town|Berry Islands|Chub Cay)$', '区', '區'),\n",
]:
    if bad in src:
        src = src.replace(bad, '', 1)
        print('removed:', bad.strip()[:80])
    else:
        print('NOT FOUND:', bad.strip()[:80])
io.open(p, 'w', encoding='utf-8').write(src)
print('done')
