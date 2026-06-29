from __future__ import annotations

from dataclasses import dataclass

from aliexpress_spider.config import CrawlFilters


@dataclass(frozen=True)
class ListingCandidate:
    product_id: str
    url: str
    category: str
    price: float | None = None
    rating: float | None = None
    reviews: int | None = None
    sold_count: int | None = None


def passes_listing_filters(candidate: ListingCandidate, filters: CrawlFilters) -> bool:
    """Apply quick filters when listing cards expose metrics."""
    if candidate.price is not None and candidate.price >= filters.max_price_usd:
        return False
    if candidate.rating is not None and candidate.rating < filters.min_rating:
        return False
    if candidate.reviews is not None and candidate.reviews < filters.min_reviews:
        return False
    if candidate.sold_count is not None and candidate.sold_count < filters.min_sold_count:
        return False
    return True


def passes_product_filters(product: dict, filters: CrawlFilters) -> bool:
    price = product.get("price")
    rating = product.get("rating")
    reviews = product.get("reviews")
    sold_count = product.get("sold_count")

    if price is None or price >= filters.max_price_usd:
        return False
    if rating is None or rating < filters.min_rating:
        return False
    if reviews is None or reviews < filters.min_reviews:
        return False
    if sold_count is None or sold_count < filters.min_sold_count:
        return False
    return True
