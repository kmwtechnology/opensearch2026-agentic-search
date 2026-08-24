# syntax=docker/dockerfile:1
#
# Builds and containerizes the Lucille ETL pipeline with custom ESCI stages.
#
# Stage 1: Compile lucille-esci Java source code and resolve all runtime dependencies.
# lucille-esci/src/ contains custom Lucille stages (e.g., AttributeNormalizerStage for
# color/brand normalization); lucille-esci/pom.xml pins the Lucille version (via the
# LUCILLE_VERSION build arg) and declares dependencies on lucille-core, lucille-parquet,
# and JAXB compat. Maven compiles the custom stages and copies all runtime deps to
# /app/lib/ for the final classpath.
#
# Stage 2: Runtime image — JRE with all compiled stages and dependencies.
#
# Note: lucille-esci/pom.xml + Maven Central resolution is enough — no Lucille source
# checkout needed. All runtime jars (lucille-core, lucille-parquet, JAXB compat, and
# custom stages) are resolved/compiled and layered into a minimal JRE image.
#
# Runtime entrypoint uses LUCILLE_CONF, LUCILLE_OPTS, and JAVA_OPTS env vars.

# Build stage: compile custom stages + resolve dependencies
# Uses lightweight Maven image to reduce build layer size (~400MB vs 800MB for full Maven)
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

# Runtime stage: minimal JRE with all compiled stages and dependencies
FROM eclipse-temurin:21-jre-alpine

LABEL maintainer="kmwtechnology"
LABEL description="Lucille Search ETL with custom ESCI attribute normalizer stage"

WORKDIR /lucille
RUN mkdir -p /lucille/conf /lucille/lib

# Copy compiled custom stages (AttributeNormalizerStage + classes)
COPY --from=build /build/lucille-esci/target/lucille-esci-1.0.0.jar /lucille/lib/

# Copy all resolved dependencies (lucille-core, lucille-parquet, JAXB compat, and transitive deps)
COPY --from=build /app/lib/*.jar /lucille/lib/

# Create non-root user for security
RUN addgroup -g 1000 lucille \
 && adduser -D -u 1000 -G lucille lucille \
 && chown -R lucille:lucille /lucille

# Environment variables for Lucille Runner
ENV LUCILLE_CONF=""
ENV LUCILLE_OPTS=""
ENV JAVA_OPTS=""

COPY docker/lucille/docker-entrypoint.sh /lucille/docker-entrypoint.sh
RUN chmod +x /lucille/docker-entrypoint.sh

USER lucille

ENTRYPOINT ["/lucille/docker-entrypoint.sh"]
