# Validation scope

## Automated checks

The test suite covers authenticated API access, model/operation allowlists, context and
output limits, queue admission, disconnect cleanup, streaming responses, monitor operator
access, bounded trace retention, atomic source indexing, private client generation, and
FIM updates across supported YAML layouts. Tests use synthetic data and mock upstreams.

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check codeassist scripts tests
```

Client transfer scripts are intended to run on Python 3.10+ without package downloads.
The gateway requires Python 3.11+. Verify script syntax and client package completeness
when distributing them separately.

## Live checks

`scripts/smoke.py` checks the local API and source-aware chat. `scripts/check-client.py`
checks client connectivity, readiness, FIM and chat. `scripts/check-fim.py` exercises a
larger synthetic C++ fixture, checks completion budgets, and uses g++ when available.
`scripts/benchmark.py` measures first-token and end-to-end latency at one, two, and three
concurrent requests. Its output does not include source or generated response text.

Local validation artifacts and request captures are excluded from this source repository.
A benchmark result must identify model/runtime, hardware, context/output sizes, concurrency,
warm/cold state, and prompt reuse. Short cached synthetic requests are not a capacity
measurement for a large repository or sustained multi-user autocomplete.

## Deployment acceptance

Verify remote LAN access from an actual client, not just server loopback. Check chat and
editor inline completion separately. Test restart, model persistence, cancelled streams,
and mixed long/short requests. Missing models should fail readiness rather than trigger
an external provider fallback.

For offline acceptance, preserve LAN connectivity while removing internet access from
both clients and server, restart services/editor, then test chat, FIM, and intended source
retrieval. The Compose overlay only isolates Ollama; general egress policy is separate.

Generated code requires target-toolchain compilation and relevant tests. Source citations,
C++14 instructions, static diagnostics, and LLM judgments do not prove correctness.
Planned compiler analysis/build-variant features need their own coverage and quality tests.
