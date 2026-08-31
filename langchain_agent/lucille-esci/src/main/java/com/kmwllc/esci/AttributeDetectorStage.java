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
 * Generic Lucille stage for detecting and normalizing a discovered
 * variant->canonical attribute (color, material, or any future attribute
 * type) from unstructured text — one parameterized class instead of a
 * dedicated Java class per attribute type.
 *
 * <p>Unlike a hypothetical "normalize an existing structured field" stage,
 * there's no pre-existing raw field for a discovered attribute — this stage
 * performs detection AND normalization in one step, scanning {@code
 * chunk_text} (title + description + bullet_point, built by an earlier
 * pipeline stage) for known variant terms.
 *
 * <p>Sources its variant->canonical lookup from the OpenSearch-backed
 * attribute mapping store ({@code agentic_hybrid_search_attribute_mappings},
 * filtered by {@code attribute_type: <attributeType>}) — this is also where
 * the live agent enrichment flywheel writes newly discovered variants, so a
 * full reindex always reflects the latest agent learning. There is no
 * bundled-file fallback (attribute taxonomies are OS-native, built via
 * discovery, not hand-authored) — if OpenSearch is unreachable at start(),
 * this stage logs a warning and produces no fields for that run rather than
 * hard-failing ingestion.
 *
 * <p>The generated products.conf emits one stage entry per attribute type
 * currently registered in the mapping store — e.g. a "detectColor" stage and
 * a "detectMaterial" stage, each an independent instance of this same class
 * with a different {@code attributeType} parameter (see config_generator.py).
 *
 * <p>Configuration (in generated products.conf):
 * <pre>{@code
 * {
 *   name: "detectMaterial"
 *   class: "com.kmwllc.esci.AttributeDetectorStage"
 *   attributeType: "material"
 *   openSearchUrl: ${OPENSEARCH_URL}
 * }
 * }</pre>
 *
 * <p>Outputs (per document, field names built from {@code attributeType}):
 * - product_&lt;attributeType&gt;: raw matched text snippet, original casing
 *   preserved — for scored full-text search, dual-mapped in the index mapping.
 * - product_&lt;attributeType&gt;_primary: normalized canonical value (or absent)
 * - product_&lt;attributeType&gt;_secondary: second distinct value if detected (or absent)
 */
public class AttributeDetectorStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(AttributeDetectorStage.class);
  private static final String MAPPING_INDEX = "agentic_hybrid_search_attribute_mappings";

  public static final Spec SPEC =
      SpecBuilder.stage().requiredString("attributeType").optionalString("openSearchUrl").build();

  protected String attributeType;
  protected Map<String, String> lookup;
  private Pattern variantPattern;
  private String rawFieldName;
  private String primaryFieldName;
  private String secondaryFieldName;

  public AttributeDetectorStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() {
    this.attributeType = config.getString("attributeType");
    this.rawFieldName = "product_" + attributeType;
    this.primaryFieldName = "product_" + attributeType + "_primary";
    this.secondaryFieldName = "product_" + attributeType + "_secondary";

    this.lookup = new HashMap<>();

    if (!config.hasPath("openSearchUrl")) {
      log.warn(
          "No openSearchUrl configured for AttributeDetectorStage(attributeType={}) — detection disabled for this run.",
          attributeType);
      buildVariantPattern();
      return;
    }

    String openSearchUrl = config.getString("openSearchUrl");
    try {
      lookup = loadLookupFromOpenSearch(openSearchUrl);
      log.info(
          "Loaded {} '{}' mappings from OpenSearch ({}/{})",
          lookup.size(), attributeType, openSearchUrl, MAPPING_INDEX);
    } catch (Exception e) {
      log.warn(
          "Failed to load '{}' mappings from OpenSearch at {}: {} — detection disabled for this run.",
          attributeType, openSearchUrl, e.getMessage());
      lookup = new HashMap<>();
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
    if (lookup.isEmpty()) {
      variantPattern = null;
      return;
    }

    List<String> variants = new ArrayList<>(lookup.keySet());
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
   * Query the OpenSearch-backed attribute mapping store for all
   * variant->canonical documents matching this stage's attributeType.
   *
   * @param openSearchUrl base URL, e.g. http://localhost:9200
   * @return variant (lowercase) -> canonical lookup map
   * @throws Exception on any HTTP/parse failure
   */
  private Map<String, String> loadLookupFromOpenSearch(String openSearchUrl) throws Exception {
    String searchUrl = openSearchUrl.replaceAll("/$", "") + "/" + MAPPING_INDEX + "/_search";
    String requestBody =
        "{\"query\":{\"term\":{\"attribute_type\":\"" + attributeType + "\"}},\"size\":10000}";

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

    Map<String, String> result = new HashMap<>();
    for (JsonNode hit : hits) {
      JsonNode source = hit.path("_source");
      String variant = source.path("variant").asText(null);
      String canonical = source.path("canonical").asText(null);
      if (variant != null && canonical != null) {
        result.put(variant.toLowerCase(), canonical);
      }
    }

    return result;
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

      DetectedAttribute[] detected = detectAttributes(text);

      if (detected[0] != null) {
        doc.setField(rawFieldName, detected[0].rawText);
        doc.setField(primaryFieldName, detected[0].canonical);
      }
      if (detected[1] != null) {
        doc.setField(secondaryFieldName, detected[1].canonical);
      }
    } catch (Exception e) {
      log.warn("Failed to detect '{}' for doc {}: {}", attributeType, doc.getId(), e.getMessage());
    }

    return null; // No child documents
  }

  // Package-private (not `private`) so tests in this package can inspect
  // matches directly instead of only asserting the doc fields processDocument sets.
  static class DetectedAttribute {
    final String rawText;
    final String canonical;

    DetectedAttribute(String rawText, String canonical) {
      this.rawText = rawText;
      this.canonical = canonical;
    }
  }

  /**
   * Scan text for variant matches, in order of first appearance.
   *
   * @param text combined chunk_text (title + description + bullet_point)
   * @return [primary, secondary] — either or both may be null. Secondary is
   *     only populated when it resolves to a canonical distinct from primary.
   */
  DetectedAttribute[] detectAttributes(String text) {
    Matcher matcher = variantPattern.matcher(text);
    List<DetectedAttribute> found = new ArrayList<>();
    Set<String> seenCanonicals = new LinkedHashSet<>();

    while (matcher.find() && found.size() < 2) {
      String rawMatch = matcher.group();
      String canonical = lookup.get(rawMatch.toLowerCase());
      if (canonical != null && !seenCanonicals.contains(canonical)) {
        seenCanonicals.add(canonical);
        found.add(new DetectedAttribute(rawMatch, canonical));
      }
    }

    DetectedAttribute primary = found.size() > 0 ? found.get(0) : null;
    DetectedAttribute secondary = found.size() > 1 ? found.get(1) : null;
    return new DetectedAttribute[] {primary, secondary};
  }
}
