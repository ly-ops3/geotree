# geo-registry 工程笔记

## 环境

- Windows + Python 3.13；PostgreSQL `127.0.0.1:5432` / db `geo_registry` / user `postgres` / 空密码（本地配置）
- GeoNames 源文件：`N:\项目\SV\geo`（allCountries.zip、alternateNames.txt、admin1CodesASCII.txt、admin2Codes.txt、countryInfo.txt）
- 无 Docker。中文输出会 GBK 乱码：跑 Python 用 `python -X utf8`，或脚本内 `sys.stdout` 包 UTF-8；PowerShell 不支持 heredoc，复杂脚本写 `.py` 文件再跑

## 常用入口

```powershell
python -X utf8 scripts/geo/audit_zh_coverage.py        # 覆盖率审计 → audit_zh_coverage.out.txt
python -X utf8 scripts/geo/fill_zh_via_wikidata.py --level=4          # P1566 反查补中文
python -X utf8 scripts/geo/fill_zh_via_wikidata.py --level=7 --min-pop=10000  # PPL 精选
python -X utf8 scripts/geo/fill_zh_via_p300.py --level=2              # ISO 3166-2 反查
python -X utf8 scripts/geo/apply_admin_terms.py                       # 通名规范应用
```

## 数据约定

- `name_zh`=简体，`name_zh_hant`=繁体（OpenCC 兜底，`zh`/`zh-CN`→简体，`zh-TW`/`zh-Hant` 系→繁体）
- `feature_class`/`feature_code` 是正式列；`admin2_code` 不再存 `H.MTN` 式特征标签
- 自然特征 `level=8` + `is_selectable=FALSE`，不进级联选择器
- 补名纪律：只写实有来源（alternateNames zh 标记/Wikidata zh label/CLDR/手工表），缺失留空不编造；UPDATE 一律带 `仅当空 OR name_zh=name_en` 守卫

## level 映射

1=COUNTRY(PCLI) 2=ADM1 3=ADM2 4=ADM3 5=ADM4 6=ADM5 7=PPL 8=自然地理

## 实施记录

见 `docs/Chatlog/2.md`。
