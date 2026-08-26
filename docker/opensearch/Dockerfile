ARG OPENSEARCH_VERSION=3.8.0
ARG OPENSEARCH_DIGEST=sha256:bcc1797519726ceb6d651d4a3e60b7c30da91793914a8dfe75fd441d4f641509

FROM opensearchproject/opensearch:${OPENSEARCH_VERSION}@${OPENSEARCH_DIGEST}

# Install analysis-phonetic plugin for phonetic matching (Soundex, Metaphone, etc.)
# Must run with --batch flag to skip confirmation prompts
RUN opensearch-plugin install --batch analysis-phonetic
