"""Run:  .venv/bin/python -m unittest discover -s backend/tests -t ."""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend import config
from backend.main import app
from backend.session_manager import manager


class DetectorKeyTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_open_when_no_key_is_configured(self):
        with mock.patch.object(config, "DETECTOR_KEY", ""):
            self.assertEqual(self.client.delete("/api/sessions/nope").status_code, 200)

    def test_key_required_when_configured(self):
        with mock.patch.object(config, "DETECTOR_KEY", "secret"):
            # A local path as url would let /media serve any file, so this must be refused without the key.
            r = self.client.post("/api/sessions", json={"source": "url", "url": "/proc/self/environ"})
            self.assertEqual(r.status_code, 401)
            wrong = self.client.delete("/api/sessions/nope", headers={"X-Detector-Key": "wrong"})
            self.assertEqual(wrong.status_code, 401)
            right = self.client.delete("/api/sessions/nope", headers={"X-Detector-Key": "secret"})
            self.assertEqual(right.status_code, 200)
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_local_files_only_from_demo_dir(self):
        # The portal route adds the key for anyone, so the path check is what stops reading files via /media.
        started = mock.Mock(summary=lambda: {"id": "s1"})
        with mock.patch.object(manager, "create", mock.AsyncMock(return_value=started)):
            for body in ({"source": "url", "url": "/etc/hosts"},
                         {"source": "url", "url": "backend/demo/../config.py"},
                         {"source": "url", "url": "https://twitch.tv/x", "chat_script": "/etc/hosts"}):
                self.assertEqual(self.client.post("/api/sessions", json=body).status_code, 400, body)
            ok = self.client.post("/api/sessions", json={"source": "url", "url": "backend/demo/demo_stream.mp4"})
            self.assertEqual(ok.status_code, 200)
            live = self.client.post("/api/sessions", json={"source": "url", "url": "https://twitch.tv/x"})
            self.assertEqual(live.status_code, 200)


if __name__ == "__main__":
    unittest.main()
