"""Verify a configured real AI provider; no user data, database, or mail access.

Run as ``python -m app.check_ai`` in the backend container. Configuration and the
API key are read from the process environment, never from command arguments.
"""
import asyncio
import json
import sys

import httpx

from .config import Settings
from .services.ai import verify_provider


async def check() -> dict:
    settings = Settings.from_env()
    async with httpx.AsyncClient(follow_redirects=False) as client:
        return await verify_provider(settings, client)


def main() -> int:
    try:
        result = asyncio.run(check())
        if result.get("verified") is not True or result.get("proposal_valid") is not True:
            raise ValueError("Verification did not succeed.")
        # A strict output allowlist keeps provider replies and diagnostics out of
        # Cloud Run logs, even if the verifier gains more fields in the future.
        public = {name: result[name] for name in ("verified", "provider", "model", "proposal_valid")}
    except Exception:
        # Configuration errors may contain URLs or credentials. Never print the
        # exception, provider response, request headers, or a traceback.
        print(json.dumps({"verified": False, "proposal_valid": False}), file=sys.stderr)
        return 1
    print(json.dumps(public, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
