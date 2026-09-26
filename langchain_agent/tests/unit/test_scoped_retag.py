"""Unit tests for pipeline/scoped_retag.py (#147).

The detection cases are ported one-for-one from the Java stage's own suite
(lucille-esci/.../AttributeDetectorStageTest.java) -- the scoped re-tag is only
correct if it tags a product exactly as a full Lucille run would.
"""

from unittest.mock import MagicMock

import pytest

from pipeline.scoped_retag import candidate_query, detect_attributes, retag, tag_fields

WATERPROOF = {
    "waterproof": "waterproof",
    "fully waterproof": "waterproof",
    "weatherproof": "waterproof",
    "water resistant": "water-resistant",
    "water-resistant": "water-resistant",
    "splash proof": "water-resistant",
}
COLOR = {"black": "black", "charcoal": "black", "navy": "blue", "crimson": "red"}


class TestDetectAttributesParityWithJava:
    def test_detects_single_attribute(self):
        primary, secondary = detect_attributes("Genuine Weatherproof Boots", WATERPROOF)
        assert primary == ("Weatherproof", "waterproof")
        assert secondary is None

    def test_prefers_longer_phrase_over_shorter_substring(self):
        primary, _ = detect_attributes("Trail Boots, Fully Waterproof Construction", WATERPROOF)
        assert primary == ("Fully Waterproof", "waterproof")

    def test_detects_two_distinct_attributes(self):
        primary, secondary = detect_attributes("Waterproof Upper, Water Resistant Sole", WATERPROOF)
        assert primary[1] == "waterproof"
        assert secondary[1] == "water-resistant"

    def test_duplicate_canonical_does_not_fill_secondary_slot(self):
        primary, secondary = detect_attributes(
            "Waterproof Upper, Fully Waterproof Sole", WATERPROOF
        )
        assert primary[1] == "waterproof"
        assert secondary is None

    def test_no_match(self):
        assert detect_attributes("Plastic Phone Case", WATERPROOF) == (None, None)

    def test_word_boundary_prevents_partial_word_match(self):
        assert detect_attributes("Waterproofing Guide Booklet", WATERPROOF) == (None, None)

    def test_case_insensitive_keeps_original_raw_text(self):
        primary, _ = detect_attributes("WATERPROOF Hiking Boots", WATERPROOF)
        assert primary == ("WATERPROOF", "waterproof")

    def test_empty_lookup_detects_nothing(self):
        assert detect_attributes("Black boots", {}) == (None, None)

    def test_color_field_names(self):
        fields = tag_fields("color", "Charcoal Wool Coat", COLOR)
        assert fields == {
            "product_color": "Charcoal",
            "product_color_primary": "black",
            "product_color_secondary": None,
        }

    def test_ascii_word_boundary_like_java(self):
        # Java 21's \b is ASCII by default: an accented letter is a non-word
        # char, so "tan" inside "tané" still matches in Java -- and must here.
        primary, _ = detect_attributes("Couleur tané", {"tan": "brown"})
        assert primary == ("tan", "brown")


class TestCandidateQuery:
    def test_matches_text_and_existing_raw_tag_per_variant(self):
        q = candidate_query("color", ["tan"])
        assert {"match_phrase": {"chunk_text.words": "tan"}} in q["bool"]["should"]
        assert {"match_phrase": {"product_color": "tan"}} in q["bool"]["should"]
        assert q["bool"]["minimum_should_match"] == 1


def _client_with_hits(hits):
    client = MagicMock()
    client.search.side_effect = [{"hits": {"hits": hits}}, {"hits": {"hits": []}}]
    client.bulk.return_value = {"errors": False, "items": []}
    return client


class TestRetag:
    def test_corrects_a_wrong_tag_and_skips_unchanged(self):
        hits = [
            {  # tagged yellow from "tan" -- the correction demo's precondition
                "_id": "B1",
                "sort": ["B1"],
                "_source": {
                    "chunk_text": "Dark Tan Leather Boot",
                    "product_color": "Tan",
                    "product_color_primary": "yellow",
                },
            },
            {  # already right after the change -- must not be rewritten
                "_id": "B2",
                "sort": ["B2"],
                "_source": {
                    "chunk_text": "Black boot",
                    "product_color": "Black",
                    "product_color_primary": "black",
                },
            },
        ]
        client = _client_with_hits(hits)
        lookup = {"tan": "brown", "black": "black"}

        result = retag(client, "idx", "color", ["tan"], lookup)

        assert (result.candidates, result.updated) == (2, 1)
        actions = client.bulk.call_args.kwargs["body"]
        assert actions[0] == {"update": {"_index": "idx", "_id": "B1"}}
        assert actions[1]["script"]["params"]["fields"] == {
            "product_color": "Tan",
            "product_color_primary": "brown",
            "product_color_secondary": None,
        }
        client.indices.refresh.assert_called_once_with(index="idx")

    def test_no_detection_keeps_the_raw_dataset_field(self):
        """product_color is the ESCI dataset's own column; Lucille never deletes it."""
        hits = [
            {
                "_id": "B4",
                "sort": ["B4"],
                "_source": {
                    "chunk_text": "Tan leather boot",
                    "product_color": "Multicolor",
                    "product_color_primary": "yellow",
                },
            }
        ]
        client = _client_with_hits(hits)

        retag(client, "idx", "color", ["tan"], lookup={})  # tan mapping removed

        fields = client.bulk.call_args.kwargs["body"][1]["script"]["params"]["fields"]
        assert "product_color" not in fields  # untouched, not removed
        assert fields == {"product_color_primary": None, "product_color_secondary": None}

    def test_removed_mapping_clears_tags(self):
        hits = [
            {
                "_id": "B3",
                "sort": ["B3"],
                "_source": {
                    "chunk_text": "Waterproof hiking boot",
                    "product_waterproof": "Waterproof",
                    "product_waterproof_primary": "waterproof",
                },
            }
        ]
        client = _client_with_hits(hits)

        result = retag(client, "idx", "waterproof", ["waterproof"], lookup={})

        assert result.updated == 1
        fields = client.bulk.call_args.kwargs["body"][1]["script"]["params"]["fields"]
        assert fields == {
            "product_waterproof_primary": None,
            "product_waterproof_secondary": None,
        }

    def test_no_changes_means_no_bulk_and_no_refresh(self):
        client = _client_with_hits([])
        assert retag(client, "idx", "color", ["tan"], {"tan": "brown"}).updated == 0
        client.bulk.assert_not_called()
        client.indices.refresh.assert_not_called()

    def test_bulk_errors_raise(self):
        hits = [{"_id": "B1", "sort": ["B1"], "_source": {"chunk_text": "tan boot"}}]
        client = _client_with_hits(hits)
        client.bulk.return_value = {
            "errors": True,
            "items": [{"update": {"error": {"type": "boom"}}}],
        }
        with pytest.raises(RuntimeError, match="1 bulk updates failed"):
            retag(client, "idx", "color", ["tan"], {"tan": "brown"})

    def test_blank_variants_are_a_no_op(self):
        client = MagicMock()
        assert retag(client, "idx", "color", ["  "], {}).candidates == 0
        client.search.assert_not_called()
