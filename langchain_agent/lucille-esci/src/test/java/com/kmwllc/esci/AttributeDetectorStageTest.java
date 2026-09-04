package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;

import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.StageException;
import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * Unit tests for AttributeDetectorStage — the generic, parameterized stage
 * that replaced the dedicated MaterialNormalizerStage/AttributeNormalizerStage
 * classes. Deliberately exercises TWO distinct attributeType values
 * ("material" and "color") to prove genericity, not just material renamed.
 *
 * <p>Uses real Typesafe configs (not Mockito) because the Stage constructor
 * validates the config against SPEC, which now requires the same
 * {@code opensearch { url, index }} block as the indexer.
 */
class AttributeDetectorStageTest {

  private static Config configFor(String attributeType) {
    return ConfigFactory.parseString(
        "attributeType: \"" + attributeType + "\"\n"
            + "opensearch { url: \"http://localhost:1\","
            + " index: \"agentic_hybrid_search_attribute_mappings\" }");
  }

  /** Build a stage with a fixed lookup, bypassing start()'s real OpenSearch load. */
  private AttributeDetectorStage stageWithLookup(String attributeType, Map<String, String> lookup) {
    AttributeDetectorStage stage = new AttributeDetectorStage(configFor(attributeType));
    stage.initFieldNames();
    stage.lookup = lookup;
    stage.buildVariantPattern();
    return stage;
  }

  private Map<String, String> materialLookup() {
    Map<String, String> lookup = new HashMap<>();
    lookup.put("leather", "leather");
    lookup.put("genuine leather", "leather");
    lookup.put("cowhide", "leather");
    lookup.put("cotton", "cotton");
    lookup.put("cotton blend", "cotton");
    lookup.put("stainless steel", "metal");
    return lookup;
  }

  private Map<String, String> colorLookup() {
    Map<String, String> lookup = new HashMap<>();
    lookup.put("black", "black");
    lookup.put("charcoal", "black");
    lookup.put("navy", "blue");
    lookup.put("crimson", "red");
    return lookup;
  }

  // ── Genericity: same class, two attribute types, distinct field names ───

  @Test
  void testFieldNamesBuiltFromAttributeTypeParameter_material() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Genuine Leather Wallet");

    stage.processDocument(doc);

    assertEquals("Genuine Leather", doc.getString("product_material"));
    assertEquals("leather", doc.getString("product_material_primary"));
  }

  @Test
  void testFieldNamesBuiltFromAttributeTypeParameter_color() {
    AttributeDetectorStage stage = stageWithLookup("color", colorLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Charcoal Wool Sweater");

    stage.processDocument(doc);

    assertEquals("Charcoal", doc.getString("product_color"));
    assertEquals("black", doc.getString("product_color_primary"));
    // Confirms no cross-contamination between attribute types' field names
    assertFalse(doc.has("product_material"));
    assertFalse(doc.has("product_material_primary"));
  }

  @Test
  void testTwoStageInstancesOnSameDocumentDontCollide() {
    AttributeDetectorStage colorStage = stageWithLookup("color", colorLookup());
    AttributeDetectorStage materialStage = stageWithLookup("material", materialLookup());

    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Black Genuine Leather Wallet");

    colorStage.processDocument(doc);
    materialStage.processDocument(doc);

    assertEquals("black", doc.getString("product_color_primary"));
    assertEquals("leather", doc.getString("product_material_primary"));
  }

  // ── detectAttributes() logic (mirrors the prior MaterialNormalizerStage coverage) ──

  @Test
  void testDetectsSingleAttribute() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Genuine Cowhide Boots");

    assertNotNull(detected[0]);
    assertEquals("Cowhide", detected[0].rawText);
    assertEquals("leather", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testPrefersLongerPhraseOverShorterSubstring() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Christian Art Gifts Genuine Leather Wallet");

    assertEquals("Genuine Leather", detected[0].rawText);
    assertEquals("leather", detected[0].canonical);
  }

  @Test
  void testDetectsTwoDistinctAttributes() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Leather and Cotton Blend Jacket");

    assertNotNull(detected[0]);
    assertNotNull(detected[1]);
    assertEquals("leather", detected[0].canonical);
    assertEquals("cotton", detected[1].canonical);
  }

  @Test
  void testDuplicateCanonicalDoesNotFillSecondarySlot() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Leather Trim, Genuine Cowhide Sole");

    assertNotNull(detected[0]);
    assertEquals("leather", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testNoMatchReturnsNullPrimaryAndSecondary() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Plastic Phone Case");

    assertNull(detected[0]);
    assertNull(detected[1]);
  }

  @Test
  void testWordBoundaryPreventsPartialWordMatch() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("Cottonwood Tree Ornament");

    assertNull(detected[0]);
  }

  @Test
  void testCaseInsensitiveMatching() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    var detected = stage.detectAttributes("STAINLESS STEEL Water Bottle");

    assertNotNull(detected[0]);
    assertEquals("metal", detected[0].canonical);
    assertEquals("STAINLESS STEEL", detected[0].rawText);
  }

  @Test
  void testEmptyLookupProducesNoPattern() {
    AttributeDetectorStage stage = stageWithLookup("material", new HashMap<>());
    assertDoesNotThrow(() -> stage.processDocument(Document.create("doc1")));
  }

  @Test
  void testProcessDocumentSkipsWhenNoChunkText() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    Document doc = Document.create("doc1");

    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_material"));
  }

  @Test
  void testProcessDocumentSetsSecondaryWhenTwoAttributesFound() {
    AttributeDetectorStage stage = stageWithLookup("material", materialLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Leather and Cotton Blend Jacket");

    stage.processDocument(doc);

    assertEquals("leather", doc.getString("product_material_primary"));
    assertEquals("cotton", doc.getString("product_material_secondary"));
  }

  // ── start(): config validation + hard failure on an unreachable store ────

  @Test
  void testStartWithUnreachableOpenSearchThrowsStageException() {
    // Detection must never degrade silently: an unreachable / unauthorized
    // mapping store fails the ingest instead of producing an index with no
    // attribute fields (#71, #72).
    AttributeDetectorStage stage = new AttributeDetectorStage(configFor("material"));
    StageException e = assertThrows(StageException.class, stage::start);
    assertTrue(e.getMessage().contains("'material' mappings"), e.getMessage());
    assertTrue(e.getMessage().contains("localhost/agentic_hybrid_search_attribute_mappings"),
        e.getMessage());
    assertDoesNotThrow(stage::stop);
  }

  @Test
  void testMissingOpensearchBlockIsRejectedByStageSpec() {
    // The `opensearch { url, index }` parent block is required, exactly like
    // the indexer's -- the old `openSearchUrl` key is gone, and omitting the
    // block no longer means "detection disabled".
    Config config = ConfigFactory.parseString("attributeType: \"material\"");
    assertThrows(Exception.class, () -> new AttributeDetectorStage(config));
  }

  @Test
  void testLegacyOpenSearchUrlKeyIsRejectedByStageSpec() {
    Config config = ConfigFactory.parseString(
        "attributeType: \"material\"\n"
            + "openSearchUrl: \"http://localhost:1\"\n"
            + "opensearch { url: \"http://localhost:1\", index: \"x\" }");
    assertThrows(Exception.class, () -> new AttributeDetectorStage(config));
  }
}
