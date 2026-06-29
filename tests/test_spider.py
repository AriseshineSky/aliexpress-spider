from __future__ import annotations

import unittest

from aliexpress_spider.filters import ListingCandidate, passes_listing_filters, passes_product_filters
from aliexpress_spider.config import CrawlFilters
from aliexpress_spider.elasticsearch_store import product_doc_id
from aliexpress_spider.formatter import to_standard_product
from aliexpress_spider.network import adapt_payload_to_legacy, extract_search_candidates
from aliexpress_spider.parser import AliExpressPageParser


SAMPLE_RUN_PARAMS = {
    "productInfoComponent": {
        "productId": "3256804196142652",
        "subject": "Sample Automotive LED Light",
        "categoryId": "34",
    },
    "titleModule": {
        "subject": "Sample Automotive LED Light",
        "feedbackRating": {"averageStar": 4.6, "totalValidNum": 1500},
        "formatTradeCount": "2,500 sold",
    },
    "feedbackComponent": {"evarageStar": 4.6, "totalValidNum": 1500},
    "tradeComponent": {"formatTradeCount": "2500"},
    "imageComponent": {"imagePathList": ["https://ae01.alicdn.com/kf/sample.jpg"]},
    "priceModule": {
        "origPrice": {"maxAmount": {"currency": "USD", "value": 29.99}},
        "discountPrice": {"maxActivityAmount": {"currency": "USD", "value": 19.99}},
    },
    "specsModule": {
        "props": [{"attrName": "Brand Name", "attrValue": "AutoLite"}]
    },
    "skuModule": {
        "productSKUPropertyList": [],
        "skuPriceList": [
            {
                "skuAttr": "",
                "skuVal": {"availQuantity": 500, "skuAmount": {"value": 19.99}},
            }
        ],
    },
    "shippingModule": {
        "generalFreightInfo": {
            "originalLayoutResultList": [
                {
                    "bizData": {
                        "company": "AliExpress Standard Shipping",
                        "currency": "USD",
                        "displayAmount": 0,
                        "deliveryDayMin": 7,
                        "deliveryDayMax": 15,
                        "tracking": True,
                    }
                }
            ]
        }
    },
    "breadcrumbComponent": {
        "pathList": [
            {"name": "Home", "url": "/", "cateId": "0"},
            {
                "name": "Automotive",
                "url": "https://www.aliexpress.us/category/34/automobiles-motorcycles.html",
                "cateId": "34",
            },
            {
                "name": "Exterior Accessories",
                "url": "https://www.aliexpress.us/category/200001/item.html",
                "cateId": "200001",
            },
        ]
    },
}


SAMPLE_MODULAR_PDP = {
    "ret": ["SUCCESS::调用成功"],
    "data": {
        "result": {
            "GLOBAL_DATA": {
                "globalData": {
                    "subject": "240W 5 Ports GaN Fast USB Charger",
                    "productId": "3256810301084549",
                    "categoryPath": "44/629/100000433",
                    "category3": "629",
                    "image": "https://ae-pic-a1.aliexpress-media.com/kf/sample-main.jpg",
                }
            },
            "PRICE": {
                "selectedSkuId": 12000052568856213,
                "skuIdStrPriceInfoMap": {
                    "12000052568856213": {
                        "originalPrice": {"currency": "USD", "value": 7.99},
                        "salePriceString": "$3.84",
                    }
                },
            },
            "PC_RATING": {
                "rating": "4.9",
                "totalValidNum": 26724,
                "otherText": "This seller: 13 sales | Total sales: 100K+",
            },
            "HEADER_IMAGE_PC": {
                "imagePathList": [
                    "https://ae-pic-a1.aliexpress-media.com/kf/sample-1.jpg",
                    "https://ae-pic-a1.aliexpress-media.com/kf/sample-2.jpg",
                ]
            },
            "PRODUCT_PROP_PC": {
                "showedProps": [{"attrName": "Plug Type", "attrValue": "EU/US Plug Charger"}]
            },
            "SHIPPING": {
                "deliveryLayoutInfo": [
                    {
                        "bizData": {
                            "company": "AliExpress Standard Shipping",
                            "currency": "USD",
                            "displayAmount": 0,
                            "deliveryDayMin": 7,
                            "deliveryDayMax": 14,
                            "tracking": True,
                        }
                    }
                ]
            },
            "SHOP_CARD_PC": {
                "storeName": "Stone's Store",
                "sellerInfo": {
                    "storeNum": 1103576287,
                    "storeURL": "//www.aliexpress.com/store/1103576287",
                },
            },
        }
    },
}


class NetworkTestCase(unittest.TestCase):
    def test_product_doc_id(self):
        self.assertEqual(
            product_doc_id({"source": "Aliexpress", "product_id": "3256810301084549"}),
            "Aliexpress_3256810301084549",
        )

    def test_adapt_modular_pdp_payload(self):
        legacy = adapt_payload_to_legacy(SAMPLE_MODULAR_PDP)
        parser = AliExpressPageParser()
        parsed = parser.parse(legacy)
        self.assertEqual(parsed["product_id"], "3256810301084549")
        self.assertEqual(parsed["title"], "240W 5 Ports GaN Fast USB Charger")
        self.assertAlmostEqual(parsed["rating"], 4.9)
        self.assertEqual(parsed["reviews"], 26724)
        self.assertEqual(parsed["sold_count"], 100000)
        self.assertAlmostEqual(parser.get_product_price(parsed), 3.84)
        self.assertGreaterEqual(len(parsed["gallery_images"]), 2)
        self.assertEqual(parsed["specifications"][0]["name"], "Plug Type")

    def test_adapt_modular_not_found(self):
        payload = {
            "ret": ["SUCCESS::调用成功"],
            "data": {
                "result": {
                    "GLOBAL_DATA": {
                        "globalData": {"errorCode": "SITEM_NOT_EXIST", "i18n": {}},
                    }
                }
            },
        }
        legacy = adapt_payload_to_legacy(payload)
        self.assertFalse(AliExpressPageParser().is_product_exist(legacy))

    def test_extract_search_candidates_with_list_result(self):
        payload = {"data": {"result": []}}
        self.assertEqual(extract_search_candidates(payload), [])


class ParserTestCase(unittest.TestCase):
    def setUp(self):
        self.parser = AliExpressPageParser()

    def test_parse_sample_product(self):
        parsed = self.parser.parse(SAMPLE_RUN_PARAMS)
        self.assertEqual(parsed["product_id"], "3256804196142652")
        self.assertEqual(parsed["title"], "Sample Automotive LED Light")
        self.assertEqual(parsed["rating"], 4.6)
        self.assertEqual(parsed["reviews"], 1500)
        self.assertEqual(parsed["sold_count"], 2500)
        self.assertAlmostEqual(self.parser.get_product_price(parsed), 19.99)

    def test_extract_product_id_from_url(self):
        url = "https://www.aliexpress.us/item/3256804196142652.html"
        self.assertEqual(self.parser.extract_product_id_from_url(url), "3256804196142652")


class FilterTestCase(unittest.TestCase):
    def setUp(self):
        self.filters = CrawlFilters()

    def test_passes_product_filters(self):
        product = {
            "price": 49.99,
            "rating": 4.5,
            "reviews": 1200,
            "sold_count": 1500,
        }
        self.assertTrue(passes_product_filters(product, self.filters))

    def test_rejects_high_price(self):
        product = {
            "price": 120.0,
            "rating": 4.8,
            "reviews": 2000,
            "sold_count": 2000,
        }
        self.assertFalse(passes_product_filters(product, self.filters))

    def test_listing_candidate_partial_metrics(self):
        candidate = ListingCandidate(
            product_id="1",
            url="https://example.com/item/1.html",
            category="Automotive",
            price=80,
            rating=None,
            reviews=None,
            sold_count=None,
        )
        self.assertTrue(passes_listing_filters(candidate, self.filters))


class FormatterTestCase(unittest.TestCase):
    def test_to_standard_product(self):
        parser = AliExpressPageParser()
        parsed = parser.parse(SAMPLE_RUN_PARAMS)
        standard = to_standard_product(
            parsed,
            url="https://www.aliexpress.us/item/3256804196142652.html",
            description="<p>LED light for cars</p>",
            category_name="Automotive",
        )
        self.assertIsNotNone(standard)
        assert standard is not None
        self.assertEqual(standard["source"], "Aliexpress")
        self.assertEqual(standard["sku"], "ALI_3256804196142652")
        self.assertEqual(standard["reviews"], 1500)
        self.assertEqual(standard["sold_count"], 2500)
        self.assertLess(standard["price"], 100)


if __name__ == "__main__":
    unittest.main()
