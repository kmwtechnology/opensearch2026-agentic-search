package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kmwllc.lucille.core.Document;
import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;
import java.util.Set;
import org.junit.jupiter.api.Test;

/**
 * Unit tests for FilterJudgmentsToProductsStage's processDocument logic.
 * Bypasses start()'s real OpenSearch scroll by setting productIds directly,
 * same pattern as AttributeDetectorStageTest bypasses its lookup load.
 */
class FilterJudgmentsToProductsStageTest {

  private final ObjectMapper mapper = new ObjectMapper();

  private FilterJudgmentsToProductsStage stageWithProductIds(Set<String> productIds) {
    Config config = ConfigFactory.parseString(
        "opensearch { url: \"http://localhost:1\", index: \"test_products\" }");
    // start() (the real OpenSearch scroll) is deliberately never called --
    // productIds is set directly, same bypass AttributeDetectorStageTest uses.
    FilterJudgmentsToProductsStage stage = new FilterJudgmentsToProductsStage(config);
    stage.productIds = productIds;
    return stage;
  }

  private JsonNode judgments(String... entries) throws Exception {
    // entries like "B001:4.0", alternating product_id:relevance pairs
    StringBuilder json = new StringBuilder("[");
    for (int i = 0; i < entries.length; i++) {
      String[] parts = entries[i].split(":");
      if (i > 0) {
        json.append(",");
      }
      json.append("{\"product_id\":\"").append(parts[0])
          .append("\",\"esci_label\":\"E\",\"relevance\":").append(parts[1]).append("}");
    }
    json.append("]");
    return mapper.readTree(json.toString());
  }

  @Test
  void testKeepsOnlyJudgmentsForKnownProducts() throws Exception {
    FilterJudgmentsToProductsStage stage = stageWithProductIds(Set.of("B001", "B003"));
    Document doc = Document.create("q1");
    doc.setField("judgments", judgments("B001:4.0", "B002:1.0", "B003:0.1"));

    stage.processDocument(doc);

    assertFalse(doc.isDropped());
    JsonNode kept = doc.getJson("judgments");
    assertEquals(2, kept.size());
    assertEquals("B001", kept.get(0).get("product_id").asText());
    assertEquals("B003", kept.get(1).get("product_id").asText());
    assertEquals(2, doc.getInt("num_judgments"));
  }

  @Test
  void testDropsDocumentWhenNoProductsMatch() throws Exception {
    FilterJudgmentsToProductsStage stage = stageWithProductIds(Set.of("B999"));
    Document doc = Document.create("q1");
    doc.setField("judgments", judgments("B001:4.0", "B002:1.0"));

    stage.processDocument(doc);

    assertTrue(doc.isDropped());
  }

  @Test
  void testDropsDocumentWhenJudgmentsFieldMissing() {
    FilterJudgmentsToProductsStage stage = stageWithProductIds(Set.of("B001"));
    Document doc = Document.create("q1");

    stage.processDocument(doc);

    assertTrue(doc.isDropped());
  }

  @Test
  void testKeepsAllJudgmentsWhenAllProductsKnown() throws Exception {
    FilterJudgmentsToProductsStage stage = stageWithProductIds(Set.of("B001", "B002"));
    Document doc = Document.create("q1");
    doc.setField("judgments", judgments("B001:4.0", "B002:1.0"));

    stage.processDocument(doc);

    assertFalse(doc.isDropped());
    assertEquals(2, doc.getJson("judgments").size());
    assertEquals(2, doc.getInt("num_judgments"));
  }
}
