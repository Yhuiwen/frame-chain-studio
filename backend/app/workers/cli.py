import argparse
import asyncio
import logging
import signal

from sqlmodel import Session

from app.db import engine, init_db
from app.providers.config_loader import load_registry_from_env
from app.workers.generation_worker import GenerationWorker
from app.workers.settings import load_worker_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Frame Chain Studio generation Worker.")
    parser.add_argument("--once", action="store_true", help="Process one due batch and exit.")
    parser.add_argument("--until-idle", action="store_true", help="Process currently due work and exit.")
    return parser


async def main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    init_db()
    registry = load_registry_from_env()
    if not registry.list_capabilities():
        raise SystemExit("No providers configured. Set FCS_PROVIDER_CONFIG_FILE.")
    settings = load_worker_settings()

    def session_factory() -> Session:
        return Session(engine)

    worker = GenerationWorker(session_factory=session_factory, registry=registry, settings=settings)
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
