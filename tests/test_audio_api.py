import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api


class AudioApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.auth_headers = {"Authorization": "Bearer test-user-token"}

    def tearDown(self):
        with api.protection_sessions_lock:
            api.protection_sessions.clear()

    @patch.object(api.history_store, "verify_user", return_value={"id": "user"})
    def test_rejects_non_pcm_content(self, _verify_user):
        response = self.client.post(
            "/analyze/audio",
            headers={**self.auth_headers, "Content-Type": "audio/wav"},
            content=b"not-pcm",
        )

        self.assertEqual(response.status_code, 415)

    @patch.object(api.history_store, "verify_user", return_value={"id": "user"})
    @patch.object(api, "analyze_and_save")
    @patch.object(api, "transcribe_pcm16", return_value="Тестовая ситуация")
    def test_forwards_actual_sample_rate(
        self,
        transcribe,
        analyze_and_save,
        _verify_user,
    ):
        analyze_and_save.return_value = api.AnalyzeResponse(
            risk_score=10,
            risk_level="LOW",
            action_safety="SAFE",
            category="TEST",
            intent="TEST",
            context="TEST",
            factors=[],
            red_flags=[],
            actions=[],
            conclusion="OK",
            transcript="Тестовая ситуация",
        )
        audio = bytes(9_600)

        response = self.client.post(
            "/analyze/audio",
            headers={
                **self.auth_headers,
                "Content-Type": "audio/pcm;rate=48000",
            },
            content=audio,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "Тестовая ситуация")
        transcribe.assert_called_once_with(audio, 48_000)
        analyze_and_save.assert_called_once_with(
            "Тестовая ситуация",
            "test-user-token",
            "Тестовая ситуация",
        )

    def test_live_protection_session_detects_danger(self):
        with patch.object(
            api.history_store,
            "verify_user",
            return_value={"id": "user"},
        ):
            start_response = self.client.post(
                "/protect/start",
                headers=self.auth_headers,
            )
            session_id = start_response.json()["session_id"]

            with patch.object(
                api,
                "transcribe_pcm16",
                return_value=(
                    "Я сотрудник банка. Срочно назовите код из СМС."
                ),
            ):
                chunk_response = self.client.post(
                    "/protect/audio",
                    headers={
                        **self.auth_headers,
                        "Content-Type": "audio/pcm;rate=16000",
                        "X-Protection-Session": session_id,
                    },
                    content=bytes(3_200),
                )

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(chunk_response.status_code, 200)
        self.assertGreaterEqual(chunk_response.json()["risk_score"], 60)

    def test_live_session_cannot_be_used_with_another_token(self):
        with patch.object(
            api.history_store,
            "verify_user",
            return_value={"id": "user"},
        ):
            start_response = self.client.post(
                "/protect/start",
                headers=self.auth_headers,
            )
            session_id = start_response.json()["session_id"]
            response = self.client.post(
                "/protect/audio",
                headers={
                    "Authorization": "Bearer another-user-token",
                    "Content-Type": "audio/pcm;rate=16000",
                    "X-Protection-Session": session_id,
                },
                content=bytes(3_200),
            )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
