import json
import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("ai_guard.db")


class HistoryStore:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT (
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ),
                    input_text TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    red_flags TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    conclusion TEXT NOT NULL
                )
                """
            )

    def save(
        self,
        *,
        input_text: str,
        risk_score: int,
        risk_level: str,
        category: str,
        red_flags: list[str],
        actions: list[str],
        conclusion: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_history (
                    input_text,
                    risk_score,
                    risk_level,
                    category,
                    red_flags,
                    actions,
                    conclusion
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    input_text,
                    risk_score,
                    risk_level,
                    category,
                    json.dumps(red_flags, ensure_ascii=False),
                    json.dumps(actions, ensure_ascii=False),
                    conclusion,
                ),
            )

            if cursor.lastrowid is None:
                raise RuntimeError("SQLite не вернул id записи истории")

            return cursor.lastrowid

    def list_recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    input_text,
                    risk_score,
                    risk_level,
                    category,
                    red_flags,
                    actions,
                    conclusion
                FROM analysis_history
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "input_text": row["input_text"],
                "risk_score": row["risk_score"],
                "risk_level": row["risk_level"],
                "category": row["category"],
                "red_flags": json.loads(row["red_flags"]),
                "actions": json.loads(row["actions"]),
                "conclusion": row["conclusion"],
            }
            for row in rows
        ]
