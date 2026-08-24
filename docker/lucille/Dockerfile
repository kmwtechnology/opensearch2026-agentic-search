# syntax=docker/dockerfile:1
#
# Resolves Lucille (core + the parquet connector plugin) from Maven Central,
# pinned to LUCILLE_VERSION — the same value used by lucille-esci/pom.xml and
# lucille_ingest.sh — by reusing that same pom.xml as the dependency manifest.
# No git clone or compile step: Lucille 0.11.1+ publishes real releases to
# Maven Central, so this is a plain dependency resolution + flatten, the same
# mechanism already verified end-to-end for the lucille-esci module.
#
# Not extending the published kmwtechnology/lucille Docker Hub image because
# that image is tagged <version>.<docker_revision> (e.g. 0.11.1.0) — a scheme
# not algorithmically derivable from LUCILLE_VERSION — and is amd64-only, so
# Apple Silicon would run it under emulation. Maven Central artifacts are
# plain, architecture-independent jars and use the clean LUCILLE_VERSION tag.
#
# Runtime layout and entrypoint mirror upstream's own Dockerfile:
# https://github.com/kmwtechnology/lucille/blob/main/Dockerfile

FROM maven:3.9-eclipse-temurin-21 AS deps
ARG LUCILLE_VERSION
COPY langchain_agent/lucille-esci/pom.xml /build/pom.xml
WORKDIR /build
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q dependency:copy-dependencies \
      -Dlucille.version="${LUCILLE_VERSION}" \
      -DincludeScope=runtime \
      -DoutputDirectory=/deps

FROM eclipse-temurin:21-jre

LABEL maintainer="kmwtechnology"
LABEL description="Lucille Search ETL image, resolved from Maven Central with the parquet connector"

WORKDIR /lucille
RUN mkdir -p /lucille/conf /lucille/lib

COPY --from=deps /deps/*.jar /lucille/lib/

RUN groupadd -r lucille \
 && useradd -r -g lucille -d /lucille -s /usr/sbin/nologin lucille \
 && chown -R lucille:lucille /lucille

# LUCILLE_CONF: path to the Lucille config file (required)
# JAVA_OPTS: JVM flags such as heap size and GC settings
# LUCILLE_OPTS: Lucille Runner CLI flags
ENV LUCILLE_CONF=""
ENV LUCILLE_OPTS=""
ENV JAVA_OPTS=""

COPY docker/lucille/docker-entrypoint.sh /lucille/docker-entrypoint.sh
RUN chmod +x /lucille/docker-entrypoint.sh

USER lucille

ENTRYPOINT ["/lucille/docker-entrypoint.sh"]
