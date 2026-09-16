# Semantic context implementation

Base: `adf23373c9fed7d0413fd996fe2e065322b00996`.

Scope: implement explicit semantic dependencies and a bounded, deterministic definition closure, then integrate it with the existing guidance path. The requested implementation plan is `commerce-agents_下一阶段实施计划_语义依赖与上下文检索.md` supplied in the conversation.

The work is staged as reviewable commits: baseline; schema and metadata; pure builder; runtime; diagnostics; release compatibility; evaluation contracts. Optional render generation and paid model evaluations are excluded. Existing release snapshots, business checks, PG topology and historical reports remain unchanged.

The dedicated pull-request workflow runs offline tests without model credentials. Its seven-day artifact contains only the tracked source archive, commit identity and validation outputs; it does not include `.git`, runtime databases or untracked credentials. CI results are evidence only after the workflow has actually completed. No tests have been independently completed at this initial baseline commit.

- [x] Confirm main matches the specification baseline.
- [x] Add an offline CI evidence path.
- [ ] Freeze legacy contract/request expectations.
- [ ] Implement semantic schema and reference validation.
- [ ] Implement and test the pure closure builder.
- [ ] Integrate opt-in runtime guidance.
- [ ] Add safe diagnostics and complete metrics.
- [ ] Bind schemas and effective prompts to releases.
- [ ] Record actual test results and remaining limitations.
