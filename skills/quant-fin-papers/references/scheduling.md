# 定时增补方案

目标：每天（或每周）自动把新论文补进资料库，并给出一份可读的增补摘要。

三种方式互不冲突，建议**只选一种**，避免同一天跑两次（虽然去重是幂等的，但会浪费请求额度）。

---

## 方案 A：DSH 内的定时任务（推荐）

适合"agent 自己盯着这件事"的场景：定时唤醒一个会话，跑 `fetch`，再用 `digest` 汇报。

```
schedule_create(
  title="量化金融文献增补",
  prompt="""运行 quant-fin-papers skill：
1) python3 scripts/quantpapers.py fetch --root /绝对路径/quant-finance-library
2) python3 scripts/quantpapers.py digest --print
用 5 条以内的要点汇报本次新增了什么方向的工作论文，不要贴全文。""",
  daily={"time": "08:30:00", "time_zone": "Asia/Shanghai"})
```

要点：

- `--root` 必须写绝对路径，定时会话的工作目录可能和你现在不同。
- 汇报口径写死在 prompt 里，避免每次输出格式漂移。
- 想要工作日跑就用 `cron` 形式：`{"expression": "30 8 * * 1-5", "time_zone": "Asia/Shanghai"}`。

---

## 方案 B：macOS launchd

适合机器常开、不依赖 DSH 进程的场景。

```bash
# 先看将要写入什么
scripts/install_schedule.sh --print-launchd --hour 8 --minute 30 \
  --root /Users/you/quant-finance-library

# 安装（写入 ~/Library/LaunchAgents/com.quantfin.papers.plist 并 bootstrap）
scripts/install_schedule.sh --install-launchd --hour 8 --minute 30 \
  --root /Users/you/quant-fin-library

# 立刻跑一次验证
launchctl kickstart -k gui/$(id -u)/com.quantfin.papers
tail -f /Users/you/quant-finance-library/logs/fetch.log

# 卸载
scripts/install_schedule.sh --uninstall
```

注意：

- 如果 `python3` 来自 Homebrew 或 pyenv，launchd 的 PATH 很干净，脚本里已经写死了解释器的绝对路径；换 Python 后要重新安装。
- `RunAtLoad=false`，所以加载时不会立刻跑，只按日历时间触发。
- macOS 13+ 首次运行会弹"后台项目已添加"，属于正常提示。

---

## 方案 C：cron（Linux / 服务器）

```bash
scripts/install_schedule.sh --print-cron --hour 8 --minute 30 \
  --root /srv/quant-finance-library
# 输出形如：
# 30 8 * * * cd "/srv/quant-finance-library" && "/usr/bin/python3" ".../quantpapers.py" fetch --root "/srv/quant-finance-library" >> "/srv/quant-finance-library/logs/fetch.log" 2>&1
crontab -e   # 粘贴
```

服务器上建议再配一条日志轮转（`logs/fetch.log` 每天几十行，不管也行）。

---

## 存储是 SMB 时

- `fetch` 启动时会 `ensure_storage`：没挂载且 `storage.auto_mount=true` 就自动挂载；挂不上直接失败退出，返回码 1。
- launchd/cron 跑在 DSH 沙箱外，挂载没问题；但**要求触发时网络可达**。NAS 只在 VPN 内网可达时，定时任务会一直失败——日志里能看到 `server connection failed`。
- 密码不要写进 plist：用 macOS 钥匙串（`security add-internet-password -s <ip> -a <user> -w`，`connect` 会自动读），或给 launchd 配 `EnvironmentVariables` 的 `QF_SMB_PASSWORD`。
- 挂载点掉线重连后，`pdf_path` 是相对 `storage.root` 的，不需要修索引；只要挂到同样的 `subdir` 就能对上。
- 日志别放挂载点上（掉线就写不了），保持在本地库目录。

## 增量游标

`state/last_run.json` 记录每个源的抓取结果与时间：

```json
{
  "last_fetch": "2026-11-02T04:53:23Z",
  "since": "2026-10-23T04:52:03Z",
  "sources": {"arxiv": {"found": 15, "new": 15, "downloaded": 3}},
  "totals": {"found": 110, "new": 110, "downloaded": 3},
  "errors": []
}
```

- 下一次 `fetch` 不带 `--since` 时，会用 `last_fetch - overlap_days(1天)` 作为起点，防止两次运行之间的空隙漏掉论文。
- 想强制重抓某段时间：显式给 `--since`。
- 想彻底重来：换一个 `--root` 或删掉 `state/` + `index.db`（**会丢已有索引，PDF 还在**）。

`state/last_digest.json` 同理，控制 `digest` 的默认时间窗。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| launchd 跑完日志是空的 | Python 路径写错，进程没起来 | 手动执行 plist 里的 ProgramArguments 看报错 |
| 每天都是 0 新增 | 正常，周末/假期 arXiv 不放新稿 | 看 `stats` 的 runs 表确认真的跑了 |
| 同一篇出现两条 | 一条有 DOI 一条没有，标题又被改写 | `list --query` 找到后手工删掉弱的那条，或统一用 DOI 源 |
| 定时任务和 agent 同时跑 | 两个方案都装了 | 只留一个；或者把 agent 的改成 `--since 1d` 只做汇报 |
| 服务器磁盘涨得快 | PDF 全量留存 | `--no-pdf` 只收元数据；或把 `max_pdf_mb` 调小 |
