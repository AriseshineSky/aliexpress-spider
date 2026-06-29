from __future__ import annotations

import re
from typing import Any


class AliExpressPageParser:
    """Extract structured product data from AliExpress `runParams.data`."""

    def parse(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_id": self.get_pid(data),
            "title": self.get_title(data),
            "rating": self.get_rating(data),
            "reviews": self.get_feedback(data),
            "sold_count": self.get_orders(data),
            "specifications": self.get_specs(data),
            "gallery_images": self.get_gallery_images(data),
            "options": self.get_options(data),
            "sku_products": self.get_sku_products(data),
            "store": self.get_store(data),
            "price_info": self.get_price(data),
            "shippings": self.get_shippings(data),
            "breadcrumbs": self.get_breadcrumbs(data),
            "category_id": self.get_category_id(data),
            "meta_keywords": self.get_meta_keywords(data),
        }

    def is_product_exist(self, data: dict[str, Any]) -> bool:
        return not data.get("i18nMap", {}).get("PAGE_NOT_FOUND_NOTICE", "")

    def get_pid(self, data: dict[str, Any]) -> str:
        info = data.get("pageModule") or data.get("productInfoComponent") or {}
        return str(info.get("productId") or info.get("idStr") or "")

    def get_breadcrumbs(self, data: dict[str, Any]) -> list[dict[str, str]]:
        breadcrumbs: list[dict[str, str]] = []
        cats_to_ignore = {"home", "all categories"}
        path_list = (
            data.get("breadcrumbComponent", {}).get("pathList")
            or data.get("crossLinkModule", {}).get("breadCrumbPathList")
            or []
        )
        for item in path_list:
            name = item.get("name", "")
            if not name or name.lower() in cats_to_ignore:
                continue
            url = item.get("url", "")
            if "/category/" not in url:
                continue
            cid = item.get("cateId", "")
            if not cid:
                continue
            breadcrumbs.append({"name": name, "url": url, "cid": str(cid)})
        return breadcrumbs

    def get_title(self, data: dict[str, Any]) -> str:
        return (
            data.get("productInfoComponent", {}).get("subject")
            or data.get("titleModule", {}).get("subject")
            or ""
        )

    def get_rating(self, data: dict[str, Any]) -> float:
        rating = (
            data.get("feedbackComponent", {}).get("evarageStar")
            or data.get("titleModule", {}).get("feedbackRating", {}).get("averageStar")
            or 0
        )
        return float(rating)

    def get_feedback(self, data: dict[str, Any]) -> int:
        feedback = (
            data.get("feedbackComponent", {}).get("totalValidNum")
            or data.get("titleModule", {}).get("feedbackRating", {}).get("totalValidNum")
            or 0
        )
        return int(feedback)

    def get_orders(self, data: dict[str, Any]) -> int:
        orders_s = (
            data.get("tradeComponent", {}).get("formatTradeCount")
            or data.get("titleModule", {}).get("formatTradeCount")
            or "0"
        )
        digits = "".join(ch for ch in str(orders_s) if ch.isdigit())
        return int(digits or "0")

    def get_specs(self, data: dict[str, Any]) -> list[dict[str, str]]:
        specs: list[dict[str, str]] = []
        props = (
            data.get("specsModule") or data.get("productPropComponent") or {}
        ).get("props", [])
        for prop in props:
            name = prop.get("attrName", "")
            value = prop.get("attrValue", "")
            if name and value:
                specs.append({"name": name, "value": value})
        return specs

    def get_gallery_images(self, data: dict[str, Any]) -> list[str]:
        images = (data.get("imageComponent") or data.get("imageModule") or {}).get(
            "imagePathList", []
        )
        return [self._normalize_image_url(url) for url in images if url]

    def get_options(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        sku_module = data.get("skuComponent") or data.get("skuModule") or {}
        for sku_property in sku_module.get("productSKUPropertyList", []):
            option = {
                "id": str(sku_property.get("skuPropertyId", "")),
                "name": sku_property.get("skuPropertyName", ""),
                "skus": [],
            }
            for property_value in sku_property.get("skuPropertyValues", []):
                sku_id = property_value.get("propertyValueId", "0")
                if sku_id == "0":
                    sku_id = property_value.get("propertyValueIdLong", "0")
                option["skus"].append(
                    {
                        "id": str(sku_id),
                        "name": property_value.get("propertyValueName", ""),
                        "presentation": property_value.get("propertyValueDisplayName", ""),
                        "img_url": property_value.get("skuPropertyImagePath", ""),
                    }
                )
            options.append(option)
        return options

    def get_sku_products(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return (data.get("priceComponent") or data.get("skuModule") or {}).get(
            "skuPriceList", []
        )

    def get_store(self, data: dict[str, Any]) -> dict[str, Any]:
        store_feedback = data.get("storeFeedbackComponent") or {}
        store_module = data.get("storeModule") or data.get("sellerComponent") or {}
        positive_rate = store_module.get("positiveRate") or store_feedback.get(
            "sellerPositiveRate", "0%"
        )
        return {
            "id": str(store_module.get("storeNum", "")),
            "name": store_module.get("storeName", ""),
            "url": "https:" + store_module.get("storeURL", "") if store_module.get("storeURL") else "",
            "store_num": str(store_module.get("storeNum", "")),
            "positives": store_module.get("positiveNum", store_feedback.get("sellerPositiveNum", 0)),
            "positive_rate": float(str(positive_rate).strip("%") or 0),
        }

    def get_price(self, data: dict[str, Any]) -> dict[str, Any]:
        price_module = data.get("priceModule") or {}
        original_price = data.get("priceComponent") or price_module.get("origPrice") or {}
        discount_price = data.get("priceComponent") or price_module.get("discountPrice") or {}
        empty: dict[str, Any] = {}
        return {
            "maxAmount": {
                "currency": original_price.get("maxAmount", empty).get("currency", "USD"),
                "value": original_price.get("maxAmount", empty).get("value", 0),
            },
            "maxActivityAmount": {
                "currency": discount_price.get("maxActivityAmount", empty).get("currency", "USD"),
                "value": discount_price.get("maxActivityAmount", empty).get("value", 0),
            },
            "minAmount": {
                "currency": original_price.get("minAmount", empty).get("currency", "USD"),
                "value": original_price.get("minAmount", empty).get("value", 0),
            },
            "minActivityAmount": {
                "currency": discount_price.get("minActivityAmount", empty).get("currency", "USD"),
                "value": discount_price.get("minActivityAmount", empty).get("value", 0),
            },
        }

    def get_shippings(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        shipping_module = data.get("shippingModule") or {}
        layout = (
            shipping_module.get("generalFreightInfo", {}).get("originalLayoutResultList")
            or data.get("webGeneralFreightCalculateComponent", {}).get("originalLayoutResultList")
            or []
        )
        shippings: list[dict[str, Any]] = []
        for shipping in layout:
            biz = shipping.get("bizData") or {}
            shippings.append(
                {
                    "company": biz.get("company", ""),
                    "currency": biz.get("currency", "USD"),
                    "amount": float(biz.get("displayAmount", 0) or 0),
                    "delivery_day_min": int(biz.get("deliveryDayMin", 42) or 42),
                    "delivery_day_max": int(biz.get("deliveryDayMax", 42) or 42),
                    "tracking": bool(biz.get("tracking", False)),
                    "provider": biz.get("shipFrom", "China"),
                    "provider_code": biz.get("deliveryProviderCode", ""),
                }
            )
        return shippings

    def get_category_id(self, data: dict[str, Any]) -> str:
        info = data.get("productInfoComponent") or data.get("commonModule") or {}
        return str(info.get("categoryId", ""))

    def get_meta_keywords(self, data: dict[str, Any]) -> list[str]:
        page_module = data.get("pageModule") or data.get("metaDataComponent") or {}
        keywords = page_module.get("keywords", "")
        return [
            keyword.strip()
            for keyword in keywords.split(",")
            if keyword.strip() and "aliexpress" not in keyword.lower()
        ]

    def get_description_url(self, data: dict[str, Any]) -> str:
        return str((data.get("descriptionComponent") or {}).get("pcDescUrl") or "")

    def get_default_shipping(self, shippings: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not shippings:
            return None
        free_with_tracking = [
            s for s in shippings if s.get("tracking") and float(s.get("amount", 0)) <= 0
        ]
        if free_with_tracking:
            return sorted(free_with_tracking, key=lambda s: s.get("delivery_day_min", 999))[0]
        tracked = [s for s in shippings if s.get("tracking")]
        if tracked:
            return sorted(tracked, key=lambda s: float(s.get("amount", 0)))[0]
        return shippings[0]

    def get_product_price(self, parsed: dict[str, Any]) -> float:
        price_info = parsed["price_info"]
        activity = float(price_info.get("maxActivityAmount", {}).get("value") or 0)
        regular = float(price_info.get("maxAmount", {}).get("value") or 0)
        if activity > 0:
            return activity
        if regular > 0:
            return regular
        sku_products = parsed.get("sku_products") or []
        if sku_products:
            return self._get_sku_price(sku_products[0].get("skuVal") or {})
        return 0.0

    def _get_sku_price(self, sku_val: dict[str, Any]) -> float:
        sku_amount = float((sku_val.get("skuAmount") or {}).get("value", 0) or 0)
        if sku_amount:
            return sku_amount
        for key in (
            "skuCalPrice",
            "actSkuCalPrice",
            "skuMultiCurrencyCalPrice",
            "actSkuMultiCurrencyCalPrice",
            "skuMultiCurrencyDisplayPrice",
            "actSkuMultiCurrencyDisplayPrice",
        ):
            value = float(str(sku_val.get(key, 0)).replace(",", "") or 0)
            if value:
                return value
        return 0.0

    def _normalize_image_url(self, url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http"):
            return url
        return "https://" + url.lstrip("/")

    @staticmethod
    def extract_product_id_from_url(url: str) -> str | None:
        match = re.search(r"/item/(\d+)\.html", url)
        return match.group(1) if match else None
