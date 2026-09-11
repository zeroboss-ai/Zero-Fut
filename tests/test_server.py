import asyncio
import json
import unittest
from fastapi.testclient import TestClient
from backend.main import app

class TestServerEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("NIFTY", data["symbols"])
        self.assertIn("SENSEX", data["symbols"])

    def test_expiries_endpoint(self):
        resp = self.client.get("/api/expiries?symbol=NIFTY")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["symbol"], "NIFTY")
        self.assertIsInstance(data["expiries"], list)

    def test_history_endpoint(self):
        resp = self.client.get("/api/history?symbol=NIFTY&interval=1s")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("bars", data)

    def test_index_html_served(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ZeroSyN", resp.text)
        self.assertIn("Synthetic Future", resp.text)

    def test_websocket_stream(self):
        with self.client.websocket_connect("/ws") as websocket:
            # First message should be SNAPSHOT
            data = websocket.receive_json()
            self.assertEqual(data["type"], "SNAPSHOT")
            self.assertIn("synthetic", data)
            self.assertIn("history", data)
            syn = data["synthetic"]
            self.assertIn("synthetic_future", syn)
            self.assertIn("spot", syn)
            self.assertIn("basis", syn)
            print("Received initial WS SNAPSHOT:", syn["symbol"], "F_syn:", syn["synthetic_future"])

if __name__ == "__main__":
    unittest.main()
