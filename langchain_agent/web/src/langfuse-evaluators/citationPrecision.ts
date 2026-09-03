// Langfuse Code Evaluator source (issue #56 Phase B, /evals).
//
// THIS FILE IS SUBMITTED VERBATIM TO LANGFUSE as an Evaluator's `source_code`
// (see scripts/register_langfuse_evaluator.py) and executed inside the
// Langfuse worker via the `insecure-local` dispatcher -- self-hosted Langfuse
// only runs TypeScript/JavaScript Code Evaluators locally (no AWS Lambda), so
// this mirrors integrations/langfuse_eval.py's citation_precision() in TS
// rather than reusing the Python implementation directly.
//
// Per Langfuse's contract (must return >=1 score, complete within 2s, no
// network access, deterministic): the evaluator sees the LangGraph trace's
// serialized output (which includes `citations` and `retrieved_documents`,
// confirmed present via a real trace in ClickHouse) and the dataset item's
// `expected_output.judgments` (ESCI ground truth) -- no OpenSearch/API access
// needed, everything required is already embedded in those two places.
//
// No imports/exports: this must be valid as a standalone function body when
// executed by Langfuse's sandbox, not as an ES module. citationPrecision.test.ts
// imports this file's raw text (`?raw`) and evaluates it directly, so the test
// exercises the exact bytes submitted to Langfuse, not a parallel copy.

type Citation = { label: string; url?: string };
type RetrievedDocument = { metadata?: { product_id?: string } };

type EvaluationContext = {
  observation: {
    input: unknown;
    output: {
      citations?: Citation[];
      retrieved_documents?: RetrievedDocument[];
    };
    metadata: unknown;
    toolCalls: unknown[];
  };
  experiment:
    | {
        itemExpectedOutput: { judgments?: Record<string, number> } | null;
        itemMetadata: unknown;
      }
    | undefined;
};

type NumericScore = {
  name: string;
  value: number;
  dataType: "NUMERIC";
  comment?: string;
};

type EvaluationResult = { scores: NumericScore[] };

// Sentinel for "nothing to score" (no ground truth, or no citations) --
// distinct from a genuine 0.0 precision, and the contract requires at least
// one score even when there's nothing meaningful to compute.
const NO_DATA_SENTINEL = -1;

// Deliberately not exported (see file header): Langfuse's sandbox executes this
// as a standalone function body, not an ES module, so `export` would break the
// submitted source. citationPrecision.test.ts exercises it via `?raw` + eval instead.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function evaluate({ observation: { output }, experiment }: EvaluationContext): EvaluationResult {
  const judgments = experiment?.itemExpectedOutput?.judgments;
  const citations = output?.citations ?? [];
  const retrievedDocuments = output?.retrieved_documents ?? [];

  if (!judgments || citations.length === 0) {
    return {
      scores: [
        {
          name: "eval_citation_precision_ts",
          value: NO_DATA_SENTINEL,
          dataType: "NUMERIC",
          comment: "No ESCI ground truth or no citations to score for this trace.",
        },
      ],
    };
  }

  // Citation labels look like "[1,3] Some Product Title" -- the leading
  // bracket holds 1-based indices into retrieved_documents (see
  // pipeline_nodes.py's citations_dict construction / citation_precision()'s
  // Python equivalent in integrations/langfuse_eval.py).
  const citationIndexRe = /^\[([\d,]+)\]/;
  const citedProductIds = new Set<string>();

  for (const citation of citations) {
    const match = citationIndexRe.exec(citation.label ?? "");
    if (!match) continue;
    for (const idxStr of match[1].split(",")) {
      const docIdx = parseInt(idxStr, 10) - 1;
      const productId = retrievedDocuments[docIdx]?.metadata?.product_id;
      if (productId) citedProductIds.add(productId);
    }
  }

  if (citedProductIds.size === 0) {
    return {
      scores: [
        {
          name: "eval_citation_precision_ts",
          value: NO_DATA_SENTINEL,
          dataType: "NUMERIC",
          comment: "Citations present but none carried a resolvable product_id.",
        },
      ],
    };
  }

  let relevant = 0;
  for (const productId of citedProductIds) {
    if ((judgments[productId] ?? 0) > 0) relevant += 1;
  }
  const precision = relevant / citedProductIds.size;

  return {
    scores: [
      {
        name: "eval_citation_precision_ts",
        value: precision,
        dataType: "NUMERIC",
        comment: `${relevant}/${citedProductIds.size} cited products have positive ESCI relevance.`,
      },
    ],
  };
}
