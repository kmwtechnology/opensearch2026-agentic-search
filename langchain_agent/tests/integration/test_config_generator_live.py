"""
Integration test for config_generator's live-store default: confirms
generate_products_conf(None) actually queries AttributeMappingStore rather
than requiring attribute_types to always be passed explicitly.

Requires a live local OpenSearch (docker compose up -d) with at least one
attribute type registered.
"""

import re

import pytest

from config_generator import generate_products_conf

pytestmark = pytest.mark.integration


def test_none_queries_live_store():
    conf = generate_products_conf(None)

    assert "connectors:" in conf
    assert re.search(r'class: "com\.kmwllc\.esci\.AttributeDetectorStage"', conf)
