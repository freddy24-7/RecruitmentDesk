"""The flow a visitor follows, in a real browser: gate, generate, review, submit."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_CODE

pytestmark = pytest.mark.e2e


def enter(page: Page, app_url: str) -> None:
    page.goto(app_url)
    page.get_by_label("Access code").fill(E2E_CODE.lower())
    page.get_by_role("button", name="Enter").click()
    expect(page.get_by_role("button", name="Generate vacancy")).to_be_visible()


def generate(page: Page, title: str = "Cloud Engineer") -> None:
    page.get_by_role("button", name="Generate vacancy").click()
    dialog = page.get_by_role("dialog", name="Generate vacancy")
    dialog.get_by_label("Vacancy title").fill(title)
    dialog.get_by_label("Sector").select_option("Finance")
    dialog.get_by_role("checkbox", name="senior").check()
    dialog.get_by_role("checkbox", name="hybrid").check()
    dialog.get_by_role("button", name="Generate", exact=True).click()


def test_nothing_is_reachable_without_a_code(page: Page, app_url: str) -> None:
    page.goto(app_url)

    expect(page.get_by_label("Access code")).to_be_visible()
    expect(page.get_by_role("button", name="Generate vacancy")).to_have_count(0)
    assert page.request.get(f"{app_url}/api/vacancies").status == 401

    page.get_by_label("Access code").fill("ZZZZZ")
    page.get_by_role("button", name="Enter").click()

    expect(page.get_by_role("alert")).to_have_text(
        "That code is not valid. Check the code and try again."
    )


def test_generate_review_edit_and_submit(page: Page, app_url: str) -> None:
    enter(page, app_url)
    expect(page.get_by_text("Nothing here yet")).to_be_visible()

    generate(page)

    # A spinner with a status text while the job runs.
    dialog = page.get_by_role("dialog", name="Generate vacancy")
    expect(dialog.get_by_role("status")).to_have_text("Writing the vacancy…")
    ready = dialog.get_by_role("button", name="Your vacancy is ready to be viewed")
    expect(ready).to_be_visible(timeout=15_000)
    ready.click()

    # Review: each section in an editable field.
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_label("Title", exact=True)).to_have_value("Cloud Engineer")
    expect(page.get_by_text("Version 1, as generated")).to_be_visible()
    save = page.get_by_role("button", name="Save changes")
    expect(save).to_be_disabled()

    page.get_by_label("The role").fill("You lead the platform team.")
    page.get_by_label("Responsibilities").fill("Lead the team\n\nMentor engineers")
    save.click()
    expect(page.get_by_text("Version 2, edited by you")).to_be_visible()
    expect(page.get_by_label("Responsibilities")).to_have_value(
        "Lead the team\nMentor engineers"
    )

    page.get_by_role("button", name="Submit vacancy").click()

    # It moved to the submitted vacancies.
    expect(page.get_by_role("heading", name="Submitted vacancies")).to_be_visible()
    expect(page.get_by_role("heading", name="Cloud Engineer")).to_be_visible()
    expect(page.get_by_text(re.compile(r"Submitted on \d+ \w+ \d{4}"))).to_be_visible()

    page.get_by_role("button", name="Open vacancy").click()
    expect(page.get_by_text("You lead the platform team.")).to_be_visible()
    # Actions whose prerequisites are missing are visible, disabled, with a reason.
    long_list = page.get_by_role("button", name="Generate long-list")
    expect(long_list).to_have_attribute("aria-disabled", "true")
    expect(long_list).to_have_accessible_description(
        "Generate candidates and a selection script first."
    )

    # A reload keeps the session and the data, and does not ask for the code.
    page.reload()
    expect(page.get_by_role("button", name="Generate vacancy")).to_be_visible()
    expect(page.get_by_label("Access code")).to_have_count(0)
    page.get_by_role("button", name="Submitted vacancies").click()
    expect(page.get_by_role("heading", name="Cloud Engineer")).to_be_visible()


def test_the_dialog_can_be_closed_while_the_job_runs(page: Page, app_url: str) -> None:
    enter(page, app_url)
    generate(page, title="Risk Analyst")
    dialog = page.get_by_role("dialog", name="Generate vacancy")
    expect(dialog.get_by_role("status")).to_be_visible()

    page.keyboard.press("Escape")

    expect(dialog).to_have_count(0)
    # Focus goes back to where the dialog was opened from.
    expect(page.get_by_role("button", name="Generate vacancy")).to_be_focused()
    # The job was not lost: the page follows it and shows the result.
    expect(page.get_by_role("heading", name="Risk Analyst")).to_be_visible()
    expect(
        page.get_by_role("button", name="Your vacancy is ready to be viewed")
    ).to_be_visible(timeout=15_000)


def test_cancel_vacancy_needs_confirmation_and_then_deletes(
    page: Page, app_url: str
) -> None:
    enter(page, app_url)
    generate(page)
    page.get_by_role("dialog").get_by_role(
        "button", name="Your vacancy is ready to be viewed"
    ).click(timeout=15_000)

    page.get_by_role("button", name="Cancel vacancy").click()
    confirmation = page.get_by_role("alertdialog", name="Cancel this vacancy?")
    # The dialog states exactly what will be deleted.
    expect(confirmation).to_contain_text("the vacancy “Cloud Engineer”")
    expect(confirmation).to_contain_text("its generated text and all your edits")

    confirmation.get_by_role("button", name="Keep vacancy").click()
    expect(confirmation).to_have_count(0)
    expect(page.get_by_label("Title", exact=True)).to_have_value("Cloud Engineer")

    page.get_by_role("button", name="Cancel vacancy").click()
    page.get_by_role("button", name="Delete vacancy").click()

    expect(page.get_by_text("Nothing here yet")).to_be_visible()
    page.get_by_role("button", name="Submitted vacancies").click()
    expect(page.get_by_text("No vacancies have yet been submitted")).to_be_visible()
    assert page.request.get(f"{app_url}/api/vacancies").json() == []
