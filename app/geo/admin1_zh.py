"""GeoNames admin1 码 → 中文名（CLDR 常用译名，按 ISO3166-2 键）。"""

ADMIN1_ZH = {
    # 美国
    'US.AL': '亚拉巴马州',
    'US.AK': '阿拉斯加州',
    'US.AZ': '亚利桑那州',
    'US.AR': '阿肯色州',
    'US.CA': '加利福尼亚州',
    'US.CO': '科罗拉多州',
    'US.CT': '康涅狄格州',
    'US.DE': '特拉华州',
    'US.DC': '华盛顿哥伦比亚特区',
    'US.FL': '佛罗里达州',
    'US.GA': '佐治亚州',
    'US.HI': '夏威夷州',
    'US.ID': '爱达荷州',
    'US.IL': '伊利诺伊州',
    'US.IN': '印第安纳州',
    'US.IA': '艾奥瓦州',
    'US.KS': '堪萨斯州',
    'US.KY': '肯塔基州',
    'US.LA': '路易斯安那州',
    'US.ME': '缅因州',
    'US.MD': '马里兰州',
    'US.MA': '马萨诸塞州',
    'US.MI': '密歇根州',
    'US.MN': '明尼苏达州',
    'US.MS': '密西西比州',
    'US.MO': '密苏里州',
    'US.MT': '蒙大拿州',
    'US.NE': '内布拉斯加州',
    'US.NV': '内华达州',
    'US.NH': '新罕布什尔州',
    'US.NJ': '新泽西州',
    'US.NM': '新墨西哥州',
    'US.NY': '纽约州',
    'US.NC': '北卡罗来纳州',
    'US.ND': '北达科他州',
    'US.OH': '俄亥俄州',
    'US.OK': '俄克拉荷马州',
    'US.OR': '俄勒冈州',
    'US.PA': '宾夕法尼亚州',
    'US.RI': '罗得岛州',
    'US.SC': '南卡罗来纳州',
    'US.SD': '南达科他州',
    'US.TN': '田纳西州',
    'US.TX': '德克萨斯州',
    'US.UT': '犹他州',
    'US.VT': '佛蒙特州',
    'US.VA': '弗吉尼亚州',
    'US.WA': '华盛顿州',
    'US.WV': '西弗吉尼亚州',
    'US.WI': '威斯康星州',
    'US.WY': '怀俄明州',
    # 澳大利亚
    'AU.NSW': '新南威尔士州',
    'AU.VIC': '维多利亚州',
    'AU.QLD': '昆士兰州',
    'AU.SA': '南澳大利亚州',
    'AU.WA': '西澳大利亚州',
    'AU.TAS': '塔斯马尼亚州',
    'AU.ACT': '首都领地',
    'AU.NT': '北领地',
    # 加拿大
    'CA.ON': '安大略省',
    'CA.QC': '魁北克省',
    'CA.BC': '不列颠哥伦比亚省',
    'CA.AB': '艾伯塔省',
    # 英国
    'GB.ENG': '英格兰',
    'GB.SCT': '苏格兰',
    'GB.WLS': '威尔士',
    'GB.NIR': '北爱尔兰',
    # 爱尔兰
    'IE.L': '伦斯特省',
    'IE.M': '芒斯特省',
    'IE.C': '康诺特省',
    'IE.U': '阿尔斯特省',
    'IE.D': '都柏林',
}


def admin1_zh(admin1_code, fallback_en=None):
    from app.geo.names_zh import admin1_name_zh

    zh = admin1_name_zh(admin1_code)
    if zh:
        return zh
    return None
