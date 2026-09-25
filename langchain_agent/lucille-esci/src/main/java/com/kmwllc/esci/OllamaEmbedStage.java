package com.kmwllc.esci;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.StageException;
import com.kmwllc.lucille.core.UpdateMode;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Iterator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Embeds a text field with a local Ollama embedding model (issue #148).
 *
 * <p>Lucille ships {@code OpenAIEmbed} (OpenAI models only, no base-URL option)
 * and {@code PromptOllama} (chat only), but nothing that embeds through
 * Ollama -- hence this stage. It calls Ollama's {@code /api/embed} directly
 * with the JDK HTTP client, so the module takes on no new dependency.
 *
 * <p>Throughput is GPU-bound, not request-bound: one document per request with
 * ~4 Lucille worker threads measured the same ~100 docs/s as 64-document
 * batches (nomic-embed-text, M4 Max). So there's no batching here.
 *
 * <p>Asymmetric models such as nomic-embed-text expect a task prefix
 * ({@code "search_document: "} at ingest, {@code "search_query: "} at query
 * time); set {@code prefix} to match what the query side prepends.
 *
 * <p>Failure is hard, never silent: {@link #start()} refuses to run if the
 * server is unreachable or the model isn't pulled, and a document that still
 * can't be embedded after retries throws. An index of products with no vectors
 * would look healthy and quietly turn every hybrid query into BM25-only.
 *
 * <p>Configuration:
 * <pre>{@code
 * {
 *   name: "embedChunkText"
 *   class: "com.kmwllc.esci.OllamaEmbedStage"
 *   source: "chunk_text"
 *   dest: "embedding"                 # optional, default "embedding"
 *   hostURL: ${OLLAMA_HOST}           # e.g. http://host.docker.internal:11434
 *   modelName: "nomic-embed-text"
 *   prefix: "search_document: "       # optional, default ""
 *   dimensions: 768                   # optional; asserts the vector length
 *   timeoutSeconds: 120               # optional, default 120
 * }
 * }</pre>
 */
public class OllamaEmbedStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(OllamaEmbedStage.class);
  private static final ObjectMapper MAPPER = new ObjectMapper();
  static final int MAX_ATTEMPTS = 4;

  public static final Spec SPEC =
      SpecBuilder.stage()
          .requiredString("source", "hostURL", "modelName")
          .optionalString("dest", "prefix")
          .optionalNumber("dimensions", "timeoutSeconds")
          .build();

  private final String source;
  private final String dest;
  private final String hostURL;
  private final String modelName;
  private final String prefix;
  private final Integer dimensions;
  private final Duration timeout;
  // Package-private so tests can shorten it; production backs off 1s, 2s, 4s.
  long retryBaseMillis = 1000;

  private HttpClient http;

  public OllamaEmbedStage(com.typesafe.config.Config config) {
    super(config);
    this.source = config.getString("source");
    this.dest = config.hasPath("dest") ? config.getString("dest") : "embedding";
    this.hostURL = config.getString("hostURL").replaceAll("/+$", "");
    this.modelName = config.getString("modelName");
    this.prefix = config.hasPath("prefix") ? config.getString("prefix") : "";
    this.dimensions = config.hasPath("dimensions") ? config.getInt("dimensions") : null;
    this.timeout =
        Duration.ofSeconds(config.hasPath("timeoutSeconds") ? config.getInt("timeoutSeconds") : 120);
  }

  @Override
  public void start() throws StageException {
    http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    // One real embed call up front: proves the server is reachable, the model
    // is pulled, and the vector has the expected length -- before any
    // document goes through.
    float[] probe;
    try {
      probe = embed("probe");
    } catch (StageException e) {
      throw new StageException(
          "Ollama embedding model '" + modelName + "' is not usable at " + hostURL
              + " -- is Ollama running and has `ollama pull " + modelName + "` been done?"
              + " Refusing to index products without vectors.",
          e);
    }
    log.info("Ollama embeddings ready: model={} host={} dims={}", modelName, hostURL, probe.length);
  }

  @Override
  public Iterator<Document> processDocument(Document doc) throws StageException {
    if (!doc.hasNonNull(source) || doc.getString(source).isBlank()) {
      log.warn("Doc {} has no '{}' text -- indexing it without an embedding", doc.getId(), source);
      return null;
    }
    float[] vector = embed(prefix + doc.getString(source));
    Float[] boxed = new Float[vector.length];
    for (int i = 0; i < vector.length; i++) {
      boxed[i] = vector[i];
    }
    doc.update(dest, UpdateMode.OVERWRITE, boxed);
    return null;
  }

  /** One text -> one vector, retrying transient failures (connection errors, 5xx). */
  float[] embed(String text) throws StageException {
    ObjectNode body = MAPPER.createObjectNode().put("model", modelName).put("input", text);
    HttpRequest request =
        HttpRequest.newBuilder(URI.create(hostURL + "/api/embed"))
            .timeout(timeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
            .build();

    Exception last = null;
    for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      try {
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        int status = response.statusCode();
        if (status == 200) {
          return parseVector(response.body());
        }
        last = new IOException("HTTP " + status + ": " + response.body());
        if (status < 500) {
          break; // a 4xx (e.g. unknown model) won't fix itself on retry
        }
      } catch (IOException e) {
        last = e;
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new StageException("Interrupted while embedding", e);
      }
      if (attempt < MAX_ATTEMPTS) {
        sleep(retryBaseMillis << (attempt - 1));
      }
    }
    throw new StageException("Ollama /api/embed failed for model " + modelName + ": " + last, last);
  }

  private float[] parseVector(String json) throws StageException {
    JsonNode vectors;
    try {
      vectors = MAPPER.readTree(json).path("embeddings");
    } catch (IOException e) {
      throw new StageException("Unparseable /api/embed response", e);
    }
    if (!vectors.isArray() || vectors.isEmpty() || !vectors.get(0).isArray()) {
      throw new StageException("/api/embed response has no embeddings: " + json);
    }
    JsonNode first = vectors.get(0);
    if (dimensions != null && first.size() != dimensions) {
      throw new StageException(
          "Model " + modelName + " returned " + first.size() + "-dim vectors, expected "
              + dimensions + " (the index mapping's knn_vector dimension)");
    }
    float[] out = new float[first.size()];
    for (int i = 0; i < out.length; i++) {
      out[i] = (float) first.get(i).asDouble();
    }
    return out;
  }

  private static void sleep(long millis) throws StageException {
    try {
      Thread.sleep(millis);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new StageException("Interrupted while backing off", e);
    }
  }
}
