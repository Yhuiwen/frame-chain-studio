import argparse
import asyncio
import logging
import signal
from datetime import timedelta

from sqlmodel import Session, select

from app.core.config import get_settings
from app.db import engine, init_db
from app.models.entities import GenerationTaskResult, utcnow
from app.workers.result_processing_service import load_result_worker_settings
from app.workers.result_worker import ResultWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Frame Chain Studio result processing Worker.")
    parser.add_argument("--once", action="store_true", help="Process one due batch and exit.")
    parser.add_argument("--until-idle", action="store_true", help="Process currently due work and exit.")
    parser.add_argument("--cleanup-temp", action="store_true", help="Remove stale unreferenced result temp files and exit.")
    return parser


def cleanup_temp_files() -> int:
    settings = get_settings()
    temp_root = (settings.storage_dir / "temp" / "results").resolve()
    if not temp_root.exists():
        return 0
    cutoff = utcnow().replace(tzinfo=None) - timedelta(hours=settings.result_temp_file_ttl_hours)
    with Session(engine) as session:
        referenced = {
            item.temporary_relative_path
            for item in session.exec(select(GenerationTaskResult)).all()
            if item.temporary_relative_path
        }
    deleted = 0
    for path in temp_root.glob("*.part"):
        resolved = path.resolve()
        if temp_root not in resolved.parents or path.is_symlink():
            continue
        relative = resolved.relative_to(settings.storage_dir.resolve()).as_posix()
        if relative in referenced:
            continue
        modified = path.stat().st_mtime
        if modified <= cutoff.timestamp():
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted


async def main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    init_db()
    if args.cleanup_temp:
        deleted = cleanup_temp_files()
        logging.info("deleted stale result temp files count=%s", deleted)
        return
    settings = load_result_worker_settings()

    def session_factory() -> Session:
        return Session(engine)

    worker = ResultWorker(session_factory=session_factory, settings=settings)
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
