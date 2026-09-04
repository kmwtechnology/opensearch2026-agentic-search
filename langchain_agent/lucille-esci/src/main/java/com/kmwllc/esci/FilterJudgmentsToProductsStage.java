package com.kmwllc.esci;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.StageException;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import com.kmwllc.lucille.util.OpenSearchUtils;
import java.io.IOException;
import java.net.URI;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import org.opensearch.client.opensearch.OpenSearchClient;
import org.opensearch.client.opensearch.core.ScrollResponse;
import org.opensearch.client.opensearch.core.SearchResponse;
import org.opensearch.client.opensearch.core.search.Hit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Trims each judgments document's {@code judgments} array down to only the
 * product ids actually present in a target product index, dropping the
 * document entirely if none remain.
 *
 * <p>Unfiltered, the judgments index references whatever product catalog the
 * source ESCI dataset covers (up to ~1.8M products across all judged
 * queries), while any given ingest -- local dev's 10k-product sample, a
 * larger GCP dataset, whatever -- only indexes a subset. Most judged queries
 * then have zero retrievable judged products, so nothing downstream (eval
 * scoring, quality-gate calibration) can ever use them. This stage keeps the
 * judgments index aligned with whatever product set was actually ingested,
 * for any deployment size, computed fresh at ingest time rather than baked
 * into a static parquet file.
 *
 * <p>Loads the full set of product ids from the target index once at {@link
 * #start()} via a scroll (there is no bound on product-catalog size this
 * needs to support), not per-document -- same one-time-load-then-reuse
 * pattern as {@link AttributeDetectorStage}'s mapping lookup.
 *
 * <p>Connects through Lucille's own {@link OpenSearchUtils} client, so the
 * stage's {@code opensearch} block takes exactly the same keys (and TLS
 * behaviour, including {@code acceptInvalidCert}) as the indexer's.
 *
 * <p>Configuration:
 * <pre>{@code
 * {
 *   name: "filterJudgmentsToProducts"
 *   class: "com.kmwllc.esci.FilterJudgmentsToProductsStage"
 *   opensearch {
 *     url: ${OPENSEARCH_URL}
 *     index: ${OPENSEARCH_INDEX}   // the PRODUCTS index, not the judgments target
 *     acceptInvalidCert: true
 *   }
 * }
 * }</pre>
 */
public class FilterJudgmentsToProductsStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(FilterJudgmentsToProductsStage.class);
  private static final int SCROLL_PAGE_SIZE = 5000;
  private static final String SCROLL_KEEPALIVE = "1m";

  public static final Spec SPEC =
      SpecBuilder.stage().requiredParent(OpenSearchUtils.OPENSEARCH_PARENT_SPEC).build();

  // Package-private (not `private`) so tests can set it directly, bypassing
  // start()'s real OpenSearch scroll -- same pattern as AttributeDetectorStage.lookup.
  Set<String> productIds;

  private OpenSearchClient client;

  public FilterJudgmentsToProductsStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() throws StageException {
    String productsIndex = OpenSearchUtils.getOpenSearchIndex(config);
    String host = URI.create(OpenSearchUtils.getOpenSearchUrl(config)).getHost();
    try {
      client = OpenSearchUtils.getOpenSearchRestClient(config);
      productIds = loadProductIds(productsIndex);
      log.info("Loaded {} product ids from {}/{} for judgments filtering",
          productIds.size(), host, productsIndex);
    } catch (Exception e) {
      throw new StageException(
          "Failed to load product ids from " + host + "/" + productsIndex
              + " -- refusing to run unfiltered (would silently keep every judgment). "
              + "Run the products ingest before the judgments ingest.",
          e);
    }
    if (productIds.isEmpty()) {
      throw new StageException(
          "Loaded zero product ids from " + host + "/" + productsIndex
              + " -- products index is empty or not yet ingested. Run the products ingest first.");
    }
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

  @Override
  public Iterator<Document> processDocument(Document doc) {
    JsonNode judgments = doc.getJson("judgments");
    if (judgments == null || !judgments.isArray()) {
      doc.setDropped(true);
      return null;
    }

    ObjectMapper mapper = new ObjectMapper();
    ArrayNode kept = mapper.createArrayNode();
    for (JsonNode judgment : judgments) {
      String productId = judgment.path("product_id").asText(null);
      if (productId != null && productIds.contains(productId)) {
        kept.add(judgment);
      }
    }

    if (kept.isEmpty()) {
      doc.setDropped(true);
      return null;
    }

    doc.setField("judgments", kept);
    doc.setField("num_judgments", kept.size());
    return null;
  }

  private Set<String> loadProductIds(String productsIndex) throws IOException {
    Set<String> ids = new HashSet<>();

    SearchResponse<Void> response = client.search(s -> s
        .index(productsIndex)
        .size(SCROLL_PAGE_SIZE)
        .scroll(t -> t.time(SCROLL_KEEPALIVE))
        .source(src -> src.fetch(false))
        .query(q -> q.matchAll(m -> m)),
        Void.class);
    String scrollId = response.scrollId();
    List<Hit<Void>> hits = response.hits().hits();
    addIds(hits, ids);

    while (scrollId != null && !hits.isEmpty()) {
      String currentScrollId = scrollId;
      ScrollResponse<Void> scrollResponse = client.scroll(r -> r
          .scrollId(currentScrollId)
          .scroll(t -> t.time(SCROLL_KEEPALIVE)),
          Void.class);
      scrollId = scrollResponse.scrollId();
      hits = scrollResponse.hits().hits();
      addIds(hits, ids);
    }

    if (scrollId != null) {
      String finalScrollId = scrollId;
      client.clearScroll(c -> c.scrollId(finalScrollId));
    }
    return ids;
  }

  private void addIds(List<Hit<Void>> hits, Set<String> ids) {
    for (Hit<Void> hit : hits) {
      if (hit.id() != null) {
        ids.add(hit.id());
      }
    }
  }
}
