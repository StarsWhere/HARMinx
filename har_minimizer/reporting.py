from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlparse, parse_qs

from .models import MinimizationResult, ProcessedRequest, ReportEntry
from .filtering import build_dedup_key


class ReportWriter:
    def __init__(self, path: str):
        self.path = Path(path)

    def write(self, entries: Iterable[ReportEntry]) -> None:
        data = [self._to_dict(entry) for entry in entries]
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _to_dict(self, entry: ReportEntry) -> Dict:
        return {
            "index": entry.index,
            "method": entry.method,
            "url": entry.url,
            "path": entry.path,
            "query": entry.query,
            "baseline": {
                "status": entry.baseline_status,
                "length": entry.baseline_length,
            },
            "final": {
                "status": entry.final_status,
                "length": entry.final_length,
            },
            "matched_baseline": entry.matched,
            "headers": entry.header_counts,
            "body": entry.body_counts,
            "minimized_headers": entry.minimized_headers,
            "minimized_body": entry.minimized_body,
            "error": entry.error,
        }


class HarExporter:
    def __init__(self, raw_har: Dict):
        self.raw = deepcopy(raw_har)

    def apply(
        self,
        processed: Iterable[ProcessedRequest],
        include_metadata: bool = True,
        deduplicate_identical: bool = False,
    ) -> None:
        entries = self.raw.get("log", {}).get("entries", [])
        for item in processed:
            if not item.result.matched:
                continue
            index = item.request.index
            if index >= len(entries):
                continue
            entry = entries[index]
            request_block = entry.setdefault("request", {})
            request_block["headers"] = deepcopy(item.result.headers)
            if item.result.body_text is not None:
                post_data = request_block.setdefault("postData", {})
                post_data["text"] = item.result.body_text
                if item.request.mime_type:
                    post_data.setdefault("mimeType", item.request.mime_type)
            elif request_block.get("postData") and "text" in request_block["postData"]:
                request_block["postData"]["text"] = item.request.body_text or ""
            if include_metadata:
                meta = entry.setdefault("_minimized", {})
                meta.update(
                    {
                        "original_header_count": len(item.request.headers),
                        "final_header_count": len(item.result.headers),
                        "header_candidates": item.result.header_candidates,
                        "body_candidates": item.result.body_candidates,
                        "matched": item.result.matched,
                    }
                )
        if deduplicate_identical:
            self._deduplicate_entries()

    def write(self, path: str) -> None:
        target = Path(path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.raw, indent=2, ensure_ascii=False), encoding="utf-8")

    def _deduplicate_entries(self) -> None:
        log = self.raw.get("log", {})
        entries = log.get("entries", [])
        seen = set()
        deduped: List[Dict] = []
        for entry in entries:
            request = entry.get("request", {}) or {}
            url = request.get("url", "") or ""
            method = request.get("method", "") or ""
            post_data = request.get("postData", {}) or {}
            body_text = post_data.get("text")
            parsed = urlparse(url)
            query_dict = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            key = build_dedup_key(method=method, url=url, query=query_dict, body_text=body_text)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        log["entries"] = deduped
