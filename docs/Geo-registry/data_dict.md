# User ask:
但是这些地名出现在了不该出现的大区层级，有什么手段治治？
源数据中就是这样吗？
源数据中的各个字段分别是什么含义？给我一个数据字典。

---

**结论先说：** 那些罗马音小地名不是自然地理，也不是 GeoNames 里挂在「大区」下的；源数据里只有行政码和坐标，**树是我们导入时拼出来的**。出现在大区下一屏，多半是 **UI 把都道府县下的大量 PPL（`level=7`）全摊开了**，或需要在大区节点上 **只展示 ADM1**。

---

## 一、为什么会出现在「大区」那一层？

### 源数据里并没有「大区」

GeoNames 只有：`国家 → admin1~4 码 → 各类地名`。  
**华北 / 九州地方** 是你们后来加的 `source='macro', level=15`，脚本只把 **都道府县/州（level=2 ADM1）** 挂到大区下。

正常树应是：

```
日本 → 九州·冲绳（macro）→ 冲绳县 / 福冈县…（ADM1）→ 市町村 / 小地名（PPL, level=7）
```

`Furue` 这类是 **PPL（居民点）**，在源文件里是 `feature class = P`，带 `admin1=47`（冲绳）等字段，**不会写「属于九州地方」**。

### 更可能的原因（按概率）

1. **其实已点到都道府县，但界面像停在大区**  
   级联第三列是「当前选中节点的子节点」。选中九州后下一列应是 8 个府县；再点冲绳，才会刷出成千上万 PPL。罗马音列表往往是 **府县下的村/小岛**，不是大区直属。

2. **`get_children` 对行政节点返回了海量 PPL**  
   父节点是 ADM1 时，子节点里既有 ADM2，也有大量 `level=7`。排序里 PPL 会混进来，**`population=0` 的小地名仍 `is_selectable=true`**，一展开就像「满屏乱名」。

3. **真挂错父节点（需 SQL 证实）**  
   若 `Furue.parent_id` 直接等于大区 id，才是数据错误。大区脚本只改了 ADM1 的 `parent_id`，**不应**把 PPL 挂到大区。可在库里查：

```sql
-- 九州·冲绳大区下直接挂了什么
SELECT level, COUNT(*), MIN(name_en), MAX(name_en)
FROM geo_places
WHERE parent_id = (
  SELECT id FROM geo_places
  WHERE source = 'macro' AND source_id = 'JP.kyushu_okinawa'
)
GROUP BY level
ORDER BY level;
```

- 正常：**只有 `level=2`，约 8 条**（各都道府县）  
- 若出现 **`level=7`**：才是挂错，需要修数据或导入逻辑

### 怎么「治」（不动行政建制）

| 手段 | 做法 | 侵入性 |
|------|------|--------|
| **按父节点类型过滤（推荐）** | 父节点是 `macro`（level=15）时，`get_children` **只返回 level=2** | 小，改 API |
| **限制国外深度** | 国外资料地区只选到 **国家/大区/都道府县**，不展示 PPL | 中 |
| **PPL 门槛** | `level=7` 且 `population=0` → `is_selectable=false` 或查询里 `population > 0` | 中 |
| **重导缩小 PPL** | 国外不用 `allCountries` 全量 PPL，改用 `cities5000.zip` 等 | 大 |
| **按 population=0 删除** | 不推荐，会删掉大量真实小地名，且碰不到 ADM（ADM 是 `NULL` 不是 0） | 不推荐 |

源数据本身就是这样：**小国、小岛、村里大量 PPL 且人口字段为空**，不是你们导入独有的 bug。

---

## 二、GeoNames 源文件数据字典

### 1. `allCountries.txt`（主表，Tab 分隔，约 19 列）

| 列号 | 字段名 | 含义 | 示例 |
|------|--------|------|------|
| 0 | geonameid | 唯一 ID | `2994701` |
| 1 | name | 主名称（当地语言） | `Roc Meler` |
| 2 | asciiname | ASCII 名 | `Roc Meler` |
| 3 | alternatenames | 逗号分隔别名 | 多语言/历史名 |
| 4 | latitude | 纬度 | `42.58765` |
| 5 | longitude | 经度 | `1.7418` |
| 6 | **feature class** | 大类 | `P` 居民点、`A` 行政区、`H` 水文、`T` 地形、`L` 地貌、`V` 植被… |
| 7 | **feature code** | 小类 | `PPL` 村/镇、`ADM1` 一级行政区、`PPLA` 首府… [完整表](https://www.geonames.org/export/codes.html) |
| 8 | country code | ISO 国家二字 | `JP` |
| 9 | cc2 | 备用国家码 | 多为空 |
| 10 | admin1 | 一级行政区码 | 日本 `47`=冲绳 |
| 11 | admin2 | 二级 | |
| 12 | admin3 | 三级 | |
| 13 | admin4 | 四级 | |
| 14 | **population** | 人口 | 常为空 → 导入写成 `0` |
| 15 | elevation | 海拔 | |
| 16 | dem | 数字高程 | |
| 17 | timezone | 时区 | `Asia/Tokyo` |
| 18 | modification date | 修改日 | |

**日本 `Furue` 类记录**：一般是 `feature class=P`，`feature code=PPL` 或 `PPLX` 等，带 `admin1`，**不是**自然地理（自然地理是 `H/T/L/V`，且你们只给中国对照层导了 level=8）。

### 2. `countryInfo.txt`（国家列表）

| 字段 | 含义 |
|------|------|
| ISO | 二字国码 |
| ISO3 / ISO-Numeric | 三字/数字码 |
| Country | 英文名 |
| Capital | 首都 |
| Population | 全国人口 |
| geonameid | 国家在 GeoNames 的 id |
| … | 货币、语言等 |

### 3. `admin1CodesASCII.txt`

格式：`国家.ADM1码 \t 英文名 \t ASCII名 \t geonameid`  
例：`JP.47 \t Okinawa \t Okinawa \t …` → 导入为 **level=2 ADM1**。

### 4. `admin2Codes.txt`

格式：`国家.ADM1.ADM2 \t 名 \t …` → **level=3 ADM2**。

### 5. `alternateNames.zip` → `zh_altnames.sqlite`

别名表：`geonameid` + 中文名，用于批量汉化，**不改变层级**。

---

## 三、你们库表 `geo_places` 数据字典

| 字段 | 含义 | 谁写入 |
|------|------|--------|
| `id` | 主键 | 自增 |
| `parent_id` | 父节点（树） | 导入/大区脚本拼出来 |
| **`level`** | **语义层级（最重要）** | 见下表 |
| `source` | `ok_zh` / `geonames` / `macro` | |
| `source_id` | 源唯一键 | geonameid 或 `CN.huabei` 等 |
| `iso_country` | 国家二字 | |
| `admin1_code` | 如 `JP.47` | GeoNames 行政码 |
| `admin2_code` | ADM2 码；**level≥8 中国自然地理时存 feature 标签**（如 `H.RSV`） | |
| `name_en` / `name_zh` / `name_local` | 英/中/当地名 | |
| `population` | 人口；**ADM 多为 NULL，PPL 常为 0** | |
| `is_selectable` | 能否被选作资料地区 | macro 为 false |
| `sort_key` | 排序 | |

### `level` 含义（项目约定）

| level | 含义 | population 典型 |
|-------|------|-----------------|
| 1 | 国家 | NULL |
| 2 | ADM1 / 省州都道府县 | NULL |
| 3–6 | ADM2–ADM5 | NULL |
| **7** | **居民点 PPL（罗马音多在这）** | **0 = 源里没人口，不是自然地理** |
| **8** | **中国自然地理**（H/T/L/V） | NULL；看 `admin2_code` 特征码 |
| **15** | **地理大区 macro** | NULL |

**没有单独的「自然地理」布尔字段**；国外自然地理本次根本没导入，靠 `level` + `feature class`（源）/ `admin2_code`（库内 level=8）区分。

---

## 四、和 `population=0` 的关系（再强调）

- **472 万 `population=0`** ≈ 几乎都是 **`level=7` 的 PPL**，源里人口列为空。  
- **行政建制** 是 `level 1–6`，`population` 为 **NULL**，不会被 `population=0` 命中。  
- **不能**用「删光 population=0」来清界面，也 **删不到** 行政层。

---

若要改选择器（例如大区下只显示府县、国外不展示 `pop=0` 的 PPL），需要改 `get_children` 逻辑；我当前是 Ask 模式，你切到 **Agent 模式** 我可以直接帮你改一版规则。