# syntax=docker/dockerfile:1
#
# Lucille ETL runtime with custom ESCI stages, layered onto the published image.
#
# Strategy: Use the prebuilt kmwtechnology/lucille image (published to Docker Hub)
# as the base, and only compile + layer our custom stages. This avoids rebuilding
# Lucille itself on every CI run.
#
# Stage 1: Compile custom ESCI stages only (lucille-esci/src/ contains
# AttributeNormalizerStage for color/brand normalization). Maven resolves
# lucille-parquet and other deps from Maven Central via lucille-esci/pom.xml.
# No Lucille source checkout needed.
#
# Stage 2: Layer compiled stages + dependencies onto the published base image.
# The kmwtechnology/lucille image already has lucille-core and the runner;
# we only add our custom stages and the lucille-parquet plugin it needs.
#
# Runtime entrypoint uses LUCILLE_CONF, LUCILLE_OPTS, and JAVA_OPTS env vars.

# Compile stage: custom stages + dependencies from Maven Central
# (lucille-core is already in the base image, no need to re-resolve it)
ARG LUCILLE_VERSION
FROM maven:3.9-eclipse-temurin-21-alpine AS build
ARG LUCILLE_VERSION
COPY langchain_agent/lucille-esci /build/lucille-esci
WORKDIR /build/lucille-esci
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q package \
      -Dlucille.version="${LUCILLE_VERSION}" \
      -DskipTests && \
    mvn -B -q dependency:copy-dependencies \
      -Dlucille.version="${LUCILLE_VERSION}" \
      -DincludeScope=runtime \
      -DoutputDirectory=/app/lib && \
    rm -rf /build/lucille-esci/target/classes /build/lucille-esci/src

# Runtime stage: layer onto published kmwtechnology/lucille image (not a bare JRE)
# The published image already has lucille-core, Runner, and base config.
ARG LUCILLE_VERSION
FROM kmwtechnology/lucille:${LUCILLE_VERSION}

LABEL description="Lucille Search ETL with custom ESCI attribute normalizer stage"

# Layer compiled custom stages into the existing /lucille/lib/
COPY --from=build /build/lucille-esci/target/lucille-esci-1.0.0.jar /lucille/lib/

# Layer runtime dependencies (lucille-parquet + transitives)
# The published image already has lucille-core, so we only add what's missing.
COPY --from=build /app/lib/*.jar /lucille/lib/

# Ensure ownership is correct (published image may have different user)
RUN chown -R lucille:lucille /lucille 2>/dev/null || true
