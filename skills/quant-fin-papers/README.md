# quant-fin-papers

量化金融文献的本地采集与持续增补技能（agent skill）。

- **抓**：arXiv 全 q-fin 分类、Crossref 20 本核心期刊（按 ISSN）、NBER 工作论文 RSS、**东方财富券商研报**、**巨潮资讯公司公告**，可选 OpenAlex。
- **净**：DOI → arXiv → 标题三级去重；出版日期异常与跨学科噪声双重过滤；付费墙先查 Unpaywall 找 OA 版本。
- **存**：文档统一落到一个存储目录（本地或 SMB 挂载点），**按下载源分文件夹**：`arxiv/2026/xxx.pdf`、`NBER/2026/xxx.pdf`，研报按月细分 `eastmoney/2026/11/xxx.pdf`；SQLite 索引与元数据留在本地。
- **报**：`digest` 生成 Markdown 增补摘要，只讲"上次之后新增了什么"。
- **续**：增量游标 + launchd/cron 生成器 + DSH 定时任务模板。

零第三方依赖，Python 3.8+。

## 30 秒上手

```bash
python3 scripts/quantpapers.py init   --root /abs/path/quant-finance-library

# 可选：把下载目录挂到 SMB 共享（例：//192.168.3.20/papers）
python3 scripts/quantpapers.py connect --root /abs/path/quant-finance-library \
    --ip 192.168.3.20 --share papers --user me --subdir quant-papers

python3 scripts/quantpapers.py config --set email=you@example.org     # 建议填真实邮箱
python3 scripts/quantpapers.py fetch  --root /abs/path/quant-finance-library --since 14d
python3 scripts/quantpapers.py digest --root /abs/path/quant-finance-library --print
```

## 存储

```
<storage.root>/              # 本地目录或 SMB 挂载点
├── arxiv/<年>/*.pdf
├── crossref/<年>/*.pdf
├── NBER/<年>/*.pdf
├── eastmoney/<年>/<月>/*.pdf   # 券商研报
└── cninfo/<年>/<月>/*.pdf      # 上市公司公告
```

- `connect` 负责挂载并做写入探测；`storage` 查看状态；`disconnect` 卸载。
- 密码优先取 macOS 钥匙串，其次 `$QF_SMB_PASSWORD`，最后 `--password`（不推荐）。
- SMB 掉线时 `fetch` 直接失败退出，不会把 PDF 写回本地。
- Linux 上 `connect` 走 `mount -t cifs`（需要 sudo）。

## 目录

```
SKILL.md                    # 给 agent 的说明书（何时用、怎么用、边界）
config.example.json         # 默认配置（含 storage 段）
scripts/quantpapers.py      # 采集/去重/归档/摘要/挂载 CLI
scripts/install_schedule.sh # launchd / cron 定时任务生成器
references/sources.md       # 数据源细节、期刊清单、如何扩展
references/scheduling.md    # 三种定时方案与增量游标
```

## 实测基线

一次 `fetch --since 14d`（arXiv + 20 本期刊 + NBER）：

- 约 100 条记录入库，1 分半左右；
- arXiv PDF 全部可下并落到 `arxiv/<年>/`，出版商 PDF 大多 403（按设计跳过并标记 `closed`）；
- 同一窗口重跑：新增 0，说明去重与增量游标有效。

## 边界

只获取开放可得的内容（arXiv、OA、RSS 元数据），不绕过付费墙、不模拟登录、不抓 Google Scholar。
