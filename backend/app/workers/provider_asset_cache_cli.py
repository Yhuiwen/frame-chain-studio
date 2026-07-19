import argparse
import logging
from datetime import timedelta

from sqlmodel import Session

from app.db import engine, init_db
from app.models.entities import utcnow
from app.services.provider_asset_cache import cleanup_expired_provider_asset_cache


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Provider upload asset cache.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    cleanup = subcommands.add_parser("cleanup", help="Delete expired Provider asset cache rows.")
    cleanup.add_argument("--batch-size", type=int, default=500)
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument(
        "--older-than",
        type=float,
        default=None,
        help="Also delete non-expiring rows not updated for this many hours.",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    init_db()
    if args.command == "cleanup":
        older_than = timedelta(hours=args.older_than) if args.older_than is not None else None
        with Session(engine) as session:
            count = cleanup_expired_provider_asset_cache(
                session,
                now=utcnow(),
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                older_than=older_than,
            )
        logging.info("provider asset cache cleanup complete count=%s dry_run=%s", count, args.dry_run)


if __name__ == "__main__":
    main()
