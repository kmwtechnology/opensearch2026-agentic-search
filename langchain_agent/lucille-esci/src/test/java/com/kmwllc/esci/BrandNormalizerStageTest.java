package com.kmwllc.esci;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.kmwllc.lucille.core.Document;
import com.typesafe.config.Config;
import java.util.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Unit tests for BrandNormalizerStage. */
class BrandNormalizerStageTest {

  private BrandNormalizerStage stage;

  @BeforeEach
  void setUp() {
    Config mockConfig = mock(Config.class);
    stage = new BrandNormalizerStage(mockConfig);
    stage.start();
  }

  @Test
  void testBrandSimple() {
    assertEquals("nike", stage.normalizeBrand("Nike"));
  }

  @Test
  void testBrandLowercase() {
    assertEquals("adidas", stage.normalizeBrand("ADIDAS"));
  }

  @Test
  void testBrandGenericPlaceholder() {
    assertEquals("generic", stage.normalizeBrand("generic"));
  }

  @Test
  void testBrandUnknown() {
    assertEquals("generic", stage.normalizeBrand("unknown"));
  }

  @Test
  void testBrandNotSpecified() {
    assertEquals("generic", stage.normalizeBrand("brand not specified"));
  }

  @Test
  void testBrandEmpty() {
    assertEquals("generic", stage.normalizeBrand(""));
  }

  @Test
  void testBrandNull() {
    assertEquals("generic", stage.normalizeBrand(null));
  }

  @Test
  void testBrandWhitespace() {
    assertEquals("generic", stage.normalizeBrand("   "));
  }

  @Test
  void testBrandVariousGenericForms() {
    assertEquals("generic", stage.normalizeBrand("as shown"));
    assertEquals("generic", stage.normalizeBrand("various"));
    assertEquals("generic", stage.normalizeBrand("multiple"));
    assertEquals("generic", stage.normalizeBrand("not specified"));
    assertEquals("generic", stage.normalizeBrand("unbranded"));
  }

  @Test
  void testProcessDocumentSetsNormalizedField() {
    Document doc = Document.create("doc1");
    doc.setField("product_brand", "Sony");

    stage.processDocument(doc);

    assertEquals("sony", doc.getString("product_brand_normalized"));
  }

  @Test
  void testProcessDocumentSkipsWhenNoBrandField() {
    Document doc = Document.create("doc1");
    assertDoesNotThrow(() -> stage.processDocument(doc));
    assertFalse(doc.has("product_brand_normalized"));
  }
}
