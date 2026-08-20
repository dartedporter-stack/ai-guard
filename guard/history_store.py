from typing import Any

import httpx

from config import SUPABASE_ANON_KEY, SUPABASE_URL


class HistoryStore:
    def __init__(
        self,
        supabase_url: str | None = SUPABASE_URL,
        anon_key: str | None = SUPABASE_ANON_KEY,
    ):
        self.supabase_url = (supabase_url or "").rstrip("/")
        self.anon_key = anon_key or ""

    def _require_configuration(self) -> None:
        if not self.supabase_url or not self.anon_key:
            raise RuntimeError(
                "SUPABASE_URL и SUPABASE_ANON_KEY не настроены для API"
            )

    def _headers(self, access_token: str) -> dict[str, str]:
        self._require_configuration()
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def verify_user(self, access_token: str) -> None:
        try:
            response = httpx.get(
                f"{self.supabase_url}/auth/v1/user",
                headers=self._headers(access_token),
                timeout=10,
            )
        except httpx.HTTPError as error:
            raise RuntimeError("Не удалось проверить сессию Supabase") from error

        if response.status_code in {401, 403}:
            raise PermissionError("Недействительная сессия Supabase")

        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError("Не удалось проверить сессию Supabase") from error

    def save(
        self,
        *,
        access_token: str,
        input_text: str,
        risk_score: int,
        risk_level: str,
        category: str,
        red_flags: list[str],
        actions: list[str],
        conclusion: str,
    ) -> int:
        try:
            response = httpx.post(
                f"{self.supabase_url}/rest/v1/analysis_history",
                headers={
                    **self._headers(access_token),
                    "Prefer": "return=representation",
                },
                json={
                    "input_text": input_text,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "category": category,
                    "red_flags": red_flags,
                    "actions": actions,
                    "conclusion": conclusion,
                },
                timeout=10,
            )
            response.raise_for_status()
            records = response.json()
            return int(records[0]["id"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("Не удалось сохранить историю в Supabase") from error

    def list_recent(
        self,
        *,
        access_token: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        try:
            response = httpx.get(
                f"{self.supabase_url}/rest/v1/analysis_history",
                headers=self._headers(access_token),
                params={
                    "select": (
                        "id,created_at,input_text,risk_score,risk_level,category,"
                        "red_flags,actions,conclusion"
                    ),
                    "order": "created_at.desc,id.desc",
                    "limit": str(limit),
                },
                timeout=10,
            )
            response.raise_for_status()
            records = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError("Не удалось загрузить историю из Supabase") from error

        if not isinstance(records, list):
            raise RuntimeError("Supabase вернул некорректную историю")

        return records
