import argparse
import asyncio
import logging
import os
import secrets
import signal
import socket

from sqlmodel import Session

from app.core.config import get_settings
from app.db import engine, init_db
from app.workers.render_worker import RenderWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Frame Chain Studio render Worker.")
    parser.add_argument("--once", action="store_true", help="Process one due render and exit.")
    parser.add_argument("--until-idle", action="store_true", help="Process currently due renders and exit.")
    return parser


async def main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    init_db()
    settings = get_settings()
    worker_id = os.getenv("FCS_WORKER_ID") or f"render-{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(4)}"

    def session_factory() -> Session:
        return Session(engine)

    worker = RenderWorker(
        session_factory=session_factory,
        worker_id=worker_id,
        lease_seconds=settings.render_worker_lease_seconds,
        poll_interval_seconds=settings.worker_heartbeat_seconds,
    )
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signame):
            try:
                loop.add_signal_handler(getattr(signal, signame), worker.stop)
            except (NotImplementedError, RuntimeError):
                pass
    if args.once:
        await worker.run_once()
        return
    if args.until_idle:
        await worker.run_until_idle()
        return
    await worker.run_forever()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
