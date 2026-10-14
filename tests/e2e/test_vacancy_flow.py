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


def submitted_vacancy(page: Page, app_url: str) -> None:
    """Enter, generate a vacancy, submit it and open it."""
    enter(page, app_url)
    generate(page)
    page.get_by_role("dialog").get_by_role(
        "button", name="Your vacancy is ready to be viewed"
    ).click(timeout=15_000)
    page.get_by_role("button", name="Submit vacancy").click()
    page.get_by_role("button", name="Open vacancy").click()
    expect(page.get_by_role("list", name="Actions")).to_be_visible()


def test_generate_candidates_and_read_a_cv(page: Page, app_url: str) -> None:
    submitted_vacancy(page, app_url)

    page.get_by_role("button", name="Generate candidates").click()
    dialog = page.get_by_role("dialog", name="Generate candidates")
    dialog.get_by_label("Number of candidates").fill("101")
    dialog.get_by_role("button", name="Generate", exact=True).click()
    # More than 100 is refused in the form; nothing starts.
    expect(dialog.get_by_label("Number of candidates")).to_have_attribute(
        "aria-invalid", "true"
    )

    dialog.get_by_label("Number of candidates").fill("6")
    dialog.get_by_role("button", name="Generate", exact=True).click()

    # Progress as "x of N created".
    expect(dialog.get_by_role("status")).to_have_text(
        re.compile(r"\d of 6 candidates created")
    )
    view = dialog.get_by_role("button", name="View candidates (6)")
    expect(view).to_be_visible(timeout=30_000)
    view.click()

    # A page of its own for this vacancy, labelled as synthetic data.
    expect(
        page.get_by_role("heading", name="Candidates for Cloud Engineer")
    ).to_be_visible()
    expect(
        page.get_by_text("Synthetic data. These people do not exist")
    ).to_be_visible()
    rows = page.get_by_role("table").get_by_role("row")
    expect(rows).to_have_count(7)  # the header and six candidates
    expect(page.get_by_text("@example.com")).to_have_count(0)  # shown on the CV only

    # Sorting changes the order; searching narrows the list.
    first_name = rows.nth(1).get_by_role("button").inner_text()
    page.get_by_role("button", name="Name", exact=True).click()
    expect(page.get_by_role("columnheader", name="Name")).to_have_attribute(
        "aria-sort", "ascending"
    )
    page.get_by_label("Search candidates").fill(first_name)
    expect(rows).to_have_count(2)
    expect(page.get_by_role("status")).to_have_text("Showing 1 of 6 candidates")

    # The CV detail view.
    page.get_by_role("button", name=first_name).click()
    expect(page.get_by_role("heading", name=first_name, level=2)).to_be_visible()
    expect(
        page.get_by_text("Synthetic data. This person does not exist.")
    ).to_be_visible()
    expect(
        page.get_by_text(re.compile(r"@example\.com · \+44 7700 900\d{3}"))
    ).to_be_visible()
    expect(page.get_by_role("heading", name="Employment")).to_be_visible()
    expect(
        page.get_by_text(re.compile(r"\w{3} \d{4} to (present|\w{3} \d{4})")).first
    ).to_be_visible()

    # Back at the vacancy, generating again says what it replaces.
    page.get_by_role("button", name="Back to candidates").click()
    page.get_by_role("button", name="Back to vacancy").click()
    page.get_by_role("button", name="Generate candidates").click()
    expect(page.get_by_role("dialog").get_by_role("note")).to_contain_text(
        "This replaces the 6 existing candidates of this vacancy."
    )
    expect(
        page.get_by_role("dialog").get_by_role("button", name="Replace candidates")
    ).to_be_visible()


def test_propose_edit_and_save_a_selection_script(page: Page, app_url: str) -> None:
    submitted_vacancy(page, app_url)

    page.get_by_role("button", name="Generate selection script").click()
    dialog = page.get_by_role("dialog", name="Selection script")
    # The dialog opens with a proposal from the model.
    expect(dialog.get_by_role("status")).to_have_text(
        "Reading the vacancy and proposing criteria…"
    )
    first = dialog.get_by_role("group", name="Item 1")
    expect(first.get_by_label("Keywords")).to_have_value(
        "Microsoft Azure, AWS", timeout=15_000
    )
    expect(first.get_by_label("Years")).to_have_value("3")
    expect(first.get_by_label("Requirement")).to_have_value("hard")
    expect(first).to_contain_text(
        "From the required qualifications: “Experience with Microsoft Azure”"
    )
    expect(dialog.get_by_role("group", name="Item 4")).to_contain_text(
        "not found in the vacancy text"
    )

    # Cancel saves nothing.
    first.get_by_label("Years").fill("9")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_text("Selection script ready")).to_have_count(0)
    assert (
        page.request.get(f"{app_url}/api/vacancies").json()[0]["script"]["exists"]
        is False
    )

    # Reopening shows the same proposal again, without asking the model twice.
    page.get_by_role("button", name="Generate selection script").click()
    first = dialog.get_by_role("group", name="Item 1")
    expect(first.get_by_label("Years")).to_have_value("3")

    # Edit, flip, remove, add, and submit.
    first.get_by_label("Keywords").fill("Microsoft Azure, AWS, GCP")
    first.get_by_label("Years").fill("5")
    dialog.get_by_role("group", name="Item 2").get_by_label(
        "Requirement"
    ).select_option("soft")
    # Item 5 was proposed as hard but quoted from the responsibilities.
    expect(dialog.get_by_role("group", name="Item 5")).to_contain_text(
        "Proposed as hard, made soft: it is not in the required qualifications."
    )
    dialog.get_by_role("button", name="Remove item 5").click()
    dialog.get_by_role("button", name="Remove item 4").click()
    dialog.get_by_role("button", name="Add item").click()
    dialog.get_by_role("group", name="Item 4").get_by_label("Keywords").fill("Python")
    dialog.get_by_role("button", name="Submit").click()

    expect(dialog).to_have_count(0)
    expect(page.get_by_text("Selection script ready (4 items).")).to_be_visible()

    # The saved script is what opens next time.
    page.get_by_role("button", name="Generate selection script").click()
    expect(dialog).to_contain_text("The saved script for this vacancy.")
    expect(
        dialog.get_by_role("group", name="Item 1").get_by_label("Keywords")
    ).to_have_value("Microsoft Azure, AWS, GCP")
    expect(
        dialog.get_by_role("group", name="Item 4").get_by_label("Keywords")
    ).to_have_value("Python")
    page.keyboard.press("Escape")

    # Editing the vacancy marks the script as out of date.
    page.get_by_role("button", name="Edit vacancy").click()
    page.get_by_label("The role").fill("A different role altogether.")
    page.get_by_role("button", name="Save changes").click()
    page.get_by_role("button", name="Stop editing").click()
    expect(page.get_by_text("Selection script out of date.")).to_be_visible()


def test_generate_the_lists_and_read_the_evidence(page: Page, app_url: str) -> None:
    submitted_vacancy(page, app_url)
    notice = page.get_by_text("Suggestions to support a recruiter. A person decides.")

    # Before candidates and a script exist, the list actions say what is missing.
    long_list = page.get_by_role("button", name="Generate long-list")
    expect(long_list).to_have_accessible_description(
        "Generate candidates and a selection script first."
    )

    page.get_by_role("button", name="Generate candidates").click()
    dialog = page.get_by_role("dialog", name="Generate candidates")
    dialog.get_by_label("Number of candidates").fill("10")
    dialog.get_by_role("button", name="Generate", exact=True).click()
    expect(dialog.get_by_role("button", name="View candidates (10)")).to_be_visible(
        timeout=40_000
    )
    page.keyboard.press("Escape")
    expect(long_list).to_have_accessible_description(
        "Generate a selection script first."
    )

    page.get_by_role("button", name="Generate selection script").click()
    script = page.get_by_role("dialog", name="Selection script")
    expect(script.get_by_role("group", name="Item 1")).to_be_visible(timeout=15_000)
    script.get_by_role("button", name="Submit").click()
    expect(page.get_by_text("Selection script ready (5 items).")).to_be_visible()

    # Now the lists can be made. One run produces both.
    expect(long_list).not_to_have_attribute("aria-disabled", "true")
    long_list.click()
    expect(
        page.get_by_role("heading", name="Long list for Cloud Engineer")
    ).to_be_visible()
    expect(notice).to_be_visible()
    expect(page.get_by_role("status")).to_have_text(
        re.compile(r"\d of 6 candidates assessed")
    )

    # 10 candidates: a long list of 3 and a short list of 1.
    expect(page.get_by_role("heading", level=3)).to_have_count(3, timeout=40_000)
    first = page.get_by_role("heading", level=3).first
    expect(first).to_have_text(re.compile(r"^1\. \S+"))
    top = page.locator("li.card").first
    # Name, phone, email, and the paragraph explaining why.
    expect(top).to_contain_text(re.compile(r"\+44 7700 900\d{3} · \S+@example\.com"))
    expect(top).to_contain_text("Found in the CV: ")
    expect(top).to_contain_text("years)")
    expect(notice).to_be_visible()

    # The evidence: where in the CV the claims come from.
    top.get_by_role("button", name="Show evidence").click()
    expect(page.get_by_role("heading", name="Requirements")).to_be_visible()
    expect(
        page.get_by_role("row", name=re.compile("Microsoft Azure or AWS"))
    ).to_contain_text("Met")
    expect(page.get_by_role("heading", name="Evidence from the CV")).to_be_visible()
    expect(page.get_by_text(re.compile(r"Job 1: .+: “")).first).to_be_visible()
    expect(notice).to_be_visible()

    # The short list is the top of the long list.
    page.get_by_role("button", name="Back to list").click()
    page.get_by_role("button", name="Short list", exact=True).click()
    expect(
        page.get_by_role("heading", name="Short list for Cloud Engineer")
    ).to_be_visible()
    expect(page.get_by_role("heading", level=3)).to_have_count(1)
    expect(page.get_by_role("heading", level=3)).to_have_text(first.inner_text())
    expect(notice).to_be_visible()

    # Back on the vacancy the lists are there to open again.
    page.get_by_role("button", name="Back to vacancy").click()
    expect(page.get_by_role("button", name="View long list (3)")).to_be_visible()
    expect(page.get_by_role("button", name="View short list (1)")).to_be_visible()
