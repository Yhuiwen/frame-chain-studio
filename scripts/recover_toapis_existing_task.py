from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.providers.toapis import ToApisProvider  # noqa: E402
from app.providers.models import RemoteJobStatus  # noqa: E402


async def run(remote_task_id: str) -> int:
    key = os.getenv("TOAPIS_API_KEY")
    if not key:
        print("TOAPIS_API_KEY_REQUIRED", file=sys.stderr)
        return 1
    provider = ToApisProvider(key)
    try:
        result = await provider.get_job(f"image:{remote_task_id}")
    finally:
        await provider.aclose()
    if result.normalized_status != RemoteJobStatus.SUCCEEDED or len(result.result_urls) != 1:
        print("EXISTING_REMOTE_TASK_RESULT_NOT_READY", file=sys.stderr)
        return 1
    print(json.dumps({"result_url": result.result_urls[0].url, "remote_gets": 1}, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-remote-task-id", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.existing_remote_task_id))


if __name__ == "__main__":
    raise SystemExit(main())
