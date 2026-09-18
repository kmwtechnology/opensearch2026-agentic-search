package com.kmwllc.esci;

import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import java.util.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Lucille stage for normalizing product brand names.
 *
 * <p>Unlike color/waterproof (discovered variant->canonical taxonomies, sourced
 * from the OpenSearch-backed attribute mapping store via {@link
 * AttributeDetectorStage}), brand normalization is a fixed, deterministic
 * transform — lowercase plus generic-placeholder consolidation — with no
 * taxonomy to discover or grow. Kept as its own small, always-present stage
 * with no OpenSearch dependency, always in the generated config's fixed
 * prelude.
 *
 * <p>Configuration (in generated products.conf):
 * <pre>{@code
 * {
 *   name: "normalizeBrand"
 *   class: "com.kmwllc.esci.BrandNormalizerStage"
 * }
 * }</pre>
 *
 * <p>Outputs (per document):
 * - product_brand_normalized: normalized brand (lowercase; "generic" if
 *   placeholder, otherwise original lowercased)
 */
public class BrandNormalizerStage extends Stage {
  private static final Logger log = LoggerFactory.getLogger(BrandNormalizerStage.class);

  public static final Spec SPEC = SpecBuilder.stage().build();

  protected Set<String> genericBrandPatterns;

  public BrandNormalizerStage(com.typesafe.config.Config config) {
    super(config);
  }

  @Override
  public void start() {
    this.genericBrandPatterns =
        Set.of(
            "generic", "unknown", "unbranded", "brand not specified",
            "as shown", "various", "multiple", "not specified");
  }

  @Override
  public Iterator<Document> processDocument(Document doc) {
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
