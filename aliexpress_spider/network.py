from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


def _parse_json_body(text: str) -> dict[str, Any] | None:
    body = text.strip()
    if not body:
        return None
    if body.startswith("mtopjsonp") or body.startswith(" mtopjsonp"):
        start = body.index("(") + 1
        end = body.rfind(")")
        body = body[start:end]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _digits(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits or "0")


def _float_value(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalize_image(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    return "https://" + url.lstrip("/")


@dataclass
class ResponseCollector:
    max_search_payloads: int = 30
    max_pdp_payloads: int = 10
    pdp_payloads: list[dict[str, Any]] = field(default_factory=list)
    search_payloads: list[dict[str, Any]] = field(default_factory=list)

    def clear_search(self) -> None:
        self.search_payloads.clear()

    def clear_pdp(self) -> None:
        self.pdp_payloads.clear()

    async def handle_response(self, response) -> None:
        url = response.url
        if "mtop" not in url and "aer-webapi" not in url:
            return
        try:
            text = await response.text()
        except Exception:
            return
        payload = _parse_json_body(text)
        if not payload:
            return
        if "mtop.aliexpress.pdp.pc.query" in url or "pdp.pc.query" in url:
            self.pdp_payloads.append(payload)
            if len(self.pdp_payloads) > self.max_pdp_payloads:
                del self.pdp_payloads[: -self.max_pdp_payloads]
        if any(
            marker in url
            for marker in (
                "aer-webapi/v1/search",
                "aliexpressrecommend.recommend",
                "search-pc",
            )
        ):
            self.search_payloads.append(payload)
            if len(self.search_payloads) > self.max_search_payloads:
                del self.search_payloads[: -self.max_search_payloads]

    def attach(self, page) -> None:
        page.on("response", lambda response: self._schedule(page, response))

    def _schedule(self, page, response) -> None:
        page.context._loop.create_task(self.handle_response(response))


def extract_search_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    data = payload.get("data")
    if not isinstance(data, dict):
        return candidates

    products_v2 = data.get("productsFeed", {}).get("productsV2") or data.get("productsV2")
    if isinstance(products_v2, list):
        for item in products_v2:
            candidate = _candidate_from_products_v2(item)
            if candidate:
                candidates.append(candidate)

    result = data.get("result")
    mods = data.get("mods")
    if mods is None and isinstance(result, dict):
        mods = result.get("mods")
    if isinstance(mods, dict):
        for item in mods.get("itemList", {}).get("content", []):
            candidate = _candidate_from_recommend_item(item)
            if candidate:
                candidates.append(candidate)

    for item in data.get("itemList", []):
        candidate = _candidate_from_recommend_item(item)
        if candidate:
            candidates.append(candidate)

    return candidates


def _candidate_from_products_v2(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        pdp = (
            item.get("snippetContainer", {})
            .get("itemData", {})
            .get("pdpInfo", {})
        )
        raw = pdp.get("preloadedData")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raw = {}
        product_id = str(
            item.get("productId")
            or pdp.get("productId")
            or raw.get("productId")
            or _digits(pdp.get("url"))
        )
        if not product_id or product_id == "0":
            match = re.search(r"/item/(\d+)\.html", str(pdp.get("url", "")))
            product_id = match.group(1) if match else ""
        if not product_id:
            return None
        price_info = raw.get("price") or {}
        return {
            "product_id": product_id,
            "url": str(pdp.get("url") or f"https://www.aliexpress.us/item/{product_id}.html"),
            "title": raw.get("title"),
            "price": _float_value(price_info.get("value") if isinstance(price_info, dict) else price_info),
            "rating": _float_value(raw.get("rating")),
            "reviews": _digits(raw.get("reviewCount") or raw.get("reviews")),
            "sold_count": _digits(raw.get("salesCount") or raw.get("tradeCount") or raw.get("orders")),
        }
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _candidate_from_recommend_item(item: dict[str, Any]) -> dict[str, Any] | None:
    product_id = str(item.get("productId") or item.get("itemId") or item.get("id") or "")
    if not product_id:
        return None
    url = item.get("productUrl") or item.get("itemUrl") or item.get("detailUrl")
    if url and not str(url).startswith("http"):
        url = "https:" + str(url)
    if not url:
        url = f"https://www.aliexpress.us/item/{product_id}.html"
    return {
        "product_id": product_id,
        "url": url,
        "title": item.get("title") or item.get("subject"),
        "price": _float_value(item.get("salePrice") or item.get("price")),
        "rating": _float_value(item.get("evaluationRate") or item.get("starRating") or item.get("rating")),
        "reviews": _digits(item.get("reviewCount") or item.get("feedbackCount")),
        "sold_count": _digits(item.get("tradeCount") or item.get("orders") or item.get("sold")),
    }


def _parse_count_text(text: str) -> int:
    if not text:
        return 0
    upper = str(text).upper()
    match = re.search(r"(\d+(?:\.\d+)?)\s*M\+?", upper)
    if match:
        return int(float(match.group(1)) * 1_000_000)
    match = re.search(r"(\d+(?:\.\d+)?)\s*K\+?", upper)
    if match:
        return int(float(match.group(1)) * 1_000)
    return _digits(text)


def _sold_count_from_rating_block(rating_block: dict[str, Any]) -> str | int:
    for text in (rating_block.get("otherText"), rating_block.get("popText")):
        if not text:
            continue
        total_match = re.search(r"total sales:\s*([^|]+)", str(text), re.IGNORECASE)
        if total_match:
            return _parse_count_text(total_match.group(1))
        sold_match = re.search(r"(\d[\d,+\w.]*)\s+(?:sold|sales|orders)", str(text), re.IGNORECASE)
        if sold_match:
            return _parse_count_text(sold_match.group(1))
    return 0


def _price_amount_from_sku_info(info: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    original = info.get("originalPrice") or {}
    currency = original.get("currency") or "USD"
    original_value = _float_value(original.get("value"))
    sale_value = _float_value(str(info.get("salePriceString", "")).replace("$", ""))
    if sale_value <= 0:
        sale_value = original_value
    return (
        {"currency": currency, "value": original_value},
        {"currency": currency, "value": sale_value},
    )


def _is_modular_pdp_result(result: dict[str, Any]) -> bool:
    return any(key in result for key in ("GLOBAL_DATA", "PRICE", "PC_RATING", "HEADER_IMAGE_PC"))


def _adapt_modular_sku_properties(sku_block: dict[str, Any]) -> list[dict[str, Any]]:
    properties: list[dict[str, Any]] = []
    for sku_property in sku_block.get("skuProperties") or []:
        if not isinstance(sku_property, dict):
            continue
        values: list[dict[str, Any]] = []
        for property_value in sku_property.get("skuPropertyValues") or []:
            if not isinstance(property_value, dict):
                continue
            value_id = property_value.get("propertyValueId")
            if value_id in (None, "", "0", 0):
                value_id = property_value.get("propertyValueIdLong")
            values.append(
                {
                    "propertyValueId": value_id,
                    "propertyValueIdLong": property_value.get("propertyValueIdLong"),
                    "propertyValueName": property_value.get("propertyValueName", ""),
                    "propertyValueDisplayName": property_value.get("propertyValueDisplayName")
                    or property_value.get("propertyValueDefinitionName", ""),
                    "skuPropertyImagePath": property_value.get("skuPropertyImagePath", ""),
                }
            )
        properties.append(
            {
                "skuPropertyId": sku_property.get("skuPropertyId"),
                "skuPropertyName": sku_property.get("skuPropertyName", ""),
                "skuPropertyValues": values,
            }
        )
    return properties


def _adapt_modular_sku_price_list(
    sku_block: dict[str, Any], sku_map: dict[str, Any]
) -> list[dict[str, Any]]:
    sku_price_list: list[dict[str, Any]] = []
    sku_paths = sku_block.get("skuPaths") or []
    if sku_paths:
        for path in sku_paths:
            if not isinstance(path, dict):
                continue
            sku_id = str(path.get("skuIdStr") or path.get("skuId") or "")
            price_info = sku_map.get(sku_id) or {}
            _, sale_amount = _price_amount_from_sku_info(price_info)
            stock = path.get("skuStock")
            if stock is None:
                stock = 100 if path.get("salable", True) else 0
            sku_price_list.append(
                {
                    "skuAttr": path.get("skuAttr") or path.get("path") or sku_id,
                    "skuVal": {
                        "availQuantity": _digits(stock),
                        "skuAmount": sale_amount,
                    },
                }
            )
        return sku_price_list

    for sku_id, info in sku_map.items():
        _, sale_amount = _price_amount_from_sku_info(info)
        sku_price_list.append(
            {
                "skuAttr": str(sku_id),
                "skuVal": {
                    "availQuantity": 100,
                    "skuAmount": sale_amount,
                },
            }
        )
    return sku_price_list


def _adapt_modular_pdp_result(result: dict[str, Any]) -> dict[str, Any]:
    global_wrapper = result.get("GLOBAL_DATA") or {}
    global_data = global_wrapper.get("globalData") if isinstance(global_wrapper, dict) else {}
    if not isinstance(global_data, dict):
        global_data = {}

    error_code = global_data.get("errorCode")
    if error_code and error_code != "SUCCESS":
        return {"i18nMap": {"PAGE_NOT_FOUND_NOTICE": str(error_code)}}

    title = global_data.get("subject") or ""
    product_id = str(global_data.get("productId") or "")
    category_id = str(
        global_data.get("category3")
        or global_data.get("category2")
        or global_data.get("category1")
        or (global_data.get("categoryPath") or "").split("/")[-1]
        or ""
    )

    rating_block = result.get("PC_RATING") or {}
    if not isinstance(rating_block, dict):
        rating_block = {}
    rating = _float_value(rating_block.get("rating"))
    reviews = _digits(rating_block.get("totalValidNum"))
    sold = _sold_count_from_rating_block(rating_block)

    image_block = result.get("HEADER_IMAGE_PC") or {}
    if not isinstance(image_block, dict):
        image_block = {}
    images = image_block.get("imagePathList") or image_block.get("currentSkuImages") or []
    if global_data.get("image") and global_data["image"] not in images:
        images = [global_data["image"], *images]

    price_block = result.get("PRICE") or {}
    if not isinstance(price_block, dict):
        price_block = {}
    sku_map = price_block.get("skuIdStrPriceInfoMap") or {}
    selected_sku = str(price_block.get("selectedSkuId") or "")
    selected_info = sku_map.get(selected_sku) if selected_sku else None
    if not selected_info and sku_map:
        selected_info = next(iter(sku_map.values()))
    selected_info = selected_info or {}

    max_amount, max_activity_amount = _price_amount_from_sku_info(selected_info)
    sku_block = result.get("SKU") or {}
    if not isinstance(sku_block, dict):
        sku_block = {}
    product_sku_property_list = _adapt_modular_sku_properties(sku_block)
    sku_price_list = _adapt_modular_sku_price_list(sku_block, sku_map)

    prop_block = result.get("PRODUCT_PROP_PC") or {}
    if not isinstance(prop_block, dict):
        prop_block = {}
    props = prop_block.get("showedProps") or prop_block.get("outerProps") or []

    shipping_block = result.get("SHIPPING") or {}
    if not isinstance(shipping_block, dict):
        shipping_block = {}
    delivery_layout = shipping_block.get("deliveryLayoutInfo") or []

    shop_block = result.get("SHOP_CARD_PC") or {}
    if not isinstance(shop_block, dict):
        shop_block = {}
    seller_info = shop_block.get("sellerInfo") or {}

    legacy: dict[str, Any] = {
        "productInfoComponent": {
            "subject": title,
            "productId": product_id,
            "categoryId": category_id,
        },
        "titleModule": {
            "subject": title,
            "feedbackRating": {"averageStar": rating, "totalValidNum": reviews},
            "formatTradeCount": sold,
        },
        "feedbackComponent": {"evarageStar": rating, "totalValidNum": reviews},
        "tradeComponent": {"formatTradeCount": sold},
        "priceModule": {
            "origPrice": {"maxAmount": max_amount},
            "discountPrice": {"maxActivityAmount": max_activity_amount},
        },
        "imageComponent": {"imagePathList": [_normalize_image(url) for url in images if url]},
        "specsModule": {"props": props},
        "skuModule": {
            "productSKUPropertyList": product_sku_property_list,
            "skuPriceList": sku_price_list,
        },
        "shippingModule": {
            "generalFreightInfo": {"originalLayoutResultList": delivery_layout},
        },
        "breadcrumbComponent": {"pathList": []},
        "storeModule": {
            "storeName": shop_block.get("storeName"),
            "storeNum": seller_info.get("storeNum") or seller_info.get("adminSeq"),
            "storeURL": seller_info.get("storeURL"),
            "positiveRate": shop_block.get("sellerPositiveRate"),
        },
        "descriptionComponent": {
            "pcDescUrl": (result.get("DESC") or {}).get("pcDescUrl") or "",
        },
    }
    return legacy


def adapt_payload_to_legacy(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}
    if any(key in data for key in ("titleModule", "productInfoComponent", "priceModule", "feedbackComponent")):
        return data

    ret = data.get("ret") or []
    result = data.get("data", {}).get("result")
    if ret and not any("SUCCESS" in str(item) for item in ret):
        if not isinstance(result, dict) or not result:
            return {"i18nMap": {"PAGE_NOT_FOUND_NOTICE": str(ret[0])}}

    if not isinstance(result, dict):
        return data

    if _is_modular_pdp_result(result):
        return _adapt_modular_pdp_result(result)

    legacy: dict[str, Any] = {
        "productInfoComponent": {},
        "titleModule": {},
        "feedbackComponent": {},
        "tradeComponent": {},
        "priceModule": {"origPrice": {}, "discountPrice": {}},
        "imageComponent": {"imagePathList": []},
        "specsModule": {"props": []},
        "skuModule": {"productSKUPropertyList": [], "skuPriceList": []},
        "shippingModule": {"generalFreightInfo": {"originalLayoutResultList": []}},
        "breadcrumbComponent": {"pathList": []},
        "storeModule": {},
    }

    for module in result.values():
        if not isinstance(module, dict):
            continue
        if "globalData" in module and isinstance(module["globalData"], dict):
            _merge_module(legacy, module["globalData"])
        _merge_module(legacy, module)

    title = (
        legacy["productInfoComponent"].get("subject")
        or legacy["titleModule"].get("subject")
        or _find_first(result, ("subject", "title", "productTitle"))
    )
    product_id = str(
        legacy["productInfoComponent"].get("productId")
        or _find_first(result, ("productId", "itemId"))
        or ""
    )
    legacy["productInfoComponent"]["subject"] = title
    legacy["productInfoComponent"]["productId"] = product_id
    legacy["titleModule"]["subject"] = title
    return legacy


def _merge_module(legacy: dict[str, Any], module: dict[str, Any]) -> None:
    if "subject" in module or "title" in module:
        subject = module.get("subject") or module.get("title")
        legacy["productInfoComponent"]["subject"] = subject
        legacy["titleModule"]["subject"] = subject
    if "productId" in module or "itemId" in module:
        pid = module.get("productId") or module.get("itemId")
        legacy["productInfoComponent"]["productId"] = str(pid)

    if "imagePathList" in module or "currentSkuImages" in module:
        images = module.get("imagePathList") or module.get("currentSkuImages") or []
        legacy["imageComponent"]["imagePathList"] = [_normalize_image(url) for url in images if url]

    for rating_key in ("averageStar", "evarageStar", "tradeScore", "rating"):
        if rating_key in module:
            legacy["feedbackComponent"]["evarageStar"] = _float_value(module[rating_key])
            legacy["titleModule"].setdefault("feedbackRating", {})["averageStar"] = _float_value(
                module[rating_key]
            )
    for review_key in ("totalValidNum", "reviewCount", "tradeCount", "feedbackCount"):
        if review_key in module and review_key != "tradeCount":
            legacy["feedbackComponent"]["totalValidNum"] = _digits(module[review_key])
            legacy["titleModule"].setdefault("feedbackRating", {})["totalValidNum"] = _digits(
                module[review_key]
            )
    if "formatTradeCount" in module or "salesCount" in module or "tradeCount" in module:
        sold = module.get("formatTradeCount") or module.get("salesCount") or module.get("tradeCount")
        legacy["tradeComponent"]["formatTradeCount"] = sold
        legacy["titleModule"]["formatTradeCount"] = sold
    elif "otherText" in module or "popText" in module:
        sold = _sold_count_from_rating_block(module)
        if sold:
            legacy["tradeComponent"]["formatTradeCount"] = sold
            legacy["titleModule"]["formatTradeCount"] = sold

    if "minAmount" in module or "maxAmount" in module or "minActivityAmount" in module:
        legacy["priceModule"]["origPrice"] = {
            "minAmount": module.get("minAmount") or {},
            "maxAmount": module.get("maxAmount") or {},
        }
        legacy["priceModule"]["discountPrice"] = {
            "minActivityAmount": module.get("minActivityAmount") or module.get("minAmount") or {},
            "maxActivityAmount": module.get("maxActivityAmount") or module.get("maxAmount") or {},
        }
    if "skuPriceList" in module:
        legacy["skuModule"]["skuPriceList"] = module.get("skuPriceList") or []
    if "productSKUPropertyList" in module:
        legacy["skuModule"]["productSKUPropertyList"] = module.get("productSKUPropertyList") or []
    if "props" in module or "showedProps" in module or "outerProps" in module:
        legacy["specsModule"]["props"] = (
            module.get("props") or module.get("showedProps") or module.get("outerProps") or []
        )
    if "skuIdStrPriceInfoMap" in module:
        sku_map = module.get("skuIdStrPriceInfoMap") or {}
        selected_sku = str(module.get("selectedSkuId") or "")
        selected_info = sku_map.get(selected_sku) if selected_sku else None
        if not selected_info and sku_map:
            selected_info = next(iter(sku_map.values()))
        if selected_info:
            max_amount, max_activity_amount = _price_amount_from_sku_info(selected_info)
            legacy["priceModule"]["origPrice"] = {"maxAmount": max_amount}
            legacy["priceModule"]["discountPrice"] = {"maxActivityAmount": max_activity_amount}
        sku_price_list: list[dict[str, Any]] = []
        for sku_id, info in sku_map.items():
            _, sale_amount = _price_amount_from_sku_info(info)
            sku_price_list.append(
                {
                    "skuAttr": str(sku_id),
                    "skuVal": {"availQuantity": 100, "skuAmount": sale_amount},
                }
            )
        legacy["skuModule"]["skuPriceList"] = sku_price_list
    if "deliveryLayoutInfo" in module:
        legacy["shippingModule"]["generalFreightInfo"]["originalLayoutResultList"] = module.get(
            "deliveryLayoutInfo"
        ) or []
    if "pathList" in module:
        legacy["breadcrumbComponent"]["pathList"] = module.get("pathList") or []
    if "originalLayoutResultList" in module:
        legacy["shippingModule"]["generalFreightInfo"]["originalLayoutResultList"] = module.get(
            "originalLayoutResultList"
        )
    if "storeName" in module or "storeNum" in module:
        legacy["storeModule"].update(
            {
                "storeName": module.get("storeName"),
                "storeNum": module.get("storeNum"),
                "storeURL": module.get("storeURL"),
            }
        )


def _find_first(obj: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        for value in obj.values():
            found = _find_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first(item, keys)
            if found not in (None, ""):
                return found
    return None


def is_captcha_page(title: str, html: str) -> bool:
    lowered = f"{title}\n{html}".lower()
    return any(
        marker in lowered
        for marker in (
            "captcha interception",
            "please slide to verify",
            "unusual traffic",
            "punish",
            "x5secdata",
        )
    )
