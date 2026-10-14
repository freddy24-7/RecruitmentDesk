"""Evaluate the lists against the planted ground truth, and write a report (PRD 10).

    uv run python scripts/evaluate_lists.py --services fake
    uv run python scripts/evaluate_lists.py --services mistral --vacancies 4

With the fake model this checks the evaluation code itself: the fake answers
from the facts, so the scores must come out right. With `mistral` it measures
the real model and costs money: the script states the expected number of
calls and asks before it starts (or pass --yes).

It works in a database of its own (`<name>_eval`), so the test suite, which
empties the test database, cannot wipe an evaluation half-way. Reports go to
reports/.
"""

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATABASE = (
    "postgresql+asyncpg://recruitdesk:recruitdesk@localhost:5433/recruitdesk"
)


def expected_calls(
    vacancies: int, candidates: int, repeats: int, name_swaps: int
) -> int:
    """Roughly how many model calls a run makes (CV retries come on top)."""
    long = min(10, max(1, (candidates * 30 + 50) // 100))
    assessed = min(candidates, 2 * long)
    short = min(4, max(1, (candidates * 10 + 50) // 100))
    # Interview questions: one core set and one follow-up set per short-listed
    # candidate.
    questions = 1 + short
    per_vacancy = (
        1 + 1 + candidates + 1 + repeats * assessed + 2 * name_swaps + questions
    )
    return vacancies * per_vacancy


async def _create_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": parsed.database},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    finally:
        await admin.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--services", choices=["fake", "mistral"], required=True)
    parser.add_argument("--vacancies", type=int, default=4)
    parser.add_argument("--candidates", type=int, default=20)
    parser.add_argument(
        "--repeats", type=int, default=3, help="screening runs per vacancy"
    )
    parser.add_argument("--name-swaps", type=int, default=2)
    parser.add_argument(
        "--yes", action="store_true", help="do not ask before real calls"
    )
    parser.add_argument("--out", default=str(REPO_ROOT / "reports"))
    args = parser.parse_args(argv)

    calls = expected_calls(
        args.vacancies, args.candidates, args.repeats, args.name_swaps
    )
    if args.services == "mistral" and not args.yes:
        answer = input(f"About {calls} real model calls. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("Stopped.")
            return 1

    # Its own database, chosen before the application reads its settings.
    base = make_url(os.environ.get("DATABASE_URL") or LOCAL_DATABASE)
    if base.database is None:
        raise SystemExit("DATABASE_URL has no database name")
    eval_url = base.set(database=f"{base.database.removesuffix('_eval')}_eval")
    os.environ["DATABASE_URL"] = eval_url.render_as_string(hide_password=False)
    os.environ["LLM_PROVIDER"] = args.services
    os.environ["FRONTEND_DIST"] = "does-not-exist"

    asyncio.run(_create_database(os.environ["DATABASE_URL"]))
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=os.environ,
        check=True,
        capture_output=True,
    )

    from app.evaluation.run import Report, evaluate, to_markdown
    from app.main import create_app

    async def run() -> Report:
        app = create_app()
        try:
            return await evaluate(
                app,
                args.services,
                args.vacancies,
                args.candidates,
                args.repeats,
                args.name_swaps,
            )
        finally:
            await app.state.job_runner.shutdown()

    report = asyncio.run(run())
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"evaluation-{stamp}-{args.services}"
    (out / f"{name}.md").write_text(to_markdown(report))
    (out / f"{name}.json").write_text(report.to_json())
    print(f"Report written to {out / name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
