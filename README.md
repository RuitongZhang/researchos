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
once if needed and then starts `.build/debug/LiteratureRadar` in the background.

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
