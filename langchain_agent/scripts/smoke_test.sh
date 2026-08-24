#!/bin/bash
###############################################################################
# Smoke Test Script
#
# Standalone bash script to run smoke tests against any deployment.
# Tests all critical endpoints and validates response formats.
#
# Usage:
#   ./scripts/smoke_test.sh http://localhost:8000
#   ./scripts/smoke_test.sh https://agentic-hybrid-search-xyz.us-central1.run.app
#
# Environment Variables:
#   API_KEY - Optional API key for authenticated requests (default: "test-api-key")
#   TIMEOUT - Curl timeout in seconds (default: 10)
###############################################################################

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_URL="${1:-http://localhost:8000}"
API_KEY="${API_KEY:-test-api-key}"
TIMEOUT="${TIMEOUT:-10}"
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
log_test() {
    echo -e "${BLUE}▶${NC} $1"
}

log_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((TESTS_PASSED++))
}

log_fail() {
    echo -e "${RED}✗${NC} $1"
    ((TESTS_FAILED++))
}

log_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Validate URL format
validate_url() {
    if ! [[ "$SERVICE_URL" =~ ^https?:// ]]; then
        log_fail "Invalid URL format. Must start with http:// or https://"
        exit 1
    fi
}

# Test health endpoint
test_health() {
    log_test "Testing health endpoint"

    response=$(curl -s -w "\n%{http_code}" --max-time "$TIMEOUT" "$SERVICE_URL/api/health" || echo "000")
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)

    if [ "$http_code" != "200" ]; then
        log_fail "Health endpoint returned $http_code (expected 200)"
        echo "Response: $body"
        return 1
    fi

    # Verify JSON structure
    if ! echo "$body" | grep -q '"status"'; then
        log_fail "Health response missing 'status' field"
        return 1
    fi

    if ! echo "$body" | grep -q '"postgres"'; then
        log_fail "Health response missing 'postgres' field"
        return 1
    fi

    if ! echo "$body" | grep -q '"google_ai"'; then
        log_fail "Health response missing 'google_ai' field"
        return 1
    fi

    if ! echo "$body" | grep -q '"vector_store"'; then
        log_fail "Health response missing 'vector_store' field"
        return 1
    fi

    log_pass "Health endpoint responsive with all required fields"
    log_info "Response: $body"
}

# Test database connectivity
test_database() {
    log_test "Testing database connectivity via health check"

    response=$(curl -s --max-time "$TIMEOUT" "$SERVICE_URL/api/health")

    if echo "$response" | grep -q '"postgres": *true'; then
        log_pass "PostgreSQL is healthy"
    elif echo "$response" | grep -q '"postgres": *false'; then
        log_fail "PostgreSQL is not healthy"
        return 1
    else
        log_fail "Could not determine PostgreSQL status"
        return 1
    fi
}

# Test OpenSearch connectivity
test_opensearch() {
    log_test "Testing OpenSearch connectivity via health check"

    response=$(curl -s --max-time "$TIMEOUT" "$SERVICE_URL/api/health")

    if echo "$response" | grep -q '"vector_store": *true'; then
        log_pass "OpenSearch is healthy"
    elif echo "$response" | grep -q '"vector_store": *false'; then
        log_fail "OpenSearch is not healthy"
        return 1
    else
        log_fail "Could not determine OpenSearch status"
        return 1
    fi
}

# Test document count
test_document_count() {
    log_test "Testing product document count"

    response=$(curl -s --max-time "$TIMEOUT" "$SERVICE_URL/api/health")
    doc_count=$(echo "$response" | grep -o '"document_count": *[0-9]*' | grep -o '[0-9]*' || echo "0")

    if [ -z "$doc_count" ] || [ "$doc_count" -eq 0 ]; then
        log_fail "No products indexed (document_count: $doc_count)"
        return 1
    fi

    log_pass "Products indexed (count: $doc_count)"
}

# Test valid API key
test_valid_api_key() {
    log_test "Testing valid API key authentication"

    response=$(curl -s -w "\n%{http_code}" \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer $API_KEY" \
        "$SERVICE_URL/api/conversations" || echo "000")

    http_code=$(echo "$response" | tail -n1)

    # 200 or 400 is OK (means auth passed, data issue is separate)
    # 401/403 means auth failed
    if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
        log_fail "Valid API key rejected (HTTP $http_code)"
        return 1
    fi

    log_pass "Valid API key accepted (HTTP $http_code)"
}

# Test invalid API key
test_invalid_api_key() {
    log_test "Testing invalid API key rejection"

    response=$(curl -s -w "\n%{http_code}" \
        --max-time "$TIMEOUT" \
        -H "Authorization: Bearer invalid-fake-key-xyz" \
        "$SERVICE_URL/api/conversations" || echo "000")

    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
        log_pass "Invalid API key properly rejected (HTTP $http_code)"
    else
        log_fail "Invalid API key not rejected (HTTP $http_code, expected 401/403)"
        return 1
    fi
}

# Test response time
test_response_time() {
    log_test "Testing response time for health check"

    start_time=$(date +%s%N)
    curl -s --max-time "$TIMEOUT" "$SERVICE_URL/api/health" > /dev/null
    end_time=$(date +%s%N)

    elapsed_ms=$(( (end_time - start_time) / 1000000 ))

    if [ "$elapsed_ms" -lt 1000 ]; then
        log_pass "Health check responded in ${elapsed_ms}ms"
    else
        log_info "Health check took ${elapsed_ms}ms (acceptable)"
    fi
}

# Test service is accessible
test_service_accessible() {
    log_test "Testing service accessibility"

    if curl -s --max-time 5 "$SERVICE_URL/api/health" > /dev/null 2>&1; then
        log_pass "Service is accessible"
    else
        log_fail "Service is not accessible at $SERVICE_URL"
        return 1
    fi
}

# Test HTTPS certificate (for Cloud Run)
test_https_certificate() {
    if [[ "$SERVICE_URL" =~ ^https:// ]]; then
        log_test "Testing HTTPS certificate validation"

        if curl -s -I --cacert /etc/ssl/certs/ca-certificates.crt \
            --max-time "$TIMEOUT" "$SERVICE_URL/api/health" > /dev/null 2>&1; then
            log_pass "HTTPS certificate is valid"
        else
            log_fail "HTTPS certificate validation failed"
            return 1
        fi
    fi
}

# Run all tests
run_all_tests() {
    echo ""
    echo -e "${BLUE}====== Agentic Hybrid Search - Deployment Smoke Tests ======${NC}"
    echo ""
    log_info "Testing deployment: $SERVICE_URL"
    echo ""

    # Service connectivity
    echo -e "${BLUE}▬ Service Connectivity${NC}"
    test_service_accessible || true
    test_https_certificate || true

    # Basic health checks
    echo ""
    echo -e "${BLUE}▬ Health Checks${NC}"
    test_health || true
    test_database || true
    test_opensearch || true
    test_document_count || true

    # Authentication
    echo ""
    echo -e "${BLUE}▬ Authentication${NC}"
    test_valid_api_key || true
    test_invalid_api_key || true

    # Performance
    echo ""
    echo -e "${BLUE}▬ Performance${NC}"
    test_response_time || true

    # Summary
    echo ""
    echo -e "${BLUE}====== Test Summary ======${NC}"
    total=$((TESTS_PASSED + TESTS_FAILED))
    echo -e "Total: $total | ${GREEN}Passed: $TESTS_PASSED${NC} | ${RED}Failed: $TESTS_FAILED${NC}"
    echo ""

    if [ "$TESTS_FAILED" -eq 0 ]; then
        echo -e "${GREEN}✓ All smoke tests passed!${NC}"
        return 0
    else
        echo -e "${RED}✗ Some tests failed${NC}"
        return 1
    fi
}

# Main
main() {
    validate_url
    run_all_tests
}

main "$@"
