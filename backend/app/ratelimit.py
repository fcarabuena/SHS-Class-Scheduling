"""A small in-memory rate limiter.

Enough for one API process. With several processes, put the limit in the
reverse proxy or a shared store instead.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check(key: str, rule: str) -> None:
    """Raises 429 when ``key`` exceeds ``rule`` ("attempts/seconds")."""
    limit_text, _, window_text = rule.partition("/")
    limit, window = int(limit_text), int(window_text or 60)
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            wait = max(1, int(window - (now - hits[0])))
            raise HTTPException(
                429, f"Too many attempts. Please try again in about {max(1, wait // 60)} minute(s).", headers={"Retry-After": str(wait)}
            )
        hits.append(now)
