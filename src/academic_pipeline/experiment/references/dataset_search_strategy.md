# Dataset Search Strategy

## MANDATORY: Search before proposing ANY dataset

Before including any dataset in your ExperimentPlan, you MUST:

1. Search for it using web_search_exa
2. Fetch the result page using web_fetch_exa to confirm data is downloadable
3. Record the exact URL or package loading instruction

## Query patterns (try AT LEAST 3 different queries):

1. "{topic keywords} public dataset CSV download"
2. "{topic keywords} benchmark dataset UCI ML repository"
3. "{topic keywords} dataset HuggingFace"
4. "{topic keywords} ucimlrepo fetch_ucirepo"
5. "{topic keywords} experiment data open access"
6. "{domain} open data government portal"

## FORBIDDEN sources (sandbox has NO credentials):

- Kaggle API (kaggle.api, kaggle competitions download) — requires ~/.kaggle/kaggle.json
- Any source requiring API keys, OAuth, or login credentials
- Google Drive links requiring consent clicks

## After finding a URL, VERIFY it:

Use web_fetch_exa to read the page. Check:

- Does the page have actual data (not just a description)?
- Is the data downloadable (CSV, JSON, Parquet, or via Python API)?
- How many rows/columns? Is it large enough for ML? (>100 rows minimum)
- Is it actually about your topic or just a keyword match?

## Known reliable package-based sources (no URL needed):

- sklearn.datasets: load_iris, load_wine, fetch_california_housing, fetch_openml("name")
- ucimlrepo: fetch_ucirepo(id=N)
- HuggingFace: datasets.load_dataset("name")
- statsmodels.datasets: macrodata, anes96, etc.

## For each dataset, record:

- name: Human-readable name
- source: "sklearn" | "ucimlrepo" | "huggingface" | "url"
- download_instruction: Exact Python code to load it
- expected_shape: "N rows x M columns"
- target_column: The prediction target
- verified_via: "search_result" | "known_package" (NEVER "memory")

## If you cannot find a suitable dataset:

Set dataset_sources to an empty list. Do NOT fabricate URLs.
