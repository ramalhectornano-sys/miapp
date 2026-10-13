import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.check_ai import main
from app.config import Settings


class CheckAiCommandTests(unittest.TestCase):
    def test_success_returns_only_public_verification_metadata(self):
        result = {
            "verified": True, "proposal_valid": True, "provider": "openai_compatible",
            "model": "openai/gpt-oss-20b", "reply": "PRIVATE provider text", "secret": "PRIVATE key",
        }
        output, errors = io.StringIO(), io.StringIO()
        with patch("app.check_ai.Settings.from_env", return_value=Settings()) as load_settings, \
                patch("app.check_ai.verify_provider", new=AsyncMock(return_value=result)) as verify, \
                redirect_stdout(output), redirect_stderr(errors):
            status = main()
        self.assertEqual(status, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(json.loads(output.getvalue()), {
            "verified": True, "proposal_valid": True, "provider": "openai_compatible", "model": "openai/gpt-oss-20b",
        })
        load_settings.assert_called_once_with()
        verify.assert_awaited_once()
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_demo_is_failure_and_cannot_claim_live_verification(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("app.check_ai.Settings.from_env", return_value=Settings()), \
                redirect_stdout(output), redirect_stderr(errors):
            status = main()
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(json.loads(errors.getvalue()), {"verified": False, "proposal_valid": False})

    def test_provider_failure_does_not_print_http_detail_or_exception(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("app.check_ai.Settings.from_env", return_value=Settings()), \
                patch("app.check_ai.verify_provider", new=AsyncMock(side_effect=HTTPException(502, "PRIVATE URL token"))), \
                redirect_stdout(output), redirect_stderr(errors):
            status = main()
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(json.loads(errors.getvalue()), {"verified": False, "proposal_valid": False})
        self.assertNotIn("PRIVATE", errors.getvalue())

    def test_configuration_failure_does_not_print_secret_diagnostic(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("app.check_ai.Settings.from_env", side_effect=ValueError("PRIVATE environment data")), \
                redirect_stdout(output), redirect_stderr(errors):
            status = main()
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(json.loads(errors.getvalue()), {"verified": False, "proposal_valid": False})
        self.assertNotIn("PRIVATE", errors.getvalue())

    def test_failed_verifier_result_never_becomes_success_exit(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("app.check_ai.Settings.from_env", return_value=Settings()), \
                patch("app.check_ai.verify_provider", new=AsyncMock(return_value={"verified": False, "proposal_valid": False})), \
                redirect_stdout(output), redirect_stderr(errors):
            status = main()
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(json.loads(errors.getvalue())["verified"], False)


if __name__ == "__main__":
    unittest.main()
