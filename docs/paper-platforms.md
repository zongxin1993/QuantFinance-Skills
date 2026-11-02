# 金融论文 / 券商研报 / 因子平台调研

> 实测时间：2026-11-02｜方法：直接发 HTTP 请求验证可达性与返回格式，不采信二手说法。
> 结论按「能不能真的把 PDF 拿下来」分级，而不是按「有没有网页」分级。

---

## 0. 一句话结论

| 分级 | 平台 |
|---|---|
| **全文可白拿** | arXiv、东方财富研报、巨潮资讯公告、SEC EDGAR、DOAJ、EconStor |
| **只有元数据** | Crossref（含 SSRN 的 DOI 记录）、OpenAlex（需免费 key）、RePEc/IDEAS |
| **明确下不了** | SSRN 正文、CEPR、IMF、慧博、发现报告、萝卜投研、Wind/Choice/Bloomberg |

---

## 1. 学术论文平台

| 平台 | 接入方式 | 实测 | 全文 | 说明 |
|---|---|---|---|---|
| **arXiv** | Atom API + RSS | ✅ 200 | ✅ 直下 | 已在用，9 个 q-fin 分类，PDF 无鉴权 |
| **Crossref** | REST API | ✅ 200 | ⚠️ 仅 OA | 已在用；按 ISSN 盯 20 本刊 |
| **NBER** | RSS | ✅ 200 | ❌ | 已在用，只有摘要，无 PDF 字段 |
| **OpenAlex** | REST API | ⚠️ 429 无 key | ⚠️ OA 链接 | 免费 key 后可用，覆盖广 |
| **Semantic Scholar** | Graph API | ⚠️ 429 | ❌ | 无 key 限流严重 |
| **SSRN** | 无公开 API | ❌ **403** | ❌ | 正文被 Cloudflare 挡死，脚本拿不到 |
| **CEPR** | RSS 页 | ❌ **403** | ❌ | 站点整体反爬 |
| **IMF** | RSS | ❌ **403** | ❌ | — |
| **BIS** | RSS | ⚠️ 需确认路径 | ❌ | 老 URL 已失效，站点改版 |
| **RePEc / IDEAS** | HTML + NEP | ✅ 200 | ❌ 需跳转 | 无官方 API，但页面可解析；NEP 邮件列表可当信号源 |
| **EconStor** | OAI-PMH | ✅ 200 | ✅ OA | 德国经济文献库，DSpace，开放获取 |
| **DOAJ** | REST API | ✅ 200 | ✅ OA | 开放获取期刊目录，返回标题+链接 |
| **CORE** | REST API | ⚠️ 429 | ✅ OA | 需注册 key，聚合全球 OA 论文 |

**关键判断：SSRN 是量化金融论文的主战场（因子、异象、资产定价几乎都先发这里），但它的正文拿不到。** 可行的替代是拿元数据：
- Crossref 里 SSRN 的 DOI 前缀是 `10.2139`，用 `filter=prefix:10.2139,from-created-date:...` 能列出新论文（实测一周 1805 条），有标题/作者/摘要，没有 PDF。
- 很多 SSRN 工作论文同时挂在 NBER 或 arXiv 上，可以用标题匹配找回全文。

---

## 2. 券商 / 企业研报平台

### 2.1 国内（重点）

| 平台 | 接入方式 | 实测 | 全文 | 说明 |
|---|---|---|---|---|
| **东方财富研报中心** | JSON API + PDF 直链 | ✅ **200** | ✅ **PDF** | **最值得接**，免费、无需登录 |
| **巨潮资讯** | POST JSON API + PDF | ✅ **200** | ✅ **PDF** | 公告/年报/招股书，不是研报但补基本面 |
| 慧博投研 | 网页 | ✅ 200 | ❌ | 会员制，PDF 需付费下载 |
| 发现报告（fxbaogao） | 网页 / MCP | ✅ 200 | ❌ | VIP 制，社区有 MCP 封装但底层仍需会员 |
| 萝卜投研 | 网页 | — | ❌ | 需登录，部分数据免费 |
| 同花顺 iFinD | 商业 API | — | 💰 | 按年授权 |
| Wind / Choice | 商业 API | — | 💰 | 机构授权，最贵也最全 |
| 券商官网 | 网页 | — | ⚠️ | 各家分散，格式不统一，适合定向抓某一家 |

**东方财富研报 API 实测细节：**

```
GET https://reportapi.eastmoney.com/report/list
    ?industryCode=*&pageSize=50&pageNo=1
    &beginTime=2026-10-25&endTime=2026-11-02
    &qType=0&code=*
```

- `qType=0` 个股研报（一周 1105 条）、`qType=1` 行业研报（338 条）、`qType=2` 策略/晨报（251 条）。
- 返回字段很全：标题、股票代码/名称、机构、评级（增持/买入…）、评级变动、作者、未来三年 EPS/PE 预测、`infoCode`。
- **PDF 直链规律：`https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf`**，实测 4/4 命中，返回 `application/pdf`，无需 Referer、无需登录。

**巨潮资讯 API 实测细节：**

```
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
Content-Type: application/x-www-form-urlencoded
pageNum=1&pageSize=30&column=szse&tabName=fulltext
&category=category_ndbg_szsh&seDate=2026-10-01~2026-11-02
```

- 返回 `announcements[].adjunctUrl`，拼成 `http://static.cninfo.com.cn/{adjunctUrl}` 即 PDF（实测 200 / 547KB / 8 页）。
- `category` 可切年报、半年报、招股书、临时公告。

### 2.2 海外

| 平台 | 接入方式 | 实测 | 全文 | 说明 |
|---|---|---|---|---|
| **SEC EDGAR** | JSON API + full-text search | ✅ **200** | ✅ | 10-K/10-Q/8-K，免费无需 key |
| AlphaSense | 商业 | — | 💰 | 卖方研报+专家访谈，企业级 |
| Bloomberg / Refinitiv | 商业 | — | 💰 | 终端授权 |
| FactSet / Morningstar / Zacks | 商业 | — | 💰 | 各有 API，按席位收费 |
| Seeking Alpha | 订阅 | — | 💰 | 个人投资者内容为主 |
| annualreports.com | 网页 | — | ⚠️ | 年报 PDF 聚合，抓取需注意频率 |

SEC EDGAR 两个可用端点（都要带 User-Agent，否则 403）：
- 全文检索：`https://efts.sec.gov/LATEST/search-index?q="asset pricing"`
- 公司文件索引：`https://data.sec.gov/submissions/CIK0000320193.json`
- 注意：老的 `browse-edgar` 页面现在返回 403，别再用了。

---

## 3. 因子论文与因子数据

### 3.1 论文从哪来

| 渠道 | 状态 | 说明 |
|---|---|---|
| SSRN | ❌ 正文不可得 | 因子论文首发地，只能拿 Crossref 元数据 |
| arXiv q-fin.PM / q-fin.ST | ✅ | 组合管理、统计金融，PDF 直下 |
| NBER | ✅ 摘要 | 因子相关宏观/资产定价工作论文 |
| 期刊（JPM、JFE、RFS、QF…） | ⚠️ 元数据 | 正文在订阅墙后 |
| AQR / Robeco / Research Affiliates | ⚠️ 页面可抓 | 有免费 PDF，但需解析页面，反爬中等 |
| Open Source Asset Pricing | ✅ | 不只是数据，还维护 200+ 因子的**论文引用清单** |

### 3.2 因子数据（免费、可直接下载）

| 数据集 | 地址 | 内容 |
|---|---|---|
| Kenneth French Data Library | `mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html` | 3/5 因子、动量、行业组合，ZIP/CSV |
| Open Source Asset Pricing | `openassetpricing.com/data/`（HuggingFace: `OpenSourceAP/CrossSection`） | 200+ 异象的可复现组合收益 |
| JKP Global Factor Data | `jkpfactors.com/data`（S3: `jkpfactors-data.s3.amazonaws.com/public/`） | 全球 150+ 因子月度数据 |
| AQR Data Library | `aqr.com/Insights/Datasets` | QMJ、BAB、价值动量等因子序列 |

---

## 4. 实测证据汇总

| 目标 | URL | 状态码 | 结论 |
|---|---|---|---|
| SSRN 论文页 | papers.ssrn.com/sol3/papers.cfm | **403** | 挡脚本 |
| SSRN 直链 PDF | papers.ssrn.com/sol3/Delivery.cfm | **403** | 同样挡 |
| RePEc/EconPapers | econpapers.repec.org | 200 | 可解析 |
| IDEAS 期刊页 | ideas.repec.org/s/eee/jfinec.html | 200 | 可解析 |
| CEPR | cepr.org/rss-feeds | **403** | 反爬 |
| IMF | imf.org/.../RSS | **403** | 反爬 |
| Fed RSS | federalreserve.gov/feeds/feds.xml | 200 | 可用 |
| Semantic Scholar | api.semanticscholar.org | **429** | 限流 |
| 东财研报 API | reportapi.eastmoney.com/report/list | 200 | JSON，可用 |
| 东财 PDF | pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf | 200 | PDF，4/4 |
| 巨潮查询 | cninfo.com.cn/new/hisAnnouncement/query | 200 | JSON，可用 |
| 巨潮 PDF | static.cninfo.com.cn/finalpage/… | 200 | PDF |
| SEC 全文检索 | efts.sec.gov/LATEST/search-index | 200 | JSON |
| SEC 公司索引 | data.sec.gov/submissions/CIK….json | 200 | JSON |
| SEC 老接口 | sec.gov/cgi-bin/browse-edgar | **403** | 弃用 |
| DOAJ | doaj.org/api/search/articles/… | 200 | JSON |
| EconStor OAI | econstor.eu/oai/request | 200 | XML |
| CORE | api.core.ac.uk/v3 | **429** | 需 key |
| Open Source AP | openassetpricing.com | 200 | 有数据页 |
| JKP | jkpfactors.com | 200 | S3 直下 |

---

## 5. 建议的接入顺序

> 更新（2026-11-02）：P0 两个源已落地到 `quant-fin-papers`，实测东财单次 277–295 条、巨潮 12 条，PDF 均可直下。

| 优先级 | 平台 | 理由 | 预估工作量 |
|---|---|---|---|
| **P0** ✅ | 东方财富研报 | 免费、无鉴权、PDF 直链稳定、覆盖个股+行业+策略 | 已实现 |
| **P0** ✅ | 巨潮资讯 | 年报/招股书是研究基础设施，同样免费直下 | 已实现 |
| **P1** | SEC EDGAR | 海外公司基本面唯一免费全文源 | ~130 行 |
| **P1** | OpenAlex | 免费 key 后覆盖度远超 Crossref，补全摘要 | ~80 行（已有骨架） |
| **P2** | DOAJ / EconStor | 开放获取期刊全文，补充学术侧 | ~80 行 |
| **P2** | Crossref `prefix:10.2139` | 把 SSRN 的元数据纳入，缓解"看不到因子新论文" | ~30 行（扩展现有） |
| **P3** | AQR / Robeco 论文页 | 因子研究精品，但需页面解析 | ~100 行，易碎 |

### 不建议碰

- **SSRN 正文**：Cloudflare + 登录，绕过成本高且违反 ToS。
- **Wind / Choice / Bloomberg**：商业授权，技术上也要专用终端。
- **慧博 / 发现报告**：会员制，抓取等于绕过付费。
- **Google Scholar**：明确违反 ToS，且反爬极强。

---

## 6. 合规与运维提醒

1. **频率**：东财、巨潮都是公开接口但不是给爬虫设计的，建议 ≤1 req/s，加 `User-Agent` 和重试退避。
2. **只做个人研究**：下载的研报不要二次分发或商用。
3. **接口会变**：东财 `infoCode` 规则、巨潮 `category` 枚举都可能调整，adapter 要能优雅降级（拿不到 PDF 就只存元数据）。
4. **PDF 存储**：研报体量大（单篇 1–5MB），按 `源/年份/月份` 分目录，别和论文混在一起。
5. **去重**：研报用 `infoCode` 或 `(机构, 标题, 日期)` 做键，比标题哈希稳。
