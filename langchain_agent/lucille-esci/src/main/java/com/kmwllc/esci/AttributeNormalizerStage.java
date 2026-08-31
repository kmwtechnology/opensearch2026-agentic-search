package com.kmwllc.esci;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.UpdateMode;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import com.typesafe.config.Config;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.Duration;
import java.util.*;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Lucille stage for normalizing product colors and brands.
 *
 * <p>Loads the color variant→canonical lookup from the OpenSearch-backed
 * attribute mapping store ({@code agentic_hybrid_search_attribute_mappings}),
 * which is also where the live agent enrichment flywheel writes newly
 * discovered mappings — so a full reindex always reflects the latest agent
 * learning. Falls back to the bundled {@code color_mappings.json} if the
 * OpenSearch query fails at start() (missing index on a fresh environment,
 * network issue, etc.) so ingestion never hard-fails on this dependency.
 *
 * <p>Normalizes raw color/brand strings to canonical forms:
 * - Colors: canonical forms sourced from the mapping store (16 forms as of
 *   the original taxonomy: black, white, blue, red, green, yellow, pink,
 *   purple, brown, gray, orange, clear, multicolor, natural, mixed)
 * - Brands: lowercase + generic consolidation
 *
 * <p>Configuration (in products.conf):
 * <pre>{@code
 * {
 *   name: "normalizeAttributes"
 *   class: "com.kmwllc.esci.AttributeNormalizerStage"
 *   openSearchUrl: ${OPENSEARCH_URL}
 *   colorMappingsPath: "/lucille/conf/color_mappings.json"  # fallback only
 * }
 * }</pre>
 *
 * <p>Outputs (per document):
 * - product_color_primary: normalized primary color (or absent if unclassified)
 * - product_color_secondary: normalized secondary color if multi-color (or absent)
 * - product_brand_normalized: normalized brand name
 */
public class AttributeNormalizerStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(AttributeNormalizerStage.class);
  private static final String MAPPING_INDEX = "agentic_hybrid_search_attribute_mappings";

  public static final Spec SPEC = SpecBuilder.stage()
      .optionalString("colorMappingsPath")
      .optionalString("openSearchUrl")
      .build();

  protected Map<String, String> colorLookup;
  protected Set<String> genericBrandPatterns;

  public AttributeNormalizerStage(com.typesafe.config.Config config) {
    super(config);
  }

  /**
   * Initialize stage: build the color variant→canonical lookup, preferring
   * the OpenSearch-backed mapping store and falling back to the bundled
   * color_mappings.json if that's unavailable or unconfigured.
   */
  @Override
  public void start() {
    this.colorLookup = null;

    if (config.hasPath("openSearchUrl")) {
      String openSearchUrl = config.getString("openSearchUrl");
      try {
        colorLookup = loadColorLookupFromOpenSearch(openSearchUrl);
        log.info(
            "Loaded {} color mappings from OpenSearch ({}/{})",
            colorLookup.size(), openSearchUrl, MAPPING_INDEX);
      } catch (Exception e) {
        log.warn(
            "Failed to load color mappings from OpenSearch at {}: {} — falling back to bundled JSON",
            openSearchUrl, e.getMessage());
        colorLookup = null;
      }
    }

    if (colorLookup == null) {
      colorLookup = loadColorLookupFromFile();
    }

    // Brand generics
    this.genericBrandPatterns =
        Set.of(
            "generic", "unknown", "unbranded", "brand not specified",
            "as shown", "various", "multiple", "not specified");
  }

  /**
   * Query the OpenSearch-backed attribute mapping store for all color
   * variant→canonical documents ({@code attribute_type: "color"}).
   *
   * @param openSearchUrl base URL, e.g. http://localhost:9200
   * @return variant (lowercase) → canonical lookup map
   * @throws Exception on any HTTP/parse failure — caller falls back to the bundled JSON
   */
  private Map<String, String> loadColorLookupFromOpenSearch(String openSearchUrl) throws Exception {
    String searchUrl = openSearchUrl.replaceAll("/$", "") + "/" + MAPPING_INDEX + "/_search";
    String requestBody =
        "{\"query\":{\"term\":{\"attribute_type\":\"color\"}},\"size\":10000}";

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

  /** Fallback: load color_mappings.json from the local filesystem (legacy behavior). */
  private Map<String, String> loadColorLookupFromFile() {
    String colorMappingsPath = "color_mappings.json";
    if (config.hasPath("colorMappingsPath")) {
      colorMappingsPath = config.getString("colorMappingsPath");
    }

    Map<String, String> lookup = new HashMap<>();
    try {
      String json = Files.readString(Paths.get(colorMappingsPath));
      ObjectMapper mapper = new ObjectMapper();
      @SuppressWarnings("unchecked")
      Map<String, Object> mappings = mapper.readValue(json, Map.class);

      @SuppressWarnings("unchecked")
      Map<String, List<String>> baseColors = (Map<String, List<String>>) mappings.get("base_colors");

      if (baseColors != null) {
        for (Map.Entry<String, List<String>> entry : baseColors.entrySet()) {
          String canonical = entry.getKey();
          for (String variant : entry.getValue()) {
            lookup.put(variant.toLowerCase(), canonical);
          }
        }
      }

      log.info("Loaded {} color mappings from bundled file {}", lookup.size(), colorMappingsPath);
    } catch (Exception e) {
      log.warn("Failed to load color_mappings.json from {}: {}", colorMappingsPath, e.getMessage());
    }

    return lookup;
  }

  /** Process a single document: normalize color and brand fields. */
  @Override
  public Iterator<Document> processDocument(Document doc) {
    // Normalize color field
    if (doc.has("product_color")) {
      try {
        List<String> colorValues = doc.getStringList("product_color");
        if (colorValues != null && !colorValues.isEmpty()) {
          String rawColor = colorValues.get(0);
          String[] colors = normalizeColor(rawColor);

          if (colors[0] != null) {
            doc.setField("product_color_primary", colors[0]);
          }
          if (colors[1] != null) {
            doc.setField("product_color_secondary", colors[1]);
          }
        }
      } catch (Exception e) {
        log.warn("Failed to normalize color for doc {}: {}", doc.getId(), e.getMessage());
      }
    }

    // Normalize brand field
    if (doc.has("product_brand")) {
      try {
        List<String> brandValues = doc.getStringList("product_brand");
        if (brandValues != null && !brandValues.isEmpty()) {
          String rawBrand = brandValues.get(0);
          String normalized = normalizeBrand(rawBrand);
          doc.setField("product_brand_normalized", normalized);
        }
      } catch (Exception e) {
        log.warn("Failed to normalize brand for doc {}: {}", doc.getId(), e.getMessage());
      }
    }

    return null; // No child documents
  }

  /**
   * Normalize a color string to (primary, secondary) canonical forms.
   *
   * <p>Process:
   * 1. Lowercase, strip leading single letter (e.g., "A Black" → "black")
   * 2. Remove trailing numbers and punctuation
   * 3. Split on compound separators (&, /, +, comma)
   * 4. Strip descriptors (light, dark, pale, etc.)
   * 5. Remove parentheticals
   * 6. Look up each word against color_lookup
   * 7. Return first two unique matches as (primary, secondary)
   *
   * @param color raw color string from product data
   * @return [primary_canonical, secondary_canonical] (either or both may be null)
   */
  public String[] normalizeColor(String color) {
    if (color == null || color.trim().isEmpty()) {
      return new String[] {null, null};
    }

    String normalized = color.toLowerCase();

    // Strip leading single letter (e.g., "A Black" → "Black")
    normalized = normalized.replaceAll("^[a-z]\\s+", "");

    // Strip trailing numbers and noise
    normalized = normalized.replaceAll("[\\s]*\\d+\\s*$", "");
    normalized = normalized.replaceAll("[\\s]*[.!?]\\s*$", "");

    // Split on compound separators (& / + ,)
    normalized = normalized.replaceAll("\\s*[&/+,]\\s*", "|");

    // Strip descriptors (light, dark, pale, bright, soft, etc.) — repeated (+) so
    // stacked descriptors like "deep dark blue" fully reduce to "blue", not just
    // strip the first one and leave "dark" (itself a color-lookup variant) exposed.
    normalized =
        normalized.replaceAll(
            "^(?:(?:light|dark|pale|deep|bright|soft|matte|glossy|metallic|neon|electric|hot|cool|warm|baby|vintage|antique|distressed|faded|heather|sparkle)\\s+)+",
            "");

    // Remove parentheticals
    normalized = normalized.replaceAll("\\s*\\([^)]*\\)", "");

    List<String> foundColors = new ArrayList<>();
    for (String part : normalized.split("\\|")) {
      part = part.trim();
      for (String word : part.split("\\s+")) {
        String cleanWord = word.replaceAll("[s,.-]+$", "");
        if (colorLookup.containsKey(cleanWord)) {
          foundColors.add(colorLookup.get(cleanWord));
          break; // Use first match per part
        }
      }
    }

    // Deduplicate while preserving order
    Set<String> seen = new LinkedHashSet<>(foundColors);
    foundColors.clear();
    foundColors.addAll(seen);

    String primary = foundColors.size() > 0 ? foundColors.get(0) : null;
    String secondary = foundColors.size() > 1 ? foundColors.get(1) : null;

    return new String[] {primary, secondary};
  }

  /**
   * Normalize a brand string to lowercase, consolidating generics.
   *
   * @param brand raw brand string from product data
   * @return normalized brand (lowercase; "generic" if placeholder, else original lowercased)
   */
  public String normalizeBrand(String brand) {
    if (brand == null || brand.trim().isEmpty()) {
      return "generic";
    }

    String normalized = brand.toLowerCase().trim();
    if (genericBrandPatterns.contains(normalized)) {
      return "generic";
    }
    return normalized;
  }
}
