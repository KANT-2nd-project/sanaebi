# Independent blind AI review protocol

Read only the assigned blind batch and document snapshot. Do not read mapping.json, candidate configs, prompt source, other run outputs, or prior judgments. This is AI review, not human approval. Do not invoke generation APIs or modify production files.

Use each case's frozen required claims, forbidden claims, optional background, exact evidence, and absence checks. Verify citations against the complete fixed snapshot when needed. Equivalent paraphrases count; optional background is not mandatory. Do not require procedures unrelated to the question. Distinguish missing supplied-document evidence from asserting that a policy does not exist in reality.

For every response write one JSON judgment with blind_id, case_id, verdict (pass/partial/fail/uncertain), severity (critical/material/omission/style/none), reason, required_claims assessment with response evidence, forbidden_claims assessment, issues (objects with kind, evidence, reason), and dimensions.

Issue kinds: critical_error, material_error, required_omission, over_abstention, format_error, style_relevance.
Dimensions exactly: format, grounding, scope_conditions, completeness, abstention, action_boundary, style, relevance. Each dimension has status (pass/fail/na/uncertain), evidence string, reason string.

Pass: satisfies necessary requested claims, supported scope/conditions, correct answer-only JSON, Korean polite style, no relevant forbidden assertion.
Partial: supported core answer with a noncritical necessary omission or incomplete handling of unknown portion.
Fail: material unsupported policy or distorted condition, fabricated authority/menu/action completion/payment guarantee, invalid format, refusal/error/truncation.
Uncertain: evidence or criterion genuinely ambiguous; never promote automatically.
Critical is reserved for consequential fabricated permissions, completed actions, menus/payment guarantees or similarly serious grounded errors; ordinary omission is not critical. Explicit refusal is a failed task response, not proof of unsafe generation.

Assess all eight dimensions separately. Format is supplied parsed status + raw JSON; do not conflate valid JSON with grounded content. Relevance and polite Korean are observable, stylistic taste is not scored. Mention concrete quoted response and source evidence for every failed dimension. Keep candidate identity unknown throughout review.
