"""
Unit tests for config_generator — pure string-rendering logic, no
OpenSearch dependency (attribute_types is passed explicitly in every test).

See tests/integration/test_config_generator_live.py for the one test that
queries the live OS-backed store (attribute_types=None default).
"""

from config_generator import _stage_name, generate_products_conf


class TestStageNaming:
    def test_simple_type(self):
        assert _stage_name("material") == "detectMaterial"

    def test_another_simple_type(self):
        assert _stage_name("color") == "detectColor"

    def test_underscore_type_camelcased(self):
        assert _stage_name("glass_ceramic") == "detectGlassCeramic"

    def test_hyphenated_type_camelcased(self):
        assert _stage_name("size-category") == "detectSizeCategory"


class TestGenerateProductsConf:
    def test_one_stage_block_per_attribute_type(self):
        conf = generate_products_conf(["color", "material"])

        assert conf.count('class: "com.kmwllc.esci.AttributeDetectorStage"') == 2

    def test_stage_names_are_distinct_and_correct(self):
        conf = generate_products_conf(["color", "material"])

        assert 'name: "detectColor"' in conf
        assert 'name: "detectMaterial"' in conf

    def test_attribute_type_parameter_interpolated_correctly(self):
        conf = generate_products_conf(["material"])

        assert 'attributeType: "material"' in conf

    def test_output_field_names_documented_per_type(self):
        conf = generate_products_conf(["material"])

        assert "product_material" in conf
        assert "product_material_primary" in conf
        assert "product_material_secondary" in conf

    def test_empty_attribute_types_produces_no_detector_stages(self):
        conf = generate_products_conf([])

        # The header comment mentions AttributeDetectorStage.java by name
        # regardless of attribute count — check for an actual stage
        # instantiation, not the bare class-name substring.
        assert 'class: "com.kmwllc.esci.AttributeDetectorStage"' not in conf
        # Fixed prelude/epilogue stages still present
        assert "BrandNormalizerStage" in conf
        assert "buildChunkText" in conf

    def test_three_attribute_types_yields_three_stages(self):
        conf = generate_products_conf(["color", "material", "pattern"])

        assert conf.count('class: "com.kmwllc.esci.AttributeDetectorStage"') == 3
        assert 'name: "detectPattern"' in conf

    def test_fixed_prelude_stages_always_present(self):
        conf = generate_products_conf(["material"])

        for stage_class in [
            "com.kmwllc.lucille.stage.Concatenate",
            "com.kmwllc.lucille.stage.CopyFields",
            "com.kmwllc.lucille.stage.DeleteFields",
            "com.kmwllc.esci.BrandNormalizerStage",
        ]:
            assert stage_class in conf

    def test_fixed_epilogue_present(self):
        conf = generate_products_conf(["material"])

        assert "setCollectionId" in conf
        assert "removeEmptyFields" in conf
        assert 'type: "OpenSearch"' in conf

    def test_no_normalizeattributes_or_normalizematerial_stage_names_remain(self):
        """Regression: the retired dedicated stage names must not leak into
        generated output — only the generic detect<Type> naming."""
        conf = generate_products_conf(["color", "material"])

        assert '"normalizeAttributes"' not in conf
        assert '"normalizeMaterial"' not in conf
        assert "AttributeNormalizerStage" not in conf
        assert "MaterialNormalizerStage" not in conf

    def test_output_is_syntactically_balanced_braces(self):
        """Cheap sanity check on generated HOCON — not a full parser, but
        catches an unbalanced brace from a template bug."""
        conf = generate_products_conf(["color", "material"])
        assert conf.count("{") == conf.count("}")

    def test_stage_order_prelude_then_attributes_then_epilogue(self):
        conf = generate_products_conf(["material"])

        brand_pos = conf.index('class: "com.kmwllc.esci.BrandNormalizerStage"')
        material_pos = conf.index('class: "com.kmwllc.esci.AttributeDetectorStage"')
        collection_pos = conf.index('name: "setCollectionId"')

        assert brand_pos < material_pos < collection_pos
