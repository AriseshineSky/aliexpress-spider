from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from aliexpress_spider.config import CategoryConfig, CrawlSettings
from aliexpress_spider.filters import ListingCandidate, passes_listing_filters, passes_product_filters
from aliexpress_spider.formatter import to_standard_product
from aliexpress_spider.network import (
    ResponseCollector,
    adapt_payload_to_legacy,
    extract_search_candidates,
    is_captcha_page,
)
from aliexpress_spider.html_utils import clean_product_description, normalize_specifications
from aliexpress_spider.output import ProductWriter
from aliexpress_spider.parser import AliExpressPageParser

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
"""


class CrawlBlockedError(RuntimeError):
    """AliExpress captcha or anti-bot page detected."""


class AliExpressCrawler:
    def __init__(self, settings: CrawlSettings):
        self.settings = settings
        self.parser = AliExpressPageParser()
        self.writer = ProductWriter.from_settings(
            settings.output_dir,
            settings.elasticsearch,
            enable_es=settings.enable_elasticsearch,
        )
        self._seen_product_ids: set[str] = set()

    async def run(self) -> dict[str, int]:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        stats = {
            "categories": 0,
            "listing_candidates": 0,
            "detail_fetched": 0,
            "passed_filters": 0,
            "validated": 0,
            "captcha_hits": 0,
        }

        async with async_playwright() as playwright:
            context, browser = await self._create_browser_context(playwright)
            try:
                for category in self.settings.categories:
                    stats["categories"] += 1
                    logger.info("Crawling category: %s", category.name)
                    await self._crawl_category(context, category, stats)
            finally:
                await context.close()
                if browser is not None:
                    await browser.close()

        self.writer.close()
        if self.writer.es_writer is not None:
            stats["es_saved"] = self.writer.es_saved
            stats["es_failed"] = self.writer.es_failed
        return stats

    async def _create_browser_context(self, playwright) -> tuple[BrowserContext, Browser | None]:
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if self.settings.user_data_dir:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.user_data_dir),
                headless=self.settings.headless,
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
                args=launch_args,
            )
            await context.add_init_script(STEALTH_SCRIPT)
            return context, None

        browser = await playwright.chromium.launch(
            headless=self.settings.headless,
            args=launch_args,
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
        )
        await context.add_init_script(STEALTH_SCRIPT)
        return context, browser

    async def _crawl_category(
        self, context: BrowserContext, category: CategoryConfig, stats: dict[str, int]
    ) -> None:
        saved_in_category = 0
        captcha_hits = 0
        detail_tries = 0
        filtered_out = 0
        listing_seen = 0
        seen_in_category: set[str] = set()
        page_no = 0

        page = await context.new_page()
        collector = ResponseCollector()

        async def on_response(response) -> None:
            await collector.handle_response(response)

        page.on("response", on_response)

        try:
            loaded = False
            listing_urls = [category.url, self._wholesale_search_url(category.name)]

            while True:
                page_no += 1
                if self._page_limit_reached(page_no):
                    logger.info(
                        "Reached max listing pages (%s) for %s",
                        self.settings.max_pages_per_category,
                        category.name,
                    )
                    break
                if self._product_quota_reached(saved_in_category):
                    break

                if page_no == 1:
                    page_candidates: list[ListingCandidate] = []
                    for url in listing_urls:
                        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
                        await self._sleep()
                        if await self._handle_captcha(page, return_url=url):
                            captcha_hits += 1
                        await page.wait_for_timeout(3000)
                        loaded = True
                        page_candidates = self._filter_listing_candidates(
                            self._merge_candidates(
                                self._candidates_from_collector(collector, category.name)
                                + await self._extract_listing_candidates(page, category.name)
                            )
                        )
                        if page_candidates:
                            break
                        logger.info("No listing data from %s, trying fallback URL", url)
                    if not loaded or not page_candidates:
                        logger.warning("No listing candidates for category %s", category.name)
                        break
                else:
                    logger.info("Category %s page %s", category.name, page_no)
                    if not await self._goto_next_page(page):
                        logger.info("No further listing pages for %s", category.name)
                        break
                    await self._sleep()
                    if await self._handle_captcha(page, return_url=page.url):
                        captcha_hits += 1
                    await page.wait_for_timeout(3000)
                    page_candidates = self._filter_listing_candidates(
                        self._merge_candidates(
                            self._candidates_from_collector(collector, category.name)
                            + await self._extract_listing_candidates(page, category.name)
                        )
                    )
                    if not page_candidates:
                        logger.info("Empty listing page %s for %s", page_no, category.name)
                        break

                listing_seen += len(page_candidates)
                for candidate in page_candidates:
                    if self._product_quota_reached(saved_in_category):
                        break
                    if candidate.product_id in self._seen_product_ids:
                        continue
                    if candidate.product_id in seen_in_category:
                        continue
                    seen_in_category.add(candidate.product_id)
                    detail_tries += 1

                    product = await self._fetch_product(context, candidate)
                    stats["detail_fetched"] += 1
                    if not product:
                        continue

                    if not passes_product_filters(product, self.settings.filters):
                        filtered_out += 1
                        logger.info(
                            "Filtered out %s (price=%s rating=%s reviews=%s sold=%s)",
                            candidate.product_id,
                            product.get("price"),
                            product.get("rating"),
                            product.get("reviews"),
                            product.get("sold_count"),
                        )
                        continue

                    stats["passed_filters"] += 1
                    standard = to_standard_product(
                        product["parsed"],
                        url=product["url"],
                        description=product.get("description", ""),
                        category_name=category.name,
                    )
                    if not standard:
                        logger.warning("StandardProduct validation failed for %s", candidate.product_id)
                        continue

                    self.writer.write(standard, category.name)
                    self._seen_product_ids.add(candidate.product_id)
                    saved_in_category += 1
                    stats["validated"] += 1
                    logger.info(
                        "Saved product %s | %s | $%.2f | rating=%s | reviews=%s | sold=%s",
                        standard["product_id"],
                        standard["title"][:60],
                        standard["price"],
                        standard["rating"],
                        standard["reviews"],
                        standard["sold_count"],
                    )
                    await self._sleep()
        finally:
            await page.close()

        stats["listing_candidates"] += listing_seen
        stats["captcha_hits"] += captcha_hits
        quota_label = (
            "unlimited"
            if self.settings.max_products_per_category <= 0
            else str(self.settings.max_products_per_category)
        )
        logger.info(
            "Category %s done: saved %s/%s (pages=%s, listing=%s, detail_tries=%s, filtered=%s, captcha=%s)",
            category.name,
            saved_in_category,
            quota_label,
            page_no,
            listing_seen,
            detail_tries,
            filtered_out,
            captcha_hits,
        )
        if (
            self.settings.max_products_per_category > 0
            and saved_in_category < self.settings.max_products_per_category
        ):
            logger.warning(
                "Category %s below quota. Strict filters (rating>=%s reviews>=%s sold>=%s) "
                "or listing exhaustion. Try --max-pages, --all-products, or lower --min-rating/--min-reviews/--min-sold.",
                category.name,
                self.settings.filters.min_rating,
                self.settings.filters.min_reviews,
                self.settings.filters.min_sold_count,
            )

    def _product_quota_reached(self, saved_in_category: int) -> bool:
        limit = self.settings.max_products_per_category
        return limit > 0 and saved_in_category >= limit

    def _page_limit_reached(self, page_no: int) -> bool:
        limit = self.settings.max_pages_per_category
        return limit > 0 and page_no > limit

    def _filter_listing_candidates(
        self, candidates: list[ListingCandidate]
    ) -> list[ListingCandidate]:
        filtered = [
            candidate
            for candidate in candidates
            if passes_listing_filters(candidate, self.settings.filters)
        ]
        if not filtered and candidates:
            logger.info(
                "Listing filters removed all %s candidates; keeping unfiltered pool for detail checks",
                len(candidates),
            )
            filtered = candidates
        return filtered

    def _wholesale_search_url(self, category_name: str) -> str:
        slug = quote(category_name.lower().replace("&", "and").replace(",", "").replace(" ", "-"))
        return (
            f"https://www.aliexpress.us/w/wholesale-{slug}.html"
            f"?SortType=total_tranpro_desc&maxPrice=99"
        )

    def _candidates_from_collector(
        self, collector: ResponseCollector, category_name: str
    ) -> list[ListingCandidate]:
        candidates: list[ListingCandidate] = []
        for payload in collector.search_payloads:
            for item in extract_search_candidates(payload):
                candidates.append(self._to_listing_candidate(item, category_name))
        return candidates

    def _to_listing_candidate(self, item: dict, category_name: str) -> ListingCandidate:
        product_id = str(item["product_id"])
        url = item.get("url") or f"https://www.aliexpress.us/item/{product_id}.html"
        if not str(url).startswith("http"):
            url = "https:" + str(url)
        return ListingCandidate(
            product_id=product_id,
            url=str(url).split("?")[0],
            category=category_name,
            price=item.get("price"),
            rating=item.get("rating"),
            reviews=item.get("reviews"),
            sold_count=item.get("sold_count"),
        )

    def _merge_candidates(self, candidates: list[ListingCandidate]) -> list[ListingCandidate]:
        merged: dict[str, ListingCandidate] = {}
        for candidate in candidates:
            existing = merged.get(candidate.product_id)
            if existing is None:
                merged[candidate.product_id] = candidate
                continue
            merged[candidate.product_id] = ListingCandidate(
                product_id=candidate.product_id,
                url=candidate.url or existing.url,
                category=candidate.category,
                price=candidate.price if candidate.price is not None else existing.price,
                rating=candidate.rating if candidate.rating is not None else existing.rating,
                reviews=candidate.reviews if candidate.reviews is not None else existing.reviews,
                sold_count=candidate.sold_count
                if candidate.sold_count is not None
                else existing.sold_count,
            )
        return list(merged.values())

    async def _extract_listing_candidates(self, page: Page, category_name: str) -> list[ListingCandidate]:
        script = """
        () => {
          const results = [];
          const selectors = [
            '[class*="card-out-wrapper"] a[href*="/item/"]',
            'a[href*="/item/"]'
          ];
          const seen = new Set();
          for (const selector of selectors) {
            for (const anchor of document.querySelectorAll(selector)) {
              const href = anchor.href || '';
              const match = href.match(/\\/item\\/(\\d+)\\.html/);
              if (!match) continue;
              const productId = match[1];
              if (seen.has(productId)) continue;
              seen.add(productId);

              const card = anchor.closest('[class*="card"], [class*="item"], [class*="product"], li, div');
              let price = null;
              let rating = null;
              let reviews = null;
              let sold = null;

              if (card) {
                const text = card.innerText || '';
                const priceMatch = text.match(/\\$\\s?(\\d+(?:\\.\\d+)?)/);
                if (priceMatch) price = parseFloat(priceMatch[1]);

                const ratingMatch = text.match(/(\\d\\.\\d)\\s*\\(/);
                if (ratingMatch) rating = parseFloat(ratingMatch[1]);

                const reviewsMatch = text.match(/\\((\\d[\\d,]*)\\)/);
                if (reviewsMatch) reviews = parseInt(reviewsMatch[1].replace(/,/g, ''), 10);

                const soldMatch = text.match(/(\\d[\\d,+]*)\\s+sold/i);
                if (soldMatch) sold = parseInt(soldMatch[1].replace(/[,+]/g, ''), 10);
              }

              results.push({
                product_id: productId,
                url: href.split('?')[0],
                price,
                rating,
                reviews,
                sold_count: sold,
              });
            }
          }
          return results;
        }
        """
        raw_items = await page.evaluate(script)
        return [self._to_listing_candidate(item, category_name) for item in raw_items]

    async def _goto_next_page(self, page: Page) -> bool:
        selectors = [
            "button.comet-pagination-next:not([disabled])",
            "li.next-next:not(.disabled) a",
            "a[aria-label='Next Page']",
        ]
        for selector in selectors:
            element = await page.query_selector(selector)
            if not element:
                continue
            try:
                await element.click()
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await self._sleep()
                return True
            except Exception:
                continue
        return False

    async def _fetch_product(self, context: BrowserContext, candidate: ListingCandidate) -> dict | None:
        page = await context.new_page()
        collector = ResponseCollector()

        async def on_response(response) -> None:
            await collector.handle_response(response)

        page.on("response", on_response)

        url = candidate.url
        if "gatewayAdapt" not in url:
            url = f"{url}?gatewayAdapt=glo2usa"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await self._sleep()
            if await self._handle_captcha(page, return_url=url):
                await page.reload(wait_until="domcontentloaded", timeout=90000)
                await self._sleep()

            legacy_data = None
            run_params = await page.evaluate(
                "() => (window.runParams && window.runParams.data) ? window.runParams.data : null"
            )
            if run_params and self.parser.is_product_exist(run_params):
                legacy_data = run_params

            fallback_legacy = None
            for payload in collector.pdp_payloads:
                adapted = adapt_payload_to_legacy(payload)
                if not adapted or not self.parser.is_product_exist(adapted):
                    continue
                if self.parser.get_title(adapted) and self.parser.get_pid(adapted):
                    legacy_data = adapted
                    break
                if fallback_legacy is None:
                    fallback_legacy = adapted
            if legacy_data is None:
                legacy_data = fallback_legacy

            if not legacy_data:
                logger.warning("No product payload for %s", candidate.product_id)
                return None

            parsed = self.parser.parse(legacy_data)
            parsed["product_id"] = parsed["product_id"] or candidate.product_id
            price = self.parser.get_product_price(parsed)
            if price <= 0 and candidate.price:
                price = candidate.price
            if parsed.get("rating", 0) <= 0 and candidate.rating:
                parsed["rating"] = candidate.rating
            if parsed.get("reviews", 0) <= 0 and candidate.reviews:
                parsed["reviews"] = candidate.reviews
            if parsed.get("sold_count", 0) <= 0 and candidate.sold_count:
                parsed["sold_count"] = candidate.sold_count

            page_content = await self._fetch_page_content(
                page,
                pc_desc_url=self.parser.get_description_url(legacy_data),
            )
            description = page_content.get("description") or ""
            dom_specs = page_content.get("specifications") or []
            if dom_specs:
                parsed["specifications"] = normalize_specifications(dom_specs)

            return {
                "url": candidate.url,
                "description": description,
                "price": price,
                "rating": parsed.get("rating"),
                "reviews": parsed.get("reviews"),
                "sold_count": parsed.get("sold_count"),
                "parsed": parsed,
            }
        except CrawlBlockedError:
            raise
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", candidate.url, exc)
            return None
        finally:
            await page.close()

    async def _fetch_page_content(
        self, page: Page, *, pc_desc_url: str = ""
    ) -> dict[str, str | list[dict[str, str]]]:
        extract_script = """
        () => {
          const result = { description: '', specifications: [] };

          const specRoot =
            document.querySelector('#nav-specification') ||
            document.querySelector('[data-pl="product-specs"]');
          if (specRoot) {
            specRoot.scrollIntoView({ block: 'center' });
            const viewMore = Array.from(
              specRoot.querySelectorAll('button, [role="button"], span, a')
            ).find((el) => {
              const text = (el.textContent || '').trim().toLowerCase();
              return text === 'view more' || text === 'show more' || text === 'more';
            });
            if (viewMore) {
              viewMore.click();
            }

            specRoot.querySelectorAll('[class*="specification--prop"]').forEach((prop) => {
              const nameEl = prop.querySelector('[class*="specification--title"] span, [class*="specification--title"]');
              const descEl = prop.querySelector('[class*="specification--desc"]');
              const name = (nameEl?.textContent || '').trim();
              const value = (
                descEl?.getAttribute('title') ||
                descEl?.querySelector('span')?.textContent ||
                descEl?.textContent ||
                ''
              ).trim();
              if (name && value) {
                result.specifications.push({ name, value });
              }
            });
          }

          const descriptionSection = document.querySelector('#nav-description');
          if (descriptionSection) {
            descriptionSection.scrollIntoView({ block: 'center' });
          }

          const descriptionHosts = [
            document.querySelector('#nav-description #product-description'),
            document.querySelector('#nav-description [class*="product-description"]'),
            document.querySelector('#product-description'),
          ].filter(Boolean);

          const findDescriptionHtml = (root) => {
            if (!root) return '';
            if (root.shadowRoot) {
              const inner = root.shadowRoot.querySelector('.product-description, #product-description');
              if (inner?.innerHTML?.trim()) return inner.innerHTML;
            }
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let node;
            while ((node = walker.nextNode())) {
              if (!node.shadowRoot) continue;
              const inner = node.shadowRoot.querySelector('.product-description, #product-description');
              if (inner?.innerHTML?.trim()) return inner.innerHTML;
            }
            const direct = root.querySelector('.product-description, [class*="product-description"]');
            if (direct?.innerHTML?.trim()) return direct.innerHTML;
            if (root.innerHTML?.trim() && root.innerHTML.length > 40) return root.innerHTML;
            return '';
          };

          for (const host of descriptionHosts) {
            const html = findDescriptionHtml(host);
            if (html) {
              result.description = html;
              break;
            }
          }

          return result;
        }
        """

        for attempt in range(4):
            try:
                await page.evaluate("window.scrollBy(0, 900)")
                await self._sleep(short=True)
                await page.wait_for_selector(
                    "#nav-specification, #nav-description, #product-description",
                    timeout=10000,
                )
                raw = await page.evaluate(extract_script)
                description = clean_product_description(str(raw.get("description") or ""))
                specifications = raw.get("specifications") or []
                if not description and pc_desc_url:
                    description = await self._fetch_description_url(page, pc_desc_url)
                if description or specifications:
                    return {
                        "description": description,
                        "specifications": specifications,
                    }
            except Exception as exc:
                logger.debug("Page content extract attempt %s failed: %s", attempt + 1, exc)

        if pc_desc_url:
            description = await self._fetch_description_url(page, pc_desc_url)
            if description:
                return {"description": description, "specifications": []}

        return {"description": "", "specifications": []}

    async def _fetch_description_url(self, page: Page, url: str) -> str:
        if not url:
            return ""
        try:
            response = await page.request.get(url)
            if response.ok:
                return clean_product_description(await response.text())
        except Exception as exc:
            logger.debug("Failed to fetch description url %s: %s", url, exc)
        return ""

    async def _fetch_description(self, page: Page) -> str:
        content = await self._fetch_page_content(page)
        return str(content.get("description") or "")

    async def _handle_captcha(self, page: Page, *, return_url: str | None = None) -> bool:
        title = await page.title()
        html = await page.content()
        if not is_captcha_page(title, html):
            return False

        logger.warning("Captcha detected on page: %s", page.url)
        if self.settings.exit_on_block:
            raise CrawlBlockedError(f"Blocked by AliExpress captcha: {page.url}")
        if self.settings.captcha_wait_seconds <= 0:
            return True

        logger.warning(
            "Waiting up to %s seconds for manual captcha solve in %s browser...",
            self.settings.captcha_wait_seconds,
            "headed" if not self.settings.headless else "headless",
        )

        poll_ms = 2000
        elapsed_ms = 0
        timeout_ms = self.settings.captcha_wait_seconds * 1000
        while elapsed_ms < timeout_ms:
            await page.wait_for_timeout(poll_ms)
            elapsed_ms += poll_ms
            title = await page.title()
            html = await page.content()
            if not is_captcha_page(title, html):
                logger.info("Captcha cleared after %ss", elapsed_ms // 1000)
                break

        reload_url = return_url or page.url
        try:
            await page.goto(reload_url, wait_until="domcontentloaded", timeout=90000)
        except Exception:
            await page.reload(wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2000)

        title = await page.title()
        html = await page.content()
        if is_captcha_page(title, html):
            logger.warning("Captcha still present after wait on %s", page.url)
            if self.settings.exit_on_block:
                raise CrawlBlockedError(f"Blocked by AliExpress captcha: {page.url}")
            return True

        logger.info("Page accessible after captcha solve: %s", page.url)
        return False

    async def _sleep(self, short: bool = False) -> None:
        low, high = self.settings.request_delay_ms
        if short:
            low, high = max(300, low // 2), max(600, high // 2)
        await asyncio.sleep(random.randint(low, high) / 1000)


def run_crawler(settings: CrawlSettings) -> dict[str, int]:
    crawler = AliExpressCrawler(settings)
    return asyncio.run(crawler.run())
