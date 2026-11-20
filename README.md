# 会话汇总 · Agent Session Memory

在 DeepSeek Harness 桌面版里，输入一个关键词，找到其他 Agent 里讨论过的方案，点回当时的原话，再决定带哪些段落进入新会话。[下载 Windows 插件](https://github.com/hangphuong3076-sudo/dsh-agent-session-memory/releases/latest)

## 为什么做这个插件

同一个项目可能先在 Codex 里定需求，在 Kimi Code 里试另一种解法，最后回到 Harness 继续。最费时间的是记起「在哪个客户端、哪段对话里改过条件」。把整份聊天粘给下一个 Agent，也容易把早已放弃的建议当成最终决定。

这个插件适合同时推进多个项目、经常更换桌面 Agent，或需要复核历史决定的人。比如你可以找出两次讨论交付格式的会话，看到哪句话出自用户、哪句仅是助手建议，然后只把最终约束和两条依据交给下一个 Agent。

## 怎么用

1. **找会话。** 在 Harness 侧栏打开「会话汇总」，输入关键词或一句描述，按相关度、最新或最早排序。结果显示客户端和项目，同一会话的多处命中可以展开。
2. **选原话。** 点「浏览全部分段」，按语义相关度找局部细节，或按原文顺序查看上下文。可以跨页勾选，再复制带会话、消息引用和字符位置的 Markdown。
3. **比较方案。** 在「比较方案」里选两个会话，对照用户要求、助手方案和依据。条件变更由规则提示，点回双方原话后再判断。也可以在 Harness 新聊天里让 Agent 先列候选，再按序号选。
4. **读日报。** 首页先展示已保存的日报和截止时间。平时按需手动刷新；Harness 保持运行时，默认北京时间 23:00 按项目整理当天发言，关掉插件面板也能执行。宿主退出或休眠期间错过的任务会在后续运行时补算。

## 安装与首次使用

适用环境为 Windows、DeepSeek Harness 桌面版、可从 PATH 启动的 64 位 Python。建议使用 Python 3.11 或 3.12。到 Release 下载 `dsh-agent-session-memory-0.8.2.tgz`，在下载目录打开 PowerShell，运行：

```powershell
dsh plugin --profile desktop add --offline .\dsh-agent-session-memory-0.8.2.tgz
$pluginDir = Join-Path $env:USERPROFILE '.dsh\profiles\desktop\node_modules\dsh-agent-session-memory'
python -m pip install -r (Join-Path $pluginDir 'requirements.txt')
```

如果找不到 `dsh`，用 Harness 安装目录内的 `resources\runtime\cli\bin\dsh.cmd` 替代命令名。完全退出再打开 Harness，点击「会话汇总 → 手动刷新」即可建立自己的索引。基础检索支持关键词、近似拼写及中英词典扩展。

**首次启用语义检索**时，在同一 PowerShell 窗口执行：

```powershell
& (Join-Path $pluginDir 'install-minilm.ps1')
```

脚本从公开上游下载量化 ONNX 权重和分词器，校验固定的 SHA-256，并安装 CPU 推理依赖。下载一次即可；文件已存在且校验通过时复用。重启 Harness 并手动刷新，或等待晚间更新。模型在本机生成 384 维向量，无需 API Key 或显卡。[固定模型版本](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/tree/2c4055b12046f11709e9df2c122e59ffbdc2f900) · [下载与校验代码](fetch_minilm.py)

## 怎样从一个问题找回原话

![本机检索流程：桌面会话按发言切分，片段和位置写入本机索引，查询返回可定位的原话。](docs/search-flow.svg)

- **按来源读取。** 适配 DeepSeek Harness、Codex、Claude Code、Kimi Code、WorkBuddy、ZCode、玻尔、Pi、OpenClaw、ChatLab、EvoScientist 和 ChatGPT 的本地导出。项目依据来自会话目录或项目标记，也可手动归类。ChatGPT 需要先导出到本机。
- **按发言切分。** 每条非空用户发言、助手回复和导入文档都参与索引。长消息优先在句末或换行处切开，相邻段保留约 16 个 token 的重叠。相同文本可复用向量，每次出现仍各自保留消息引用和字符偏移。
- **按问题检索。** 精确编号适合直接查关键词，跨语言描述可以结合词典、全文检索与可选 MiniLM 相似度。先按会话聚合，再看命中段。日报另用规则抽取原句和本地 TF-IDF／LSA 检索，便于逐条核对。

## 实际效果

### 六道可复现的原话检索题

我们生成了六段虚构 Claude 格式会话，其中三条分别讲货车防滑、钢琴调音、夜间观测，另三条作干扰。对每个目标分别用中文原词和英文描述查询。**成功标准是第一条结果指向正确会话，且能从返回的位置读到正确原话。** 同一道题只给一个查询机会，工具读取相同的文件。白板对照另列其可见输入。

| 对照方式 | 中文原词 | 英文描述 | 本插件相对增益 |
|---|---:|---:|---|
| 白板 Agent，新聊天只收到问题，不提供历史文件、工具或原文 | — | — | 六题的原始输入均没有可引用的历史消息；插件提供了 6/6 条可核验原话。生成模型答题正确率未测 |
| 简单 Prompt「在给定目录按我的原词搜索，返回第一条原话」；按提示实际执行一次固定字符串检索 | 3/3 | 0/3 | 3/6 → 6/6，首条原话命中率增加 **50 个百分点** |
| mblode 的 `chat-history` SKILL，自带检索脚本，使用原查询 | 3/3 | 0/3 | 3/6 → 6/6，同一指标增加 **50 个百分点** |
| 同一 SKILL，额外提供恰好出现在原文的中文关键词 | 3/3 | 3/3 | 6/6 → 6/6，**0 个百分点** |
| 本插件，全文检索、词典和本地 MiniLM 联合工作 | **3/3** | **3/3** | 六次均能回查原句 |

例如，输入 *tuning a piano and adjusting the pitch of its strings*，首条结果能定位到「演出前请为钢琴调音，调整每根琴弦的音高。」如果已经知道原文用了「琴弦」，对照工具同样能找到它。这组题衡量**用户不知道原词时的一次检索**。样本仅有三个主题，未拆分词典和模型各自的贡献，也未测试 Agent 自主翻译、反复调用工具后的成功率。

**与高关注同类 SKILL 的差异。** thedotmack 的 `claude-mem/mem-search` 先查索引，再看时间线、按需取回观察记录，适合回答「以前怎么做的」。本插件把「任选两段桌面对话，比较需求是否变过，每项点回说话人的原句」做成直接操作；也可以在同一长会话跨页选段、按原顺序复制。这里没有对 `claude-mem` 运行相同的完整采集与检索流程，故对它的准确率和耗时增益均未测。上表的数值只对应实际运行的 `chat-history`。截至 2026-11-20，两者所在仓库分别有 118,517 和 211 Stars，Stars 表示项目关注度。[claude-mem 的固定版 SKILL](https://github.com/thedotmack/claude-mem/blob/c0f37d60b2e4860851575e3cbb003f23fc340d4e/plugin/skills/mem-search/SKILL.md) · [chat-history 的固定版 SKILL](https://github.com/mblode/agent-skills/blob/ff9805a3dabf4529f4d88f6b3f09c5a33cb0fcb6/skills/chat-history/SKILL.md)

**复现方法。** 安装本地模型与基础依赖，在 PATH 中准备 ripgrep，下载上游固定版本的 `history.py`，在本仓库执行以下命令。脚本只在临时目录生成虚构输入与索引，输出每题的命中情况。[对照脚本](https://github.com/mblode/agent-skills/blob/ff9805a3dabf4529f4d88f6b3f09c5a33cb0fcb6/skills/chat-history/scripts/history.py) · [完整题目和评分程序](benchmarks/recall.py)

```powershell
$python = Join-Path $env:USERPROFILE '.dsh\storages\agent-session-memory\minilm-runtime\Scripts\python.exe'
& $python -B -X utf8 .\benchmarks\recall.py .\history.py
```

### 一次真实规模的本地验证

在一台 Windows 机器上，单次迁移处理 **4,144 个会话、63,065 条正文**，生成 **531,443 个正文分段**，耗时约 **19 分钟**。逐段核对引用、字符偏移和消息末尾，覆盖了全部已收录正文；无变更时立即重跑，新增编码 **0 段**。这些数字说明全库覆盖和增量行为，耗时会随机器和语料变化。公开材料只保留计数和虚构复现实例。

## 数据在哪里

发布包含插件代码、中英公共词典和模型安装脚本。用户自己的会话、切分原文、日报和向量保存在本机，默认历史库位于 `%LOCALAPPDATA%\AgentSessionMemory`。首次安装从公共源下载依赖；侧栏检索与建索引在本地执行。若从聊天里调用工具，选中的结果会进入该聊天上下文；是否发送到云端取决于 Harness 使用的聊天模型。

## 引用与致敬

| 作者与项目 | 具体贡献和本项目的使用方式 |
|---|---|
| [HarryHeYu · sessionFlow](https://github.com/HarryHeYu/sessionFlow) 与 [dsh-sessionflow](https://github.com/HarryHeYu/dsh-sessionflow) | 跨 Agent 查找历史、按当前问题组织交接背景，以及在 Harness 中接续工作的设计启发。 |
| [yckbz · zotero-vectorize](https://github.com/yckbz/zotero-vectorize) | 借鉴条目级与正文分段检索、增量索引、从命中位置回到原文的思路。在这里，对应的是「会话 → 消息片段 → 发言位置」。 |
| [Sentence Transformers · 多语言 MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) 与 [Xenova · ONNX 版本](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2) | 直接使用上游预训练模型、量化权重及分词器进行本地推理。权重按需从上游下载。 |
| [Paul Andrew Denisowski、CC-CEDICT 社区与 MDBG](https://www.mdbg.net/chinese/dictionary?page=cedict) | 随包词典源于 CC-CEDICT。转换脚本筛选短释义、统一大小写并生成双向索引，改编词典沿用 CC BY-SA 4.0。[词典许可及改动](DICTIONARY-LICENSE.txt) |
| [mblode · agent-skills](https://github.com/mblode/agent-skills) 与 [thedotmack · claude-mem](https://github.com/thedotmack/claude-mem) | 分别用于可重复的工具对照和功能比较。上游 SKILL 与脚本保留在原项目。 |
| [tt-a1i · Archify](https://github.com/tt-a1i/archify) | 用于绘制 README 的本地检索流程图。 |

**本项目独立实现**桌面来源适配、项目归类、晚间日报、原话引用、会话级结果聚合、两段方案对比与跨页选段。sessionFlow 和 zotero-vectorize 对这里的影响是产品与检索设计；运行插件无需安装这两个项目。

