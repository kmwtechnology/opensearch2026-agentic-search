/**
 * TypeScript types for WebSocket events from the agent API.
 * These mirror the Pydantic models in api/schemas/events.py
 */

// Base event interface
export interface BaseEvent {
  type: string
  timestamp: string
  node?: string
}

// Connection events
export interface ConnectionEstablished extends BaseEvent {
  type: 'connection_established'
  thread_id: string
  existing_messages: number
}

export interface ConnectionError extends BaseEvent {
  type: 'connection_error'
  error: string
}

// Conversation context events
export interface ConversationContextEvent extends BaseEvent {
  type: 'conversation_context'
  previous_message_count: number
  is_new_conversation: boolean
  summary?: string
}

// Node lifecycle events
export interface NodeStartEvent extends BaseEvent {
  type: 'node_start'
  node: string
  input_summary?: string
}

export interface NodeEndEvent extends BaseEvent {
  type: 'node_end'
  node: string
  duration_ms: number
  output_summary?: string
}

// Query evaluator events
export interface QueryEvaluationEvent extends BaseEvent {
  type: 'query_evaluation'
  node: 'query_evaluator'
  query: string
  alpha: number
  query_analysis: string
  search_strategy: 'lexical-heavy' | 'balanced' | 'semantic-heavy'
}

export interface IntentClassificationEvent extends BaseEvent {
  type: 'intent_classification'
  node: 'intent_classifier'
  intent: string
  user_query: string
  reasoning: string
  confidence?: number  // 0.0-1.0 confidence score
}

export interface QueryExpansionEvent extends BaseEvent {
  type: 'query_expansion'
  node: 'retriever'
  original_query: string
  expanded_query: string
  expansion_reason: string
}

export type OpenSearchQueryType = 'hybrid' | 'bm25_baseline' | 'quality_gate_retry'

export interface OpenSearchQueryEvent extends BaseEvent {
  type: 'opensearch_query'
  node: 'retriever'
  query: string
  alpha: number  // 0.0=lexical, 1.0=semantic
  filters?: Record<string, unknown>[]  // Applied attribute filters
  filter_summary?: string  // Human-readable summary (e.g., "brand: Sony, color: blue")
  intent: string  // intent that triggered the search
  optimizations?: Record<string, boolean>  // Per-feature toggles applied to this search
  query_type?: OpenSearchQueryType  // Which kind of query this event represents
  body?: Record<string, unknown>  // Full DSL body sent to OpenSearch (embeddings scrubbed)
  index?: string  // Index the search ran against
  params?: Record<string, string>  // Query-string params (e.g. search_pipeline)
}

export interface QualityGateEvent extends BaseEvent {
  type: 'quality_gate'
  node: 'quality_gate'
  triggered: boolean
  original_alpha: number
  new_alpha?: number
  max_score: number
  threshold: number
  reason: string
}

export interface SummaryEvent extends BaseEvent {
  type: 'summary_generated'
  node: 'summary'
  summary_text?: string
  message_count: number
}

// Hybrid search events
export interface SearchCandidate {
  source: string
  snippet: string
  full_content?: string
  vector_score?: number
  text_score?: number
  rrf_score?: number
  url?: string
}

export interface HybridSearchStartEvent extends BaseEvent {
  type: 'hybrid_search_start'
  node: 'retriever'
  query: string
  alpha: number
  fetch_k: number
}

export interface HybridSearchResultEvent extends BaseEvent {
  type: 'hybrid_search_result'
  node: 'retriever'
  candidate_count: number
  candidates: SearchCandidate[]
}

// Reranker events
export interface RerankerStartEvent extends BaseEvent {
  type: 'reranker_start'
  node: 'reranker'
  model: string
  candidate_count: number
}

export interface RerankedDocument {
  source: string
  score: number
  rank: number
  original_rank: number
  snippet: string
  rank_change: number
  url?: string
  // Optional component scores (may be included from hybrid search)
  vector_score?: number
  text_score?: number
  rrf_score?: number
  page_content?: string
}

export interface RerankerResultEvent extends BaseEvent {
  type: 'reranker_result'
  node: 'reranker'
  results: RerankedDocument[]
  reranking_changed_order: boolean
}

// Search progress events
export interface SearchProgressEvent extends BaseEvent {
  type: 'search_progress'
  node: 'retriever'
  stage: 'embedding' | 'vector_search' | 'text_search' | 'fusion'
  message: string
}

export interface RerankerProgressEvent extends BaseEvent {
  type: 'reranker_progress'
  node: 'reranker'
  stage: 'scoring' | 'ranking'
  progress: number  // 0.0-1.0
  message: string
}

// Document grading events
export interface DocumentGradingStartEvent extends BaseEvent {
  type: 'document_grading_start'
  node: 'document_grader'
  document_count: number
}

export interface DocumentGradeEvent extends BaseEvent {
  type: 'document_grade'
  node: 'document_grader'
  source: string
  relevant: boolean
  score: number
  reasoning: string
}

export interface DocumentGradingSummaryEvent extends BaseEvent {
  type: 'document_grading_summary'
  node: 'document_grader'
  grade: 'pass' | 'fail'
  relevant_count: number
  total_count: number
  average_score: number
  reasoning: string
}

// Query transformation events
export interface QueryTransformationEvent extends BaseEvent {
  type: 'query_transformation'
  node: 'query_transformer'
  original_query: string
  transformed_query: string
  iteration: number
  max_iterations: number
  reasons: string[]
}

// LLM response events
export interface LLMReasoningStartEvent extends BaseEvent {
  type: 'llm_reasoning_start'
  node: 'agent'
}

export interface LLMReasoningChunkEvent extends BaseEvent {
  type: 'llm_reasoning_chunk'
  node: 'agent'
  content: string
  is_complete: boolean
}

export interface LLMResponseStartEvent extends BaseEvent {
  type: 'llm_response_start'
  node: 'agent'
}

export interface LLMResponseChunkEvent extends BaseEvent {
  type: 'llm_response_chunk'
  node: 'agent'
  content: string
  is_complete: boolean
}

export interface LLMResponseCorrectedEvent extends BaseEvent {
  type: 'llm_response_corrected'
  node: 'llm_judge'
  corrected_content: string
  original_faithfulness: number
  corrected_faithfulness: number
}

export interface ToolCallEvent extends BaseEvent {
  type: 'tool_call'
  node: 'agent'
  tool_name: string
  tool_args: Record<string, unknown>
}

// Response grading events
export interface ResponseGradingEvent extends BaseEvent {
  type: 'response_grading'
  node: 'response_grader'
  grade: 'pass' | 'fail'
  score: number
  score_source?: 'reranker' | 'honest_ack' | 'llm'  // Source of the score
  reasoning: string
  retry_count: number
  max_retries: number
}

// Response improvement events
export interface ResponseImprovementEvent extends BaseEvent {
  type: 'response_improvement'
  node: 'response_improver'
  feedback: string
  retry_count: number
}

// Completion events
export interface AgentCompleteEvent extends BaseEvent {
  type: 'agent_complete'
  thread_id: string
  total_duration_ms: number
  final_response: string
  iterations: number
  response_retries: number
  documents_used: number
  title?: string
  citations?: { label: string; url: string }[]
}

export interface AgentErrorEvent extends BaseEvent {
  type: 'agent_error'
  error: string
  node?: string
  recoverable: boolean
}

// Token budget events
export interface TokenBudgetEvent extends BaseEvent {
  type: 'token_budget'
  total_tokens_used: number
  token_budget: number
  budget_exceeded: boolean
  warning_threshold_hit: boolean
}

// Cache hit events
export interface CacheHitEvent extends BaseEvent {
  type: 'cache_hit'
  node: 'query_evaluator'
  query: string
  cached_result: Record<string, unknown>
}

// Metrics events
export interface MetricsEvent extends BaseEvent {
  type: 'metrics'
  query_evaluation_ms?: number
  retrieval_ms?: number
  reranking_ms?: number
  document_grading_ms?: number
  llm_generation_ms?: number
  response_grading_ms?: number
  total_ms: number
}

// Confidence score events
export interface ConfidenceScoreEvent extends BaseEvent {
  type: 'confidence_score'
  node: string
  score: number
  confidence: number
  early_stop_triggered: boolean
}

// Link verification events
export interface LinkVerificationEvent extends BaseEvent {
  type: 'link_verification'
  node: 'agent'
  total_links_checked: number
  valid_links: number
  broken_links: number
  broken_link_sources: string[]
  cache_hits: number
}

export interface DocumentReplacementEvent extends BaseEvent {
  type: 'document_replacement'
  node: 'agent'
  replacements_made: number
  replacement_details: Array<{ old_source: string; new_source: string; reason: string }>
  documents_after_replacement: number
}

// Clarification events
export interface ClarificationRequestedEvent extends BaseEvent {
  type: 'clarification_requested'
  node: 'content_type_classifier'
  clarification_type: string
  reason: string
  candidates: Array<{
    type: string
    confidence: number
    description: string
  }>
  threshold: number
  original_query: string
}

export interface ClarificationResolvedEvent extends BaseEvent {
  type: 'clarification_resolved'
  node: 'content_type_clarification_resolver'
  clarification_type: string
  original_classification: string
  user_selected: string
  confidence_before: number
  confidence_after: number
  user_response: string
}

// ============================================================================
// PIPELINE QUALITY SUMMARY
// ============================================================================

export interface StageMetrics {
  ndcg10: number
  mrr: number
  recall20: number
  precision10: number
  judged_count: number
}

export type ConfidenceLabel = 'high' | 'medium' | 'low'

export interface ConfidenceProxy {
  top1_score: number
  score_gap: number
  score_variance: number
  rank_changes_count: number
  confidence_label: ConfidenceLabel
}

export type GenerationVerdict = 'llm_better' | 'tied' | 'llm_worse'

export type HallucinationCategory =
  | 'fabrication'
  | 'cross_product_bleed'
  | 'inference'
  | 'overreach'

export interface FlaggedClaim {
  claim: string
  category: HallucinationCategory
  reasoning?: string
}

export interface GenerationJudgment {
  verdict: GenerationVerdict
  pairwise_justification: string
  faithfulness: number
  answer_relevance: number
  citation_accuracy: number
  context_utilization: number
  hallucinations: FlaggedClaim[]
}

export type PipelineStageName = 'stock_bm25' | 'bm25' | 'hybrid' | 'reranked'

export interface LatencyStage {
  stage: PipelineStageName
  latency_ms: number
  ndcg?: number | null
  ndcg_lift_per_100ms?: number | null
}

export interface PipelineSummaryEvent extends BaseEvent {
  type: 'pipeline_summary'
  has_ground_truth: boolean
  query: string
  optimizations: Record<string, boolean>
  stock_bm25?: StageMetrics | null
  bm25?: StageMetrics | null
  hybrid?: StageMetrics | null
  reranked?: StageMetrics | null
  confidence?: ConfidenceProxy | null
  generation?: GenerationJudgment | null
  original_generation?: GenerationJudgment | null
  hallucination_retry_used?: boolean
  corrected_response?: string | null
  latency: LatencyStage[]
}

// Union type of all events
export type AgentEvent =
  | ConnectionEstablished
  | ConnectionError
  | ConversationContextEvent
  | NodeStartEvent
  | NodeEndEvent
  | QueryEvaluationEvent
  | IntentClassificationEvent
  | QueryExpansionEvent
  | OpenSearchQueryEvent
  | QualityGateEvent
  | SummaryEvent
  | HybridSearchStartEvent
  | HybridSearchResultEvent
  | RerankerStartEvent
  | RerankerResultEvent
  | SearchProgressEvent
  | RerankerProgressEvent
  | DocumentGradingStartEvent
  | DocumentGradeEvent
  | DocumentGradingSummaryEvent
  | QueryTransformationEvent
  | LLMReasoningStartEvent
  | LLMReasoningChunkEvent
  | LLMResponseStartEvent
  | LLMResponseChunkEvent
  | LLMResponseCorrectedEvent
  | ToolCallEvent
  | ResponseGradingEvent
  | ResponseImprovementEvent
  | AgentCompleteEvent
  | AgentErrorEvent
  | PipelineSummaryEvent
  | TokenBudgetEvent
  | CacheHitEvent
  | MetricsEvent
  | ConfidenceScoreEvent
  | LinkVerificationEvent
  | DocumentReplacementEvent
  | ClarificationRequestedEvent
  | ClarificationResolvedEvent

// Helper type guards
export function isQueryEvaluation(event: AgentEvent): event is QueryEvaluationEvent {
  return event.type === 'query_evaluation'
}

export function isDocumentGradingSummary(event: AgentEvent): event is DocumentGradingSummaryEvent {
  return event.type === 'document_grading_summary'
}

export function isResponseGrading(event: AgentEvent): event is ResponseGradingEvent {
  return event.type === 'response_grading'
}

export function isAgentComplete(event: AgentEvent): event is AgentCompleteEvent {
  return event.type === 'agent_complete'
}

export function isAgentError(event: AgentEvent): event is AgentErrorEvent {
  return event.type === 'agent_error'
}

export function isQueryExpansion(event: AgentEvent): event is QueryExpansionEvent {
  return event.type === 'query_expansion'
}

export function isQualityGate(event: AgentEvent): event is QualityGateEvent {
  return event.type === 'quality_gate'
}

export function isIntentClassification(event: AgentEvent): event is IntentClassificationEvent {
  return event.type === 'intent_classification'
}

// Node names for routing
export type NodeName =
  | 'query_evaluator'
  | 'retriever'
  | 'reranker'
  | 'quality_gate'
  | 'agent'
  | 'intent_classifier'
  | 'summary'
  | 'llm_judge'

// Node status for UI
export type NodeStatus = 'idle' | 'running' | 'complete' | 'error'

// Step representation for the observability panel
export interface ObservabilityStep {
  id: string
  node: NodeName
  status: NodeStatus
  startTime: Date
  endTime?: Date
  durationMs?: number
  events: AgentEvent[]
  summary?: string
}
