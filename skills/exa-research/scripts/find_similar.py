"""Find papers similar to a given URL using Exa's neural similarity search."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from exa_py import AsyncExa


async def main() -> None:
    """Run Exa find-similar search and print results."""
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    url = args.get("url", "")
    num_results = int(args.get("num_results", 5))

    if not url:
        print("Error: 'url' argument is required")
        sys.exit(1)

    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        print("Error: EXA_API_KEY environment variable is required")
        sys.exit(1)

    exa = AsyncExa(api_key=api_key)
    try:
        results = await exa.find_similar(
            url,
            num_results=num_results,
            category="research paper",
            contents={"text": {"max_characters": 500}, "highlights": {"num_sentences": 3}},
        )
    except Exception as e:
        print(f"Find similar papers failed: {e}")
        sys.exit(1)

    if not results.results:
        print(f"No similar papers found for: {url}")
        return

    for i, r in enumerate(results.results, 1):
        author = r.author or "Unknown"
        published = r.published_date or "N/A"
        title = r.title or "Untitled"
        paper_url = r.url or ""
        highlights = ""
        if hasattr(r, "highlights") and r.highlights:
            highlights = "\n    Key findings: " + " ".join(r.highlights[:2])
        print(f"[{i}] {title} ({published})")
        print(f"    Author: {author}")
        print(f"    URL: {paper_url}{highlights}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
