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
 * ("waterproof" and "color") to prove genericity, not just one type renamed.
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

  private Map<String, String> waterproofLookup() {
    Map<String, String> lookup = new HashMap<>();
    lookup.put("waterproof", "waterproof");
    lookup.put("fully waterproof", "waterproof");
    lookup.put("weatherproof", "waterproof");
    lookup.put("water resistant", "water-resistant");
    lookup.put("water-resistant", "water-resistant");
    lookup.put("splash proof", "water-resistant");
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
  void testFieldNamesBuiltFromAttributeTypeParameter_waterproof() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Fully Waterproof Hiking Boots");

    stage.processDocument(doc);

    assertEquals("Fully Waterproof", doc.getString("product_waterproof"));
    assertEquals("waterproof", doc.getString("product_waterproof_primary"));
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
    assertFalse(doc.has("product_waterproof"));
    assertFalse(doc.has("product_waterproof_primary"));
  }

  @Test
  void testTwoStageInstancesOnSameDocumentDontCollide() {
    AttributeDetectorStage colorStage = stageWithLookup("color", colorLookup());
    AttributeDetectorStage waterproofStage = stageWithLookup("waterproof", waterproofLookup());

    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Black Fully Waterproof Boots");

    colorStage.processDocument(doc);
    waterproofStage.processDocument(doc);

    assertEquals("black", doc.getString("product_color_primary"));
    assertEquals("waterproof", doc.getString("product_waterproof_primary"));
  }

  // ── detectAttributes() logic (mirrors the prior MaterialNormalizerStage coverage) ──

  @Test
  void testDetectsSingleAttribute() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Genuine Weatherproof Boots");

    assertNotNull(detected[0]);
    assertEquals("Weatherproof", detected[0].rawText);
    assertEquals("waterproof", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testPrefersLongerPhraseOverShorterSubstring() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Trail Boots, Fully Waterproof Construction");

    assertEquals("Fully Waterproof", detected[0].rawText);
    assertEquals("waterproof", detected[0].canonical);
  }

  @Test
  void testDetectsTwoDistinctAttributes() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Waterproof Upper, Water Resistant Sole");

    assertNotNull(detected[0]);
    assertNotNull(detected[1]);
    assertEquals("waterproof", detected[0].canonical);
    assertEquals("water-resistant", detected[1].canonical);
  }

  @Test
  void testDuplicateCanonicalDoesNotFillSecondarySlot() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Waterproof Upper, Fully Waterproof Sole");

    assertNotNull(detected[0]);
    assertEquals("waterproof", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testNoMatchReturnsNullPrimaryAndSecondary() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Plastic Phone Case");

    assertNull(detected[0]);
    assertNull(detected[1]);
  }

  @Test
  void testWordBoundaryPreventsPartialWordMatch() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("Waterproofing Guide Booklet");

    assertNull(detected[0]);
  }

  @Test
  void testCaseInsensitiveMatching() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    var detected = stage.detectAttributes("WATERPROOF Hiking Boots");

    assertNotNull(detected[0]);
    assertEquals("waterproof", detected[0].canonical);
    assertEquals("WATERPROOF", detected[0].rawText);
  }

  @Test
  void testEmptyLookupProducesNoPattern() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", new HashMap<>());
    assertDoesNotThrow(() -> stage.processDocument(Document.create("doc1")));
  }

  @Test
  void testProcessDocumentSkipsWhenNoChunkText() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    Document doc = Document.create("doc1");

    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_waterproof"));
  }

  @Test
  void testProcessDocumentSetsSecondaryWhenTwoAttributesFound() {
    AttributeDetectorStage stage = stageWithLookup("waterproof", waterproofLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Waterproof Upper, Water Resistant Sole");

    stage.processDocument(doc);

    assertEquals("waterproof", doc.getString("product_waterproof_primary"));
    assertEquals("water-resistant", doc.getString("product_waterproof_secondary"));
  }

  // ── start(): config validation + hard failure on an unreachable store ────

  @Test
  void testStartWithUnreachableOpenSearchThrowsStageException() {
    // Detection must never degrade silently: an unreachable / unauthorized
    // mapping store fails the ingest instead of producing an index with no
    // attribute fields (#71, #72).
    AttributeDetectorStage stage = new AttributeDetectorStage(configFor("waterproof"));
    StageException e = assertThrows(StageException.class, stage::start);
    assertTrue(e.getMessage().contains("'waterproof' mappings"), e.getMessage());
    assertTrue(e.getMessage().contains("localhost/agentic_hybrid_search_attribute_mappings"),
        e.getMessage());
    assertDoesNotThrow(stage::stop);
  }

  @Test
  void testMissingOpensearchBlockIsRejectedByStageSpec() {
    // The `opensearch { url, index }` parent block is required, exactly like
    // the indexer's -- the old `openSearchUrl` key is gone, and omitting the
    // block no longer means "detection disabled".
    Config config = ConfigFactory.parseString("attributeType: \"waterproof\"");
    assertThrows(Exception.class, () -> new AttributeDetectorStage(config));
  }

  @Test
  void testLegacyOpenSearchUrlKeyIsRejectedByStageSpec() {
    Config config = ConfigFactory.parseString(
        "attributeType: \"waterproof\"\n"
            + "openSearchUrl: \"http://localhost:1\"\n"
            + "opensearch { url: \"http://localhost:1\", index: \"x\" }");
    assertThrows(Exception.class, () -> new AttributeDetectorStage(config));
  }
}
