package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;

import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.StageException;
import com.sun.net.httpserver.HttpServer;
import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Unit tests for OllamaEmbedStage, against a real in-process HTTP server that
 * stands in for Ollama's /api/embed -- so the request body, status handling and
 * retries are exercised for real rather than mocked.
 */
class OllamaEmbedStageTest {

  private HttpServer server;
  private final List<String> requestBodies = new ArrayList<>();
  private final AtomicInteger failuresBeforeSuccess = new AtomicInteger(0);
  private volatile int failureStatus = 503;
  private volatile String responseBody = "{\"embeddings\":[[0.1,0.2,0.3]]}";

  @BeforeEach
  void startServer() throws IOException {
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext(
        "/api/embed",
        exchange -> {
          synchronized (requestBodies) {
            requestBodies.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
          }
          boolean fail = failuresBeforeSuccess.getAndUpdate(n -> Math.max(0, n - 1)) > 0;
          byte[] out = (fail ? "{\"error\":\"boom\"}" : responseBody).getBytes(StandardCharsets.UTF_8);
          exchange.sendResponseHeaders(fail ? failureStatus : 200, out.length);
          try (OutputStream os = exchange.getResponseBody()) {
            os.write(out);
          }
        });
    server.start();
  }

  @AfterEach
  void stopServer() {
    server.stop(0);
  }

  private OllamaEmbedStage stage(Map<String, Object> overrides) throws StageException {
    Map<String, Object> conf = new java.util.HashMap<>(Map.of(
        "name", "embed",
        "class", OllamaEmbedStage.class.getName(),
        "source", "chunk_text",
        "hostURL", "http://127.0.0.1:" + server.getAddress().getPort() + "/",
        "modelName", "nomic-embed-text"));
    conf.putAll(overrides);
    Config config = ConfigFactory.parseMap(conf);
    OllamaEmbedStage stage = new OllamaEmbedStage(config);
    stage.retryBaseMillis = 1;
    stage.start();
    return stage;
  }

  @Test
  void embedsSourceIntoDestWithPrefix() throws Exception {
    OllamaEmbedStage stage = stage(Map.of("prefix", "search_document: ", "dimensions", 3));
    Document doc = Document.create("B0001");
    doc.setField("chunk_text", "blue running shoes");

    stage.processDocument(doc);

    assertEquals(List.of(0.1f, 0.2f, 0.3f), doc.getFloatList("embedding"));
    String last = requestBodies.get(requestBodies.size() - 1);
    assertTrue(last.contains("\"model\":\"nomic-embed-text\""), last);
    assertTrue(last.contains("\"input\":\"search_document: blue running shoes\""), last);
  }

  @Test
  void customDestField() throws Exception {
    OllamaEmbedStage stage = stage(Map.of("dest", "vec"));
    Document doc = Document.create("B0002");
    doc.setField("chunk_text", "tan boots");
    stage.processDocument(doc);
    assertEquals(3, doc.getFloatList("vec").size());
    assertFalse(doc.has("embedding"));
  }

  @Test
  void blankSourceIsSkippedNotEmbedded() throws Exception {
    OllamaEmbedStage stage = stage(Map.of());
    int before = requestBodies.size();
    Document doc = Document.create("B0003");
    doc.setField("chunk_text", "   ");
    stage.processDocument(doc);
    assertFalse(doc.has("embedding"));
    assertEquals(before, requestBodies.size());
  }

  @Test
  void retriesTransient5xxThenSucceeds() throws Exception {
    OllamaEmbedStage stage = stage(Map.of());
    failuresBeforeSuccess.set(OllamaEmbedStage.MAX_ATTEMPTS - 1);
    Document doc = Document.create("B0004");
    doc.setField("chunk_text", "sewing machine");
    stage.processDocument(doc);
    assertEquals(3, doc.getFloatList("embedding").size());
  }

  @Test
  void persistent5xxFailsTheDocument() throws Exception {
    OllamaEmbedStage stage = stage(Map.of());
    failuresBeforeSuccess.set(OllamaEmbedStage.MAX_ATTEMPTS);
    Document doc = Document.create("B0005");
    doc.setField("chunk_text", "waterproof boots");
    assertThrows(StageException.class, () -> stage.processDocument(doc));
  }

  @Test
  void clientErrorIsNotRetried() throws Exception {
    OllamaEmbedStage stage = stage(Map.of());
    failureStatus = 404;
    failuresBeforeSuccess.set(1);
    int before = requestBodies.size();
    Document doc = Document.create("B0006");
    doc.setField("chunk_text", "boots");
    assertThrows(StageException.class, () -> stage.processDocument(doc));
    assertEquals(before + 1, requestBodies.size());
  }

  @Test
  void startFailsWhenServerUnreachable() {
    server.stop(0);
    assertThrows(StageException.class, () -> stage(Map.of()));
  }

  @Test
  void startFailsOnDimensionMismatch() {
    assertThrows(StageException.class, () -> stage(Map.of("dimensions", 768)));
  }

  @Test
  void startFailsOnResponseWithoutEmbeddings() {
    responseBody = "{\"embeddings\":[]}";
    assertThrows(StageException.class, () -> stage(Map.of()));
  }
}
