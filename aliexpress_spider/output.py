from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aliexpress_spider.elasticsearch_store import ElasticsearchProductWriter, ElasticsearchSettings


class ProductWriter:
    def __init__(
        self,
        output_dir: Path,
        *,
        es_writer: ElasticsearchProductWriter | None = None,
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = self.output_dir / f"products_{timestamp}.jsonl"
        self._fh = self.jsonl_path.open("a", encoding="utf-8")
        self.es_writer = es_writer
        self.es_saved = 0
        self.es_failed = 0

    @classmethod
    def from_settings(
        cls,
        output_dir: Path,
        es_settings: ElasticsearchSettings | None,
        *,
        enable_es: bool = True,
    ) -> ProductWriter:
        es_writer = None
        if enable_es and es_settings is not None:
            es_writer = ElasticsearchProductWriter(es_settings)
        return cls(output_dir, es_writer=es_writer)

    @property
    def path(self) -> Path:
        return self.jsonl_path

    def write(self, product: dict, category_name: str) -> None:
        record = {"category": category_name, **product}
        self._fh.write(json.dumps(record, ensure_ascii=False))
        self._fh.write("\n")
        self._fh.flush()

        if self.es_writer is not None:
            self.es_writer.write(product, category_name)

    def close(self) -> None:
        self._fh.close()
        if self.es_writer is not None:
            self.es_writer.close()
            self.es_saved = self.es_writer.saved
            self.es_failed = self.es_writer.failed
