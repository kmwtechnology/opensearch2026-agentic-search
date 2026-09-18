package com.kmwllc.esci;

import com.fasterxml.jackson.databind.node.ObjectNode;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.StageException;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import com.kmwllc.lucille.util.OpenSearchUtils;
import java.io.IOException;
import java.net.URI;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.opensearch.client.opensearch.OpenSearchClient;
import org.opensearch.client.opensearch.core.SearchResponse;
import org.opensearch.client.opensearch.core.search.Hit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Generic Lucille stage for detecting and normalizing a discovered
 * variant->canonical attribute (color, waterproof, or any future attribute
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
 * discovery, not hand-authored).
 *
 * <p>Connects through Lucille's own {@link OpenSearchUtils} client, so the
 * stage's {@code opensearch} block takes exactly the same keys (and TLS /
 * basic-auth behaviour, including {@code acceptInvalidCert}) as the
 * indexer's. A failure to load the lookup is a hard {@link StageException}:
 * this stage is only emitted into products.generated.conf when its attribute
 * type is registered in the store (see config_generator.py), so an
 * unreachable or unauthorized store is always a real error, and degrading
 * silently would produce an index with no attribute fields at all -- which
 * is exactly how the hosted cluster ended up that way (#71, #72).
 *
 * <p>The generated products.conf emits one stage entry per attribute type
 * currently registered in the mapping store — e.g. a "detectColor" stage and
 * a "detectWaterproof" stage, each an independent instance of this same class
 * with a different {@code attributeType} parameter (see config_generator.py).
 *
 * <p>Configuration (in generated products.conf):
 * <pre>{@code
 * {
 *   name: "detectWaterproof"
 *   class: "com.kmwllc.esci.AttributeDetectorStage"
 *   attributeType: "waterproof"
 *   // Same client + TLS settings as the indexer's root `opensearch` block
 *   // (HOCON merge), pointed at the mapping store index.
 *   opensearch: ${opensearch} { index: "agentic_hybrid_search_attribute_mappings" }
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
  private static final int MAX_MAPPINGS = 10000;

  public static final Spec SPEC =
      SpecBuilder.stage()
          .requiredString("attributeType")
          .requiredParent(OpenSearchUtils.OPENSEARCH_PARENT_SPEC)
          .build();

  protected String attributeType;
  // Package-private so tests can set it directly, bypassing start()'s real
  // OpenSearch load -- same pattern as FilterJudgmentsToProductsStage.productIds.
  protected Map<String, String> lookup;
  private Pattern variantPattern;
  private String rawFieldName;
  private String primaryFieldName;
  private String secondaryFieldName;
  private OpenSearchClient client;

  public AttributeDetectorStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() throws StageException {
    initFieldNames();

    String mappingIndex = OpenSearchUtils.getOpenSearchIndex(config);
    String host = URI.create(OpenSearchUtils.getOpenSearchUrl(config)).getHost();
    try {
      client = OpenSearchUtils.getOpenSearchRestClient(config);
      lookup = loadLookup(mappingIndex);
    } catch (Exception e) {
      throw new StageException(
          "Failed to load '" + attributeType + "' mappings from " + host + "/" + mappingIndex
              + " -- refusing to run with detection silently disabled (would index every product"
              + " with no product_" + attributeType + "_* fields).",
          e);
    }

    if (lookup.isEmpty()) {
      log.warn(
          "Loaded zero '{}' mappings from {}/{} -- no product_{}_* fields will be produced this run.",
          attributeType, host, mappingIndex, attributeType);
    } else {
      log.info(
          "Loaded {} '{}' mappings from {}/{}", lookup.size(), attributeType, host, mappingIndex);
    }

    buildVariantPattern();
  }

  @Override
  public void stop() throws StageException {
    if (client == null) {
      return;
    }
    try {
      client._transport().close();
    } catch (IOException e) {
      throw new StageException("Error closing OpenSearch client.", e);
    }
  }

  /**
   * Derive the attribute type and output field names from config. Split out
   * of start() so tests can set up a stage with a fixed lookup without
   * touching OpenSearch.
   */
  void initFieldNames() {
    this.attributeType = config.getString("attributeType");
    this.rawFieldName = "product_" + attributeType;
    this.primaryFieldName = "product_" + attributeType + "_primary";
    this.secondaryFieldName = "product_" + attributeType + "_secondary";
    this.lookup = new HashMap<>();
  }

  /**
   * Build a single alternation regex over all known variants, longest-first,
   * so a longer/more specific phrase (e.g. "cotton blend") is preferred over
   * a shorter one it contains (e.g. "cotton") when both would otherwise
   * match at the same starting position.
   */
  void buildVariantPattern() {
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
   * @param mappingIndex the mapping store index name
   * @return variant (lowercase) -> canonical lookup map
   * @throws IOException on any transport/parse failure
   */
  private Map<String, String> loadLookup(String mappingIndex) throws IOException {
    SearchResponse<ObjectNode> response = client.search(s -> s
        .index(mappingIndex)
        .size(MAX_MAPPINGS)
        .source(src -> src.filter(f -> f.includes("variant", "canonical")))
        .query(q -> q.term(t -> t
            .field("attribute_type")
            .value(v -> v.stringValue(attributeType)))),
        ObjectNode.class);

    Map<String, String> result = new HashMap<>();
    for (Hit<ObjectNode> hit : response.hits().hits()) {
      ObjectNode source = hit.source();
      if (source == null) {
        continue;
      }
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
