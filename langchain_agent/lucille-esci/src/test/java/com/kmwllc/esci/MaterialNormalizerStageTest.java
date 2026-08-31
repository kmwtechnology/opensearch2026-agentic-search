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
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;

/** Unit tests for MaterialNormalizerStage detection + normalization logic. */
class MaterialNormalizerStageTest {

  /** Build a stage with a fixed material lookup, bypassing start()'s OpenSearch call. */
  private MaterialNormalizerStage stageWithLookup(Map<String, String> lookup) {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(false);
    MaterialNormalizerStage stage = new MaterialNormalizerStage(mockConfig);
    stage.materialLookup = lookup;
    invokeBuildVariantPattern(stage);
    return stage;
  }

  /** buildVariantPattern is private; invoke it directly since we're in-package. */
  private void invokeBuildVariantPattern(MaterialNormalizerStage stage) {
    try {
      var method = MaterialNormalizerStage.class.getDeclaredMethod("buildVariantPattern");
      method.setAccessible(true);
      method.invoke(stage);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  private Map<String, String> defaultLookup() {
    Map<String, String> lookup = new HashMap<>();
    lookup.put("leather", "leather");
    lookup.put("genuine leather", "leather");
    lookup.put("cowhide", "leather");
    lookup.put("cotton", "cotton");
    lookup.put("cotton blend", "cotton");
    lookup.put("stainless steel", "metal");
    return lookup;
  }

  // ── detectMaterials() ────────────────────────────────────────────────────

  @Test
  void testDetectsSingleMaterial() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("Genuine Cowhide Boots");

    assertNotNull(detected[0]);
    assertEquals("Cowhide", detected[0].rawText); // original casing preserved
    assertEquals("leather", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testPrefersLongerPhraseOverShorterSubstring() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("Christian Art Gifts Genuine Leather Wallet");

    // "genuine leather" should win over standalone "leather" starting at the same phrase
    assertEquals("Genuine Leather", detected[0].rawText);
    assertEquals("leather", detected[0].canonical);
  }

  @Test
  void testDetectsTwoDistinctMaterials() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("Leather and Cotton Blend Jacket");

    assertNotNull(detected[0]);
    assertNotNull(detected[1]);
    assertEquals("leather", detected[0].canonical);
    assertEquals("cotton", detected[1].canonical);
  }

  @Test
  void testDuplicateCanonicalDoesNotFillSecondarySlot() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    // "leather" then "cowhide" both resolve to canonical "leather" — only one slot used
    var detected = stage.detectMaterials("Leather Trim, Genuine Cowhide Sole");

    assertNotNull(detected[0]);
    assertEquals("leather", detected[0].canonical);
    assertNull(detected[1]);
  }

  @Test
  void testNoMatchReturnsNullPrimaryAndSecondary() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("Plastic Phone Case");

    assertNull(detected[0]);
    assertNull(detected[1]);
  }

  @Test
  void testWordBoundaryPreventsPartialWordMatch() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("Cottonwood Tree Ornament");

    assertNull(detected[0]);
  }

  @Test
  void testCaseInsensitiveMatching() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    var detected = stage.detectMaterials("STAINLESS STEEL Water Bottle");

    assertNotNull(detected[0]);
    assertEquals("metal", detected[0].canonical);
    assertEquals("STAINLESS STEEL", detected[0].rawText);
  }

  @Test
  void testEmptyLookupProducesNoPattern() {
    MaterialNormalizerStage stage = stageWithLookup(new HashMap<>());
    // buildVariantPattern leaves variantPattern null for an empty lookup;
    // processDocument must handle this gracefully (checked via processDocument test below)
    assertDoesNotThrow(() -> stage.processDocument(Document.create("doc1")));
  }

  // ── processDocument() field wiring ───────────────────────────────────────

  @Test
  void testProcessDocumentSetsFieldsFromChunkText() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Genuine Leather Wallet for Men");

    stage.processDocument(doc);

    assertEquals("Genuine Leather", doc.getString("product_material"));
    assertEquals("leather", doc.getString("product_material_primary"));
    assertFalse(doc.has("product_material_secondary"));
  }

  @Test
  void testProcessDocumentSkipsWhenNoChunkText() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    Document doc = Document.create("doc1");

    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_material"));
  }

  @Test
  void testProcessDocumentSetsSecondaryWhenTwoMaterialsFound() {
    MaterialNormalizerStage stage = stageWithLookup(defaultLookup());
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Leather and Cotton Blend Jacket");

    stage.processDocument(doc);

    assertEquals("leather", doc.getString("product_material_primary"));
    assertEquals("cotton", doc.getString("product_material_secondary"));
  }

  // ── start() sourcing: OpenSearch + no-fallback behavior ──────────────────

  @Test
  void testStartLoadsMaterialLookupFromOpenSearch() throws IOException {
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
      when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
      when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:" + port);

      MaterialNormalizerStage stage = new MaterialNormalizerStage(mockConfig);
      stage.start();

      assertEquals("leather", stage.materialLookup.get("cowhide"));
    } finally {
      server.stop(0);
    }
  }

  @Test
  void testStartWithUnreachableOpenSearchProducesEmptyLookupNotCrash() {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
    when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:1");

    MaterialNormalizerStage stage = new MaterialNormalizerStage(mockConfig);
    assertDoesNotThrow(stage::start);

    assertTrue(stage.materialLookup.isEmpty());
    // processDocument must not crash with an empty lookup / null pattern
    Document doc = Document.create("doc1");
    doc.setField("chunk_text", "Leather Wallet");
    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_material"));
  }

  @Test
  void testStartWithNoOpenSearchUrlConfiguredProducesEmptyLookup() {
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(false);

    MaterialNormalizerStage stage = new MaterialNormalizerStage(mockConfig);
    assertDoesNotThrow(stage::start);

    assertTrue(stage.materialLookup.isEmpty());
  }
}
