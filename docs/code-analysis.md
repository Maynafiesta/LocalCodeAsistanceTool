# Source-grounded C++14 analysis design

This document describes future work. The current gateway supports text chat/FIM and
optional lexical retrieval; it does not run compilers/static analyzers or execute tool calls.

## Analysis layers

Text search and syntax structure extraction require source files, not an application build.
They can run on an ARM64/Jetson CPU using compatible tools. They do not reliably resolve
all macros, overloads, templates, or target-dependent types.

Compiler-based AST/reference analysis needs accurate compilation commands, headers,
generated headers, language flags, macros, sysroot, and target ABI. A complete link or
application execution is not required for parsing, but the parsing environment must match
the actual build. If that environment cannot be reproduced on the analysis server, run
compiler/static analysis on the build machine and transfer versioned results.

## Multiple build scenarios

Different source files can have different flags within one compilation database. Alternative
builds of the same source need explicit variant identity. A database can contain multiple
commands for one file, but tool selection must be controlled.

Capture each real product/target/debug/feature scenario separately, preserving per-file
flags and matching generated headers. Commands that build multiple modules of one product
can belong to the same scenario. Do not union incompatible macros into a global list.

Example layout:

```text
analysis/variant-A/compile_commands.json
analysis/variant-A/generated/
analysis/variant-A/cache/
analysis/variant-B/compile_commands.json
analysis/variant-B/generated/
analysis/variant-B/cache/
```

Run Cppcheck/Clang tools separately for each database and retain build identity on reports.
Use separate caches; invalidate by source/build/tool identity. Cppcheck `--force` expands
preprocessor combinations rather than reconstructing real builds.

Remap source/include/working-directory paths when moving metadata. Preserve response
files, implicit include paths, `-D/-U`, C++14, and target settings. An x86 compiler binary
cannot be executed directly by an ARM64 server; export equivalent driver information or
perform the compiler-dependent work in a compatible environment. Avoid accidentally
using the server's architecture as the source project's target.

## Selected-file review pipeline

1. Receive the selected file/function, current buffer, review question, and source/build
   identity. Apply unsaved code through an isolated temporary workspace/overlay.
2. Retrieve relevant declarations, implementations, callers, ownership/thread contracts,
   and version-specific library references. Record missing or unresolved relationships.
3. Run targeted C++14-compatible clang-tidy, Clang Static Analyzer, or Cppcheck checks on
   the relevant translation units. Header changes can affect multiple units. Filtering a
   report to changed lines does not itself reduce compiler-analysis cost.
4. Give the Instruct model the current code, bounded related sources, and raw diagnostics.
   Request explanations, small patches, and regression tests. Large files need staged review;
   the entire repository is not placed in one prompt.
5. Report file/line/build identity, trigger conditions, evidence, proposed change, and
   validation state. Distinguish tool diagnostics, model hypotheses, and tested findings.
   Keep raw diagnostics even when the model disagrees; do not claim unexecuted tests passed.

Useful review topics include resource lifetime, partial I/O and framing, timeouts, Qt thread
affinity, GStreamer reference ownership, and callback/shutdown ordering. Runtime behavior
may require protocol contracts, tests, traces, or target hardware beyond source alone.

## Models and resources

The current 1.5B Base model serves FIM; 7B Instruct serves chat/review. This compares both
size and training style. Compare Base models for FIM and Instruct models for review when
measuring quality. Model size alone does not determine correctness or a fixed speed ratio.

CPU/RAM/NVMe handle source/AST indexes, static tools, and reports. GPU memory holds weights,
context caches, and inference buffers. Integrated-GPU systems share memory with the OS/CPU.
Larger context, simultaneous models, and active requests need joint memory measurements.

Keep heavy review jobs in a separate queue/budget from latency-sensitive FIM. Shared GPU
resources still require mixed-load latency testing. Prepare all tool/model dependencies
before offline deployment; source refresh and analysis can then occur on the LAN.

## Acceptance

Begin with one representative module, real build metadata, known defects, and clean
counterexamples. Measure parse/source coverage, missing headers/macros, correct findings,
false positives, review latency, memory, and FIM interference. Expand after the pilot;
retain baselines and analyze changed/affected translation units incrementally.

References: [compilation databases](https://clang.llvm.org/docs/JSONCompilationDatabase.html),
[clangd build context](https://clangd.llvm.org/design/compile-commands),
[Bear](https://github.com/rizsotto/Bear), [Clang-Tidy](https://clang.llvm.org/extra/clang-tidy/),
[Cppcheck](https://cppcheck.sourceforge.io/manual.html).
