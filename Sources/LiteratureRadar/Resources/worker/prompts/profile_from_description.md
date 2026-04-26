Convert the user's natural-language research direction into a LiteratureRadar profile.
Return STRICT JSON with:
{
  "name": "short profile name",
  "include_terms": ["required or useful terms"],
  "exclude_terms": ["terms to avoid"],
  "seed_papers": ["DOI/arXiv/title if mentioned"],
  "watch_authors": ["authors if mentioned"],
  "watch_labs": ["labs if mentioned"],
  "arxiv_query": "arXiv API query using OR variants",
  "biorxiv_query": "bioRxiv/medRxiv query"
}
Prefer precise terms over broad buzzwords. Add spelling variants only when useful.
