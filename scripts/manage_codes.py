"""Manage access codes from the command line (PRD F0). There is no admin page.

    uv run python scripts/manage_codes.py create --count 10
    uv run python scripts/manage_codes.py status
    uv run python scripts/manage_codes.py extend --label c03 --uses 20
    uv run python scripts/manage_codes.py disable --label c03

`create` prints the new codes ONCE to the terminal and writes no file. Store
them in a password manager. Run it only on the developer's machine, never in
CI. The script acts on the database in DATABASE_URL and needs the same
ACCESS_CODE_PEPPER as the running app.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.access import admin
from app.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage RecruitDesk access codes.")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create codes and print them once")
    create.add_argument("--count", type=int, required=True)
    create.add_argument("--max-uses", type=int, default=20)

    commands.add_parser("status", help="show uses per label (never prints codes)")

    extend = commands.add_parser("extend", help="add redemptions to a code")
    extend.add_argument("--label", required=True)
    extend.add_argument("--uses", type=int, required=True)

    disable = commands.add_parser("disable", help="block a code immediately")
    disable.add_argument("--label", required=True)

    return parser


def format_status(rows: list[admin.CodeStatus]) -> str:
    if not rows:
        return "No access codes exist yet. Run: manage_codes.py create --count 10"
    lines = [f"{'label':<8}{'uses':>6}{'limit':>7}{'left':>6}  {'state':<9}last used"]
    for row in rows:
        last_used = (
            row.last_used_at.strftime("%Y-%m-%d %H:%M UTC")
            if row.last_used_at
            else "never"
        )
        state = "disabled" if row.disabled else "active"
        lines.append(
            f"{row.label:<8}{row.uses:>6}{row.max_uses:>7}{row.remaining:>6}"
            f"  {state:<9}{last_used}"
        )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    # Its own short-lived engine: this is a one-off command, not the web app.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "create":
                pepper = settings.access_code_pepper.get_secret_value()
                created = await admin.create_codes(
                    session, args.count, pepper, datetime.now(UTC), args.max_uses
                )
                await session.commit()
                print("New access codes. They are shown only once: store them now.")
                for new in created:
                    print(f"{new.label}  {new.code}")
            elif args.command == "status":
                print(format_status(await admin.list_status(session)))
            elif args.command == "extend":
                status = await admin.extend_code(session, args.label, args.uses)
                await session.commit()
                print(
                    f"{status.label}: limit is now {status.max_uses}, "
                    f"{status.remaining} uses left."
                )
            elif args.command == "disable":
                await admin.disable_code(session, args.label)
                await session.commit()
                print(f"{args.label}: disabled.")
    except admin.UnknownLabelError as error:
        print(f"No code with label {error}.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Not possible: {error}.", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
