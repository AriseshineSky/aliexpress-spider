from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from aliexpress_spider.crawler import STEALTH_SCRIPT, USER_AGENT
from aliexpress_spider.network import is_captcha_page

logger = logging.getLogger(__name__)

VERIFY_CATEGORY_URL = (
    "https://www.aliexpress.us/category/44/consumer-electronics.html?SortType=total_tranpro_desc"
)


async def _page_has_listing(page) -> bool:
    return bool(
        await page.evaluate(
            """
            () => document.querySelectorAll('a[href*="/item/"]').length >= 3
            """
        )
    )


async def _is_accessible(page) -> bool:
    title = await page.title()
    html = await page.content()
    if is_captcha_page(title, html):
        return False
    return await _page_has_listing(page)


async def _goto_category(page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
    except PlaywrightError as exc:
        logger.warning("Navigation interrupted (%s), checking current page state", exc)


async def run_verification(
    user_data_dir: Path,
    *,
    timeout_seconds: int = 300,
) -> dict[str, bool | str]:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, bool | str] = {
        "home_ok": False,
        "category_ok": False,
        "profile_dir": str(user_data_dir),
    }

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        await context.add_init_script(STEALTH_SCRIPT)
        page = await context.new_page()

        try:
            logger.info("Opening category page (captcha usually appears here)")
            await _goto_category(page, VERIFY_CATEGORY_URL)
            await page.wait_for_timeout(3000)

            poll_ms = 2000
            elapsed_ms = 0
            timeout_ms = timeout_seconds * 1000
            while elapsed_ms < timeout_ms:
                if await _is_accessible(page):
                    result["home_ok"] = True
                    result["category_ok"] = True
                    break

                title = await page.title()
                html = await page.content()
                if is_captcha_page(title, html):
                    logger.info(
                        "Captcha detected - complete the slider/check in the browser window (%ss elapsed)",
                        elapsed_ms // 1000,
                    )
                else:
                    logger.info(
                        "Waiting for product listings to load (%ss elapsed)",
                        elapsed_ms // 1000,
                    )

                await page.wait_for_timeout(poll_ms)
                elapsed_ms += poll_ms

                if elapsed_ms % 10000 == 0:
                    await _goto_category(page, VERIFY_CATEGORY_URL)
                    await page.wait_for_timeout(2000)

            if result["category_ok"]:
                result["message"] = "Verification complete. Browser profile saved for future crawls."
            else:
                result["message"] = (
                    "Timed out waiting for captcha solve or category listing. "
                    "Complete the captcha in the browser and rerun verify."
                )
        finally:
            await context.close()

    return result


def verify_session(user_data_dir: Path, timeout_seconds: int = 300) -> dict[str, bool | str]:
    return asyncio.run(run_verification(user_data_dir, timeout_seconds=timeout_seconds))
