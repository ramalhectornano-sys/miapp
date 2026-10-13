"""Start the actual container script and probe local HTTP; no cloud calls."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import unittest
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


BACKEND = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "The deployed container uses POSIX shell.")
class ContainerStartupTests(unittest.TestCase):
    def test_start_script_uses_assigned_port_and_serves_health(self):
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        environment = os.environ.copy()
        environment.update({"PORT": str(port), "AI_PROVIDER": "demo",
            "CORS_ORIGINS": "[]", "AUTHORIZED_JOB_FEEDS": "[]",
            "MAIL_SEND_ENABLED": "false"})
        process = subprocess.Popen([str(BACKEND / "start.sh")], cwd=BACKEND,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.assertIsNone(process.poll(), "Container startup exited before serving HTTP.")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.load(response)["status"], "ok")
                    return
                except (URLError, TimeoutError):
                    time.sleep(0.05)
            self.fail("Container startup did not serve HTTP on its assigned PORT.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
