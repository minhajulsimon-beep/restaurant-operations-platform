"""A small local REST source and a bounded, retrying extraction client.

This API is our demo contract. It does not impersonate Toast or promise that
Toast's nested schemas are compatible with these flat records.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from .sources import SOURCES

DEMO_TOKEN = "demo-local-token"


class APIError(RuntimeError):
    """A source request failed after its bounded retry policy."""


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


@contextmanager
def mock_server(
    source_dir: Path, *, token: str = DEMO_TOKEN,
    simulate_rate_limit: bool = True,
) -> Iterator[str]:
    """Serve an immutable snapshot on a free loopback port, then cleanly stop.

    The first authorized source request receives a 429 with Retry-After: 0.
    Snapshots avoid changing page boundaries mid-extraction. To expose newly
    edited files, start a new context. The server binds only to 127.0.0.1.
    """
    if not token:
        raise ValueError("token cannot be empty")
    source_dir = Path(source_dir)
    snapshot: dict[str, list[dict]] = {}
    for source in SOURCES:
        path = source_dir / f"{source}.jsonl"
        with path.open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        snapshot[source] = sorted(records, key=lambda r: (_timestamp(r["source_updated_at"]), r["id"]))
    rate_limit_pending = simulate_rate_limit
    request_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            # Do not log bearer credentials, source payloads, or noisy requests.
            return

        def respond(self, status: int, body: dict, retry_after: str | None = None) -> None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            if retry_after is not None:
                self.send_header("Retry-After", retry_after)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            nonlocal rate_limit_pending
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self.respond(200, {"status": "ok", "synthetic": True})
                return
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.respond(401, {"error": "invalid demo token"})
                return
            source = parsed.path.removeprefix("/v1/")
            if not parsed.path.startswith("/v1/") or source not in SOURCES:
                self.respond(404, {"error": "unknown source"})
                return
            with request_lock:
                if rate_limit_pending:
                    rate_limit_pending = False
                    self.respond(429, {"error": "simulated rate limit; retry permitted"}, retry_after="0")
                    return
            params = parse_qs(parsed.query)
            try:
                page = int(params.get("page", ["1"])[0])
                page_size = int(params.get("page_size", ["100"])[0])
                if page < 1 or not 1 <= page_size <= 1000:
                    raise ValueError("page must be >=1 and page_size must be 1..1000")
                since = _timestamp(params["modified_since"][0]) if "modified_since" in params else None
                until = _timestamp(params["modified_before"][0]) if "modified_before" in params else None
                if since is not None and until is not None and since >= until:
                    raise ValueError("modified_since must be earlier than modified_before")
            except (ValueError, IndexError) as exc:
                self.respond(400, {"error": str(exc)})
                return
            locations = set(params.get("location_ids", [""])[0].split(",")) - {""}
            selected = []
            for row in snapshot[source]:
                modified = _timestamp(row["source_updated_at"])
                if since is not None and modified < since:
                    continue
                if until is not None and modified >= until:
                    continue
                if locations and row["location_id"] not in locations:
                    continue
                selected.append(row)
            start = (page - 1) * page_size
            data = selected[start:start + page_size]
            self.respond(200, {
                "data": data, "page": page, "page_size": page_size,
                "has_more": start + page_size < len(selected),
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def iter_source(
    base_url: str, source: str, *, since: str | None = None,
    until: str | None = None, location_ids: list[str] | None = None,
    page_size: int = 100, token: str = DEMO_TOKEN, max_attempts: int = 4,
    timeout: float = 5.0,
) -> Iterator[dict]:
    """Extract all pages with timeouts, bounded retries, and fail-fast 4xx.

    Retries 429, 500, 502, 503, 504 and network timeouts. This mock contract's
    modified_since is inclusive; modified_before is exclusive. Overlapping
    extraction windows require source-key upserts in the downstream warehouse.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    if not 1 <= page_size <= 1000 or max_attempts < 1 or timeout <= 0:
        raise ValueError("invalid page size, attempts, or timeout")
    if urlsplit(base_url).scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https")
    if since is not None:
        _timestamp(since)
    if until is not None:
        _timestamp(until)
    if since is not None and until is not None and _timestamp(since) >= _timestamp(until):
        raise ValueError("since must be earlier than until")
    for page in range(1, 100001):
        params: dict[str, object] = {"page": page, "page_size": page_size}
        if since is not None:
            params["modified_since"] = since
        if until is not None:
            params["modified_before"] = until
        if location_ids:
            params["location_ids"] = ",".join(location_ids)
        request = Request(
            base_url.rstrip("/") + f"/v1/{source}?" + urlencode(params),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        response_data = None
        for attempt in range(max_attempts):
            retry_delay = min(0.1 * 2 ** attempt, 2.0)
            try:
                with urlopen(request, timeout=timeout) as response:
                    response_data = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After")
                exc.close()
                if status not in (429, 500, 502, 503, 504):
                    raise APIError(f"{source}: HTTP {status}; not retryable") from None
                if attempt + 1 == max_attempts:
                    raise APIError(f"{source}: HTTP {status} after {max_attempts} attempts") from None
                if retry_after is not None:
                    try:
                        retry_delay = min(max(float(retry_after), 0), 30)
                    except ValueError:
                        pass
            except (URLError, TimeoutError, socket.timeout):
                if attempt + 1 == max_attempts:
                    raise APIError(f"{source}: connection failed after {max_attempts} attempts") from None
            time.sleep(retry_delay)
        if not isinstance(response_data, dict) or not isinstance(response_data.get("data"), list):
            raise APIError(f"{source}: malformed API response")
        if response_data.get("page") != page or not isinstance(response_data.get("has_more"), bool):
            raise APIError(f"{source}: inconsistent pagination metadata")
        records = response_data["data"]
        if response_data["has_more"] and not records:
            raise APIError(f"{source}: empty page marked as having more data")
        for record in records:
            if not isinstance(record, dict):
                raise APIError(f"{source}: source record is not an object")
            yield record
        if not response_data["has_more"]:
            return
    raise APIError(f"{source}: pagination exceeded the safety limit")
