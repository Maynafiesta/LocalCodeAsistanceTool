# Large C++ source indexing design

This is planned work beyond the current line-based lexical prototype. Source indexing
can run without compiling the application. Compiler-level type/reference analysis needs
additional build context; see the [analysis design](code-analysis.md).

## Scope and ingestion

Start with C/C++ sources, headers, inline/template files, Makefiles, `.mk/.mak`, and Qt
`.pro/.pri/.prf` files. Exclude binaries, object files, duplicated dependencies, and generated
outputs from model retrieval. Include selected dependency headers/version documents when
needed; compiler parsing may still require generated headers excluded from retrieval.

Ingest an explicit snapshot, record exclusions/reasons, split functions/classes into bounded
chunks, and attach file/line/hash identity. Stream files instead of placing the entire source
tree in model context. Indexing does not change model weights.

The prototype skips files over 512 KB, uses overlapping 80-line chunks, omits extensionless
Makefiles and several build extensions, and rebuilds the index in full. These limitations
must be resolved and coverage measured before relying on it for a large repository.

## Storage and search

CPU SQLite FTS/symbol search is the first layer. Optional local embeddings/reranking can
improve natural-language retrieval after lexical search is evaluated. Source/index size is
not a model VRAM requirement. Budget disk for snapshots, metadata, indexes, and atomic
rebuilds; measure actual output/RSS on a representative subset before predicting full cost.

An illustrative vector size is 100,000 chunks × 768 dimensions × 4 bytes = 307.2 MB.
This excludes text, metadata, search structures, and the embedding runtime.

## Updates and build variants

Keep source/branch/commit identity. Changed, added, and deleted files need incremental
processing and invalidation. Current client buffers take precedence over older server
snapshots; path mapping must be explicit.

Source text can be shared across build variants. Compiler-derived symbols, active macro
branches, and diagnostics depend on the selected target/build. Do not merge all defines
into one artificial configuration. Capture separate real build scenarios, including
matching generated headers and include/sysroot information.

## Chat and FIM

Chat retrieves bounded relevant chunks and reports file/line references. A large index
does not remove model context limits. Retrieval errors and model errors are measured
separately.

FIM currently uses Continue's cursor/buffer context and does not query the central index.
A future integration should add small relevant declarations and examples, preferably
cached, without running full retrieval/embedding on every keystroke.

## Offline preparation

Prepare parser/tool versions, model/tokenizer assets, dependencies, and local library
documents before deployment. Source snapshots and indexes can then be created/refreshed
on the closed LAN. Test startup with no internet and intended local caches.
