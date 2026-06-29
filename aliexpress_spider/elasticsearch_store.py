from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import ConnectionError, ConnectionTimeout, SSLError, TransportError

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ElasticsearchSettings:
    url: str
    index: str
    bulk_chunk_size: int = 50
    timeout: int = 60
    max_retry: int = 3


def load_elasticsearch_settings() -> ElasticsearchSettings | None:
    load_dotenv(PROJECT_ROOT / ".env")

    url = (os.getenv("ELASTICSEARCH_URL") or "").strip()
    index = (os.getenv("ELASTICSEARCH_INDEX") or "").strip()
    if not url or not index:
        return None

    return ElasticsearchSettings(
        url=url,
        index=index,
        bulk_chunk_size=int(os.getenv("ELASTICSEARCH_BULK_CHUNK_SIZE", "50")),
        timeout=int(os.getenv("ELASTICSEARCH_TIMEOUT", "60")),
        max_retry=int(os.getenv("ELASTICSEARCH_MAX_RETRY", "3")),
    )


def normalize_es_host(url: str) -> str:
    host = url.strip()
    if not host:
        return host
    if "://" not in host:
        host = f"http://{host}"

    parsed = urlparse(host)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid ELASTICSEARCH_URL: {url}")

    if parsed.port is None:
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth = f"{auth}:{parsed.password}"
            auth = f"{auth}@"

        hostname = parsed.hostname
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"

        parsed = parsed._replace(netloc=f"{auth}{hostname}:9200")

    return parsed.geturl()


def build_es_client(settings: ElasticsearchSettings) -> Elasticsearch:
    return Elasticsearch(
        hosts=[normalize_es_host(settings.url)],
        timeout=settings.timeout,
    )


def product_doc_id(product: dict[str, Any]) -> str:
    source = str(product.get("source") or "Aliexpress").strip()
    product_id = str(product.get("product_id") or "").strip()
    if not product_id:
        raise ValueError("product_id is required for Elasticsearch document id")
    return f"{source}_{product_id}"


class ElasticsearchProductWriter:
    def __init__(self, settings: ElasticsearchSettings):
        self.settings = settings
        self.client = build_es_client(settings)
        self._buffer: list[dict[str, Any]] = []
        self.saved = 0
        self.failed = 0

    def write(self, product: dict[str, Any], category_name: str) -> None:
        record = {"category": category_name, **product}
        self._buffer.append(
            {
                "_index": self.settings.index,
                "_type": "_doc",
                "_id": product_doc_id(product),
                "_op_type": "index",
                "_source": record,
            }
        )
        if len(self._buffer) >= self.settings.bulk_chunk_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return

        batch = self._buffer
        retry = self.settings.max_retry
        while retry > 0:
            try:
                success_count, errors = helpers.bulk(
                    self.client,
                    batch,
                    raise_on_error=False,
                )
                failed_count = len(errors) if isinstance(errors, list) else 0
                self.saved += int(success_count)
                self.failed += failed_count
                if failed_count:
                    logger.warning("ES bulk had %s failures; first=%s", failed_count, errors[0])
                else:
                    logger.info("Indexed %s products to %s", int(success_count), self.settings.index)
                self._buffer.clear()
                return
            except (ConnectionTimeout, ConnectionError, SSLError, TransportError) as exc:
                retry -= 1
                logger.warning("ES bulk retry (%s left): %s", retry, exc)
                time.sleep(max(1, self.settings.max_retry - retry))

        self.failed += len(batch)
        self._buffer.clear()
        raise RuntimeError(f"Failed to index {len(batch)} products to Elasticsearch")

    def close(self) -> None:
        self.flush()
