# syntax=docker/dockerfile:1
#
# Lucille ETL runtime with custom ESCI stages, layered onto Lucille's own
# published base image.
#
# Two separate version namespaces are in play here — don't conflate them:
#   - LUCILLE_VERSION     Maven artifact version (e.g. "0.11.1"), used to
#                         resolve com.kmwllc:lucille-core/-parquet/-bom from
#                         Maven Central (kmwtechnology's pom.xml
#                         distributionManagement deploys releases there).
#   - LUCILLE_DOCKER_TAG  Docker Hub tag (e.g. "0.11.1.0") — Lucille's own
#                         release-to-docker.yml appends a docker_revision
#                         suffix ("${release_version}.${docker_revision}")
#                         that has no Maven equivalent and isn't derivable
#                         from LUCILLE_VERSION by string concatenation (the
#                         revision can be nonzero on a Dockerfile-only re-cut).
#                         Using the bare Maven version as the image tag 404s —
#                         that mismatch was the root cause of a full day's
#                         debugging here. Verify actual tags at
#                         https://hub.docker.com/r/kmwtechnology/lucille/tags
#                         before bumping either variable.
#   - LUCILLE_DOCKER_DIGEST  sha256 digest for LUCILLE_DOCKER_TAG's current
#                         content, pinned via `FROM ...:TAG@DIGEST`. Every
#                         local build resolves to this exact image content
#                         — a tag alone is mutable if kmwtechnology ever
#                         repushes it. Get the current digest with:
#                           docker pull kmwtechnology/lucille:<TAG>
#                           docker image inspect kmwtechnology/lucille:<TAG> \
#                             --format '{{index .RepoDigests 0}}'
#                         Re-run this whenever LUCILLE_DOCKER_TAG changes.
#
# Stage 1: Compile our custom ESCI stage (AttributeNormalizerStage for
# color/brand normalization) and resolve its runtime deps — lucille-parquet
# (for ParquetConnector) and lucille-core (needed at compile time; already
# present in the Stage 2 base image, see note below) — from Maven Central via
# lucille-esci/pom.xml. No Lucille source checkout needed.
#
# Stage 2: Layer the compiled stage + resolved JARs onto the published
# kmwtechnology/lucille image, which already ships lucille-core, its own
# runtime deps, the lucille user, and an identical entrypoint script — so
# nothing else needs to be recreated here. This does mean lucille-core (and
# its own transitives) get copied a second time on top of what the base
# image already has; that duplication was measured and is small next to the
# base image's own size, so it's left as-is rather than threading a Maven
# profile through to mark lucille-core `provided` — the native (non-Docker)
# ingest path (scripts/lucille_ingest.sh, LUCILLE_USE_DOCKER=false) shares
# this same pom.xml/target/lib output and needs lucille-core's Runner class
# on its classpath directly, so scoping it out here isn't free.
#
# hadoop-aws (and its ~680MB software.amazon.awssdk:bundle transitive) is
# excluded from lucille-parquet in pom.xml — it only backs the s3a://
# filesystem scheme, and every config here reads local parquet files
# (fsUri: "file:///"). That exclusion is what keeps this layer small; without
# it the image blew past the CI runner's disk budget.
#
# Runtime entrypoint uses LUCILLE_CONF, LUCILLE_OPTS, and JAVA_OPTS env vars
# (all defined by the base image already).

ARG LUCILLE_VERSION=0.11.1
ARG LUCILLE_DOCKER_TAG=0.11.1.0
ARG LUCILLE_DOCKER_DIGEST=sha256:cefa9a3b2b9ed4c3cdf92da9abb93da37dc8ba392cc64ef39b81e02387f81073

# Build stage: our custom stage + lucille-parquet + lucille-core (compile-time),
# resolved from Maven Central.
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

# Runtime stage: the published base already has lucille-core, the lucille
# user, WORKDIR, env defaults, and this exact entrypoint script — only the
# jars are new. Pinned by digest (not just tag) so every build is
# guaranteed to use byte-identical base image content.
FROM kmwtechnology/lucille:${LUCILLE_DOCKER_TAG}@${LUCILLE_DOCKER_DIGEST}

LABEL description="Lucille Search ETL with custom ESCI attribute normalizer stage"

COPY --from=build --chown=lucille:lucille /build/lucille-esci/target/lucille-esci-1.0.0.jar /lucille/lib/
COPY --from=build --chown=lucille:lucille /app/lib/*.jar /lucille/lib/
