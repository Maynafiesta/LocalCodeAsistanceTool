"""Measure FIM on a larger public C++ fixture; never read the user's project."""

import argparse
import asyncio
import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import httpx
from benchmark import COMPLETION_MODEL, credentials, percentile


def fixture():
    helpers = "\n".join(
        f"inline std::uint32_t transform_{i}(std::uint32_t x) noexcept "
        f"{{ return (x ^ {i * 31}u) + {i}u; }}"
        for i in range(64)
    )
    prefix = (
        "#include <cstdint>\nnamespace packet_helpers {\n"
        + helpers
        + "\n}\n\n// Return the sum of two integers.\nint add(int a, int b) {\n    return "
    )
    suffix = ";\n}\n\nint subtract(int a, int b) {\n    return a - b;\n}\n"
    return prefix, suffix


async def sample(client, prefix, suffix, maximum):
    started = time.perf_counter()
    first = None
    final = None
    generated = ""
    async with client.stream(
        "POST",
        "/api/generate",
        json={
            "model": COMPLETION_MODEL,
            "prompt": prefix,
            "suffix": suffix,
            "options": {"temperature": 0, "num_predict": maximum},
        },
    ) as response:
        response.raise_for_status()
        identifier = response.headers["x-codeassist-trace-id"]
        async for line in response.aiter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError("Model returned a stream error")
            if event.get("response"):
                first = first or time.perf_counter()
                generated += event["response"]
            if event.get("done"):
                final = event
    elapsed = time.perf_counter() - started
    if first is None or final is None:
        raise RuntimeError("Incomplete FIM stream")
    detail = await client.get("/v1/monitor/requests/" + identifier)
    detail.raise_for_status()
    forwarded = json.loads(detail.json()["model_request"])
    assert forwarded["options"]["num_ctx"] == 8192
    assert forwarded["options"]["num_predict"] == maximum
    return {
        "ttft_seconds": first - started,
        "latency_seconds": elapsed,
        "prompt_tokens": final.get("prompt_eval_count"),
        "output_tokens": final.get("eval_count"),
        "generated": generated,
        "context_length": forwarded["options"]["num_ctx"],
        "output_limit": forwarded["options"]["num_predict"],
    }


async def run(args):
    prefix, suffix = fixture()
    report = {
        "synthetic_fixture": True,
        "prefix_bytes": len(prefix.encode()),
        "client_prompt_budget": 4096,
        "results": [],
    }
    async with httpx.AsyncClient(
        base_url=args.server,
        timeout=150,
        trust_env=False,
        headers={"Authorization": "Bearer " + credentials(args.env, args.user)},
    ) as client:
        warm = await sample(client, prefix, suffix, 256)
        report["warmup"] = warm
        assert warm["generated"].strip() == "a + b", "Unexpected synthetic completion"
        compiler = shutil.which("g++")
        if compiler:
            checked = await asyncio.to_thread(
                subprocess.run,
                [
                    compiler,
                    "-std=c++14",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-x",
                    "c++",
                    "-fsyntax-only",
                    "-",
                ],
                input=prefix + warm["generated"] + suffix,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            report["cpp14_compiles"] = checked.returncode == 0
            assert checked.returncode == 0, checked.stderr
        for concurrency in (1, 3):
            samples = []
            for _ in range(args.rounds):
                samples.extend(
                    await asyncio.gather(
                        *(sample(client, prefix, suffix, 256) for _ in range(concurrency))
                    )
                )
            report["results"].append(
                {
                    "concurrency": concurrency,
                    "requests": len(samples),
                    "ttft_p50": statistics.median(s["ttft_seconds"] for s in samples),
                    "ttft_p95": percentile([s["ttft_seconds"] for s in samples], 0.95),
                    "latency_p95": percentile([s["latency_seconds"] for s in samples], 0.95),
                    "samples": samples,
                }
            )
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cpp14_compiles": report.get("cpp14_compiles"),
                "prompt_tokens": warm["prompt_tokens"],
                "output": warm["generated"],
                "timings": [
                    {k: v for k, v in row.items() if k != "samples"} for row in report["results"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--user", default="developer")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/fim-validation.json"))
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    asyncio.run(run(args))
