"""Measure warm-request TTFT and end-to-end latency; never store source or generated code."""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

CHAT_MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"
COMPLETION_MODEL = "qwen2.5-coder:1.5b-base"


def credentials(path: Path, user: str):
    line = next(
        line for line in path.read_text().splitlines() if line.startswith("CODEASSIST_TOKENS=")
    )
    return json.loads(line.split("=", 1)[1].strip().strip("'"))[user]


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


async def sample(client, kind, maximum):
    started = time.perf_counter()
    first = None
    final = {}
    if kind == "completion":
        endpoint = "/api/generate"
        payload = {
            "model": COMPLETION_MODEL,
            "prompt": "#include <cstdint>\nstd::uint16_t readBigEndian(const unsigned char* p) {\n",
            "suffix": "\n}\n",
            "options": {"num_predict": maximum, "temperature": 0.1},
        }
    else:
        endpoint = "/api/chat"
        payload = {
            "model": CHAT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": "In C++14, show a short function that reads a big endian uint16_t "
                    "from two bytes. Return only code.",
                }
            ],
            "options": {"num_predict": maximum, "temperature": 0.1},
        }
    try:
        async with client.stream("POST", endpoint, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise RuntimeError("upstream stream error")
                text = event.get("response") or event.get("message", {}).get("content")
                if text and first is None:
                    first = time.perf_counter()
                if event.get("done"):
                    final = event
        if not final or first is None:
            raise RuntimeError("incomplete model response")
        return {
            "kind": kind,
            "ok": True,
            "ttft_seconds": first - started,
            "latency_seconds": time.perf_counter() - started,
            "output_tokens": final.get("eval_count", 0),
            "decode_tokens_per_second": final.get("eval_count", 0)
            / max(final.get("eval_duration", 0) / 1e9, 1e-9),
        }
    except (httpx.HTTPError, ValueError, RuntimeError) as error:
        return {
            "kind": kind,
            "ok": False,
            "error_type": type(error).__name__,
            "latency_seconds": time.perf_counter() - started,
        }


async def run(args):
    token = credentials(args.env, args.user)
    report = {
        "models": {"chat": CHAT_MODEL, "completion": COMPLETION_MODEL},
        "rounds": args.rounds,
        "max_output_tokens": args.tokens,
        "results": [],
    }
    async with httpx.AsyncClient(
        base_url=args.server,
        timeout=150,
        trust_env=False,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.get("/health/ready")
        response.raise_for_status()
        # Exclude cold load from measurements and verify both models actually respond.
        for kind in ("completion", "chat"):
            warm = await sample(client, kind, 16)
            if not warm["ok"]:
                raise RuntimeError(f"Warmup failed: {warm}")
        for kind in ("completion", "chat", "mixed"):
            for concurrency in (1, 2, 3):
                samples = []
                started = time.perf_counter()
                for _ in range(args.rounds):
                    kinds = [
                        kind
                        if kind != "mixed"
                        else ("chat" if i == concurrency - 1 else "completion")
                        for i in range(concurrency)
                    ]
                    samples.extend(
                        await asyncio.gather(*(sample(client, k, args.tokens) for k in kinds))
                    )
                elapsed = time.perf_counter() - started
                successes = [s for s in samples if s["ok"]]
                row = {
                    "kind": kind,
                    "concurrency": concurrency,
                    "requests": len(samples),
                    "errors": len(samples) - len(successes),
                    "wall_seconds": elapsed,
                    "samples": samples,
                }
                if successes:
                    row.update(
                        ttft_p50=statistics.median(s["ttft_seconds"] for s in successes),
                        ttft_p95=percentile([s["ttft_seconds"] for s in successes], 0.95),
                        latency_p95=percentile([s["latency_seconds"] for s in successes], 0.95),
                        aggregate_tokens_per_second=sum(s["output_tokens"] for s in successes)
                        / elapsed,
                    )
                report["results"].append(row)
                print(
                    f"{kind}: concurrency={concurrency}, errors={row['errors']}, "
                    f"TTFT p95={row.get('ttft_p95', 0):.3f}s",
                    flush=True,
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if any(row["errors"] for row in report["results"]):
        raise SystemExit("Benchmark contains failures; inspect the report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--user", default="developer")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--tokens", type=int, default=64)
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    args = parser.parse_args()
    if args.rounds < 1 or not 1 <= args.tokens <= 256:
        parser.error("rounds >= 1 and tokens between 1 and 256 are required")
    asyncio.run(run(args))
