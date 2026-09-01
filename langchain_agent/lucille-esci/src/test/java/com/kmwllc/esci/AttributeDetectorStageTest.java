package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.kmwllc.lucille.core.Document;
import com.sun.net.httpserver.HttpServer;
import com.typesafe.config.Config;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.Test;

/**
 * Unit tests for AttributeDetectorStage — the generic, parameterized stage
 * that replaced the dedicated MaterialNormalizerStage/AttributeNormalizerStage
 * classes. Deliberately exercises TWO distinct attributeType values
 * ("material" and "color") to prove genericity, not just material renamed.
 */
class AttributeDetectorStageTest {

  /** Build a stage with a fixed lookup, bypassing start()'s OpenSearch call. */
  private AttributeDetectorStage stageWithLookup(String attributeType, Map<String, String> lookup) {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("attributeType")).thenReturn(true);
    when(mockConfig.getString("attributeType")).thenReturn(attributeType);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(false);
    AttributeDetectorStage stage = new AttributeDetectorStage(mockConfig);
    stage.start(); // sets attributeType, field names; lookup empty since no openSearchUrl
    stage.lookup = lookup;
    invokeBuildVariantPattern(stage);
    return stage;
  }

  private void invokeBuildVariantPattern(AttributeDetectorStage stage) {
    try {
      var method = AttributeDetectorStage.class.getDeclaredMethod("buildVariantPattern");
      method.setAccessible(true);
      method.invoke(stage);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
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

  // ── start() sourcing: OpenSearch + unreachable/unconfigured fallback ─────

  @Test
  void testStartLoadsLookupFromOpenSearchFilteredByAttributeType() throws IOException {
    HttpServer server = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
    int port = server.getAddress().getPort();
    String responseBody =
        "{\"hits\":{\"hits\":["
            + "{\"_source\":{\"attribute_type\":\"material\",\"variant\":\"cowhide\",\"canonical\":\"leather\"}}"
            + "]}}";
    server.createContext(
        "/agentic_hybrid_search_attribute_mappings/_search",
        exchange -> {
          byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);
          exchange.sendResponseHeaders(200, bytes.length);
          try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
          }
        });
    server.start();

    try {
      Config mockConfig = mock(Config.class);
      when(mockConfig.hasPath("attributeType")).thenReturn(true);
      when(mockConfig.getString("attributeType")).thenReturn("material");
      when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
      when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:" + port);

      AttributeDetectorStage stage = new AttributeDetectorStage(mockConfig);
      stage.start();

      assertEquals("leather", stage.lookup.get("cowhide"));
    } finally {
      server.stop(0);
    }
  }

  @Test
  void testStartWithUnreachableOpenSearchProducesEmptyLookupNotCrash() {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("attributeType")).thenReturn(true);
    when(mockConfig.getString("attributeType")).thenReturn("material");
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
    when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:1");

    AttributeDetectorStage stage = new AttributeDetectorStage(mockConfig);
    assertDoesNotThrow(stage::start);

    assertTrue(stage.lookup.isEmpty());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Leather Wallet");
    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_material"));
  }

  @Test
  void testStartWithNoOpenSearchUrlConfiguredProducesEmptyLookup() {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("attributeType")).thenReturn(true);
    when(mockConfig.getString("attributeType")).thenReturn("material");
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(false);

    AttributeDetectorStage stage = new AttributeDetectorStage(mockConfig);
    assertDoesNotThrow(stage::start);

    assertTrue(stage.lookup.isEmpty());
  }
}
