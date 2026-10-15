# GPT-6 Luna prompt-v7 fixed evaluation fixtures

These files freeze the question sets and candidate-neutral judging criteria for the readability/completeness comparison. They are AI-authored fixtures for this experiment, not human-approved policy examples or evidence of general operating quality.

## Frozen source

- Snapshot: `/home/jake/workspace/projects/sanaebi/tmp/readability-v6-20261015/snapshot.json`
- Snapshot fingerprint: `9d02a7ba77a340bea017e89ab43e25db62a8cdeef83b2a40c5bbfb203a8eddf7`
- Snapshot contains 72 documents. The raw snapshot remains outside the repository; each published-document evidence quote in these fixtures was checked as an exact substring of its referenced document body.
- `runtime_contract` evidence points to the current generation prompt/profile and is used only for assistant behavior or service scope, never as company policy evidence.

## Development set

`development.json` contains 12 cases: the prior eight fixed development cases (`R01`–`R08`) plus four new development cases (`D09`–`D12`). The earlier cases retain their question, required/forbidden criteria, and existing evidence; `R07` previously had no evidence, so an exact runtime clarification instruction is now recorded. New cases cover meeting decision records, shared-drive recovery, customer bug handoff, and safe generative-AI use.

These prior cases have been observed in earlier work and are not an unseen evaluation set.

## Final selection set

`selection.json` contains 12 AI-authored cases with the approved allocation:

| Category | Cases |
|---|---:|
| Capability introduction | 2 |
| Short single fact | 1 |
| Ordered multi-step procedure | 2 |
| Conditional alternatives | 2 |
| Partial answer and unknown detail | 1 |
| Out-of-scope general knowledge | 1 |
| Ambiguous work context | 1 |
| Composite incident response | 2 |

The two capability cases use distinct audiences and tasks, but the broad capability-introduction intent is also present in development case `R01` and in a synthetic prompt example. They are therefore explicitly marked as exposed and must not be described as wholly unseen capability intents. Other selection case intent-group IDs are disjoint from development case IDs and task groups; the fixtures do not imply independent human authorship.

## Judging

Each case separates required claims, critical claims, optional context, forbidden claims, exact evidence, common readability, and a case-specific structure rubric. Optional context is not a pass requirement. Content, common readability, and structure adherence are scored independently. A short answer can pass without Markdown; ordered steps and conditional alternatives are judged differently. Missing/uncertain/API-failure cases remain in the denominator and are not promoted to pass.

The selection rubric and thresholds are also recorded in `acceptance.md`; the response judgment format is in `judge-contract.md`. The fixture itself is not sent to the generation model as a rubric.

## Planned use and limits

The runner uses these fixed files with the frozen snapshot. The approved plan allows 36 development calls, an optional 12-call combined candidate only if both independent candidates merit it, and a 72-call final comparison after candidate freeze, for a shared maximum of 120 generation attempts. Failures count toward that cap. No API call or model judgment is represented by the fixture authoring step.

The selection set is a small AI-authored comparison set. It cannot establish broad accuracy, production readiness, or human policy approval.
