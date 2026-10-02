# Roadmap

## Implemented prototype

- Continue configuration for separate local chat/edit and FIM models.
- Authenticated FastAPI proxy with allowlisted local Ollama operations.
- Bounded inference admission, cancellation cleanup, and streaming.
- Independent completion/chat context policies.
- Optional CPU SQLite FTS5 source retrieval for chat.
- Volatile operator-only request monitoring through a browser and REST/SSE.
- Private client generation, client checks, and FIM configuration updates.
- Offline image/model export and synthetic automated tests.

## Next stages

| Stage | Work | Acceptance |
|---|---|---|
| Source coverage | Build-file coverage, larger files, exclusions inventory | Explain indexed/skipped files |
| Source structure | Function/class chunks, source identities, incremental refresh | Correct references and snapshot matching |
| Compiler context | Per-build compilation databases and compatible headers | Successful parsing of representative modules |
| Code analysis | Targeted static tools plus source-grounded model review | Known defects, false-positive measurement, verified fixes |
| FIM retrieval | Small relevant declarations/examples and current buffers | Useful suggestions within a latency budget |
| Multi-user pilot | Fairness, workload separation, HTTPS, quotas | Measured mixed-load latency and offline acceptance |

Implementation status and design are separate. Compiler analysis, build-variant selection,
central FIM retrieval, and incremental indexing are not currently implemented.

Start with a representative module and known-answer tasks. Measure source coverage,
retrieval relevance, code compilation, suggestion acceptance, diagnostic quality, RAM/VRAM,
and latency before expanding scope or choosing production hardware. Bigger models and
longer context require quality and memory measurements; they do not replace correct sources.

Details: [large-project indexing](large-cpp-index.md), [code analysis](code-analysis.md),
[validation](validation.md), [offline deployment](offline.md).
