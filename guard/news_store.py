import json
from pathlib import Path
from typing import Any


NEWS_FILE_PATH = Path(__file__).resolve().parent.parent / "data" / "news.json"


def load_news(
    news_file_path: str | Path = NEWS_FILE_PATH,
) -> list[dict[str, Any]]:
    path = Path(news_file_path)

    with path.open(encoding="utf-8") as news_file:
        articles = json.load(news_file)

    if not isinstance(articles, list) or not all(
        isinstance(article, dict) for article in articles
    ):
        raise ValueError("News data must be a list of objects")

    return sorted(
        articles,
        key=lambda article: str(article.get("published_at", "")),
        reverse=True,
    )
