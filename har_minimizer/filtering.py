from __future__ import annotations

import logging
import re
from typing import Iterable, List, Tuple

from .config import FilterConfig, ScopeConfig
from .har_loader import HarEntry

logger = logging.getLogger(__name__)


class RequestFilter:
    def __init__(self, filter_config: FilterConfig, scope_config: ScopeConfig):
        self.config = filter_config
        self.scope = scope_config
        self._url_regex = [re.compile(p) for p in filter_config.url_regex]
        self._scope_regex = [re.compile(p) for p in scope_config.include_regex]

    def apply(self, entries: Iterable[HarEntry]) -> List[HarEntry]:
        results: List[HarEntry] = []
        for entry in entries:
            if not self._matches_filter(entry):
                continue
            if not self._matches_scope(entry):
                continue
            results.append(entry)
        if self.config.deduplicate_identical:
            before = len(results)
            results = self._deduplicate(results)
            if before != len(results):
                logger.info("已过滤完全一致的请求：%s -> %s", before, len(results))
        return results

    def _matches_filter(self, entry: HarEntry) -> bool:
        request = entry.request
        cfg = self.config
        if cfg.methods and request.method.upper() not in {m.upper() for m in cfg.methods}:
            return False
        if cfg.hosts:
            if request.path and request.url:
                host = re.sub(r"^https?://", "", request.url).split("/")[0]
            else:
                host = ""
            if host not in cfg.hosts:
                return False
        if cfg.url_regex and not any(r.search(request.url) for r in self._url_regex):
            return False
        if cfg.index_range:
            start, end = cfg.index_range
            if not (start <= entry.index <= end):
                return False
        return True

    def _matches_scope(self, entry: HarEntry) -> bool:
        request = entry.request
        if not (self.scope.include_urls or self.scope.include_regex):
            return True
        url_matches = request.url in set(self.scope.include_urls)
        regex_matches = any(r.search(request.url) for r in self._scope_regex)
        return url_matches or regex_matches

    def _deduplicate(self, entries: Iterable[HarEntry]) -> List[HarEntry]:
        unique: List[HarEntry] = []
        seen: set[Tuple] = set()
        for entry in entries:
            key = build_dedup_key(
                method=entry.request.method,
                url=entry.request.url,
                query=entry.request.query,
                body_text=entry.request.body_text,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        return unique


def build_dedup_key(method: str, url: str, query: dict, body_text: str | None) -> Tuple:
    base_url = url.split("?", 1)[0]
    normalized_query = _normalize_query(query)
    body = body_text or ""
    return (method.upper(), base_url, normalized_query, body)


def _normalize_query(query: dict) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    normalized = []
    for key, value in query.items():
        if isinstance(value, (list, tuple)):
            values = tuple(str(v) for v in value)
        else:
            values = (str(value),)
        normalized.append((key, values))
    normalized.sort(key=lambda item: item[0])
    return tuple(normalized)
