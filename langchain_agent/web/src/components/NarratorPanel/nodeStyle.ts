/**
 * One visual identity per pipeline stage, shared by the narrator panel and the
 * chat's in-progress status (#103).
 *
 * Deliberately a shared module rather than a copied map: the two columns
 * describe the same step at the same moment, and an audience notices instantly
 * if "Searching the catalog" is violet on one side and blue on the other.
 *
 * Every entry pairs a color WITH an icon and is always rendered beside a text
 * label — nothing here is distinguished by color alone.
 */

import {
  Brain,
  Compass,
  ListOrdered,
  Pencil,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  type LucideIcon,
} from 'lucide-react'

export type NodeStyleKey =
  | 'intent_classifier'
  | 'query_evaluator'
  | 'query_rewriter'
  | 'retriever'
  | 'reranker'
  | 'quality_gate'
  | 'agent'
  | 'enrichment'
  | 'llm_judge'
  | 'ground_truth'

export const NODE_STYLE: Record<NodeStyleKey, { fg: string; tint: string; Icon: LucideIcon }> = {
  intent_classifier: { fg: '#065F46', tint: '#ECFDF5', Icon: Brain },
  query_evaluator: { fg: '#1E40AF', tint: '#EFF6FF', Icon: Compass },
  query_rewriter: { fg: '#0F766E', tint: '#F0FDFA', Icon: Pencil },
  retriever: { fg: '#5B21B6', tint: '#F5F3FF', Icon: Search },
  reranker: { fg: '#3730A3', tint: '#EEF2FF', Icon: ListOrdered },
  quality_gate: { fg: '#9A3412', tint: '#FFF7ED', Icon: ShieldCheck },
  agent: { fg: '#155E75', tint: '#ECFEFF', Icon: Sparkles },
  enrichment: { fg: '#065F46', tint: '#ECFDF5', Icon: Sparkles },
  llm_judge: { fg: '#9F1239', tint: '#FFF1F2', Icon: ShieldCheck },
  // Gold, not brown — deliberately reads as "gold standard" and stays clearly
  // distinct from quality_gate's rust-orange (#130 feedback: the first pass
  // was too close to that existing hue).
  ground_truth: { fg: '#A16207', tint: '#FEFCE8', Icon: Target },
}

export function nodeStyle(node: string | null | undefined) {
  return NODE_STYLE[(node ?? '') as NodeStyleKey] ?? NODE_STYLE.agent
}
