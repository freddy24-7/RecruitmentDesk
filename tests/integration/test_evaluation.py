"""The evaluation code itself, checked with fakes (CLAUDE.md, Testing).

A fake that answers from the ground truth must score perfectly. A fake that
answers badly on purpose must be caught: if the evaluation reports good
numbers for a bad model, the numbers mean nothing.
"""

import json

from fastapi import FastAPI

from app.evaluation.run import (
    SCENARIOS,
    VacancyResult,
    _jaccard,
    _quality,
    evaluate,
    to_markdown,
)
from app.llm.base import LlmRequest
from app.llm.fake import FakeLlm, fake_assessment
from scripts.evaluate_lists import expected_calls


async def run(
    app: FastAPI, vacancies: int = 1, candidates: int = 10
) -> list[VacancyResult]:
    report = await evaluate(
        app, "fake", vacancies=vacancies, candidates=candidates, repeats=2, name_swaps=1
    )
    assert "Evaluation report (fake)" in to_markdown(report)
    json.loads(report.to_json())
    return report.results


async def test_a_fake_that_answers_from_the_ground_truth_scores_perfectly(
    app: FastAPI, llm: FakeLlm
) -> None:
    results = await run(app, vacancies=2)

    assert [r.scenario["title"] for r in results] == [s["title"] for s in SCENARIOS[:2]]
    for result in results:
        assert not result.errors
        assert result.combined.short_precision == 1.0
        assert result.combined.long_recall == 1.0
        assert result.unflagged_hard_misses == 0
        assert result.claims_made > 0
        assert result.claims_supported == result.claims_made
        assert result.short_overlap == [1.0]
        assert result.long_overlap == [1.0]
        assert result.name_swap
        for swap in result.name_swap:
            assert swap["input_identical"]
            assert not swap["names_in_input"]
            assert swap["difference"] == 0
    # The run makes as many model calls as the script announces before
    # asking for confirmation.
    assert len(llm.requests) == expected_calls(2, 10, 2, 1)


async def test_a_model_that_ranks_badly_and_invents_claims_is_caught(
    app: FastAPI, llm: FakeLlm
) -> None:
    def bad_assessment(request: LlmRequest) -> str:
        answer = json.loads(fake_assessment(request))
        # The best candidates get the lowest scores, and every answer claims
        # a keyword that no CV contains.
        answer["fit_score"] = 100 - answer["fit_score"]
        answer["found"].append({"keyword": "Invented Skill", "years": 5})
        return json.dumps(answer)

    llm.responders["assessment"] = bad_assessment

    # With 20 candidates more people meet the hard requirements than fit on
    # the long list, so the scores decide the order. (With 10, only the
    # strong matches meet them, and the hard requirements alone keep them
    # on top, whatever the model says.)
    [result] = await run(app, candidates=20)

    assert result.model_only.short_precision < 1.0
    assert result.claims_supported < result.claims_made
    # The facts computed by code are unaffected by the model.
    assert result.facts_only.short_precision == 1.0
    # Hard requirements are applied by code, whatever the model says.
    assert result.unflagged_hard_misses == 0


def test_list_quality_against_the_planted_matches() -> None:
    truth = {"a": "strong", "b": "strong", "c": "partial", "d": "weak"}

    good = _quality(["a", "b", "c"], truth, short_size=2)
    bad = _quality(["c", "a", "d"], truth, short_size=2)

    assert (good.short_precision, good.long_recall) == (1.0, 1.0)
    assert (bad.short_precision, bad.long_recall) == (0.5, 0.5)
    assert bad.short == ["partial", "strong"]


def test_overlap_of_repeated_lists() -> None:
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0
    assert _jaccard({"a", "b"}, {"b", "c"}) == 0.333
    assert _jaccard(set(), set()) == 1.0


def test_expected_calls_for_the_full_run() -> None:
    # Per vacancy: vacancy, profile, 20 CVs, script, 3 runs of 12
    # assessments, 2 name swaps of 2 calls.
    assert expected_calls(4, 20, 3, 2) == 4 * (1 + 1 + 20 + 1 + 36 + 4)
    # 5 candidates give a long list of 2, so 4 are assessed per run.
    assert expected_calls(1, 5, 1, 0) == 1 + 1 + 5 + 1 + 4
