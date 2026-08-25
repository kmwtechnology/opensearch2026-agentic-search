# syntax=docker/dockerfile:1
#
# Lucille ETL runtime with custom ESCI stages, built entirely from artifacts
# resolved via Maven (com.kmwllc:lucille-core, lucille-parquet, and their
# transitives are published to Maven Central by kmwtechnology — see
# https://github.com/kmwtechnology/lucille pom.xml distributionManagement,
# which deploys releases to Sonatype Central). No dependency on a prebuilt/
# private Lucille Docker image (kmwtechnology/lucille was never published to
# a registry this build can reach).
#
# Stage 1: Compile our custom ESCI stage (AttributeNormalizerStage for
# color/brand normalization) and resolve every runtime dependency —
# including lucille-core itself — from Maven Central via lucille-esci/pom.xml.
# No Lucille source checkout needed.
#
# Stage 2: Layer the compiled stage + all resolved JARs (lucille-core,
# lucille-parquet, transitives) onto a plain JRE base image. This mirrors
# kmwtechnology/lucille's own Dockerfile (eclipse-temurin:21-jre + lucille.jar
# + lib/ + entrypoint script) but built from Central artifacts instead.
#
# Runtime entrypoint uses LUCILLE_CONF, LUCILLE_OPTS, and JAVA_OPTS env vars.

ARG LUCILLE_VERSION

# Build stage: custom stage + all runtime deps (lucille-core, lucille-parquet,
# transitives) resolved from Maven Central.
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

# Runtime stage: plain JRE base (matches kmwtechnology/lucille's own Dockerfile)
# + our custom stage jar + every Maven-Central-resolved runtime dependency.
FROM eclipse-temurin:21-jre

LABEL description="Lucille Search ETL with custom ESCI attribute normalizer stage (built from Maven Central artifacts)"

WORKDIR /lucille
RUN mkdir -p /lucille/conf /lucille/lib

# Custom stage jar + lucille-core/lucille-parquet/transitives, all resolved
# from Maven Central in the build stage above.
COPY --from=build /build/lucille-esci/target/lucille-esci-1.0.0.jar /lucille/lib/
COPY --from=build /app/lib/*.jar /lucille/lib/

RUN groupadd -r lucille \
 && useradd -r -g lucille -d /lucille -s /usr/sbin/nologin lucille \
 && chown -R lucille:lucille /lucille

# Environment variables with sensible defaults
# LUCILLE_CONF: path to the Lucille config file (required)
# JAVA_OPTS: JVM flags such as heap size and GC settings
# LUCILLE_OPTS: Lucille Runner CLI flags (e.g. -distributed, -external)
ENV LUCILLE_CONF=""
ENV LUCILLE_OPTS=""
ENV JAVA_OPTS=""

COPY docker/lucille/docker-entrypoint.sh /lucille/docker-entrypoint.sh
RUN chmod +x /lucille/docker-entrypoint.sh

USER lucille

ENTRYPOINT ["/lucille/docker-entrypoint.sh"]
