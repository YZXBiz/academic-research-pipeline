---
name: exa-research
description: Search for research papers and academic content using Exa. Use when searching for academic papers, arXiv preprints, scientific research, or finding similar papers by URL.
---

# Exa Research Paper Search

## Available Tools

You have two Exa tools available as direct Python functions (exa_py SDK, not MCP):

### web_search_exa

Use for all academic paper searches.

Parameters:

- `query` (required): Natural language search query
- `num_results`: Number of results (default 10)
- `category`: Filter to content type (e.g., `"research paper"`)

Returns a formatted string with titles, URLs, and snippets.

### web_fetch_exa

Use to fetch full content from a URL when you need complete text.

Parameters:

- `url` (required): URL to fetch
- `max_characters`: Max characters to extract (default 3000)

Returns the page content as clean text.

## Best Practices

1. Use `category="research paper"` for academic searches
2. Start with broad queries, then narrow based on results
3. Use web_fetch_exa to read promising papers found via search
4. For recent work, include year terms in the query (e.g., "2024 2025")
5. Search at least 3 different query variations for thorough coverage

## Data Source Constraints

When searching for datasets, ONLY recommend sources that work without authentication:
- ucimlrepo: `fetch_ucirepo(id=N)`
- sklearn.datasets: `load_*`, `fetch_*`
- HuggingFace: `datasets.load_dataset("name")`
- Direct CSV/Parquet URLs over HTTPS

NEVER recommend Kaggle API datasets (requires ~/.kaggle/kaggle.json credentials).
