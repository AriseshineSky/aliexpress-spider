from __future__ import annotations

from datetime import datetime
from typing import Any

from em_product.product import StandardProduct
from pydantic import ValidationError

from aliexpress_spider.parser import AliExpressPageParser


def _build_option_values(
    sku_attr: str, options_mapping: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    option_values: list[dict[str, str]] = []
    if not sku_attr:
        return option_values

    for part in sku_attr.split(";"):
        attr = part.split("#")[0]
        attr_parts = attr.split(":")
        if len(attr_parts) < 2:
            continue
        option_id, option_val = attr_parts[0], attr_parts[1]
        option = options_mapping.get(option_id)
        if not option:
            continue
        sku = option["skus"].get(option_val)
        if not sku:
            continue
        option_values.append(
            {
                "option_id": option_id,
                "option_value_id": option_val,
                "option_name": option["option_name"],
                "option_value": sku.get("presentation") or sku.get("name") or option_val,
            }
        )
    return option_values


def _build_variants(parsed: dict[str, Any], product_id: str) -> tuple[list[dict[str, Any]], bool]:
    sku_products = parsed.get("sku_products") or []
    options = parsed.get("options") or []
    if len(sku_products) <= 1:
        return [], True

    options_mapping: dict[str, dict[str, Any]] = {}
    for option in options:
        options_mapping[option["id"]] = {
            "option_name": option["name"],
            "skus": {sku["id"]: sku for sku in option.get("skus", [])},
        }

    variants: list[dict[str, Any]] = []
    parser = AliExpressPageParser()
    for sku_product in sku_products:
        sku_attr = sku_product.get("skuAttr", "")
        sku_val = sku_product.get("skuVal") or {}
        try:
            quantity = int(str(sku_val.get("availQuantity", sku_val.get("inventory", 0))).replace(",", ""))
        except ValueError:
            quantity = 0
        if quantity <= 0:
            continue

        formatted_attr = ";".join(part.split("#")[0] for part in sku_attr.split(";") if part)
        sku_suffix = formatted_attr or "default"
        option_values = _build_option_values(sku_attr, options_mapping)
        variant_images = None
        for ov in option_values:
            option = options_mapping.get(ov.get("option_id") or "")
            if not option:
                continue
            sku_meta = option["skus"].get(ov.get("option_value_id") or "")
            if sku_meta and sku_meta.get("img_url"):
                variant_images = sku_meta["img_url"]
                break
        variant = {
            "sku": f"ALI_{product_id}_{sku_suffix}",
            "barcode": None,
            "variant_id": formatted_attr or product_id,
            "price": parser._get_sku_price(sku_val),
            "currency": "USD",
            "available_qty": quantity,
            "option_values": option_values,
            "images": variant_images,
        }
        if variant["option_values"]:
            variants.append(variant)

    return variants, len(variants) == 0


def to_standard_product(
    parsed: dict[str, Any],
    *,
    url: str,
    description: str,
    category_name: str,
) -> dict[str, Any] | None:
    parser = AliExpressPageParser()
    product_id = parsed["product_id"]
    if not product_id or not parsed.get("title"):
        return None

    shipping = parser.get_default_shipping(parsed.get("shippings") or []) or {}
    price = parser.get_product_price(parsed)
    images = parsed.get("gallery_images") or []
    breadcrumbs = [item["name"] for item in parsed.get("breadcrumbs") or []]
    categories = ">".join(breadcrumbs) if breadcrumbs else category_name

    brand = None
    specifications = parsed.get("specifications") or []
    for spec in specifications:
        if spec["name"].lower().find("brand") != -1:
            brand = spec["value"]
            break

    variants, has_only_default_variant = _build_variants(parsed, product_id)
    if has_only_default_variant:
        try:
            available_qty = int(
                str(
                    (parsed.get("sku_products") or [{}])[0]
                    .get("skuVal", {})
                    .get("availQuantity", 100)
                ).replace(",", "")
            )
        except ValueError:
            available_qty = 100
    else:
        available_qty = sum(v.get("available_qty") or 0 for v in variants) or None

    payload = {
        "date": datetime.now().replace(microsecond=0).isoformat(),
        "url": url.replace("http://", "https://"),
        "source": "Aliexpress",
        "images": ";".join(images) if images else "https://",
        "product_id": product_id,
        "existence": True,
        "title": parsed["title"][:255],
        "description": description or None,
        "summary": parsed["title"][:255],
        "sku": f"ALI_{product_id}",
        "upc": None,
        "brand": brand,
        "specifications": specifications or None,
        "categories": categories,
        "videos": None,
        "options": [{"name": opt["name"], "id": opt["id"]} for opt in parsed.get("options") or []]
        or None,
        "variants": variants or None,
        "returnable": None,
        "reviews": parsed.get("reviews"),
        "rating": parsed.get("rating"),
        "sold_count": parsed.get("sold_count"),
        "price": price,
        "currency": "USD",
        "available_qty": available_qty,
        "shipping_fee": float(shipping.get("amount", 0) or 0),
        "shipping_days_min": shipping.get("delivery_day_min"),
        "shipping_days_max": shipping.get("delivery_day_max"),
        "weight": None,
        "width": None,
        "height": None,
        "length": None,
        "has_only_default_variant": has_only_default_variant,
        "price_retail": float((parsed.get("price_info") or {}).get("maxAmount", {}).get("value") or 0)
        or None,
    }

    try:
        dumped = StandardProduct(**payload).model_dump()
        dumped.pop("title_en", None)
        dumped.pop("description_en", None)
        return dumped
    except ValidationError:
        return None
