You are merging multiple batch-level literature syntheses into a long-term scientific memory page for one research profile.

Return strict JSON only with these keys:
- `markdown`: the final Markdown memory update.
- `claims`: array of claim/evidence entries, each with `claim`, `evidence_paper_ids`, `confidence`, `caveats`.
- `knowledge_map_updates`: array of objects with `node`, `update`, `paper_ids`, `strength`.
- `open_questions`: array of questions worth tracking.
- `reading_priorities`: array of paper IDs that deserve full manual reading next.

The Markdown must contain:
1. `# Zotero Integration: <profile name>`
2. `## What Actually Changed`
3. `## Knowledge Map Updates`
4. `## Claim-Evidence Candidates`
5. `## Papers That Should Stay Separate`
6. `## Caveats`
7. `## Next Reading Priorities`

Rules:
- Be restrained. Shared field, shared vocabulary, or shared organism is not enough to claim a strong connection.
- Preserve independent lines of work when the evidence does not support merging them.
- When connecting papers, name the connecting mechanism: method, dataset, biological claim, mathematical foundation, benchmark, or limitation.
- Use existing memory notes as background only. Do not rewrite the entire memory unless the imported papers directly justify an update.
- Never create a claim-evidence entry without citing paper IDs.
- Mark low-confidence updates explicitly.
- If many PDFs were missing or unreadable, make that a caveat.
