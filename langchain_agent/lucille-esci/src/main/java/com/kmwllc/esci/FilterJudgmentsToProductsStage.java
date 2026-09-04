package com.kmwllc.esci;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
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
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.security.cert.X509Certificate;
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
 * <p>Configuration:
 * <pre>{@code
 * {
 *   name: "filterJudgmentsToProducts"
 *   class: "com.kmwllc.esci.FilterJudgmentsToProductsStage"
 *   openSearchUrl: ${OPENSEARCH_URL}
 *   productsIndex: ${OPENSEARCH_INDEX}
 *   acceptInvalidCert: true  // optional; defaults to false. Set to true for self-signed certs.
 * }
 * }</pre>
 */
public class FilterJudgmentsToProductsStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(FilterJudgmentsToProductsStage.class);
  private static final int SCROLL_PAGE_SIZE = 5000;
  private static final String SCROLL_KEEPALIVE = "1m";

  public static final Spec SPEC =
      SpecBuilder.stage()
          .requiredString("openSearchUrl")
          .requiredString("productsIndex")
          .build();

  // Package-private (not `private`) so tests can set it directly, bypassing
  // start()'s real OpenSearch scroll -- same pattern as AttributeDetectorStage.lookup.
  Set<String> productIds;

  public FilterJudgmentsToProductsStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() {
    String openSearchUrl = config.getString("openSearchUrl");
    String productsIndex = config.getString("productsIndex");
    boolean acceptInvalidCert = config.hasPath("acceptInvalidCert") ? config.getBoolean("acceptInvalidCert") : false;
    try {
      productIds = loadProductIds(openSearchUrl, productsIndex, acceptInvalidCert);
      log.info("Loaded {} product ids from {}/{} for judgments filtering",
          productIds.size(), openSearchUrl, productsIndex);
    } catch (Exception e) {
      throw new RuntimeException(
          "Failed to load product ids from " + openSearchUrl + "/" + productsIndex
              + " -- refusing to run unfiltered (would silently keep every judgment). "
              + "Run the products ingest before the judgments ingest.",
          e);
    }
    if (productIds.isEmpty()) {
      throw new RuntimeException(
          "Loaded zero product ids from " + openSearchUrl + "/" + productsIndex
              + " -- products index is empty or not yet ingested. Run the products ingest first.");
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

  private Set<String> loadProductIds(String openSearchUrl, String productsIndex, boolean acceptInvalidCert) throws Exception {
    HttpClient client = createHttpClient(acceptInvalidCert);
    ObjectMapper mapper = new ObjectMapper();
    Set<String> ids = new HashSet<>();

    String initUrl = openSearchUrl.replaceAll("/$", "") + "/" + productsIndex
        + "/_search?scroll=" + SCROLL_KEEPALIVE;
    String initBody = "{\"size\":" + SCROLL_PAGE_SIZE + ",\"_source\":false,\"query\":{\"match_all\":{}}}";

    JsonNode response = postJson(client, mapper, initUrl, initBody);
    String scrollId = response.path("_scroll_id").asText(null);
    JsonNode hits = response.path("hits").path("hits");
    addIds(hits, ids);

    while (scrollId != null && hits.size() > 0) {
      String scrollUrl = openSearchUrl.replaceAll("/$", "") + "/_search/scroll";
      String scrollBody = "{\"scroll\":\"" + SCROLL_KEEPALIVE + "\",\"scroll_id\":\"" + scrollId + "\"}";
      response = postJson(client, mapper, scrollUrl, scrollBody);
      scrollId = response.path("_scroll_id").asText(null);
      hits = response.path("hits").path("hits");
      addIds(hits, ids);
    }

    return ids;
  }

  private void addIds(JsonNode hits, Set<String> ids) {
    for (JsonNode hit : hits) {
      String id = hit.path("_id").asText(null);
      if (id != null) {
        ids.add(id);
      }
    }
  }

  private JsonNode postJson(HttpClient client, ObjectMapper mapper, String url, String body) throws Exception {
    HttpRequest.Builder requestBuilder =
        HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofSeconds(30))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));

    HttpResponse<String> response =
        client.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString());
    if (response.statusCode() != 200) {
      throw new RuntimeException("OpenSearch request to " + url + " returned HTTP "
          + response.statusCode() + ": " + response.body());
    }
    return mapper.readTree(response.body());
  }

  private HttpClient createHttpClient(boolean acceptInvalidCert) throws Exception {
    HttpClient.Builder builder = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5));

    if (acceptInvalidCert) {
      SSLContext sslContext = SSLContext.getInstance("TLS");
      sslContext.init(null, new TrustManager[] {new PermissiveTrustManager()}, null);
      builder.sslContext(sslContext);
    }

    return builder.build();
  }

  private static class PermissiveTrustManager implements X509TrustManager {
    @Override
    public void checkClientTrusted(X509Certificate[] chain, String authType) {}

    @Override
    public void checkServerTrusted(X509Certificate[] chain, String authType) {}

    @Override
    public X509Certificate[] getAcceptedIssuers() {
      return new X509Certificate[0];
    }
  }
}
