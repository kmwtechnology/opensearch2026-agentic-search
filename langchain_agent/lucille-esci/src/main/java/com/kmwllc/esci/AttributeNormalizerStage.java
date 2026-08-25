package com.kmwllc.esci;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kmwllc.lucille.core.Document;
import com.kmwllc.lucille.core.Stage;
import com.kmwllc.lucille.core.UpdateMode;
import com.kmwllc.lucille.core.spec.Spec;
import com.kmwllc.lucille.core.spec.SpecBuilder;
import com.typesafe.config.Config;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Lucille stage for normalizing product colors and brands.
 *
 * <p>Loads color_mappings.json and normalizes raw color/brand strings to canonical forms:
 * - Colors: 16 canonical forms (black, white, blue, red, green, yellow, pink, purple, brown,
 *   gray, orange, clear, multicolor, natural, mixed)
 * - Brands: lowercase + generic consolidation
 *
 * <p>Configuration (in products.conf):
 * <pre>{@code
 * {
 *   name: "normalizeAttributes"
 *   class: "com.kmwllc.esci.AttributeNormalizerStage"
 *   colorMappingsPath: "/lucille/conf/color_mappings.json"
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

  public static final Spec SPEC = SpecBuilder.stage()
      .optionalString("colorMappingsPath").build();

  protected Map<String, String> colorLookup;
  protected Set<String> genericBrandPatterns;

  public AttributeNormalizerStage(com.typesafe.config.Config config) {
    super(config);
  }

  /** Initialize stage: load color_mappings.json and build reverse lookup. */
  @Override
  public void start() {
    String colorMappingsPath = "color_mappings.json";
    if (config.hasPath("colorMappingsPath")) {
      colorMappingsPath = config.getString("colorMappingsPath");
    }

    try {
      String json = Files.readString(Paths.get(colorMappingsPath));
      ObjectMapper mapper = new ObjectMapper();
      @SuppressWarnings("unchecked")
      Map<String, Object> mappings = mapper.readValue(json, Map.class);

      // Build reverse lookup: variant → canonical
      this.colorLookup = new HashMap<>();
      @SuppressWarnings("unchecked")
      Map<String, List<String>> baseColors = (Map<String, List<String>>) mappings.get("base_colors");

      if (baseColors != null) {
        for (Map.Entry<String, List<String>> entry : baseColors.entrySet()) {
          String canonical = entry.getKey();
          for (String variant : entry.getValue()) {
            colorLookup.put(variant.toLowerCase(), canonical);
          }
        }
      }

      log.info("Loaded {} color mappings from {}", colorLookup.size(), colorMappingsPath);
    } catch (Exception e) {
      log.warn("Failed to load color_mappings.json from {}: {}", colorMappingsPath, e.getMessage());
      this.colorLookup = new HashMap<>();
    }

    // Brand generics
    this.genericBrandPatterns =
        Set.of(
            "generic", "unknown", "unbranded", "brand not specified",
            "as shown", "various", "multiple", "not specified");
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
