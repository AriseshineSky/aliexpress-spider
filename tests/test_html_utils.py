from __future__ import annotations

import unittest

from aliexpress_spider.html_utils import clean_product_description, normalize_specifications


class HtmlUtilsTestCase(unittest.TestCase):
    def test_clean_product_description_removes_scripts_and_links(self):
        raw = """
        <p>Hello</p>
        <script>window.adminAccountId=1;</script>
        <style>.x{color:red}</style>
        <link rel="stylesheet" href="/x.css">
        <a href="https://example.com">Report</a>
        <p><br><br></p>
        <p><img src="https://ae01.alicdn.com/kf/sample.jpg"></p>
        """
        cleaned = clean_product_description(raw)
        self.assertIn("Hello", cleaned)
        self.assertIn("sample.jpg", cleaned)
        self.assertNotIn("<script", cleaned.lower())
        self.assertNotIn("<style", cleaned.lower())
        self.assertNotIn("<link", cleaned.lower())
        self.assertNotIn("<a ", cleaned.lower())
        self.assertNotIn("window.adminAccountId", cleaned)

    def test_normalize_specifications_dedupes(self):
        specs = [
            {"name": "Brand Name", "value": "ibcccndc"},
            {"name": "Brand Name", "value": "ibcccndc"},
            {"name": "Type", "value": "Lip Gloss"},
        ]
        normalized = normalize_specifications(specs)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["name"], "Brand Name")


if __name__ == "__main__":
    unittest.main()
