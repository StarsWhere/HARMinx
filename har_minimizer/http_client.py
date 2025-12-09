from __future__ import annotations

import threading
import time
from typing import Dict, Optional

import requests

from .config import ClientConfig
from .models import RequestData, ResponseSnapshot


class RateLimiter:
    def __init__(self, requests_per_second: Optional[float]):
        self.rps = requests_per_second
        self._lock = threading.Lock()
        self._allowance = 0.0
        self._last_check = time.monotonic()

    def wait(self) -> None:
        if not self.rps:
            return
        with self._lock:
            current = time.monotonic()
            elapsed = current - self._last_check
            self._last_check = current
            self._allowance += elapsed * self.rps
            if self._allowance > self.rps:
                self._allowance = self.rps
            if self._allowance < 1.0:
                sleep_time = (1.0 - self._allowance) / self.rps
                time.sleep(max(0.0, sleep_time))
                self._allowance = 0.0
            else:
                self._allowance -= 1.0


class HttpClient:
    def __init__(self, config: ClientConfig):
        self.config = config
        self.rate_limiter = RateLimiter(config.rate_limit.requests_per_second)
        self._local = threading.local()

    def send(self, request: RequestData, headers: Dict[str, str], body: Optional[str]) -> ResponseSnapshot:
        self.rate_limiter.wait()
        start = time.monotonic()
        try:
            session = self._get_session()
            response = session.request(
                method=request.method,
                url=request.url,
                headers=headers,
                data=body if body is not None else request.body_text,
                timeout=self.config.timeout,
                verify=self.config.verify_tls,
            )
            elapsed = time.monotonic() - start
            return ResponseSnapshot(
                status_code=response.status_code,
                body=response.text,
                elapsed=elapsed,
                error=None,
                headers=dict(response.headers),
            )
        except requests.RequestException as exc:
            elapsed = time.monotonic() - start
            return ResponseSnapshot(
                status_code=None,
                body=None,
                elapsed=elapsed,
                error=str(exc),
                headers={},
            )

    def _get_session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            if self.config.proxies:
                session.proxies.update(self.config.proxies)
            self._local.session = session
        return session
