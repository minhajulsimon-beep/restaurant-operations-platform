"""Optional live Toast raw extractor. Not used by the synthetic demo.

Only login POST and orders GET requests are implemented. Native nested Toast
objects are saved locally; business normalization is intentionally separate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


class ToastError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or bearer tokens to a redirect.


def _open(request, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def _utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("start and end must include timezone offsets")
    return stamp.astimezone(timezone.utc)


class ToastReadOnly:
    def __init__(self, base_url: str, client_id: str, client_secret: str, *, timeout=20, max_attempts=4):
        origin = urlsplit(base_url)
        if (origin.scheme != "https" or not (origin.hostname or "").endswith(".toasttab.com")
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ("", "/") or origin.port not in (None, 443)):
            raise ValueError("TOAST_BASE_URL must be a trusted HTTPS *.toasttab.com origin without a path")
        if not client_id or not client_secret:
            raise ValueError("Toast client credentials are required")
        if timeout <= 0 or not 1 <= max_attempts <= 5:
            raise ValueError("timeout must be positive; max_attempts must be 1..5")
        self.base_url, self.client_id, self.client_secret = base_url.rstrip("/"), client_id, client_secret
        self.timeout, self.max_attempts = timeout, max_attempts
        self._last_request, self._token = 0.0, None

    @classmethod
    def from_env(cls):
        names = ("TOAST_BASE_URL", "TOAST_CLIENT_ID", "TOAST_CLIENT_SECRET")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ToastError("Set required environment variables: " + ", ".join(missing))
        return cls(*(os.environ[name] for name in names))

    def _request(self, path, *, headers=None, body=None):
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, headers=request_headers,
                          data=json.dumps(body).encode() if body is not None else None)
        for attempt in range(self.max_attempts):
            time.sleep(max(0, 0.26 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            delay = min(0.5 * 2 ** attempt, 8)
            try:
                with _open(request, timeout=self.timeout) as response:
                    try:
                        return json.load(response), response.headers
                    except (ValueError, UnicodeError):
                        raise ToastError("Toast returned an invalid JSON response") from None
            except HTTPError as exc:
                status, retry_after = exc.code, exc.headers.get("Retry-After")
                exc.close()
                if status == 401:
                    raise ToastError("HTTP 401: authentication is invalid or expired") from None
                if status == 403:
                    raise ToastError("HTTP 403: check orders:read scope and restaurant access") from None
                if status not in (429, 500, 502, 503, 504):
                    raise ToastError(f"HTTP {status}: request stopped; redirects are disabled") from None
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                        except (TypeError, ValueError):
                            pass
                    if delay > 30:
                        raise ToastError("Server requested a retry delay over 30 seconds; retry the job later") from None
                failure = f"HTTP {status}: retry limit reached"
            except (URLError, TimeoutError):
                failure = "Connection failed: retry limit reached"
            if attempt + 1 == self.max_attempts:
                raise ToastError(failure) from None
            time.sleep(max(0, delay))

    def authenticate(self):
        data, _ = self._request("/authentication/v1/authentication/login", body={
            "clientId": self.client_id, "clientSecret": self.client_secret,
            "userAccessType": "TOAST_MACHINE_CLIENT",
        })
        token_info = data.get("token") if isinstance(data, dict) else None
        token = token_info.get("accessToken") if isinstance(token_info, dict) else None
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
            raise ToastError("Authentication response did not contain token.accessToken")
        self._token = token

    def iter_orders(self, restaurant_id: str, start: str, end: str, *, page_size=100):
        restaurant_id = str(UUID(restaurant_id))
        lower, upper = _utc(start), _utc(end)
        if lower >= upper or lower < datetime(2015, 12, 1, tzinfo=timezone.utc):
            raise ValueError("Choose start < end, with start on or after 2015-12-01")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be 1..100")
        if self._token is None:
            self.authenticate()
        refreshed = False
        for page in range(1, 100001):
            query = urlencode({"startDate": lower.isoformat(timespec="milliseconds"),
                               "endDate": upper.isoformat(timespec="milliseconds"),
                               "pageSize": page_size, "page": page})
            path = "/orders/v2/ordersBulk?" + query
            headers = {"Authorization": "Bearer " + self._token,
                       "Toast-Restaurant-External-ID": restaurant_id}
            try:
                data, response_headers = self._request(path, headers=headers)
            except ToastError as exc:
                if not str(exc).startswith("HTTP 401") or refreshed:
                    raise
                refreshed = True
                self._token = None
                self.authenticate()
                headers["Authorization"] = "Bearer " + self._token
                data, response_headers = self._request(path, headers=headers)
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ToastError("ordersBulk must return a JSON array of Order objects")
            yield from data
            link = response_headers.get("Link", "")
            has_next = bool(re.search(r'rel\s*=\s*[\"\']?next(?:[\"\';,\s]|$)', link, re.I))
            if (link and not has_next) or (not link and len(data) < page_size):
                return
            if has_next and not data:
                raise ToastError("Empty orders page advertised a next page")
        raise ToastError("Pagination limit reached; split the modified-time window")


def extract_to_file(client, restaurant_id, start, end, output: Path, *, force=False):
    output = Path(output)
    if output.exists() and not force:
        raise FileExistsError("Output exists; choose a new filename or explicitly use --force")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=".toast-", suffix=".partial", delete=False) as handle:
            partial = Path(handle.name)
            count = 0
            for order in client.iter_orders(restaurant_id, start, end):
                handle.write(json.dumps(order, ensure_ascii=False) + "\n")
                count += 1
        if force:
            os.replace(partial, output)
        else:
            os.link(partial, output)  # Atomic publication that never replaces an existing file.
        return count
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaurant-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing output after successful extraction")
    args = parser.parse_args()
    try:
        count = extract_to_file(ToastReadOnly.from_env(), args.restaurant_id, args.start, args.end,
                                args.output, force=args.force)
    except (ToastError, ValueError, OSError) as exc:
        parser.exit(2, f"Extraction stopped: {exc}\n")
    print(f"Saved {count} native Toast order objects. No restaurant data was changed.")


if __name__ == "__main__":
    main()
