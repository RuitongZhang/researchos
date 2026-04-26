# Research Memory OS implementation notes

## What changed

1. Replaced report-only long-term memory with a layered memory model:
   - evidence spans
   - episodic events
   - interest states
   - semantic knowledge graph
   - methodology rules
   - metacognitive items
   - context packets and retrieval traces
2. Added provenance-first write path:
   - memory change sets
   - change log
   - review queue
   - conflict / repair utilities
3. Preserved old app flows:
   - demo ingest
   - ranking
   - local search
   - profile CRUD
   - Zotero import
   - DeepSeek usefulness reading
   - weekly synthesis
   - Obsidian / Zotero export
4. Updated macOS SwiftUI UI:
   - Research OS overview
   - Memory OS dashboard
   - knowledge tree panel
   - context packet debugger
   - review queue panel
   - cleaner cards, chips, and status surfaces

## Important safety invariant

Search, skim, click, save, hide, and local analysis are shallow signals. They only update `episodic_events` and `interest_states`. They do not create validated semantic knowledge.

Commands that write long-term semantic memory require a successful DeepSeek reader call. Without a reader key, `usefulness`, `synthesize`, and `integrate-papers` fail before writing memory notes or read actions.

## Test status in this environment

Validated:

```bash
python3 -m py_compile Sources/LiteratureRadar/Resources/worker/litradar.py
python3 -m unittest discover -s Tests/python -v
```

Also smoke-tested CLI commands:

```bash
init
memory-dashboard
context-packet
```

Not validated here:

- `swift build` on macOS, because this execution environment is Linux and does not provide SwiftUI/Security frameworks.
- Real DeepSeek network calls, because no API key was available in the environment.

