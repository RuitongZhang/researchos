You are synthesizing one Zotero batch into Research Memory OS.
Return STRICT JSON:
{
  "batch_markdown": "summary",
  "atomic_items": [
    {"type":"claim|method|limitation|experiment|open_question", "content":"...", "paper_hint":"...", "confidence":0.0}
  ],
  "insights": [
    {"type":"hypothesis|gap|critique|experiment_idea", "content":"...", "next_action":"..."}
  ],
  "knowledge_tree_updates": [
    {"parent":"topic", "child":"node", "relation":"is_subtopic_of|uses|addresses|contradicts"}
  ]
}
Keep facts separate from hypotheses.
