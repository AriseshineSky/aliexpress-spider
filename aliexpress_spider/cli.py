from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from aliexpress_spider.config import DEFAULT_USER_DATA_DIR, build_settings
from aliexpress_spider.crawler import CrawlBlockedError, run_crawler
from aliexpress_spider.elasticsearch_store import (
    ElasticsearchProductWriter,
    load_elasticsearch_settings,
)
from aliexpress_spider.verify import verify_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@click.group()
def main() -> None:
    """AliExpress product crawler."""


@main.command("verify")
@click.option(
    "--user-data-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_USER_DATA_DIR,
    show_default=True,
    help="Persistent browser profile directory.",
)
@click.option(
    "--timeout",
    default=300,
    show_default=True,
    help="Seconds to wait for manual captcha solve.",
)
def verify(user_data_dir: Path, timeout: int) -> None:
    """Open a visible browser so you can pass AliExpress captcha manually."""
    click.echo("A Chromium window will open. Complete any captcha or login prompts.")
    click.echo("The session is saved to your profile for later headless crawls.")
    click.echo(f"Profile: {user_data_dir}")
    click.echo(f"Waiting up to {timeout}s...\n")

    result = verify_session(user_data_dir, timeout_seconds=timeout)
    click.echo(f"Profile: {result['profile_dir']}")
    click.echo(f"Home page OK: {result['home_ok']}")
    click.echo(f"Category listing OK: {result['category_ok']}")
    click.echo(result.get("message", ""))

    if result["home_ok"] and result["category_ok"]:
        click.echo(
            "\nYou can now crawl with:\n"
            "  python -m aliexpress_spider crawl --user-data-dir "
            f"{user_data_dir}"
        )
        raise SystemExit(0)

    click.echo(
        "\nVerification incomplete. Retry with:\n"
        f"  python -m aliexpress_spider verify --timeout {timeout}"
    )
    raise SystemExit(1)


@main.command("crawl")
@click.option(
    "--categories",
    "categories_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to categories YAML config.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for JSONL output.",
)
@click.option("--max-pages", default=5, show_default=True, help="Max listing pages per category.")
@click.option(
    "--max-products",
    default=50,
    show_default=True,
    help="Max validated products per category.",
)
@click.option("--max-price", default=100.0, show_default=True, help="Maximum price in USD.")
@click.option("--min-rating", default=4.4, show_default=True, help="Minimum review rating.")
@click.option("--min-reviews", default=1000, show_default=True, help="Minimum review count.")
@click.option("--min-sold", default=1000, show_default=True, help="Minimum sold count.")
@click.option("--headed", is_flag=True, help="Run browser in headed mode.")
@click.option(
    "--captcha-wait",
    default=0,
    show_default=True,
    help="Seconds to wait for manual captcha solve when detected.",
)
@click.option(
    "--user-data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Persistent browser profile directory.",
)
@click.option(
    "--exit-on-block/--no-exit-on-block",
    default=True,
    show_default=True,
    help="Exit immediately when captcha/block page is detected (default for headless).",
)
@click.option(
    "--no-es",
    is_flag=True,
    help="Disable Elasticsearch export even when .env is configured.",
)
def crawl(
    categories_path: Path | None,
    output_dir: Path | None,
    max_pages: int,
    max_products: int,
    max_price: float,
    min_rating: float,
    min_reviews: int,
    min_sold: int,
    headed: bool,
    captcha_wait: int,
    user_data_dir: Path | None,
    exit_on_block: bool,
    no_es: bool,
) -> None:
    """Crawl AliExpress categories and export StandardProduct JSONL."""
    settings = build_settings(
        categories_path=categories_path,
        output_dir=output_dir,
        max_pages=max_pages,
        max_products=max_products,
        headless=not headed,
        user_data_dir=user_data_dir,
        captcha_wait_seconds=captcha_wait,
        exit_on_block=exit_on_block,
        enable_elasticsearch=not no_es,
        max_price_usd=max_price,
        min_rating=min_rating,
        min_reviews=min_reviews,
        min_sold_count=min_sold,
    )

    click.echo("Filter rules:")
    click.echo(f"  price < ${settings.filters.max_price_usd}")
    click.echo(f"  rating >= {settings.filters.min_rating}")
    click.echo(f"  reviews >= {settings.filters.min_reviews}")
    click.echo(f"  sold_count >= {settings.filters.min_sold_count}")
    click.echo(f"Categories: {len(settings.categories)}")
    click.echo(f"Headless: {settings.headless}")
    click.echo(f"Exit on block: {settings.exit_on_block}")
    if settings.elasticsearch:
        click.echo(f"Elasticsearch: {settings.elasticsearch.index}")
    elif not no_es:
        click.echo("Elasticsearch: disabled (.env missing ELASTICSEARCH_URL/INDEX)")

    try:
        stats = run_crawler(settings)
    except CrawlBlockedError as exc:
        click.echo(f"\nBlocked by AliExpress anti-bot page: {exc}")
        click.echo(
            "Headless crawl stopped. To continue manually, run:\n"
            "  python -m aliexpress_spider verify\n"
            "  python -m aliexpress_spider crawl --headed --no-exit-on-block --captcha-wait 120"
        )
        raise SystemExit(2) from exc

    if stats.get("validated", 0) == 0:
        click.echo(
            "\nNo products exported. If AliExpress shows captcha, run:\n"
            "  python -m aliexpress_spider verify\n"
            "Then crawl again with the saved browser profile."
        )
    click.echo("\nDone.")
    for key, value in stats.items():
        click.echo(f"  {key}: {value}")


@main.command("import-es")
@click.argument(
    "jsonl_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def import_es(jsonl_path: Path) -> None:
    """Import StandardProduct JSONL records into Elasticsearch."""
    es_settings = load_elasticsearch_settings()
    if es_settings is None:
        raise click.ClickException(
            "Elasticsearch is not configured. Set ELASTICSEARCH_URL and ELASTICSEARCH_INDEX in .env."
        )

    writer = ElasticsearchProductWriter(es_settings)
    imported = 0
    with jsonl_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            category = str(record.pop("category", ""))
            writer.write(record, category)
            imported += 1

    writer.close()
    click.echo(f"Imported {imported} products from {jsonl_path}")
    click.echo(f"Elasticsearch index: {es_settings.index}")
    click.echo(f"  saved: {writer.saved}")
    click.echo(f"  failed: {writer.failed}")
    if writer.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
