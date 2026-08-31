package com.kmwllc.esci;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Lucille stage for detecting and normalizing product material from
 * unstructured text.
 *
 * <p>Unlike color/brand (which normalize an existing structured field),
 * there's no pre-existing {@code product_material} field on ESCI products —
 * this stage performs detection AND normalization in one step, scanning
 * {@code chunk_text} (title + description + bullet_point, built by an
 * earlier pipeline stage) for known material variant terms.
 *
 * <p>Sources the material variant→canonical lookup from the same
 * OpenSearch-backed attribute mapping store as color
 * ({@code agentic_hybrid_search_attribute_mappings}, {@code
 * attribute_type: "material"}) — this is also where the live agent
 * enrichment flywheel writes newly discovered material variants, so a full
 * reindex always reflects the latest agent learning. There is no bundled-
 * file fallback for material (it was seeded OS-native from the start, via
 * scripts/seed_material_taxonomy.py) — if OpenSearch is unreachable at
 * start(), this stage logs a warning and produces no material fields for
 * that run rather than hard-failing ingestion.
 *
 * <p>Configuration (in products.conf):
 * <pre>{@code
 * {
 *   name: "normalizeMaterial"
 *   class: "com.kmwllc.esci.MaterialNormalizerStage"
 *   openSearchUrl: ${OPENSEARCH_URL}
 * }
 * }</pre>
 *
 * <p>Outputs (per document):
 * - product_material: raw matched text snippet (e.g. "Genuine Leather"),
 *   original casing preserved — for scored full-text search, dual-mapped in
 *   opensearch_mapping.json like product_brand/product_color.
 * - product_material_primary: normalized canonical material (or absent)
 * - product_material_secondary: normalized secondary material if a second,
 *   distinct material is also detected (or absent)
 */
public class MaterialNormalizerStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(MaterialNormalizerStage.class);
  private static final String MAPPING_INDEX = "agentic_hybrid_search_attribute_mappings";

  public static final Spec SPEC = SpecBuilder.stage().optionalString("openSearchUrl").build();

  protected Map<String, String> materialLookup;
  private Pattern variantPattern;

  public MaterialNormalizerStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() {
    this.materialLookup = new HashMap<>();

    if (!config.hasPath("openSearchUrl")) {
      log.warn("No openSearchUrl configured for MaterialNormalizerStage — material detection disabled for this run.");
      buildVariantPattern();
      return;
    }

    String openSearchUrl = config.getString("openSearchUrl");
    try {
      materialLookup = loadMaterialLookupFromOpenSearch(openSearchUrl);
      log.info(
          "Loaded {} material mappings from OpenSearch ({}/{})",
          materialLookup.size(), openSearchUrl, MAPPING_INDEX);
    } catch (Exception e) {
      log.warn(
          "Failed to load material mappings from OpenSearch at {}: {} — material detection disabled for this run.",
          openSearchUrl, e.getMessage());
      materialLookup = new HashMap<>();
    }

    buildVariantPattern();
  }

  /**
   * Build a single alternation regex over all known variants, longest-first,
   * so a longer/more specific phrase (e.g. "cotton blend") is preferred over
   * a shorter one it contains (e.g. "cotton") when both would otherwise
   * match at the same starting position.
   */
  private void buildVariantPattern() {
    if (materialLookup.isEmpty()) {
      variantPattern = null;
      return;
    }

    List<String> variants = new ArrayList<>(materialLookup.keySet());
    variants.sort((a, b) -> b.length() - a.length());

    StringBuilder patternBuilder = new StringBuilder("\\b(?:");
    for (int i = 0; i < variants.size(); i++) {
      if (i > 0) {
        patternBuilder.append("|");
      }
      patternBuilder.append(Pattern.quote(variants.get(i)));
    }
    patternBuilder.append(")\\b");

    variantPattern = Pattern.compile(patternBuilder.toString(), Pattern.CASE_INSENSITIVE);
  }

  /**
   * Query the OpenSearch-backed attribute mapping store for all material
   * variant→canonical documents ({@code attribute_type: "material"}).
   *
   * @param openSearchUrl base URL, e.g. http://localhost:9200
   * @return variant (lowercase) → canonical lookup map
   * @throws Exception on any HTTP/parse failure
   */
  private Map<String, String> loadMaterialLookupFromOpenSearch(String openSearchUrl) throws Exception {
    String searchUrl = openSearchUrl.replaceAll("/$", "") + "/" + MAPPING_INDEX + "/_search";
    String requestBody = "{\"query\":{\"term\":{\"attribute_type\":\"material\"}},\"size\":10000}";

    HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    HttpRequest.Builder requestBuilder =
        HttpRequest.newBuilder()
            .uri(URI.create(searchUrl))
            .timeout(Duration.ofSeconds(10))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestBody, StandardCharsets.UTF_8));

    String osUser = System.getenv("OPENSEARCH_USER");
    String osPassword = System.getenv("OPENSEARCH_PASSWORD");
    if (osUser != null && !osUser.isBlank()) {
      String credentials = Base64.getEncoder()
          .encodeToString((osUser + ":" + osPassword).getBytes(StandardCharsets.UTF_8));
      requestBuilder.header("Authorization", "Basic " + credentials);
    }

    HttpResponse<String> response =
        client.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString());

    if (response.statusCode() != 200) {
      throw new RuntimeException(
          "OpenSearch mapping query returned HTTP " + response.statusCode() + ": " + response.body());
    }

    ObjectMapper mapper = new ObjectMapper();
    JsonNode root = mapper.readTree(response.body());
    JsonNode hits = root.path("hits").path("hits");

    Map<String, String> lookup = new HashMap<>();
    for (JsonNode hit : hits) {
      JsonNode source = hit.path("_source");
      String variant = source.path("variant").asText(null);
      String canonical = source.path("canonical").asText(null);
      if (variant != null && canonical != null) {
        lookup.put(variant.toLowerCase(), canonical);
      }
    }

    return lookup;
  }

  @Override
  public Iterator<Document> processDocument(Document doc) {
    if (variantPattern == null || !doc.has("chunk_text")) {
      return null;
    }

    try {
      List<String> chunkTextValues = doc.getStringList("chunk_text");
      if (chunkTextValues == null || chunkTextValues.isEmpty()) {
        return null;
      }
      String text = chunkTextValues.get(0);
      if (text == null || text.isEmpty()) {
        return null;
      }

      DetectedMaterial[] detected = detectMaterials(text);

      if (detected[0] != null) {
        doc.setField("product_material", detected[0].rawText);
        doc.setField("product_material_primary", detected[0].canonical);
      }
      if (detected[1] != null) {
        doc.setField("product_material_secondary", detected[1].canonical);
      }
    } catch (Exception e) {
      log.warn("Failed to detect material for doc {}: {}", doc.getId(), e.getMessage());
    }

    return null; // No child documents
  }

  // Package-private (not `private`) so tests in this package can inspect
  // matches directly instead of only asserting the doc fields processDocument sets.
  static class DetectedMaterial {
    final String rawText;
    final String canonical;

    DetectedMaterial(String rawText, String canonical) {
      this.rawText = rawText;
      this.canonical = canonical;
    }
  }

  /**
   * Scan text for material variant matches, in order of first appearance.
   *
   * @param text combined chunk_text (title + description + bullet_point)
   * @return [primary, secondary] — either or both may be null. Secondary is
   *     only populated when it resolves to a canonical distinct from primary.
   */
  DetectedMaterial[] detectMaterials(String text) {
    Matcher matcher = variantPattern.matcher(text);
    List<DetectedMaterial> found = new ArrayList<>();
    Set<String> seenCanonicals = new LinkedHashSet<>();

    while (matcher.find() && found.size() < 2) {
      String rawMatch = matcher.group();
      String canonical = materialLookup.get(rawMatch.toLowerCase());
      if (canonical != null && !seenCanonicals.contains(canonical)) {
        seenCanonicals.add(canonical);
        found.add(new DetectedMaterial(rawMatch, canonical));
      }
    }

    DetectedMaterial primary = found.size() > 0 ? found.get(0) : null;
    DetectedMaterial secondary = found.size() > 1 ? found.get(1) : null;
    return new DetectedMaterial[] {primary, secondary};
  }
}
