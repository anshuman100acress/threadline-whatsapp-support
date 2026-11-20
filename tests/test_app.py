import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)


class ChatTests(ClientTestCase):
    def test_browser_and_api(self):
        self.assertIn("Threadline Support", self.client.get("/").text)
        self.assertEqual(self.client.get("/static/chat.js").status_code, 200)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        for message, intent, fragment in [
            ("Track TL-1042", "tracking", "Shipped"),
            ("TL-9999", "tracking", "find"),
            ("Return order TL-1042", "returns", "14 days"),
            ("tee size", "size", "38 in"),
            ("human", "handoff", "live WhatsApp"),
            ("hello", "unknown", "order tracking"),
        ]:
            with self.subTest(message=message):
                response = self.client.post("/api/chat", json={"message": message})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["intent"], intent)
                self.assertIn(fragment, response.json()["reply"])

    def test_reject_blank_message(self):
        self.assertEqual(self.client.post("/api/chat", json={"message": " "}).status_code, 422)


class WebhookTests(ClientTestCase):
    def setUp(self):
        super().setUp()
        temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.queue_path = Path(temp_dir) / "data" / "handoffs.sqlite3"
        config = {
            "HANDOFF_DB_PATH": str(self.queue_path),
            "META_APP_SECRET": "test-secret",
            "META_VERIFY_TOKEN": "verify-me",
            "META_ACCESS_TOKEN": "test-access",
            "META_PHONE_NUMBER_ID": "123",
            "META_GRAPH_VERSION": "v99.0",
            "META_MODEL_API_KEY": "fake-key",
            "META_MODEL": "",
            "N8N_HANDOFF_URL": "https://workflow.example/webhook/threadline",
            "N8N_HANDOFF_TOKEN": "handoff-secret",
        }
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, config).start()
        app.completed.clear()
        self.requests = []
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: self.downstream(request))
        patch.object(app.httpx, "AsyncClient",
                     side_effect=lambda **kwargs: real_client(transport=transport, **kwargs)).start()

    def downstream(self, request):
        self.requests.append(request)
        payload = {"choices": [{"message": {"content": "returns"}}]}
        return httpx.Response(200, json=payload)

    def event(self, message, event_id):
        event = {"entry": [{"changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "123"},
            "messages": [{"type": "text", "id": event_id, "from": "15550001111",
                          "text": {"body": message}}],
        }}]}]}
        body = json.dumps(event).encode()
        signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        return body, {"X-Hub-Signature-256": "sha256=" + signature}

    def test_verification(self):
        params = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "hello"}
        self.assertEqual(self.client.get("/webhook", params=params).text, "hello")
        params["hub.verify_token"] = "wrong"
        self.assertEqual(self.client.get("/webhook", params=params).status_code, 403)

    def test_signature_and_duplicate_delivery(self):
        body, headers = self.event("Track TL-1042", "wamid.1")
        self.assertEqual(self.client.post("/webhook", content=body).status_code, 403)
        for _ in range(2):
            self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.assertEqual(len(self.requests), 1)
        self.assertIn("Shipped", json.loads(self.requests[0].content)["text"]["body"])

    def test_model_and_handoff(self):
        for message in ("I changed my mind", "human"):
            body, headers = self.event(message, message)
            self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.assertEqual([request.url.host for request in self.requests], [
            "api.meta.ai", "graph.facebook.com", "workflow.example", "graph.facebook.com"
        ])
        model_request = self.requests[0]
        self.assertEqual(model_request.url.path, "/v1/chat/completions")
        self.assertEqual(model_request.headers["Authorization"], "Bearer fake-key")
        model_payload = json.loads(model_request.content)
        self.assertEqual(model_payload["model"], "muse-spark-1.3")
        self.assertEqual(model_payload["reasoning_effort"], "minimal")
        self.assertFalse(model_payload["store"])
        self.assertIn("14 days", json.loads(self.requests[1].content)["text"]["body"])
        self.assertEqual(self.requests[2].headers["X-Handoff-Token"], "handoff-secret")
        self.assertEqual(json.loads(self.requests[2].content)["reply_to"], "15550001111")

    def test_browser_skips_model_even_with_key(self):
        response = self.client.post("/api/chat", json={"message": "I changed my mind"})
        self.assertEqual(response.json()["routing"], "rules")
        self.assertEqual(self.requests, [])

    def test_model_error_falls_back_to_supported_topics(self):
        def downstream(request):
            self.requests.append(request)
            status = 429 if request.url.host == "api.meta.ai" else 200
            return httpx.Response(status)

        with patch.object(self, "downstream", side_effect=downstream):
            body, headers = self.event("I changed my mind", "wamid.fallback")
            self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.assertEqual(len(self.requests), 2)
        self.assertIn("I can help", json.loads(self.requests[1].content)["text"]["body"])

    def assert_queued(self, event_id):
        with closing(sqlite3.connect(self.queue_path)) as db:
            self.assertEqual(db.execute("SELECT event_id, reply_to FROM handoffs").fetchall(),
                             [(event_id, "15550001111")])
        self.assertIn("support queue", json.loads(self.requests[-1].content)["text"]["body"])

    def test_handoff_without_n8n_survives_webhook_reprocessing(self):
        body, headers = self.event("human", "wamid.queue")
        with patch.dict(os.environ, {"N8N_HANDOFF_URL": ""}):
            for _ in range(2):
                app.completed.clear()
                self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.assertEqual([request.url.host for request in self.requests], ["graph.facebook.com"] * 2)
        self.assert_queued("wamid.queue")

    def test_handoff_falls_back_when_n8n_is_unavailable(self):
        def downstream(request):
            self.requests.append(request)
            return httpx.Response(503 if request.url.host == "workflow.example" else 200)

        with patch.object(self, "downstream", side_effect=downstream):
            body, headers = self.event("human", "wamid.fallback")
            self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.assert_queued("wamid.fallback")
