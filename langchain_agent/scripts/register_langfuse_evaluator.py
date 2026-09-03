"""Register this project's Langfuse Evaluators (issue #56, /evals). Local dev only.

Upserts three Evaluators (idempotent by name), each with an Evaluation Rule that
runs it against every "LangGraph" root trace:

- citation-precision-ts: our own Code Evaluator (TypeScript, via the
  `insecure-local` dispatcher -- see docker-compose.yml). Source lives in
  web/src/langfuse-evaluators/citationPrecision.ts, type-checked and unit-tested
  there (`npm test`); read verbatim and submitted as source_code.
- answer-groundedness, context-precision: Langfuse's own built-in LLM-as-judge
  templates (Retrieval category) -- independent, native cross-checks on exactly
  what this RAG pipeline's own judge.py and citation_precision() already try to
  measure, using our existing google-ai-studio LLM connection (see
  configure_langfuse_playground.py). Prompt text captured verbatim from the
  Langfuse UI's template gallery, not reauthored.

Requires `make langfuse-up` with LANGFUSE_ENABLED=true.

Usage:
    PYTHONPATH=. python scripts/register_langfuse_evaluator.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from config import LANGFUSE_BASE_URL, LANGFUSE_ENABLED, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

JUDGE_MODEL = "gemini-3.1-flash-lite-preview"  # matches config.JUDGE_MODEL

CODE_EVALUATOR_NAME = "citation-precision-ts"
CODE_EVALUATOR_SOURCE_PATH = (
    Path(__file__).parent.parent.parent
    / "langchain_agent"
    / "web"
    / "src"
    / "langfuse-evaluators"
    / "citationPrecision.ts"
)

ANSWER_GROUNDEDNESS_PROMPT = """You are an expert groundedness evaluator for context-backed AI outputs.
You will receive a user input, an assistant output, and supporting context.
Classify how well the output is supported by the supplied context.

## Scope
- Use only the supplied context as evidence.
- The user input may clarify what the output is trying to answer, but it is not evidence for factual claims.
- Judge support for the output's material claims, not whether the context is relevant or complete overall.

## Golden Rule
Select Grounded only when every material factual claim in the output is directly supported by, or logically entailed by, the context.

## Labels
- Grounded: all material claims are supported by the context.
- Somewhat grounded: core claims are supported, but one or more material claims are weakly supported, unsupported, or uncertain.
- Not grounded: a key claim is unsupported or contradicted by the context.

## Decision Rules
1. Identify the output's material factual claims and conclusions.
2. Compare each claim with the supplied context.
3. Accept reasonable inferences only when they follow directly from the context.
4. Do not use outside knowledge to fill gaps.
5. Choose exactly one label.

User input: {{input}}
Assistant output: {{output}}
Context: {{context}}"""

CONTEXT_PRECISION_PROMPT = """You are an expert context-relevance evaluator for retrieval-augmented systems.
You will receive a user input and retrieved context.
Classify how useful the context is for answering the input.

## Scope
- Judge relevance and direct usefulness of the context for the user's request.
- Do not judge whether the context is complete; evaluate completeness separately with a context-coverage evaluator.
- Do not use outside knowledge.

## Golden Rule
Select Precise context only when the context is directly useful for resolving the user's primary request with little or no irrelevant material.

## Labels
- Precise context: highly relevant and directly useful for answering the request.
- Partially useful context: contains relevant information but is incomplete, indirect, or meaningfully noisy.
- Irrelevant context: does not materially help answer the request.

## Decision Rules
1. Identify the user's primary information need.
2. Assess whether the context addresses that need directly.
3. Treat unrelated, stale, or distracting material as noise.
4. Choose exactly one label. Use Irrelevant context when the context is empty or has no meaningful connection to the request.

User input: {{input}}
Context: {{context}}"""


@dataclass
class LlmJudgeSpec:
    name: str
    description: str
    prompt: str
    categories: List[str]
    include_output_var: bool


LLM_JUDGE_EVALUATORS = [
    LlmJudgeSpec(
        name="answer-groundedness",
        description=(
            "Langfuse's built-in Retrieval template: is the response supported by the "
            "retrieved documents? Independent cross-check on judge.py's own faithfulness score."
        ),
        prompt=ANSWER_GROUNDEDNESS_PROMPT,
        categories=["Not grounded", "Somewhat grounded", "Grounded"],
        include_output_var=True,
    ),
    LlmJudgeSpec(
        name="context-precision",
        description=(
            "Langfuse's built-in Retrieval template: is the retrieved context actually "
            "useful for the query? Independent cross-check on retrieval/reranker quality."
        ),
        prompt=CONTEXT_PRECISION_PROMPT,
        categories=["Irrelevant context", "Partially useful context", "Precise context"],
        include_output_var=False,
    ),
]


def _find_by_name(items, name: str) -> Optional[object]:
    for item in items:
        if item.name == name:
            return item
    return None


# Two distinct root spans need evaluating: "LangGraph" for a live/standalone
# invocation (cli.py, api/services/observable_agent.py), and "experiment-item-run"
# for a client.run_experiment() run -- Langfuse only populates
# experiment.itemExpectedOutput on that top-level dataset-run-linked span, not on
# nested descendants, even though "LangGraph" (several levels below it in an
# experiment) carries the same citations/retrieved_documents shape in its own
# output. Confirmed empirically: eval_citation_precision_ts returned the correct
# real value once targeting experiment-item-run, but stayed at the -1 sentinel
# when only "LangGraph" was in the filter, even inside a real experiment run.
EVALUATED_SPAN_NAMES = ["LangGraph", "experiment-item-run"]


def _upsert_evaluation_rule(client, evaluator, rule_name: str) -> None:
    from langfuse.api.evaluation_commons.types.evaluation_rule_filter import (
        EvaluationRuleFilter_StringOptions,
    )
    from langfuse.api.evaluation_commons.types.evaluation_rule_options_filter_operator import (
        EvaluationRuleOptionsFilterOperator,
    )
    from langfuse.api.evaluation_rules.types.evaluation_rule_evaluator_assignment_input import (
        EvaluationRuleEvaluatorAssignmentInput,
    )

    rule_filter = [
        EvaluationRuleFilter_StringOptions(
            type="stringOptions",
            column="name",
            operator=EvaluationRuleOptionsFilterOperator.ANY_OF,
            value=EVALUATED_SPAN_NAMES,
        )
    ]

    existing_rule = _find_by_name(client.api.evaluation_rules.list(limit=100).data, rule_name)
    if existing_rule is not None:
        client.api.evaluation_rules.update(existing_rule.id, filter=rule_filter)
        print(f"  Updated evaluation rule '{rule_name}' ({existing_rule.id})")
        return
    client.api.evaluation_rules.create(
        name=rule_name,
        enabled=True,
        evaluator_assignments=[EvaluationRuleEvaluatorAssignmentInput(evaluator_id=evaluator.id)],
        filter=rule_filter,
    )
    print(f"  Created evaluation rule '{rule_name}' -> runs on {', '.join(EVALUATED_SPAN_NAMES)}")


def _register_code_evaluator(client) -> None:
    from langfuse.api.evaluation_commons.types.code_evaluator_source_code_language import (
        CodeEvaluatorSourceCodeLanguage,
    )
    from langfuse.api.evaluators.types.create_evaluator_request import CreateEvaluatorRequest_Code
    from langfuse.api.evaluators.types.update_code_evaluator_request import (
        UpdateCodeEvaluatorRequest,
    )

    if not CODE_EVALUATOR_SOURCE_PATH.exists():
        print(f"ERROR: {CODE_EVALUATOR_SOURCE_PATH} not found", file=sys.stderr)
        return
    source_code = CODE_EVALUATOR_SOURCE_PATH.read_text()

    existing = _find_by_name(client.api.evaluators.list(limit=100).data, CODE_EVALUATOR_NAME)
    if existing is not None:
        evaluator = client.api.evaluators.update(
            existing.id,
            request=UpdateCodeEvaluatorRequest(
                name=CODE_EVALUATOR_NAME,
                source_code=source_code,
                source_code_language=CodeEvaluatorSourceCodeLanguage.TYPESCRIPT,
                type="code",
            ),
        )
        print(f"Updated evaluator '{CODE_EVALUATOR_NAME}' ({evaluator.id})")
    else:
        evaluator = client.api.evaluators.create(
            request=CreateEvaluatorRequest_Code(
                name=CODE_EVALUATOR_NAME,
                description=(
                    "Citation precision against ESCI ground truth, computed in TypeScript "
                    "via the insecure-local dispatcher (local dev only)."
                ),
                source_code=source_code,
                source_code_language=CodeEvaluatorSourceCodeLanguage.TYPESCRIPT,
                type="code",
            )
        )
        print(f"Created evaluator '{CODE_EVALUATOR_NAME}' ({evaluator.id})")

    _upsert_evaluation_rule(client, evaluator, f"{CODE_EVALUATOR_NAME}-on-langgraph-traces")


def _register_llm_judge_evaluator(client, spec: LlmJudgeSpec) -> None:
    from langfuse.api.evaluation_commons.types.evaluator_output_definition import (
        EvaluatorOutputDefinition_Categorical,
    )
    from langfuse.api.evaluation_commons.types.prompt_variable_mapping_input import (
        PromptVariableMappingInput,
    )
    from langfuse.api.evaluation_commons.types.prompt_variable_mapping_source import (
        PromptVariableMappingSource,
    )
    from langfuse.api.evaluators.types.create_evaluator_request import (
        CreateEvaluatorRequest_LlmAsJudge,
    )
    from langfuse.api.evaluators.types.evaluator_model_config import EvaluatorModelConfig
    from langfuse.api.evaluators.types.update_llm_as_judge_evaluator_request import (
        UpdateLlmAsJudgeEvaluatorRequest,
    )

    variable_mapping = [
        PromptVariableMappingInput(variable="input", source=PromptVariableMappingSource.INPUT),
        # retrieved_documents lives inside the LangGraph trace's full output state --
        # json_path scopes {{context}} to just that field instead of the whole thing.
        PromptVariableMappingInput(
            variable="context",
            source=PromptVariableMappingSource.OUTPUT,
            json_path="$.retrieved_documents",
        ),
    ]
    if spec.include_output_var:
        variable_mapping.insert(
            1,
            PromptVariableMappingInput(
                variable="output", source=PromptVariableMappingSource.OUTPUT
            ),
        )

    model_config = EvaluatorModelConfig(provider="google-ai-studio", model=JUDGE_MODEL)
    output_definition = EvaluatorOutputDefinition_Categorical(
        data_type="CATEGORICAL", categories=spec.categories, should_allow_multiple_matches=False
    )

    existing = _find_by_name(client.api.evaluators.list(limit=100).data, spec.name)
    if existing is not None:
        evaluator = client.api.evaluators.update(
            existing.id,
            request=UpdateLlmAsJudgeEvaluatorRequest(
                name=spec.name,
                type="llm_as_judge",
                prompt=spec.prompt,
                model_config_=model_config,
                variable_mapping=variable_mapping,
                output_definition=output_definition,
            ),
        )
        print(f"Updated evaluator '{spec.name}' ({evaluator.id})")
    else:
        evaluator = client.api.evaluators.create(
            request=CreateEvaluatorRequest_LlmAsJudge(
                name=spec.name,
                type="llm_as_judge",
                description=spec.description,
                prompt=spec.prompt,
                model_config_=model_config,
                variable_mapping=variable_mapping,
                output_definition=output_definition,
            )
        )
        print(f"Created evaluator '{spec.name}' ({evaluator.id})")

    _upsert_evaluation_rule(client, evaluator, f"{spec.name}-on-langgraph-traces")


def main() -> int:
    if not LANGFUSE_ENABLED:
        print("LANGFUSE_ENABLED is not set -- nothing to register. Set it in .env first.")
        return 1

    try:
        from langfuse import Langfuse
    except ImportError:
        print("langfuse SDK not installed -- run `pip install -r requirements-dev.txt` first.")
        return 1

    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL
    )

    _register_code_evaluator(client)
    for spec in LLM_JUDGE_EVALUATORS:
        _register_llm_judge_evaluator(client, spec)

    print("Done. New LangGraph traces will be scored under /evals within a few seconds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
