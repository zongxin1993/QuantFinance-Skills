# QuantFinance-Skills

量化金融领域的 agent 技能集合。每个技能都是自包含的目录，带 `SKILL.md`（给模型的说明书）、可执行脚本和参考资料，可以直接被 Claude Code / DeepSeek Harness 等支持 agent skills 的运行时加载。

## 技能清单

| 技能 | 做什么 | 依赖 | 状态 |
|---|---|---|---|
| [`quant-fin-papers`](skills/quant-fin-papers/) | 量化金融文献与研报的自动采集、去重、归档、增补摘要，支持挂载 SMB 作为存储 | Python 3.8+（纯标准库） | 可用 |

## 目录约定

```
.
├── skills/                    # 每个子目录就是一个技能
│   └── quant-fin-papers/
│       ├── SKILL.md           # 必需：YAML frontmatter + 使用说明
│       ├── README.md          # 可选：给人看的简介
│       ├── config.example.json
│       ├── scripts/           # 可执行脚本
│       └── references/        # 按需加载的详细文档
├── scripts/
│   └── install.sh             # 把技能安装到本地 agent 技能目录
└── docs/                      # 跨技能的研究与设计文档
    └── paper-platforms.md     # 金融论文/研报/因子平台调研
```

## 安装

技能目录是**单一真源**：安装 = 把 `skills/*` 软链到 agent 的技能目录，改仓库里的文件立即生效，不需要同步两份。

```bash
# 默认安装到 ~/.agents/skills（Claude Code、DeepSeek Harness 都会扫描）
./scripts/install.sh

# 指定目录 / 用复制代替软链 / 卸载
./scripts/install.sh --target ~/.dsh/skills
./scripts/install.sh --copy
./scripts/install.sh --uninstall
```

装完确认：

```bash
ls -l ~/.agents/skills/quant-fin-papers
python3 ~/.agents/skills/quant-fin-papers/scripts/quantpapers.py --version
```

## 新增一个技能

1. `mkdir -p skills/<name>/scripts`
2. 写 `skills/<name>/SKILL.md`，frontmatter 必须有 `name` 和 `description`：

   ```yaml
   ---
   name: my-skill
   description: 一句话说清"什么时候该用这个技能"，写清触发场景和关键词。
   whenToUse: 可选，补充触发条件。
   ---
   ```

3. 脚本尽量只用标准库，避免让使用者先装环境
4. 长文档放 `references/`，`SKILL.md` 只留主干——它是按需加载的，写太胖会挤占上下文
5. 在 README 的技能清单里加一行

## 约定

- **不提交数据**：下载的资料库、缓存、日志都在 `.gitignore` 里，仓库只放代码和文档
- **不提交密钥**：SMB 口令走系统钥匙串或环境变量，配置示例里只留空字段
- **脚本可自检**：每个技能应能回答"我怎么知道它跑通了"——比如 `quant-fin-papers` 提供 `sample`（每源取最新一篇）和 `verify`（索引与文件对账）

## 许可

个人研究用途。技能里调用的第三方平台（arXiv、Crossref、东方财富、巨潮资讯等）内容版权归各自所有，请遵守其使用条款，不要二次分发。
