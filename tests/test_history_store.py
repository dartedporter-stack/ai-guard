import unittest
from unittest.mock import patch

import httpx

from guard.history_store import HistoryStore


def response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://example.supabase.co"),
    )


class HistoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HistoryStore(
            supabase_url="https://example.supabase.co",
            anon_key="public-anon-key",
        )

    @patch("guard.history_store.httpx.get")
    def test_verify_user_passes_the_user_token(self, mock_get) -> None:
        mock_get.return_value = response(200, {"id": "user-id"})

        self.store.verify_user("user-access-token")

        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer user-access-token")
        self.assertEqual(headers["apikey"], "public-anon-key")

    @patch("guard.history_store.httpx.get")
    def test_verify_user_rejects_an_invalid_token(self, mock_get) -> None:
        mock_get.return_value = response(401, {"message": "invalid token"})

        with self.assertRaises(PermissionError):
            self.store.verify_user("invalid-token")

    @patch("guard.history_store.httpx.get")
    def test_history_request_uses_rls_user_token(self, mock_get) -> None:
        mock_get.return_value = response(200, [])

        records = self.store.list_recent(access_token="user-access-token")

        self.assertEqual(records, [])
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer user-access-token")

    def test_missing_supabase_configuration_is_rejected(self) -> None:
        store = HistoryStore(supabase_url="", anon_key="")

        with self.assertRaises(RuntimeError):
            store.verify_user("user-access-token")


if __name__ == "__main__":
    unittest.main()
