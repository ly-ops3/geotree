# 小红书 / 即刻 短文案

读者有技术背景，直接说事：数字、方法、坑。200-300 字，附博客链接。

---

## 版本 A（数据成果型）

给 geotree 做中文名治理，新增 4.8 万条。

做法是把 GeoNames 的 87 万条 geonameid 批量反查 Wikidata
（P1566 键，SPARQL VALUES 每次绑 400 个），拿 zh label；
P1566 查不到的再用 ISO 3166-2 码走 P300 补一刀，
ADM1 又多收 58 条。

顺手修了三件事：

- 繁简混写：zh/zh-CN/zh-Hant 抢同一个 name_zh 坑，拆成双列
- 通名不齐：行政区"市/县/区"尾巴做了规则引擎，
  按（国家, 层级, 英文名模式）匹配，不是一刀切
- 自然地理：山脉河流原来塞进 is_selectable，拆出来单独管

查不到的留空，不编造——剩下 247 个 ADM1 是真没有中文名的
属地小岛。

全文：链接

#开源 #数据库 #GeoNames

---

## 版本 B（坑记型，即刻更合适）

给地理库补中文名，踩了个意料之外的坑：
Wikidata SPARQL 查 P1566 反查很顺，但 CLDR 的 zh subdivisions
上游只有 3 条（英格兰/苏格兰/威尔士）——Unicode 官方数据里
中文区划名是空的，中文地名生态全在维基不在 CLDR。

另一条死路：zh.wikipedia sitelink。以为能拿条目标题补缺，
结果 sitelink 是 zh label 的真子集（机器人同步过了），
2800 条只命中 1 条。

最后 ADM1 从 60% 补到 93.5%，PPL 大城市到 55.8%。
全部 UPDATE 带"仅当空"守卫，幂等可重跑。

全文：链接

#Wikidata #SPARQL #开源
