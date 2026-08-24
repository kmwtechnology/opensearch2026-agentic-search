FROM opensearchproject/opensearch:2.19.1

# Install analysis-phonetic plugin for phonetic matching (Soundex, Metaphone, etc.)
# Must run with --batch flag to skip confirmation prompts
RUN opensearch-plugin install --batch analysis-phonetic
