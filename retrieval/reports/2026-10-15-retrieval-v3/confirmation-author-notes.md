# Retrieval v3 confirmation author notes

- Status: frozen_independent_ai_reviewed; corrections were independently rechecked and approved. human_review is false.
- Source: data/company-knowledge/documents.jsonl, using only each document's document field. Evidence offsets are Python Unicode code points, zero-based, start-inclusive and end-exclusive.
- Split: V01–V30 are answerable, V31–V35 are partial, and V36–V40 are unanswerable. Partial cases include only source-supported claims in required_claims; unanswerable_part names the requested live or personal state that is not in the corpus. Fully unanswerable cases have empty required and optional claims.
- No retrieval model inference or external answer-generation API was used. The authoring task was completed before development experiments; no scores or experiment results were read.

## Exclusion and intent-overlap notes

Prior intent review used retrieval/reports/2026-10-15-rag-calibration/qrels-v2.json, retrieval/reports/2026-10-15-rag-calibration/new-confirmation.json, and the question text in retrieval/reports/2026-10-15-rag-quality-improvement/cases.json. Existing question wording was not reused as a paraphrase. The new cases test different requested outcomes or policy details, including:

- V02 asks for the available schedule table and collaboration window, while prior H02 asks about next month's application deadline and effective date. V03 asks about late-arrival notice and actual time entry, distinct from prior correction and early-departure procedures. V04 covers regular overtime preapproval and the emergency record branch.
- V05 and V29 split one-time domestic location-change application from changes after an approved location; prior leave and home/overseas remote-work questions concern other procedures.
- V06 asks the monetary approval tiers for a general equipment purchase; the prior SaaS/tool items concern service approval or access. V07 and V30 cover temporary-access expiry and how to revise a rejected request, separate from emergency access and current personal permission lookup.
- V09 tests mixed-classification handling and lowering a label, not whether removing a name automatically changes a document's classification. V11–V12 concern starting or expanding personal-data collection, not retention grounds, deletion requests, or incident response.
- V13 asks when an approved company removable device can be used and how to constrain copies, distinct from the prior customer-provided USB scenario. V14 asks the boundary between project dependency installs and system-level or externally connected tools. V15 asks the general password storage and rotation policy, not credential exposure response.
- V16 tests what may be posted in the finance help channel. V17 covers general record retention categories and periods, not legal-hold scope or personal-data retention basis.
- V18–V19 ask customer-support response targets and safe initial intake. They do not ask whether support can stop after a developer handoff, how to classify a bug or feature request, or what raw customer data may be copied into GitHub. V20 tests duplicate-issue search and linking.
- V21–V24 test high-risk PR review triggers, PR validation detail, normal deployment preflight, and emergency-change authorization/follow-up. They do not repeat self-approval or failure/rollback scenarios.
- V25–V26 cover retrospective eligibility and P1 review deadlines; V27 tests parallel service and security incident routing. These differ from severity/customer-update timing and 15-minute handoff questions.
- V28 asks for team preparation and buddy assignment before/at onboarding, separate from first-login MFA and security-training requirements.
- V31–V35 deliberately combine a documented general rule with a requested individual or live status. Only the rule is judged; the personal request, account, ticket, or file state is explicitly marked unknown.
- V36–V40 ask for site-specific or live operational facts absent from the corpus. They do not repeat prior questions about menus, personal leave balance, room booking, incident impact, repository access, or trip approvals.

Partial cases V32/V33/V34/V35 reuse policies in V06/V15/V18/V17 respectively; these are 40 questions, not 40 statistically independent policies.

## Evidence handling

Every evidence span was located in the cited document body and stored with its exact source text. Required claims are kept to the minimum facts needed to answer each question. Multiple source documents are listed as separate equivalent evidence alternatives only where each supports the same required claim. Initial independent feedback led to claim and evidence revisions; the post-correction semantic and span review passed before freeze.
