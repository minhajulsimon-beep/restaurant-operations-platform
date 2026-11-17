"""Mocked protocol tests. These do not contact Toast or validate live access."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from connectors.toast_readonly import ToastError, ToastReadOnly, _NoRedirect, extract_to_file

RESTAURANT = "12345678-1234-5678-1234-567812345678"
START = "2026-09-01T00:00:00.000Z"
END = "2026-09-02T00:00:00.000Z"


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(json.dumps(data).encode())
        self.headers = headers or {}


class ToastAdapterTests(unittest.TestCase):
    def client(self, **kwargs):
        return ToastReadOnly("https://example.toasttab.com", "fake-client", "fake-secret", **kwargs)

    @patch("connectors.toast_readonly.time.sleep")
    def test_auth_body_headers_and_native_order_pagination(self, _sleep):
        native = {"guid": "order-one", "checks": [{"guid": "check-one", "payments": []}]}
        replies = [Response({"token": {"accessToken": "fake-token"}}),
                   Response([native], {"Link": '<https://example.toasttab.com/orders/v2/ordersBulk?page=2>; rel="next"'}),
                   Response([{"guid": "order-two", "checks": []}])]
        with patch("connectors.toast_readonly._open", side_effect=replies) as send:
            orders = list(self.client().iter_orders(RESTAURANT, START, END, page_size=100))
        self.assertEqual(orders[0], native)
        self.assertEqual(len(orders), 2)
        login = send.call_args_list[0].args[0]
        self.assertEqual(login.get_method(), "POST")
        self.assertEqual(urlsplit(login.full_url).path, "/authentication/v1/authentication/login")
        self.assertEqual(json.loads(login.data), {"clientId": "fake-client", "clientSecret": "fake-secret", "userAccessType": "TOAST_MACHINE_CLIENT"})
        self.assertEqual(login.get_header("Content-type"), "application/json")
        request = send.call_args_list[1].args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-token")
        self.assertEqual(request.get_header("Toast-restaurant-external-id"), RESTAURANT)
        second = parse_qs(urlsplit(send.call_args_list[2].args[0].full_url).query)
        self.assertEqual(second["page"], ["2"])
        self.assertEqual(second["pageSize"], ["100"])
        self.assertEqual(second["startDate"], ["2026-09-01T00:00:00.000+00:00"])

    @patch("connectors.toast_readonly.time.sleep")
    def test_rate_limit_retries_and_auth_failure_is_not_retried(self, _sleep):
        rate_limit = HTTPError("https://example.toasttab.com/", 429, "limit", {"Retry-After": "0"}, None)
        with patch("connectors.toast_readonly._open", side_effect=[rate_limit, Response({"token": {"accessToken": "fake-token"}})]) as send:
            self.client().authenticate()
            self.assertEqual(send.call_count, 2)
        forbidden = HTTPError("https://example.toasttab.com/", 403, "forbidden", {}, None)
        with patch("connectors.toast_readonly._open", side_effect=forbidden) as send:
            with self.assertRaisesRegex(ToastError, "orders:read"):
                self.client().authenticate()
            self.assertEqual(send.call_count, 1)

    @patch("connectors.toast_readonly.time.sleep")
    def test_retry_exhaustion_and_one_expired_token_refresh(self, _sleep):
        unavailable = lambda: HTTPError("https://example.toasttab.com/", 503, "unavailable", {}, None)
        with patch("connectors.toast_readonly._open", side_effect=[unavailable(), unavailable()]) as send:
            with self.assertRaisesRegex(ToastError, "retry limit"):
                self.client(max_attempts=2).authenticate()
            self.assertEqual(send.call_count, 2)
        expired = HTTPError("https://example.toasttab.com/", 401, "expired", {}, None)
        replies = [Response({"token": {"accessToken": "old-token"}}), expired,
                   Response({"token": {"accessToken": "new-token"}}), Response([])]
        with patch("connectors.toast_readonly._open", side_effect=replies) as send:
            self.assertEqual(list(self.client().iter_orders(RESTAURANT, START, END)), [])
            self.assertEqual(send.call_args_list[3].args[0].get_header("Authorization"), "Bearer new-token")

    def test_origin_checks_and_redirects_preserve_credential_boundary(self):
        for origin in ["http://example.toasttab.com", "https://example.com", "https://toasttab.com.evil.test", "https://user:pass@example.toasttab.com", "https://example.toasttab.com/path"]:
            with self.assertRaises(ValueError):
                ToastReadOnly(origin, "fake-client", "fake-secret")
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, None, {}, "https://example.com"))

    def test_existing_output_and_failure_preserve_previous_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "orders.jsonl"
            output.write_text("existing\n")
            client = Mock()
            with self.assertRaises(FileExistsError):
                extract_to_file(client, RESTAURANT, START, END, output)
            client.iter_orders.assert_not_called()
            def fail_midstream(*args):
                yield {"guid": "one"}
                raise ToastError("planned failure")
            client.iter_orders.side_effect = fail_midstream
            with self.assertRaises(ToastError):
                extract_to_file(client, RESTAURANT, START, END, output, force=True)
            self.assertEqual(output.read_text(), "existing\n")
            self.assertEqual(list(Path(folder).glob(".toast-*.partial")), [])

    def test_success_writes_only_native_json(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "orders.jsonl"
            client = Mock()
            client.iter_orders.return_value = iter([{"guid": "one", "checks": []}])
            self.assertEqual(extract_to_file(client, RESTAURANT, START, END, output), 1)
            self.assertEqual(json.loads(output.read_text()), {"guid": "one", "checks": []})


if __name__ == "__main__":
    unittest.main()
