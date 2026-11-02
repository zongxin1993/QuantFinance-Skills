# 数据源说明与扩展

## 一、内置源

### 1. arXiv（默认开启）

- 接口：`https://export.arxiv.org/api/query`，Atom XML。
- 覆盖 9 个分类：`q-fin.CP`（计算金融）、`q-fin.EC`（经济）、`q-fin.GN`（一般金融）、`q-fin.MF`（数理金融）、`q-fin.PM`（组合管理）、`q-fin.PR`（定价）、`q-fin.RM`（风险管理）、`q-fin.ST`（统计金融）、`q-fin.TR`（交易与市场微观结构）。
- 查询形如 `(cat:q-fin.CP OR ... OR cat:q-fin.TR) AND submittedDate:[20261023 TO 20261102]`，按提交时间倒序。
- 限速：官方建议 3 秒/请求；`arxiv.pdf_delay` 控制 PDF 下载间隔，别调到 1 以下，否则容易被临时封。
- PDF：`https://arxiv.org/pdf/<id>` 可直接下载，无需鉴权。
- 返回条数上限由 `arxiv.max_results` 控制（默认 60），单次 API 最多 2000。

### 2. Crossref（默认开启，按期刊监控）

- 接口：`https://api.crossref.org/works`。
- **为什么不用关键词检索**：`query.bibliographic` 的排序质量很差，`"risk management"` 会命中兽医、农业、工程期刊；实测一次 40 条里只有 1 条真正属于量化金融。所以默认改为**按 ISSN 拉某本期刊最近入库的文章**，精度接近 100%。
- 过滤条件：`filter=issn:<ISSN>,from-created-date:<since>,type:journal-article`，`sort=created`。
  - `from-created-date` 是"记录进入 Crossref 的时间"，不是出版时间——这才是增量增补需要的信号。
- 还有一层兜底：出版年份不在 `[1990, 今年+1]` 的记录直接丢弃（Crossref 里存在 2103 年这种脏数据）。
- 默认期刊清单（`crossref.journals`）：

| 期刊 | ISSN |
|---|---|
| Journal of Finance | 0022-1082 |
| Journal of Financial Economics | 0304-405X |
| Review of Financial Studies | 0893-9454 |
| Review of Finance | 1572-3097 |
| Journal of Financial and Quantitative Analysis | 0022-1090 |
| Mathematical Finance | 0960-1627 |
| Finance and Stochastics | 0949-2984 |
| SIAM Journal on Financial Mathematics | 1945-497X |
| Quantitative Finance | 1469-7688 |
| Journal of Econometrics | 0304-4076 |
| Journal of Banking & Finance | 0378-4266 |
| Journal of Financial Markets | 1386-4181 |
| Journal of Monetary Economics | 0304-3932 |
| Management Science | 0025-1909 |
| Operations Research | 0030-364X |
| Applied Mathematical Finance | 1350-486X |
| Journal of Computational Finance | 1460-1559 |
| Financial Analysts Journal | 0015-198X |
| Journal of Portfolio Management | 0095-4918 |
| Journal of Risk | 1465-1211 |

- 加一本：`config --set crossref.journals` 不便（是数组），直接编辑 `config.json`：
  ```json
  {"name": "Journal of Derivatives", "issn": "1074-1240"}
  ```
  ISSN 可以在 <https://portal.issn.org/> 或期刊官网查到，带连字符，X 大写。
- 礼貌池：请求带 `mailto`，请把 `email` 配成真实邮箱，否则会被降级甚至 429。

### 3. RSS / Atom（默认开启）

- 通用解析器，RSS 2.0 与 Atom 都吃。每条取 `title`、`link`、`description/summary`、`pubDate/published/updated`。
- 默认只有 NBER：`https://back.nber.org/rss/new.xml`。
  - 注意：NBER 的 feed **没有 `pubDate`**，所以时间过滤对它无效，靠标题/URL 去重；首次会把当前所有条目收进来（约 35 条）。
  - 标题形如 `XXX -- by A, B, C`，解析时会切掉 `-- by` 并把作者拆出来。
- 每条 feed 支持 `relevance: true`（默认），用金融语汇闸门过滤掉明显跑题的条目（比如 NBER 里的教育、医保论文）。
- 加源的写法：

```json
"rss": {
  "feeds": [
    {"name": "NBER", "url": "https://back.nber.org/rss/new.xml", "relevance": true},
    {"name": "SSRN-FEN", "url": "https://papers.ssrn.com/sol3/JELJOUR_Results.cfm?form_name=journalBrowse&journal_id=...", "relevance": true}
  ]
}
```

### 4. OpenAlex（默认关闭）

- 需要免费 key：`POST https://api.openalex.org/api-keys`，body `{"email": "你@example.org"}`，点邮件里的链接激活。
- 有 key 后：`config --set openalex.enabled=true`、`config --set openalex.api_key=xxx`。
- 无 key 时按出口 IP 共享每日额度，实测经常已经耗尽，会返回 429。

## 二、明确不可用的源

| 源 | 现象 | 结论 |
|---|---|---|
| SSRN | 直接 403（Cloudflare） | 不做；需要时让用户手动下载放进 `pdfs/` |
| ScienceDirect / Wiley / OUP / T&F 全文 | 403 或订阅墙 | 只收元数据；OA 版本交给 Unpaywall |
| RePEc/IDEAS 的 RSS | `/rss/` 404 | 各系列有独立 feed，需要逐个确认，暂不内置 |
| Semantic Scholar | 无 key 时 429 频繁 | 可选，未内置 |
| Google Scholar | 反爬 + 违反 ToS | 不碰 |

## 三、开放获取（OA）解析

- 触发条件：PDF 链接命中 `PAYWALL_HOSTS`（Wiley、OUP、T&F、Elsevier、Springer、JSTOR、INFORMS 等）。
- 流程：查 `https://api.unpaywall.org/v2/<doi>?email=<你的邮箱>` → 取 `best_oa_location.url_for_pdf`。
- 拿到就下载；拿不到就把 `status` 标成 `closed`，只留元数据，不再重复撞墙。
- Unpaywall 拒绝 `example.com` 邮箱，所以 `email` 必须是真实地址，否则此功能自动跳过。

## 四、相关性闸门

`is_finance_related()` 用两层规则，避免采集跑偏：

1. **强短语**（命中一个即可）：asset pricing、market microstructure、quantitative finance、value at risk、expected shortfall、limit order book、option pricing、stochastic volatility、term structure、credit spread、hedge fund、yield curve……
2. **弱词**（需命中至少两个）：finance、portfolio、equity、volatility、option、derivative、hedging、arbitrage、trading、investor、liquidity、alpha、backtest……

ISSN 监控的文章不过闸门（期刊本身已保证领域），只有关键词检索和 RSS 过闸门。

## 五、研报与公告源

### 东方财富研报（默认开启）

- 列表接口：`https://reportapi.eastmoney.com/report/list`
- 关键参数：`qType`（0 个股 / 1 行业 / 2 策略 / 3 宏观）、`beginTime`/`endTime`（YYYY-MM-DD）、`pageNo`/`pageSize`（最大 100）、`code=*`、`industryCode=*`。
- 返回 JSON（不加 `cb` 参数就不会是 JSONP），字段含：标题、股票代码/名称、机构、`emRatingName`（评级）、`ratingChange`、作者、未来三年 EPS/PE 预测、`infoCode`。
- **PDF 直链：`https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf`**，无需 Referer、无需登录，实测 4/4 命中。
- 量级参考：一周约 1100 条个股研报 + 340 条行业 + 250 条策略。
- 限速：1 秒/请求足够；分页到 `len(items) < page_size` 即停。

注意：
- `qType=3`（宏观）常常返回空，别当报错。
- `author` 字段形如 `11000254035.陈伟奇`，前面的数字是分析师 ID，取 `.` 之后的部分。
- 同一篇研报可能在不同日期重复推送，用 `infoCode` 做主键去重。

### 巨潮资讯公告（默认开启）

- 查询接口：`POST http://www.cninfo.com.cn/new/hisAnnouncement/query`
- 表单：`pageNum`、`pageSize`、`column=szse`、`tabName=fulltext`、`category`、`seDate=YYYY-MM-DD~YYYY-MM-DD`、`isHLtitle=true`。
- 返回 JSON，`announcements[].adjunctUrl` 形如 `finalpage/2026-10-30/1225649682.PDF`，
  **拼上 `http://static.cninfo.com.cn/` 即 PDF**。
- `announcementTime` 是毫秒时间戳。

分类码（实测可用，写错会静默返回全部公告，所以代码里做了白名单）：

| 简称 | 含义 | category 值 |
|---|---|---|
| `ndbg` | 年度报告 | `category_ndbg_szsh` |
| `bndbg` | 半年度报告 | `category_bndbg_szsh` |
| `yjdbg` | 一季报 | `category_yjdbg_szsh` |
| `sjdbg` | 三季报 | `category_sjdbg_szsh` |

- `column=szse` 实际覆盖沪深北全部 A 股（实测能拿到 6xxxxx、688xxx、920xxx），不需要再跑 `sse`，否则重复请求。
- 年报是季节性数据：11 月基本只有零星更正公告，4 月才是高峰。想常态化追踪建议同时开 `bndbg` 和 `sjdbg`。
- 单篇 PDF 可能 5–20MB，`max_pdf_mb` 默认 60 够用；嫌占地方就调小。

## 六、扩展一个新源

在 `scripts/quantpapers.py` 里加一个 `xxx_fetch(lib, http, since, limit)`，返回 `record(...)` 的列表，然后：

```python
ADAPTERS = {"arxiv": arxiv_fetch, "crossref": crossref_fetch, "rss": rss_fetch,
            "openalex": openalex_fetch, "xxx": xxx_fetch}
```

再在 `DEFAULT_CONFIG` 里加一段 `"xxx": {"enabled": False, ...}`，`fetch` 会自动按 `enabled` 选取。`record()` 负责统一字段（title/abstract/authors/published/doi/arxiv_id/pdf_url），去重与归档逻辑不用改。
