# Routing shadow benchmark (2026-10-15)

This folder contains the frozen 40-case corpus, case-level answer rubric, and the document contexts for comparing the existing classifier gate with shadow routing. The benchmark is synthetic evaluation material; it is not an operational policy source.

## Cases and provenance

`cases.json` contains 40 questions with fixed category and snapshot IDs. The category counts are 16 `business_guidance`, 8 `partial_or_insufficient`, 6 `out_of_scope`, 4 `lookup_or_execution`, 4 `ambiguous`, and 2 `mixed_guidance_and_execution`. The four `known_regression` questions preserve the exact wording of the previously reported annual-leave, privacy-incident, and kimchi-recipe examples. The other 36 are AI-authored for this run.

The new cases are not guaranteed to represent unseen semantic intents or a held-out test set. Before freezing this version, the new questions were compared against the JSON/JSONL question fields found in the current `generation_evaluation` tree (102 files and 560 extracted question entries). No normalized exact-text duplicates were found among the 36 new questions. This scan and manual review can identify obvious overlap, but cannot prove semantic independence. In particular, this set must not be used to claim generalization to unseen user intents.

`rubric.json` fixes permitted actions, required and forbidden claims, source document IDs with exact supporting excerpts, and optional clarification guidance before model responses are evaluated. Optional clarification is not a mandatory phrase. For broad or ambiguous questions, a concise supported overview can be useful alongside a clarifying question; the rubric does not require an unsupported policy inference. For requests that require live lookup or execution, record safe refusal separately from whether the response points to a documented self-service path. A fixed safe scope response is acceptable for a clearly out-of-scope request; do not treat the absence of a repeated topic label or the phrase “문서에서 확인할 수 없습니다” as an error by itself.

## Document snapshots

`snapshots.json` stores four **complete** document sets. The selected `snapshot` in a case is the exact context for that case; `added`, `revised`, and `withdrawn` are not patches to merge at run time.

- `base` has the 71 documents from the source snapshot.
- `added` contains the full base plus the synthetic `shadow-added-001` small-meeting-room guide (72 documents); RSH-015 uses it.
- `revised` contains the full base with only `ieum-009` replaced by synthetic revision 2. The overtime application deadline changes from “before work starts” to “by 17:00 on the preceding business day”; all other source document bodies remain unchanged (71 documents). RSH-030 uses it.
- `withdrawn` contains the full base without `ieum-009` (70 documents). The remaining `ieum-004` still points to that missing document, so RSH-024 tests whether the answer respects that information gap.

The base was normalized from `/home/jake/workspace/projects/sanaebi/tmp/generation-cli-documents.jsonl`, SHA-256 `d58dc0ab1d40bdb9fff68362dc4f5a241fb34ac7fee92f551851d933c1adde74`. It is a 71-document synthetic “이음웍스” evaluation corpus, not a production database export. A lightweight scan of the source text found no email address, phone-number, Korean resident-number-like, or `@` values. No live database was changed to create the three variants.

## Evaluation interpretation

Report the four known regressions separately from the 36 AI-authored cases. Keep failures, timeouts, malformed outputs, and incomplete slots in the denominator. Use the exact case snapshot when checking evidence; do not cite an absent or superseded document. The case rubric evaluates grounded behavior on this synthetic corpus and does not establish production accuracy, policy correctness, or human approval.
