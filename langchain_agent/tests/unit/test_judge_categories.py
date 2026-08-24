"""Schema-level tests for the categorical hallucination tier (issue #6).

Covers Pydantic validation of ``FlaggedClaim`` / ``HallucinationCategory``
and the legacy-string coercion path that lets older judge outputs continue
to validate.
"""

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from judge import (
    RETRY_ELIGIBLE_CATEGORIES,
    FlaggedClaim,
    HallucinationCategory,
    JudgmentResult,
    _format_docs_for_prompt,
)


@pytest.mark.unit
class TestFlaggedClaimValidation:
    def test_accepts_all_four_categories(self):
        for cat in (
            "fabrication",
            "cross_product_bleed",
            "inference",
            "overreach",
        ):
            fc = FlaggedClaim(claim="x", category=cat)
            assert fc.category.value == cat

    def test_rejects_unknown_category(self):
        with pytest.raises(ValidationError):
            FlaggedClaim(claim="x", category="speculation")

    def test_retry_eligible_set_is_exactly_the_dangerous_two(self):
        assert RETRY_ELIGIBLE_CATEGORIES == frozenset(
            {
                HallucinationCategory.fabrication,
                HallucinationCategory.cross_product_bleed,
            }
        )


@pytest.mark.unit
class TestJudgmentResultHallucinationsField:
    def _kwargs(self, hallucinations):
        return dict(
            verdict="tied",
            pairwise_justification="ok",
            faithfulness=0.9,
            answer_relevance=0.9,
            citation_accuracy=1.0,
            context_utilization=0.7,
            hallucinations=hallucinations,
        )

    def test_accepts_list_of_dicts(self):
        result = JudgmentResult(
            **self._kwargs(
                [
                    {
                        "claim": "Made in USA",
                        "category": "fabrication",
                        "reasoning": "no FACTS support",
                    },
                    {"claim": "best in class", "category": "overreach"},
                ]
            )
        )
        assert len(result.hallucinations) == 2
        assert result.hallucinations[0].category == HallucinationCategory.fabrication
        assert result.hallucinations[1].category == HallucinationCategory.overreach

    def test_legacy_list_of_strings_coerces_to_fabrication(self):
        result = JudgmentResult(**self._kwargs(["something fishy", "another"]))
        assert len(result.hallucinations) == 2
        for fc in result.hallucinations:
            assert fc.category == HallucinationCategory.fabrication

    def test_legacy_single_string_coerces(self):
        result = JudgmentResult(**self._kwargs("only one claim"))
        assert len(result.hallucinations) == 1
        assert result.hallucinations[0].claim == "only one claim"
        assert result.hallucinations[0].category == HallucinationCategory.fabrication

    def test_none_becomes_empty_list(self):
        result = JudgmentResult(**self._kwargs(None))
        assert result.hallucinations == []

    def test_empty_string_in_legacy_list_is_dropped(self):
        result = JudgmentResult(**self._kwargs(["", "real claim", "  "]))
        assert len(result.hallucinations) == 1
        assert result.hallucinations[0].claim == "real claim"

    def test_model_dump_round_trips_through_pydantic(self):
        original = JudgmentResult(
            **self._kwargs(
                [
                    {"claim": "x", "category": "inference", "reasoning": "para"},
                ]
            )
        )
        dumped = original.model_dump()
        # The dict form should be re-parseable (this is how the API surface
        # crosses the llm_judge_node → PipelineSummaryEvent boundary).
        round_tripped = JudgmentResult(**dumped)
        assert round_tripped.hallucinations[0].category == HallucinationCategory.inference


@pytest.mark.unit
class TestFormatDocsForPrompt:
    def _doc(self, text, title="Product", product_id="ID1"):
        return Document(page_content=text, metadata={"title": title, "product_id": product_id})

    def test_default_limit_includes_tail_attributes(self):
        """Regression for issue #81: old 360-char default truncated 'Made in USA' claims
        at ~750 chars into ESCI product descriptions, causing false-positive fabrication flags."""
        long_text = (
            "Nylabone 3 Pack Of Puppy Chew Chicken Flavored Teething Bones "
            "Developing proper chewing habits is one of the best lessons your young puppy "
            "can learn. Start them down the right path now with a chew they'll love! "
            "These bones are made of softer materials for puppies. They help puppies "
            "develop proper chewing habits and grow strong teeth & jaws. Textures promote "
            "dental health by aiding in the removal of plaque and tartar. "
            "Designed to encourage positive play and teach your puppy healthy chewing habits "
            "from an early age. It's got a chicken flavor that's sure to be a hit with any pup. "
            "Keep them happy, busy and entertained while helping to clean teeth, reduce plaque "
            "and tartar, and promote proper oral hygiene. Satisfies the needs of your teething "
            "puppy with a safe, softer material that's perfect for pets that don't have "
            "permanent teeth. Made in the USA."
        )
        assert len(long_text) > 360, "test text must exceed the old 360-char limit"
        assert "Made in the USA" in long_text[-50:], "origin claim must be in the tail"

        result = _format_docs_for_prompt([self._doc(long_text)])

        assert (
            "Made in the USA" in result
        ), "origin claim was truncated — judge will false-positive flag it as fabrication"

    def test_default_limit_includes_late_bullet_attributes(self):
        """Regression for issue #84: the 1500-char fix (PR #82) was still too tight for
        products whose key attributes appear in late Amazon bullet points (e.g. Thursday
        Boot Company Captain B07PQ9M1C5 where 'glove leather interior' and 'cork-bed
        midsoles' appear at char 2039 out of 2498 total)."""
        # Simulate the Thursday Boot chunk structure: ~1300 chars of prose then bullet points
        prose = "A" * 1300
        bullets = (
            "\nTHE PERFECT FIT - size guidance bullet goes here and occupies ~200 chars.\n"
            "THE RUGGED & RESILIENT CAPTAIN - handcrafted ankle boot bullet occupies ~180 chars.\n"
            "UNPARALLELED WORKMANSHIP - genuine leather bullet occupies ~180 chars.\n"
            "THURSDAY'S SIGNATURE CRAFTSMANSHIP - featuring a fully lined supple glove leather "
            "interior, studded rubber outsoles, and cork-bed midsoles that form to your feet.\n"
        )
        chunk = prose + bullets
        # Confirm the key claims are past 1500 chars (the old limit) but within 10 000 (current limit)
        assert "cork-bed midsoles" not in chunk[:1500], "claim must be past old 1500-char limit"
        assert (
            "cork-bed midsoles" in chunk[:10_000]
        ), "claim must be within current 10 000-char limit"

        result = _format_docs_for_prompt([self._doc(chunk)])

        assert (
            "cork-bed midsoles" in result
        ), "late bullet attribute was truncated — judge will false-positive flag it as fabrication"
        assert (
            "glove leather" in result
        ), "late bullet attribute was truncated — judge will false-positive flag it as fabrication"

    def test_truncates_at_max_chars_when_explicitly_set(self):
        text = "A" * 2000
        result = _format_docs_for_prompt([self._doc(text)], max_chars=100)
        assert "…" in result
        # snippet line should be ≤ 100 chars + "…"
        snippet_line = [line for line in result.splitlines() if line.startswith("   ")][0].strip()
        assert len(snippet_line) <= 101  # 100 chars + ellipsis character

    def test_short_text_not_truncated(self):
        text = "Short description."
        result = _format_docs_for_prompt([self._doc(text)])
        assert "…" not in result
        assert "Short description." in result
