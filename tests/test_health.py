import unittest

from fastapi.testclient import TestClient

import api


class HealthEndpointTests(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        response = TestClient(api.app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
