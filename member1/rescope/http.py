"""Polite fetcher (Tasks 1.3/1.12): clear User-Agent, per-domain throttle, retry with back-off,
robots.txt check, and disk caching. A `transport` callable can be injected for offline tests."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib import robotparser
import requests
from . import config
from .cache import DiskCache


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes
    content_type: str = ""
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, cache: Optional[DiskCache] = None, transport: Optional[Callable] = None,
                 min_interval: float | None = None, respect_robots: bool | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cache = cache or DiskCache()
        self.transport = transport
        self.min_interval = config.MIN_INTERVAL_SEC if min_interval is None else min_interval
        self.respect_robots = config.RESPECT_ROBOTS if respect_robots is None else respect_robots
        self._last: dict[str, float] = {}
        self._host_fail: dict[str, int] = {}
        self.max_host_failures = config.MAX_HOST_FAILURES
        self._robots: dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def _throttle(self, host: str) -> None:
        interval = max(self.min_interval, config.HOST_MIN_INTERVAL.get(host, 0)) if self.min_interval else 0
        wait = interval - (time.time() - self._last.get(host, 0))
        if wait > 0:
            self._sleep(wait)
        self._last[host] = time.time()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots or self.transport is not None:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=10)
                rp.parse(r.text.splitlines() if r.ok else [])
                self._robots[base] = rp
            except Exception:
                self._robots[base] = None       # unreachable robots.txt: proceed politely
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(config.USER_AGENT, url)

    def get(self, url: str, ttl: float | None = 7 * 86400, params: dict | None = None,
            headers: dict | None = None, use_cache: bool = True) -> FetchResult:
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        if use_cache:
            hit = self.cache.get(key, ttl)
            if hit is not None:
                meta = self.cache.label(key) or {}
                return FetchResult(url, 200, hit, meta.get("content_type", ""), True)
        if not self.allowed(url):
            raise FetchError(f"blocked by robots.txt: {url}")
        host = urlparse(url).netloc
        if self._host_fail.get(host, 0) >= self.max_host_failures:       # circuit breaker: stop hammering a host that refuses us
            raise FetchError(f"skipped: {host} refused or timed out {self._host_fail[host]} times in a row")
        last_exc: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            self._throttle(host)
            try:
                if self.transport:
                    res = self.transport(url, params, headers)
                else:
                    r = self.session.get(url, params=params, headers=headers, timeout=config.HTTP_TIMEOUT)
                    res = FetchResult(url, r.status_code, r.content, r.headers.get("Content-Type", ""))
                if res.status in (401, 403):
                    self._host_fail[host] = self._host_fail.get(host, 0) + 1
                if res.status in (429, 500, 502, 503, 504):
                    raise FetchError(f"HTTP {res.status}")
                if res.ok:
                    self._host_fail[host] = 0
                    if use_cache:
                        self.cache.set(key, res.content, content_type=res.content_type, url=url)
                return res
            except Exception as exc:                       # retry with exponential back-off
                last_exc = exc
                self._host_fail[host] = self._host_fail.get(host, 0) + 1
                if self._host_fail[host] >= self.max_host_failures:
                    break
                self._sleep((5 if "429" in str(exc) else 1) * 2 ** attempt)     # rate-limited hosts get longer back-off
        raise FetchError(f"failed after {config.MAX_RETRIES} attempts: {url} ({last_exc})")
