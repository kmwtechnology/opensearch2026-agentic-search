package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.sun.net.httpserver.HttpServer;
import com.typesafe.config.Config;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Unit tests for AttributeNormalizerStage normalization logic. */
class AttributeNormalizerStageTest {

  private AttributeNormalizerStage stage;

  @BeforeEach
  void setUp() {
    // Construct a real (non-anonymous) instance — Lucille's Stage constructor
    // validates SPEC via getClass().getDeclaredField("SPEC"), which only sees
    // fields declared directly on the instantiated class, not inherited ones.
    // An anonymous subclass (`new AttributeNormalizerStage(config){}`) would
    // fail that check even though AttributeNormalizerStage itself declares SPEC.
    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("colorMappingsPath")).thenReturn(false);
    stage = new AttributeNormalizerStage(mockConfig);

    // Skip the real start() (requires color_mappings.json on the classpath);
    // populate the protected fields directly instead (same package as the stage).
    stage.colorLookup = new HashMap<>();
    // Base colors: black, white, blue, red, green, yellow, pink, purple, brown, gray,
    // orange, clear, multicolor, natural, mixed
    for (String variant : Arrays.asList("black", "dark", "ebony")) {
      stage.colorLookup.put(variant, "black");
    }
    for (String variant : Arrays.asList("white", "cream", "ivory")) {
      stage.colorLookup.put(variant, "white");
    }
    for (String variant : Arrays.asList("blue", "navy", "cyan", "teal")) {
      stage.colorLookup.put(variant, "blue");
    }
    for (String variant : Arrays.asList("red", "crimson", "scarlet", "burgundy")) {
      stage.colorLookup.put(variant, "red");
    }
    for (String variant : Arrays.asList("green")) {
      stage.colorLookup.put(variant, "green");
    }
    for (String variant : Arrays.asList("yellow", "gold")) {
      stage.colorLookup.put(variant, "yellow");
    }
    for (String variant : Arrays.asList("pink", "magenta", "rose")) {
      stage.colorLookup.put(variant, "pink");
    }
    for (String variant : Arrays.asList("purple", "violet", "lavender")) {
      stage.colorLookup.put(variant, "purple");
    }
    for (String variant : Arrays.asList("brown", "tan", "beige", "bronze")) {
      stage.colorLookup.put(variant, "brown");
    }
    for (String variant : Arrays.asList("gray", "grey", "silver")) {
      stage.colorLookup.put(variant, "gray");
    }
    for (String variant : Arrays.asList("orange")) {
      stage.colorLookup.put(variant, "orange");
    }
    for (String variant : Arrays.asList("clear", "transparent")) {
      stage.colorLookup.put(variant, "clear");
    }
    for (String variant : Arrays.asList("multicolor", "multi", "multi-color")) {
      stage.colorLookup.put(variant, "multicolor");
    }
    for (String variant : Arrays.asList("natural", "natural-color")) {
      stage.colorLookup.put(variant, "natural");
    }
    for (String variant : Arrays.asList("mixed")) {
      stage.colorLookup.put(variant, "mixed");
    }

    stage.genericBrandPatterns =
        Set.of(
            "generic", "unknown", "unbranded", "brand not specified",
            "as shown", "various", "multiple", "not specified");
  }

  // ── Color normalization tests ────────────────────────────────────────────

  @Test
  void testSimpleColor() {
    String[] result = stage.normalizeColor("black");
    assertEquals("black", result[0]);
    assertNull(result[1]);
  }

  @Test
  void testColorCaseInsensitive() {
    String[] result = stage.normalizeColor("BLACK");
    assertEquals("black", result[0]);
  }

  @Test
  void testColorWithLeadingLetter() {
    String[] result = stage.normalizeColor("A Black");
    assertEquals("black", result[0]);
  }

  @Test
  void testColorWithTrailingNumbers() {
    String[] result = stage.normalizeColor("blue 42");
    assertEquals("blue", result[0]);
  }

  @Test
  void testColorWithParentheses() {
    String[] result = stage.normalizeColor("green (dark)");
    assertEquals("green", result[0]);
  }

  @Test
  void testColorWithDescriptor() {
    String[] result = stage.normalizeColor("light blue");
    assertEquals("blue", result[0]);
  }

  @Test
  void testMultiColorAmpersand() {
    String[] result = stage.normalizeColor("black & white");
    assertEquals("black", result[0]);
    assertEquals("white", result[1]);
  }

  @Test
  void testMultiColorSlash() {
    String[] result = stage.normalizeColor("red / blue");
    assertEquals("red", result[0]);
    assertEquals("blue", result[1]);
  }

  @Test
  void testMultiColorPlus() {
    String[] result = stage.normalizeColor("purple + orange");
    assertEquals("purple", result[0]);
    assertEquals("orange", result[1]);
  }

  @Test
  void testMultiColorDeduplicated() {
    String[] result = stage.normalizeColor("blue and blue");
    assertEquals("blue", result[0]);
    assertNull(result[1]);
  }

  @Test
  void testColorNotClassified() {
    String[] result = stage.normalizeColor("xyz123");
    assertNull(result[0]);
    assertNull(result[1]);
  }

  @Test
  void testColorEmpty() {
    String[] result = stage.normalizeColor("");
    assertNull(result[0]);
    assertNull(result[1]);
  }

  @Test
  void testColorNull() {
    String[] result = stage.normalizeColor(null);
    assertNull(result[0]);
    assertNull(result[1]);
  }

  @Test
  void testColorVariantMapping() {
    String[] result = stage.normalizeColor("grey");
    assertEquals("gray", result[0]);
  }

  @Test
  void testColorWithMultipleDescriptors() {
    String[] result = stage.normalizeColor("deep dark blue");
    assertEquals("blue", result[0]);
  }

  @Test
  void testColorWithComma() {
    String[] result = stage.normalizeColor("red, white");
    assertEquals("red", result[0]);
    assertEquals("white", result[1]);
  }

  @Test
  void testColorOnlyDescriptor() {
    String[] result = stage.normalizeColor("light");
    assertNull(result[0]);
  }

  // ── Brand normalization tests ────────────────────────────────────────────

  @Test
  void testBrandSimple() {
    String result = stage.normalizeBrand("Nike");
    assertEquals("nike", result);
  }

  @Test
  void testBrandLowercase() {
    String result = stage.normalizeBrand("ADIDAS");
    assertEquals("adidas", result);
  }

  @Test
  void testBrandGenericPlaceholder() {
    String result = stage.normalizeBrand("generic");
    assertEquals("generic", result);
  }

  @Test
  void testBrandUnknown() {
    String result = stage.normalizeBrand("unknown");
    assertEquals("generic", result);
  }

  @Test
  void testBrandNotSpecified() {
    String result = stage.normalizeBrand("brand not specified");
    assertEquals("generic", result);
  }

  @Test
  void testBrandEmpty() {
    String result = stage.normalizeBrand("");
    assertEquals("generic", result);
  }

  @Test
  void testBrandNull() {
    String result = stage.normalizeBrand(null);
    assertEquals("generic", result);
  }

  @Test
  void testBrandWhitespace() {
    String result = stage.normalizeBrand("   ");
    assertEquals("generic", result);
  }

  @Test
  void testBrandVariousGenericForms() {
    assertEquals("generic", stage.normalizeBrand("as shown"));
    assertEquals("generic", stage.normalizeBrand("various"));
    assertEquals("generic", stage.normalizeBrand("multiple"));
    assertEquals("generic", stage.normalizeBrand("not specified"));
    assertEquals("generic", stage.normalizeBrand("unbranded"));
  }

  // ── start() sourcing tests: OpenSearch-backed lookup + fallback ─────────

  /**
   * Exercises start() end-to-end against a real HttpClient call, using an
   * embedded JDK HttpServer to stand in for OpenSearch's _search endpoint —
   * verifies the actual HTTP + JSON parsing path, not just the pure
   * normalization logic covered above.
   */
  static class StartBehaviorTests {
    private HttpServer fakeOpenSearch;
    private int port;

    void startFakeOpenSearch(int statusCode, String responseBody) throws IOException {
      fakeOpenSearch = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
      port = fakeOpenSearch.getAddress().getPort();
      fakeOpenSearch.createContext(
          "/agentic_hybrid_search_attribute_mappings/_search",
          exchange -> {
            byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(statusCode, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
              os.write(bytes);
            }
          });
      fakeOpenSearch.start();
    }

    void stopFakeOpenSearch() {
      if (fakeOpenSearch != null) {
        fakeOpenSearch.stop(0);
      }
    }
  }

  @Test
  void testStartLoadsColorLookupFromOpenSearch() throws Exception {
    StartBehaviorTests helper = new StartBehaviorTests();
    String osSearchResponse =
        "{\"hits\":{\"hits\":["
            + "{\"_source\":{\"attribute_type\":\"color\",\"variant\":\"jet black\",\"canonical\":\"black\"}},"
            + "{\"_source\":{\"attribute_type\":\"color\",\"variant\":\"navy\",\"canonical\":\"blue\"}}"
            + "]}}";
    helper.startFakeOpenSearch(200, osSearchResponse);
    try {
      Config mockConfig = mock(Config.class);
      when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
      when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:" + helper.port);
      when(mockConfig.hasPath("colorMappingsPath")).thenReturn(false);

      AttributeNormalizerStage s = new AttributeNormalizerStage(mockConfig);
      s.start();

      assertEquals("black", s.colorLookup.get("jet black"));
      assertEquals("blue", s.colorLookup.get("navy"));
      assertEquals(2, s.colorLookup.size());
    } finally {
      helper.stopFakeOpenSearch();
    }
  }

  @Test
  void testStartFallsBackToFileWhenOpenSearchUnreachable(@org.junit.jupiter.api.io.TempDir Path tempDir)
      throws Exception {
    Path mappingsFile = tempDir.resolve("color_mappings.json");
    Files.writeString(
        mappingsFile,
        "{\"base_colors\":{\"black\":[\"black\",\"jet\"],\"blue\":[\"blue\",\"navy\"]}}");

    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
    // Port 1 is a reserved/unroutable port — connection will fail fast.
    when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:1");
    when(mockConfig.hasPath("colorMappingsPath")).thenReturn(true);
    when(mockConfig.getString("colorMappingsPath")).thenReturn(mappingsFile.toString());

    AttributeNormalizerStage s = new AttributeNormalizerStage(mockConfig);
    s.start();

    assertEquals("black", s.colorLookup.get("jet"));
    assertEquals("blue", s.colorLookup.get("navy"));
  }

  @Test
  void testStartFallsBackToFileWhenOpenSearchReturnsError(@org.junit.jupiter.api.io.TempDir Path tempDir)
      throws Exception {
    StartBehaviorTests helper = new StartBehaviorTests();
    helper.startFakeOpenSearch(404, "{\"error\":\"index_not_found_exception\"}");

    Path mappingsFile = tempDir.resolve("color_mappings.json");
    Files.writeString(mappingsFile, "{\"base_colors\":{\"red\":[\"red\",\"crimson\"]}}");

    try {
      Config mockConfig = mock(Config.class);
      when(mockConfig.hasPath("openSearchUrl")).thenReturn(true);
      when(mockConfig.getString("openSearchUrl")).thenReturn("http://localhost:" + helper.port);
      when(mockConfig.hasPath("colorMappingsPath")).thenReturn(true);
      when(mockConfig.getString("colorMappingsPath")).thenReturn(mappingsFile.toString());

      AttributeNormalizerStage s = new AttributeNormalizerStage(mockConfig);
      s.start();

      assertEquals("red", s.colorLookup.get("crimson"));
    } finally {
      helper.stopFakeOpenSearch();
    }
  }

  @Test
  void testStartUsesFileWhenOpenSearchUrlNotConfigured(@org.junit.jupiter.api.io.TempDir Path tempDir)
      throws Exception {
    Path mappingsFile = tempDir.resolve("color_mappings.json");
    Files.writeString(mappingsFile, "{\"base_colors\":{\"green\":[\"green\",\"lime\"]}}");

    Config mockConfig = mock(Config.class);
    when(mockConfig.hasPath("openSearchUrl")).thenReturn(false);
    when(mockConfig.hasPath("colorMappingsPath")).thenReturn(true);
    when(mockConfig.getString("colorMappingsPath")).thenReturn(mappingsFile.toString());

    AttributeNormalizerStage s = new AttributeNormalizerStage(mockConfig);
    s.start();

    assertEquals("green", s.colorLookup.get("lime"));
  }
}
