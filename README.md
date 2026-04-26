# LiteratureRadar

LiteratureRadar is a local-first macOS research radar for tracking arXiv and bioRxiv papers, ranking them against multiple research profiles, and exporting long-term memory notes to Obsidian plus citation files for Zotero.

## Current shape

- SwiftUI macOS app shell.
- Python worker with SQLite as the source of truth.
- Official or aggregator APIs only: arXiv API, bioRxiv API, Europe PMC, OpenAlex, and Semantic Scholar.
- DeepSeek is used only after script-based filtering. Commands that write long-term memory require a successful DeepSeek call; they fail without writing a note if the key or API call fails. Non-memory triage can still return shallow local metadata analysis.

## Run

```bash
swift run LiteratureRadar
```

If you launch it from Terminal and the Terminal keeps keyboard focus, run it in
the background instead:

```bash
swift run LiteratureRadar &
```

The app also explicitly activates its main window on startup, which prevents
Settings text fields from sending typed characters back to the shell.

For double-click launch on macOS, use `Launch LiteratureRadar.command`. It builds
`dist/LiteratureRadar.app` once if needed and then opens the app bundle.
After the first build, you can also open `dist/LiteratureRadar.app` directly
like a normal macOS app.

To build the app bundle explicitly:

```bash
Scripts/build_app_bundle.sh
```

The app creates its default database at:

```text
~/Library/Application Support/LiteratureRadar/literature_radar.sqlite3
```

For command-line worker testing:

```bash
python3 Sources/LiteratureRadar/Resources/worker/litradar.py init --db /tmp/litradar.sqlite3 <<< '{"seed_demo": true}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py list-papers --db /tmp/litradar.sqlite3 <<< '{}'
```

## Test

```bash
python3 -m unittest discover -s Tests/python
swift build
```

## DeepSeek keys

The macOS app saves DeepSeek keys to Keychain:

- Reading and synthesis key: `LiteratureRadarDeepSeekReaderAPIKey`
- Fast profile-generation key: `LiteratureRadarDeepSeekFlashAPIKey`

If the fast key is empty, profile generation uses the reading key. Older keys saved under `LiteratureRadarDeepSeekAPIKey` are still read for compatibility.
The app does not read Keychain on startup; it only loads keys when you open
Settings or run a DeepSeek-backed action.

In the app:

1. Open `Settings`.
2. Paste your normal DeepSeek key into `Reading and synthesis API key`.
3. Optionally paste a separate key into `Fast profile-generation API key`.
4. Press `Save to Keychain`.

For command-line worker usage:

```bash
export DEEPSEEK_API_KEY=sk-...
export DEEPSEEK_FLASH_API_KEY=sk-...
```

## Zotero import

First version uses Zotero export files instead of directly mutating Zotero's internal SQLite database.

1. In Zotero, select the papers you want.
2. Use `File > Export Items...`.
3. Choose `BibTeX`, `RIS`, or `CSL JSON`.
4. In LiteratureRadar, open `Settings > Zotero Import`.
5. Choose either the exported file or the exported folder. For Zotero folders shaped like `export.bib` plus `files/399/paper.pdf`, LiteratureRadar resolves those relative PDF paths automatically.
6. Select the imported papers, then press `Integrate Selected`.

The worker reads local PDFs when available, processes imported papers in batches with DeepSeek, then performs a final restrained knowledge-map merge. If the DeepSeek reader key is missing or the API call fails, the integration fails and no memory note is written.

PDF extraction uses optional local tools in this order: `pypdf`, `PyPDF2`, `pdfminer.six`, `pdftotext`, then a raw-text scan. Recommended setup:

```bash
python3 -m pip install pypdf
```

If you install Python packages into a non-default Python, set:

```bash
export LITRADAR_PYTHON=/path/to/python3
```

## Notes

This first version is local-first and dependency-light. Python can run with only the standard library, but Zotero PDF reading improves when `pypdf` or another PDF text extractor is installed. The Swift app calls the worker through JSON over stdin/stdout.

## Research Memory OS 重构

本版本把原来的“长期记忆笔记列表”升级为分层科研记忆系统。核心变化：

- **L0 证据层**：`paper_chunks`、`evidence_spans` 保存原文片段、页码、section 和 quote hash。
- **L1 事件/浅层记忆**：`episodic_events`、`interest_states` 保存搜索、点击、收藏、浅读和反馈信号；这些信号不能直接晋升为事实。
- **L2 语义知识层**：`knowledge_nodes`、`knowledge_edges`、`atomic_knowledge_units` 保存概念、方法、claim、limitation、experiment、open question 以及跨论文关系。
- **L3 方法论层**：`methodology_rules` 保存可复用科研流程，例如深读 agent memory 论文时要抽取 write/store/retrieve/update/forget。
- **L4 元认知层**：`metacognitive_items` 保存 hypothesis、insight、gap、critique 和 next action。
- **L5 工作记忆层**：`context_packets`、`retrieval_traces` 记录一次任务到底激活了哪些语义知识、证据、事件、方法论和元认知上下文。

所有长期写入都通过 `memory_change_sets`、`memory_change_log` 和 `review_queue` 留痕；高风险写入不会直接覆盖知识结构。

### 新 worker 命令

```bash
python3 Sources/LiteratureRadar/Resources/worker/litradar.py memory-dashboard --db /tmp/litradar.sqlite3 <<< '{"profile_id":"default_profile"}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py mind-map --db /tmp/litradar.sqlite3 <<< '{"profile_id":"default_profile"}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py context-packet --db /tmp/litradar.sqlite3 <<< '{"query":"agent memory", "profile_id":"default_profile"}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py rebuild-taxonomy --db /tmp/litradar.sqlite3 <<< '{"profile_id":"default_profile"}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py review-list --db /tmp/litradar.sqlite3 <<< '{}'
python3 Sources/LiteratureRadar/Resources/worker/litradar.py repair-memory --db /tmp/litradar.sqlite3 <<< '{"apply":false}'
```

### UI 变化

- 新增 **Research OS** 首页：展示系统健康度、知识节点、证据片段、候选论文和工作流。
- 新增 **Memory OS** 面板：Dashboard、Knowledge Tree、Context Packet、Memory Notes、Review Queue。
- 研究方向页重构为“方向列表 + 方向编辑器 + DeepSeek Flash 方向生成”。
- Settings 中保存的 Keychain API key 会注入到 Python worker 环境变量，命令行仍支持 `DEEPSEEK_API_KEY` / `DEEPSEEK_READER_API_KEY` / `DEEPSEEK_FLASH_API_KEY`。

### 纠错入口

- `repair-memory --apply false`：只检查孤立边、无证据 claim、draft 节点等问题。
- `repair-memory --apply true`：对明显结构性错误执行保守修复。
- `review-list`：查看高风险 MemoryChangeSet。
- `context-packet`：检查某次任务到底召回了哪些记忆，便于判断是证据层、兴趣层、图谱层还是上下文组装层出了问题。
