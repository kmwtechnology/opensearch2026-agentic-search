"""
Unit tests for the trigger_enrichment LangChain tool — pure wiring/formatting
logic, enrich_attribute mocked so these never touch OpenSearch or trigger a
real reindex.
"""

from unittest.mock import patch

from quality.enrichment_service import EnrichmentResult
from tools.enrichment_tool import trigger_enrichment


class TestTriggerEnrichmentTool:
    @patch("tools.enrichment_tool.enrich_attribute")
    def test_successful_enrichment_reports_docs_and_duration(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="waterproof",
            variant="weatherproof",
            canonical="waterproof",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=18.3,
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}
        )

        assert "weatherproof" in result
        assert "waterproof" in result
        assert "9618" in result
        assert "18.3" in result
        assert "live" in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_calls_enrich_attribute_with_explicit_canonical(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True, attribute_type="color", variant="periwinkle", canonical="blue"
        )

        trigger_enrichment.invoke(
            {"attribute_type": "color", "variant": "periwinkle", "canonical": "blue"}
        )

        mock_enrich.assert_called_once_with("color", "periwinkle", explicit_canonical="blue")

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_classification_failure_reports_reason(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=False,
            attribute_type="waterproof",
            variant="unobtainium",
            reason="could not classify to a known waterproof bucket",
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "unobtainium", "canonical": "waterproof"}
        )

        assert "Could not enrich" in result
        assert "unobtainium" in result
        assert "could not classify" in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_reindex_failure_reports_mapping_saved(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="waterproof",
            variant="weatherproof",
            canonical="waterproof",
            reindex_triggered=True,
            reindex_success=False,
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}
        )

        assert "re-index failed" in result
        assert "mapping is saved" in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_correction_reports_was_now_not_added(self, mock_enrich):
        """When enrich_attribute reports corrected_from (a genuinely
        different canonical replacing a wrong one), the message must say
        "Corrected ... from X to Y" -- never "Added", which would falsely
        imply the taxonomy previously had no opinion at all."""
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            corrected_from="yellow",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=21.4,
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "color", "variant": "tan", "canonical": "brown"}
        )

        assert "Corrected" in result
        assert "yellow" in result
        assert "brown" in result
        assert "Added" not in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_fresh_addition_still_says_added_not_corrected(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="waterproof",
            variant="weatherproof",
            canonical="waterproof",
            corrected_from=None,
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=18.3,
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}
        )

        assert "Added" in result
        assert "Corrected" not in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_variant_equal_to_canonical_avoids_tautology(self, mock_enrich):
        """Confirmed live (#142): registering "waterproof" as the FIRST entry
        of a brand-new attribute type maps the term to itself. The naive
        "Added 'waterproof' as a 'waterproof' waterproof" phrasing is a
        tautology on a projector -- this must read as a registration
        instead."""
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="waterproof",
            variant="waterproof",
            canonical="waterproof",
            corrected_from=None,
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=27.8,
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "waterproof", "canonical": "waterproof"}
        )

        assert "as a new waterproof attribute" in result
        assert "as a 'waterproof' waterproof" not in result

    def test_tool_has_expected_schema(self):
        schema = trigger_enrichment.args_schema.model_json_schema()
        assert set(schema["required"]) == {"attribute_type", "variant", "canonical"}

    def test_canonical_field_description_lists_valid_buckets(self):
        schema = trigger_enrichment.args_schema.model_json_schema()
        canonical_desc = schema["properties"]["canonical"]["description"]
        assert "waterproof" in canonical_desc  # the waterproof bucket
        assert "black" in canonical_desc  # a color bucket

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_github_mode_reports_dispatch_and_run_url(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            corrected_from="yellow",
            reindex_triggered=True,
            reindex_success=True,
            reindex_mode="github",
            reindex_run_url="https://github.com/org/repo/actions/runs/42",
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "color", "variant": "tan", "canonical": "brown"}
        )

        assert "Corrected 'tan' from 'yellow' to 'brown'" in result
        assert "dispatched" in result
        assert "https://github.com/org/repo/actions/runs/42" in result
        assert "9618" not in result

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_reindex_failure_includes_error_detail(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="waterproof",
            variant="splash proof",
            canonical="waterproof",
            reindex_triggered=True,
            reindex_success=False,
            reindex_mode="github",
            reindex_error="GitHub API returned HTTP 404: Not Found",
        )

        result = trigger_enrichment.invoke(
            {"attribute_type": "waterproof", "variant": "splash proof", "canonical": "waterproof"}
        )

        assert "failed to complete" in result
        assert "HTTP 404" in result
        assert "mapping is saved" in result
