"""Take the README screenshots by walking through the app in a browser.

    uv run python scripts/take_screenshots.py https://<your-app>.up.railway.app

Asks for an access code without showing it; the code is not printed or
stored. One run uses one redemption of that code and, against the real
model, makes about 22 model calls with 10 candidates (roughly 3 cents).
Screenshots are written to docs/screenshots/. Every person in them is
fictional.
"""

import argparse
import getpass
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

# Generous: the real model takes a while for 10 CVs and the assessments.
SLOW = 240_000


def shoot(page: Page, out: Path, name: str) -> None:
    page.screenshot(path=out / f"{name}.png", full_page=True)
    print(f"  {name}.png")


def walk(page: Page, url: str, code: str, candidates: int, out: Path) -> None:
    page.goto(url)
    expect(page.get_by_label("Access code")).to_be_visible()
    shoot(page, out, "01-access-code")
    page.get_by_label("Access code").fill(code)
    page.get_by_role("button", name="Enter").click()
    expect(page.get_by_role("button", name="Generate vacancy")).to_be_visible()

    # Vacancy: choose, generate, review, submit.
    page.get_by_role("button", name="Generate vacancy").click()
    dialog = page.get_by_role("dialog", name="Generate vacancy")
    dialog.get_by_label("Vacancy title").fill("Cloud Engineer")
    dialog.get_by_label("Sector").select_option("IT and software")
    dialog.get_by_role("checkbox", name="senior").check()
    dialog.get_by_role("checkbox", name="hybrid").check()
    shoot(page, out, "02-generate-vacancy")
    dialog.get_by_role("button", name="Generate", exact=True).click()
    dialog.get_by_role("button", name="Your vacancy is ready to be viewed").click(
        timeout=SLOW
    )
    expect(page.get_by_role("button", name="Submit vacancy")).to_be_visible()
    shoot(page, out, "03-review-vacancy")
    page.get_by_role("button", name="Submit vacancy").click()
    page.get_by_role("button", name="Open vacancy").click()
    expect(page.get_by_role("list", name="Actions")).to_be_visible()

    # Candidates.
    page.get_by_role("button", name="Generate candidates").click()
    dialog = page.get_by_role("dialog", name="Generate candidates")
    dialog.get_by_label("Number of candidates").fill(str(candidates))
    dialog.get_by_role("button", name="Generate", exact=True).click()
    expect(dialog.get_by_role("status")).to_be_visible()
    shoot(page, out, "04-candidates-running")
    view = dialog.get_by_role("button", name=re.compile(r"^View candidates"))
    view.click(timeout=SLOW)
    expect(page.get_by_role("table")).to_be_visible()
    shoot(page, out, "05-candidates")
    page.get_by_role("table").get_by_role("row").nth(1).get_by_role("button").click()
    expect(page.get_by_role("heading", name="Employment")).to_be_visible()
    shoot(page, out, "06-cv")
    page.get_by_role("button", name="Back to candidates").click()
    page.get_by_role("button", name="Back to vacancy").click()

    # Selection script, as proposed.
    page.get_by_role("button", name="Generate selection script").click()
    script = page.get_by_role("dialog", name="Selection script")
    expect(script.get_by_role("group", name="Item 1")).to_be_visible(timeout=SLOW)
    shoot(page, out, "07-selection-script")
    script.get_by_role("button", name="Submit").click()
    expect(script).to_have_count(0)

    # Lists.
    page.get_by_role("button", name="Generate long-list").click()
    expect(
        page.get_by_role("heading", name=re.compile("^Long list for"))
    ).to_be_visible()
    expect(page.locator("li.card").first).to_contain_text(
        "Found in the CV: ", timeout=SLOW
    )
    page.wait_for_timeout(1_000)
    shoot(page, out, "08-long-list")
    page.locator("li.card").first.get_by_role("button", name="Show evidence").click()
    expect(page.get_by_role("heading", name="Evidence from the CV")).to_be_visible()
    shoot(page, out, "09-evidence")
    page.get_by_role("button", name="Back to list").click()
    page.get_by_role("button", name="Short list", exact=True).click()
    expect(
        page.get_by_role("heading", name=re.compile("^Short list for"))
    ).to_be_visible()
    shoot(page, out, "10-short-list")

    # Interview questions.
    page.get_by_role("button", name="Generate interview questions").click()
    page.get_by_role("button", name="Generate interview questions").click()
    core = page.get_by_role("region", name="Core questions, for every candidate")
    expect(core).to_be_visible(timeout=SLOW)
    shoot(page, out, "11-interview-questions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url")
    parser.add_argument("--candidates", type=int, default=10)
    parser.add_argument("--out", default="docs/screenshots")
    args = parser.parse_args()

    code = getpass.getpass("Access code (not shown): ").strip()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            walk(page, args.url.rstrip("/"), code, args.candidates, out)
        finally:
            browser.close()
    print(f"Screenshots written to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
