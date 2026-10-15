# Prompt v7 rule, purpose, priority, and example map

This map describes the candidate prompts added for the 2026-10-15 v7 experiment. It is an implementation aid, not an adopted-policy change. The v5 and v6 prompt text and the default profile remain unchanged.

## Rule purpose and precedence

| Priority | Rule area | Purpose | Candidate |
| --- | --- | --- | --- |
| 1 | Source grounding and service boundaries | Preserve the existing v5 constraints: answer from applicable company documents, distinguish unsupported company facts from out-of-scope requests, and never claim lookup or execution that did not occur. | Inherited unchanged from v5 |
| 2 | Output contract | Keep the existing single-key `{"answer": "..."}` JSON contract. Markdown and line breaks belong inside the answer string. | Inherited from v5; readability examples show serialization |
| 3 | Required content | Give the question's conclusion and include document-supported steps, actors, conditions, exceptions, deadlines, completion checks, and relevant failure paths. Do not invent absent steps or add unrelated background. | `examples_answer_scope_v7_completeness` |
| 4 | Readable structure | Put the answer first; use paragraphs for topic changes, bullets for parallel items or conditional branches, and numbering only for actual sequence. Capability answers use an introduction, representative work bullets, and execution limits. | `examples_answer_scope_v7_readability` |

Grounding, execution limits, and the JSON contract are fixed constraints. Content completeness applies only when supported by the supplied documents and relevant to the question. Readability changes presentation and must not remove or reorder meaning. The combined candidate appends both new rule blocks to v5; it is registered for evaluation, but the experiment runner must execute it only if both independent candidates pass the predeclared development gate.

## Example coverage

| Example | Purpose | Scope guard |
| --- | --- | --- |
| Fictional capability response | Demonstrate a short opening, parallel representative-work bullets, execution limits, and a follow-up question. | Uses the explicitly fictional “별빛연구소”; facts are format-only and must not become Sanaebi policy. |
| Fictional conditional procedure | Distinguish the shared ordered submission step from the approval and rejection branches. | Uses a fictional equipment-loan document; the alternatives are bullets, not successive numbered actions. |

Both examples use valid JSON with only the `answer` key. Escaped `\n` sequences decode to Markdown paragraph and list breaks. The examples illustrate structure, not facts or wording to copy into actual answers.

## Profile registration

| Profile | Added material |
| --- | --- |
| `examples_answer_scope_v7_readability` | v5 + readability rules + the two scoped fictional JSON examples |
| `examples_answer_scope_v7_completeness` | v5 + content-completeness rules |
| `examples_answer_scope_v7_combined` | v5 + readability rules/examples + content-completeness rules |

All three preserve the v5 user message and append to its system prompt. None changes the default profile, model settings, API, or response schema.
