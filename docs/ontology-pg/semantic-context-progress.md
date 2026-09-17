# Semantic context implementation and verification

Baseline: `adf23373c9fed7d0413fd996fe2e065322b00996` in `cfxcode/commerce-agents`.

This implements the mandatory semantic-closure mechanism in the supplied next-stage specification. Work proceeded in verified stages: definition contracts and legacy fixtures; strict schema and registry; pure builder; runtime integration; diagnostics; release compatibility; evaluation contracts. Optional render, static caching, new business scenarios, paid model trials and production activation are not included.

## Delivered

- Nine actions and nine states declare reviewed required/optional semantic dependencies; fourteen properties describe units, owners and business meaning.
- Strict typed validation rejects duplicate YAML keys/IDs, unknown or wrong-kind references, inheritance cycles, missing declarations and unsupported fields. Legacy 1.0 releases remain readable in legacy mode.
- The model-free builder handles action and state seeds, confirmed object types, ancestors, relation endpoints, property owners and check descriptions. Required closures are complete or fail; optional groups are atomic; output is deterministic, bounded and traceable.
- Opt-in closure is consumed by the existing T/P/E guidance path. Default legacy behavior and C0/O input contracts are retained. The six original action fields are explicitly projected so new YAML metadata cannot leak into legacy prompts.
- Semantic build failures are not counted as model calls. Definitions are separate from facts and approvals; T does not receive diagnostic topology; solver history does not accumulate guidance.
- Read-only task-scoped diagnostics and a bilingual semantic panel show dependencies, modes, versions, byte counts and omissions without exposing implementation paths or raw requests.
- Working versus published sources are explicit. A semantic release binds schema, effective prompts, behavioral configuration and recursive source identity, and requires matching test and independently evaluated comparison evidence. Old release files and active pointer are unchanged.
- Separate P_legacy/P_closure configurations and comparison reports fix non-treatment factors, retain all-submission denominators and reject missing usage or incompatible evidence.

## Actual offline validation

Commands ran using repository-pinned Python dependencies in an isolated Python 3.13 environment. No API/model credentials or paid requests were used for these checks.

| Stage | Command / check | Observed result |
|---|---|---|
| Foundation | Full repository pytest | 1375 passed, 1 skipped |
| Runtime integration | Reasoning tests | 278 passed |
| Integrated implementation | Reasoning tests | 306 passed |
| Final local regression, with standalone baseline-capture import fix | `python -m pytest -q -o faulthandler_timeout=10` | 1418 passed, 1 skipped, 2 pre-existing dependency warnings; 29.86 seconds |
| CI verification of transported source | Full repository pytest, Python 3.13 | 1418 passed, 1 skipped, 2 warnings; 29.16 seconds |
| Semantic evidence CLI | `verify-semantics` with the closure candidate | 221 semantic tests and 51 execution-safety tests passed |
| Real retriever preflight | 15 nodes × 0/1/2 hops × unknown/plain/variant | 135 of 135 combinations passed |
| Static checks | `ruff check .`; `ruff format --check .`; `python scripts/check.py` | Passed locally and in CI |
| Retail i18n CI | `node scripts/check_retail_i18n.cjs` | 87 products, 11 policies, 1087 content translations, 16 bilingual card renders passed |
| Web build CI | `cd examples && npm ci && npm run build` | All eight web applications compiled, including TypeScript checks |

CI verification: [run 35129430141](https://github.com/cfxcode/commerce-agents/actions/runs/35129430141), job `verified-source`. Its source manifest verifies all 39 changed-file hashes before testing; after success, the same normal UTF-8 source blobs were exported for the final PR commit. Temporary transport files and write-enabled transport workflows are removed from the final tree. The permanent semantic CI workflow has read-only repository permissions.

Earlier CI attempts caught an import-path issue in the baseline-capture subprocess and a workflow ordering issue that ran the i18n check before npm installation. The capture helper now adds its own examples import path and passes locally without a global examples PYTHONPATH override. npm installation precedes the i18n check. Failed runs remain in Actions history and are not counted as successful verification.

Initial integration tests exposed legacy dictionary/set-order differences, an incorrect disabled-override test expectation, and incomplete comparison identities. These were corrected and the affected tests rerun. Full legacy guide/solver request bytes are captured from the unmodified baseline in a subprocess with PYTHONHASHSEED=0; the compatibility assertion compares the full request rather than stripping fields.

## Verification limits

- These are offline implementation and regression checks, not evidence that closure improves model accuracy.
- Release tests use explicitly synthetic evidence in temporary directories; no real semantic release was published and no active pointer changed.
- P_legacy/P_closure paid model evaluations have not run. This PR does not carry production activation evidence.
- Compilation and existing bilingual rendering checks do not substitute for independent browser visual or full approval-click acceptance. Those manual checks have not been performed in this change.
- Transactions retain the project's single-process simulation boundary; this work does not add production authentication or cross-process transaction guarantees.

See `semantic-context.md` for APIs, exact commands, budgets and rollback constraints. Review the final commit's CI before merging. This change does not merge main or deploy an application.
