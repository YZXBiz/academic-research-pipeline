FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 tree && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv init /workspace && cd /workspace && uv add \
    pandas numpy scikit-learn xgboost lightgbm catboost \
    matplotlib seaborn scipy statsmodels shap scikit-posthocs \
    ucimlrepo datasets requests openai anthropic \
    autogluon

COPY tcp_server.py /usr/local/bin/tcp_server.py

WORKDIR /workspace

CMD ["python", "/usr/local/bin/tcp_server.py", "--port", "8000", "--workplace", "/workspace"]
