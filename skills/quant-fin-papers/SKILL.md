---
name: quant-fin-papers
description: 把量化金融领域的论文与工作论文自动采集到本地资料库并持续增补：arXiv 全 q-fin 分类、Crossref 核心期刊（JF/JFE/RFS/Math Finance/QF 等 20 本）、NBER 工作论文 RSS，带 DOI/标题去重、PDF 归档、Markdown 增补摘要和定时任务；支持挂载 SMB 共享作为下载目录，文档按来源分目录存放。Use when the user wants to download quantitative-finance papers to a local server or NAS, build or update a research library, or schedule recurring literature harvesting.
whenToUse: 用户提到"下载/采集量化金融论文"、"建本地文献库"、"自动增补文献"、"每天/每周抓新论文"、"arXiv q-fin"、"跟踪期刊新文章"、"把论文存到 NAS/SMB"时使用。
---

# 量化金融文献采集（quant-fin-papers）

一个纯标准库的本地文献管道：**抓取 → 去重 → 下载 PDF → 生成摘要 → 定时增补**。
PDF 可以放在本地，也可以挂载 SMB 共享（NAS）后按来源分目录存放。

## 何时使用

- "帮我把量化金融的论文自动下载到本地/服务器/NAS"
- "建一个论文库，每天自动补新的"
- "跟踪 arXiv q-fin 和 JF/JFE/RFS 的新文章"
- "把论文存到我的 SMB 共享里，按来源分好"

## 四条铁律

1. **索引在本地，文档在存储**：`index.db`、`digests/`、`state/` 永远在 `--root` 本地目录下；PDF 落在 `storage.root`，可以是 SMB 挂载点。**不要把 SQLite 放到 SMB 上**，会锁坏。
2. **先 `connect` 再 `fetch`**：存储类型是 `smb` 时，`fetch` 会按 `storage.auto_mount` 自动挂载，挂不上会直接失败退出，不会偷偷写到本地。
3. **文件名按来源分目录**：论文是 `<存储根>/<源名>/<年份>/<id>.pdf`，研报/公告因为量大，多一层月份：`eastmoney/2026/11/em_AP…pdf`、`cninfo/2026/10/cn_…pdf`。
4. **不要手改 `index.db`**；改配置用 `config --set`，重来就换 `--root`。

## 快速开始

```bash
cd <这个 skill 的目录>

# 0) 初始化（资料库目录建议放在工作区/数据盘）
python3 scripts/quantpapers.py init --root /abs/path/quant-finance-library

# 1) 可选：挂载 SMB 共享，之后所有 PDF 都写到这里
python3 scripts/quantpapers.py connect --root /abs/path/quant-finance-library \
    --ip 192.168.3.20 --share papers --user yourname --subdir quant-papers

# 2) 填真实邮箱（Crossref 礼貌池；也是 Unpaywall 找开放版的前提）
python3 scripts/quantpapers.py config --root /abs/path/quant-finance-library --set email=you@example.org

# 3) 采集 + 摘要
python3 scripts/quantpapers.py fetch  --root /abs/path/quant-finance-library --since 14d --pdf-limit 20
python3 scripts/quantpapers.py digest --root /abs/path/quant-finance-library --print
```

## 命令参考

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `init` | 建目录、写 `config.json`、建库 | `--root` |
| `connect` | 挂载 SMB 并把下载目录指过去 | `--ip --share --user --password --subdir --mount-point --dry-run` |
| `disconnect` | 卸载共享 | `--mount-point` |
| `storage` | 看存储类型/挂载状态/是否可写 | — |
| `fetch` | 增量采集 + 下载 PDF | `--since 7d\|12h\|2026-10-01`、`--sources arxiv,crossref,rss,openalex,eastmoney,cninfo`、`--max N`、`--pdf-limit N`、`--no-pdf`、`--json` |
| `digest` | 生成摘要：默认每源 top 15，另存一份完整版 | `--top 0`（全部）、`--since`、`--print` |
| `backfill` | 补下历史缺失的 PDF（扫 `new`/`failed` 且有链接的行） | `--limit`、`--sources` |
| `sample` | 每源取最新 N 条并下载，用于验收 | `--per-source`、`--sources`、`--no-pdf` |
| `list` | 最近入库列表 | `--query 关键词`、`--limit` |
| `stats` | 总量、按源统计、最近运行记录 | — |
| `verify` | 校验索引与挂载点上的 PDF 是否对得上 | — |
| `sync` | rsync 到另一个远端（存储已是 SMB 时通常不需要） | `--target user@host:/path/` |
| `config` | 查看/修改配置 | `--set crossref.per_journal=25` |

## SMB 挂载（connect）

```bash
# 基本用法：挂载 //192.168.3.20/papers 到 /Volumes/papers，文档写进 /Volumes/papers/quant-papers
python3 scripts/quantpapers.py connect --ip 192.168.3.20 --share papers \
    --user me --subdir quant-papers

# 只看看会执行什么，不真挂
python3 scripts/quantpapers.py connect --ip 192.168.3.20 --share papers --dry-run

# 查看状态 / 卸载
python3 scripts/quantpapers.py storage
python3 scripts/quantpapers.py disconnect
```

密码三种给法，按安全度排序：

1. **钥匙串（推荐，macOS）**：`security add-internet-password -s 192.168.3.20 -a me -w`，之后 `connect` 自动取。
2. **环境变量**：`export QF_SMB_PASSWORD=***`，适合 cron/launchd。
3. **命令行**：`--password ***`（会出现在 `ps` 和历史里，别在共享机器上用）。

行为说明：

- 默认挂载点 macOS 是 `/Volumes/<share>`，Linux 是 `/mnt/<share>`，可用 `--mount-point` 覆盖。
- `--share` 也可以直接写 `//192.168.3.20/papers`，会自动拆出 IP 和共享名。
- 挂载成功后会做一次写入探测（写 `.qf_write_test` 再删），不可写就报错，配置不落盘。
- 挂载信息写进 `config.json` 的 `storage` 段；`storage.root` = 挂载点 + `subdir`。
- **只读共享**：如果目标挂载点已存在但对当前账号只读，`connect` 不会动它，而是改挂到 `<挂载点>-rw`（如 `/Volumes/sharedir-rw`）并指向那里。
- Linux 上走 `mount -t cifs`，通常需要 sudo，报错信息会提示。

## 存储布局

```
<storage.root>/                 # SMB 挂载点或本地目录
├── arxiv/2026/2610.42119.pdf
├── crossref/2026/10.1111_jofi.70099.pdf
├── NBER/2026/w35927.pdf
├── eastmoney/2026/11/em_AP202611021831310441.pdf
├── cninfo/2026/10/cn_1225649682.pdf
└── openalex/...

<library root>/                 # 索引永远在本地
├── config.json
├── index.db
├── papers/<年>/<id>.json
├── digests/YYYY-MM-DD.md
├── state/{last_run,last_digest}.json
└── logs/
```

- 目录名就是采集源的名字（RSS 用 feed 名，如 `NBER`）。
- `pdf_path` 存的是相对 `storage.root` 的路径，换挂载点不用重建索引。
- `digest` 里的「本地 PDF」链接是 `file://` 绝对路径，点开直接到挂载点上的文件。

## 定时增补

**A. 让 agent 自己定时跑（推荐）**：

```
schedule_create(
  title="量化金融文献增补",
  prompt="运行 quant-fin-papers 的 fetch（--root 用绝对路径），再用 digest --print 汇报新增；只列标题+一句话要点。",
  daily={"time": "08:30:00", "time_zone": "Asia/Shanghai"})
```

**B. launchd（macOS 常开机器）** / **C. cron（Linux 服务器）**：

```bash
scripts/install_schedule.sh --print-launchd --hour 8 --minute 30 --root /abs/path/library
scripts/install_schedule.sh --install-launchd --hour 8 --minute 30 --root /abs/path/library
scripts/install_schedule.sh --print-cron   --hour 8 --minute 30 --root /abs/path/library
```

定时任务在 DSH 之外运行，不受沙箱限制，能直接写挂载点；前提是**运行挂载时网络可达**（NAS 在内网/VPN 上时注意开机顺序）。细节与排错见 `references/scheduling.md`。

## 数据源

| 源 | 状态 | 说明 |
|---|---|---|
| arXiv | 默认开 | 9 个 q-fin 分类，Atom API，PDF 可直下，3 秒/请求 |
| Crossref | 默认开 | 按 ISSN 盯 20 本核心期刊，`from-created-date` 抓新入库记录 |
| RSS | 默认开 | NBER 工作论文；可加任意 RSS/Atom，带相关性闸门 |
| **东方财富研报** | 默认开 | 券商个股/行业/策略研报，JSON 列表 + PDF 直链，无需登录 |
| **巨潮资讯** | 默认开 | 上市公司年报/半年报/季报公告，POST 查询 + PDF 直链 |
| OpenAlex | 默认关 | 免费 key 后可用，做跨库检索补充 |
| SSRN / ScienceDirect | 不可用 | SSRN 对脚本 403，Elsevier 需订阅，只会记录元数据 |

期刊清单、限速、怎么加新源 → `references/sources.md`。

## 状态语义

`papers.status` 是四态，`reason` 说明原因，`stats` 会打印分布：

| status | 含义 | 会不会再试 |
|---|---|---|
| `pdf` | 已下载且文件在存储里 | — |
| `closed` | 有链接但拿不到（付费墙 403/404、超过大小上限） | 否，终态 |
| `metadata` | 压根没有 PDF 链接（NBER、部分 Crossref 记录） | 否，终态 |
| `failed` | 网络错误、写盘失败等可恢复问题 | **是**，`backfill` 会重试 |
| `new` | 有链接但还没下（受 `--pdf-limit` 限制） | **是** |

`backfill` 就是扫 `new` + `failed` 里 `pdf_url` 非空的行，按 `added_at` 倒序补。SMB 掉线、429 造成的缺失靠它补，不用重跑整个时间窗口。

## 去重与增量

- 主键优先级：`uid`（研报/公告用平台 ID）→ `doi:` → `arxiv:` → `title:<sha1(规范化标题)>`。
- 同一篇既有 DOI 又有 arXiv 号时，以 DOI 为主键，不会重复入库。
- PDF 已存在（按源+年份+id 定位）就跳过下载，重跑不会重复拉。
- 付费墙链接不会硬撞：先查 Unpaywall 找开放版本，找不到就标记 `status='closed'`，只留元数据。

## 故障排查

| 症状 | 处理 |
|---|---|
| `SMB 存储不可用` | 先 `connect`；检查网络/VPN、共享名、用户名；`storage` 看挂载状态 |
| `挂载失败(rc=13/EACCES)` | 账号密码不对或无权访问该共享；先 `security add-internet-password -s <ip> -a <user> -w` 存密码 |
| `挂载失败(rc=68) server connection failed` | IP 不通或 445 端口被挡；先在 Finder「前往→连接服务器」试 `smb://ip/share` |
| `✗ 已挂载但目录不可写` | 共享以只读方式导出（Samba `read only = yes`），或该 SMB 账号无写权限。换有写权限的账号，或让管理员改 `read only = no` / `writeable = yes` |
| `未找到资料库配置` | 先 `init`，或检查 `--root` 是否指向含 `config.json` 的目录 |
| `HTTP Error 429` | 触发限速，等几分钟；把 `crossref.per_journal` 调小 |
| 大量 403 | 出版商付费墙，会自动跳过并标 `closed`；只想留元数据就 `--set download_pdf=false` |
| 换挂载点后 PDF 全"缺失" | 用同一个 `--subdir` 重挂；`pdf_path` 是相对路径，挂到同结构目录即可恢复 |

## 边界

- 只做"合法可得"的获取：开放获取 PDF、arXiv、RSS 摘要；不绕过付费墙、不模拟登录。
- 不解析 PDF 正文（没有 PyMuPDF 依赖）；需要正文抽取时再加工存储目录。
- 摘要由标题+元数据生成，不做语义去重（预印本与正式版可能各存一条，靠 DOI 合并）。
