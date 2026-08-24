/**
 * Phase 3: Load testing with k6
 *
 * Tests system behavior under load:
 * - Response time under concurrent users
 * - Throughput capacity
 * - Error rates at scale
 * - Resource usage patterns
 *
 * Run with: k6 run tests/load_test_phase3.js
 */

import http from 'k6/http'
import { check, sleep, group } from 'k6'
import { Rate, Trend, Counter, Gauge } from 'k6/metrics'

// Custom metrics
const errorRate = new Rate('errors')
const responseTime = new Trend('response_time')
const throughput = new Counter('throughput')
const concurrentUsers = new Gauge('concurrent_users')

// Test scenarios
export const options = {
  scenarios: {
    // Scenario 1: Smoke test (small load)
    smoke: {
      executor: 'constant-vus',
      vus: 1,
      duration: '30s',
      gracefulStop: '5s',
      exec: 'smokingTest',
    },
    // Scenario 2: Ramp-up test
    rampUp: {
      executor: 'ramp-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },  // Ramp up to 10 users
        { duration: '1m', target: 10 },   // Stay at 10
        { duration: '30s', target: 0 },   // Ramp down
      ],
      gracefulStop: '5s',
      exec: 'rampUpTest',
    },
    // Scenario 3: Sustained load
    sustained: {
      executor: 'constant-vus',
      vus: 5,
      duration: '2m',
      gracefulStop: '10s',
      exec: 'sustainedLoadTest',
    },
    // Scenario 4: Spike test
    spike: {
      executor: 'ramping-vus',
      stages: [
        { duration: '10s', target: 1 },
        { duration: '5s', target: 50 },    // Sudden spike
        { duration: '10s', target: 50 },   // Hold spike
        { duration: '5s', target: 1 },     // Return to normal
      ],
      gracefulStop: '5s',
      exec: 'spikeTest',
    },
  },

  thresholds: {
    // Response time thresholds
    'response_time': ['p(95)<500', 'p(99)<1000'],
    // Error rate threshold
    'errors': ['rate<0.05'],  // Less than 5% errors
  },
}

// API base URL from environment or default
const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8000'
const API_KEY = __ENV.API_KEY || 'test-key'

/**
 * Smoke test - verify basic functionality
 */
export function smokingTest() {
  concurrentUsers.set(__VU)

  group('Health Check', () => {
    const res = http.get(`${BASE_URL}/api/health`, {
      headers: {
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
    })

    const isHealthy = check(res, {
      'status is 200': (r) => r.status === 200,
      'has postgres status': (r) => r.body.includes('postgres'),
      'has opensearch status': (r) => r.body.includes('vector_store'),
      'response time < 1s': (r) => r.timings.duration < 1000,
    })

    errorRate.add(!isHealthy, { scenario: 'smoke' })
    responseTime.add(res.timings.duration, { scenario: 'smoke' })
    throughput.add(1)
  })

  sleep(1)
}

/**
 * Ramp-up test - gradually increase load
 */
export function rampUpTest() {
  concurrentUsers.set(__VU)

  group('Simple Query', () => {
    const payload = JSON.stringify({
      thread_id: `test-${__VU}-${Date.now()}`,
      messages: [
        {
          role: 'user',
          content: 'What are the best wireless headphones?',
        },
      ],
    })

    const res = http.post(`${BASE_URL}/api/chat`, payload, {
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
      timeout: '30s',
    })

    const isSuccess = check(res, {
      'status is 200': (r) => r.status === 200,
      'has response': (r) => r.body.length > 0,
      'response time < 10s': (r) => r.timings.duration < 10000,
      'not rate limited': (r) => r.status !== 429,
    })

    errorRate.add(!isSuccess, { scenario: 'rampup' })
    responseTime.add(res.timings.duration, { scenario: 'rampup' })
    throughput.add(1)
  })

  sleep(2)
}

/**
 * Sustained load test - maintain constant load
 */
export function sustainedLoadTest() {
  concurrentUsers.set(__VU)

  group('Complex Query', () => {
    const payload = JSON.stringify({
      thread_id: `sustained-${__VU}-${Date.now()}`,
      messages: [
        {
          role: 'user',
          content: 'Compare noise-canceling headphones from Sony and Bose including features and price ranges',
        },
      ],
    })

    const res = http.post(`${BASE_URL}/api/chat`, payload, {
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
      timeout: '30s',
    })

    const isSuccess = check(res, {
      'status is 200 or 202': (r) => r.status === 200 || r.status === 202,
      'has response': (r) => r.body.length > 0,
      'response time < 15s': (r) => r.timings.duration < 15000,
    })

    errorRate.add(!isSuccess, { scenario: 'sustained' })
    responseTime.add(res.timings.duration, { scenario: 'sustained' })
    throughput.add(1)
  })

  sleep(3)
}

/**
 * Spike test - sudden increase in load
 */
export function spikeTest() {
  concurrentUsers.set(__VU)

  group('Spike Query', () => {
    const payload = JSON.stringify({
      thread_id: `spike-${__VU}-${Date.now()}`,
      messages: [
        {
          role: 'user',
          content: 'What are the key features of these running shoes?',
        },
      ],
    })

    const res = http.post(`${BASE_URL}/api/chat`, payload, {
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
      timeout: '30s',
    })

    const isSuccess = check(res, {
      'status ok': (r) => r.status < 400,
      'timeout < 30s': (r) => r.timings.duration < 30000,
      'graceful degradation': (r) => r.status === 503 || r.status === 200,
    })

    errorRate.add(!isSuccess, { scenario: 'spike' })
    responseTime.add(res.timings.duration, { scenario: 'spike' })
    throughput.add(1)
  })

  sleep(1)
}

/**
 * Test multiple endpoints in sequence
 */
export function endToEndTest() {
  concurrentUsers.set(__VU)

  // Step 1: Health check
  group('1. Health Check', () => {
    http.get(`${BASE_URL}/api/health`, {
      headers: {
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
    })
  })

  sleep(1)

  // Step 2: Submit query
  group('2. Submit Query', () => {
    const payload = JSON.stringify({
      thread_id: `e2e-${__VU}-${Date.now()}`,
      messages: [
        { role: 'user', content: 'How does product search work?' },
      ],
    })

    http.post(`${BASE_URL}/api/chat`, payload, {
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
      timeout: '30s',
    })
  })

  sleep(2)

  // Step 3: Follow-up query
  group('3. Follow-up Query', () => {
    const payload = JSON.stringify({
      thread_id: `e2e-${__VU}-${Date.now()}`,
      messages: [
        { role: 'user', content: 'How does product search work?' },
        { role: 'assistant', content: 'Product search uses hybrid search combining keyword and semantic matching...' },
        { role: 'user', content: 'Tell me more about filtering by brand' },
      ],
    })

    http.post(`${BASE_URL}/api/chat`, payload, {
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'Origin': 'http://localhost:5173',
      },
      timeout: '30s',
    })
  })

  sleep(1)
}

/**
 * Setup/teardown hooks
 */
export function setup() {
  console.log('Starting load tests...')
  console.log(`API Base URL: ${BASE_URL}`)
  console.log(`Running ${JSON.stringify(options.scenarios)}`)
}

export function teardown() {
  console.log('Load tests completed')
}

/**
 * Error handling
 */
export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'summary.json': JSON.stringify(data),
  }
}

/**
 * Simple text summary
 */
function textSummary(data, options) {
  const indent = options.indent || '  '
  let summary = '\n=== Load Test Summary ===\n'

  summary += `Total requests: ${data.metrics.throughput.values.count}\n`
  summary += `Error rate: ${(data.metrics.errors.values.rate * 100).toFixed(2)}%\n`

  const responseTimeTrend = data.metrics.response_time.values
  if (responseTimeTrend) {
    summary += `Response time:\n`
    summary += `${indent}Min: ${responseTimeTrend.min || 0}ms\n`
    summary += `${indent}Max: ${responseTimeTrend.max || 0}ms\n`
    summary += `${indent}Avg: ${responseTimeTrend.avg || 0}ms\n`
    summary += `${indent}P95: ${responseTimeTrend['p(95)'] || 0}ms\n`
    summary += `${indent}P99: ${responseTimeTrend['p(99)'] || 0}ms\n`
  }

  return summary
}
