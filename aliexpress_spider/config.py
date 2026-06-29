from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml

from aliexpress_spider.elasticsearch_store import ElasticsearchSettings, load_elasticsearch_settings

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_CATEGORIES_PATH = PROJECT_ROOT / "config" / "categories.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class CategoryConfig:
    name: str
    url: str


@dataclass(frozen=True)
class CrawlFilters:
    max_price_usd: float = 100.0
    min_rating: float = 4.4
    min_reviews: int = 1000
    min_sold_count: int = 1000


DEFAULT_USER_DATA_DIR = Path.home() / ".aliexpress-spider" / "browser"


@dataclass(frozen=True)
class CrawlSettings:
    categories: list[CategoryConfig]
    filters: CrawlFilters
    max_pages_per_category: int = 5
    max_products_per_category: int = 50
    headless: bool = True
    output_dir: Path = DEFAULT_OUTPUT_DIR
    user_data_dir: Path | None = DEFAULT_USER_DATA_DIR
    request_delay_ms: tuple[int, int] = (2000, 4000)
    captcha_wait_seconds: int = 0
    exit_on_block: bool = True
    elasticsearch: ElasticsearchSettings | None = None
    enable_elasticsearch: bool = True


def load_categories(path: Path | str = DEFAULT_CATEGORIES_PATH) -> list[CategoryConfig]:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return [CategoryConfig(name=item["name"], url=item["url"]) for item in raw["categories"]]


def build_settings(
    categories_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    max_pages: int = 5,
    max_products: int = 50,
    headless: bool = True,
    user_data_dir: Path | str | None = DEFAULT_USER_DATA_DIR,
    captcha_wait_seconds: int = 0,
    exit_on_block: bool = True,
    enable_elasticsearch: bool = True,
    elasticsearch: ElasticsearchSettings | None = None,
    shuffle_categories: bool = False,
    **filter_overrides: Any,
) -> CrawlSettings:
    filters = CrawlFilters(**{k: v for k, v in filter_overrides.items() if v is not None})
    es_settings = elasticsearch
    if es_settings is None and enable_elasticsearch:
        es_settings = load_elasticsearch_settings()
    categories = load_categories(categories_path or DEFAULT_CATEGORIES_PATH)
    if shuffle_categories:
        random.shuffle(categories)
    return CrawlSettings(
        categories=categories,
        filters=filters,
        max_pages_per_category=max_pages,
        max_products_per_category=max_products,
        headless=headless,
        output_dir=Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR,
        user_data_dir=Path(user_data_dir) if user_data_dir else DEFAULT_USER_DATA_DIR,
        captcha_wait_seconds=captcha_wait_seconds,
        exit_on_block=exit_on_block,
        elasticsearch=es_settings,
        enable_elasticsearch=enable_elasticsearch,
    )
