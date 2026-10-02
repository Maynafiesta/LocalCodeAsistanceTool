"""Real inference smoke test using only public fixture code, never the user's project."""

import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
from benchmark import CHAT_MODEL, COMPLETION_MODEL, credentials


async def run(args):
    token = credentials(args.env, args.user)
    report = {}
    async with httpx.AsyncClient(
        base_url=args.server,
        timeout=150,
        trust_env=False,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        response = await client.post(
            "/api/generate",
            json={
                "model": COMPLETION_MODEL,
                "prompt": "// Return the sum of two integers.\nint add(int a, int b) {\n    return ",
                "suffix": ";\n}\n\nint subtract(int a, int b) {\n    return a - b;\n}\n",
                "stream": False,
                "options": {"num_predict": 32, "temperature": 0},
            },
        )
        response.raise_for_status()
        event = response.json()
        generated = event.get("response", "")
        if not generated.strip() or not event.get("done"):
            raise RuntimeError("No completion generated")
        report["completion"] = {"generated": generated, "output_tokens": event.get("eval_count")}
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
                input="int add(int a, int b) {\n    return "
                + generated
                + ";\n}\n\nint subtract(int a, int b) {\n    return a - b;\n}\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            report["completion"]["cpp14_compiles"] = checked.returncode == 0
            if checked.returncode:
                report["completion"]["compiler_error"] = checked.stderr
        if not args.completion_only:
            response = await client.get("/health/ready")
            response.raise_for_status()
            query = (
                "SerialFrameDecoder hasCompleteFrame hangi koşulları kontrol ediyor? "
                "Kaynak dosya adını ve satır numaralarını ver."
            )
            context = await client.get("/v1/context/search", params={"q": query})
            context.raise_for_status()
            if not context.json()["results"]:
                raise RuntimeError("Fixture index is missing; index examples/embedded first")
            response = await client.post(
                "/api/chat",
                json={
                    "model": CHAT_MODEL,
                    "stream": False,
                    "messages": [{"role": "user", "content": query}],
                    "options": {"num_predict": 512, "temperature": 0},
                },
            )
            response.raise_for_status()
            event = response.json()
            if not event.get("done") or not event.get("message", {}).get("content"):
                raise RuntimeError("No chat answer generated")
            answer = event["message"]["content"]
            report["chat"] = {
                "answer": answer,
                "mentions_fixture": "serial_frame.hpp" in answer,
                "output_tokens": event.get("eval_count"),
            }
        # Abandon a stream after the first token and verify capacity returns to zero.
        async with client.stream(
            "POST",
            "/api/generate",
            json={
                "model": COMPLETION_MODEL,
                "prompt": "// List many C++14 example functions\n",
                "options": {"num_predict": 128},
            },
        ) as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if line and json.loads(line).get("response"):
                    break
        for _ in range(30):
            metrics = (await client.get("/metrics")).json()
            if metrics["active"] == metrics["queued"] == 0:
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Abandoned stream leaked inference capacity")
        report["cancel_releases_capacity"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "completion_cpp14_compiles": report["completion"].get("cpp14_compiles"),
                "chat_mentions_fixture": report.get("chat", {}).get("mentions_fixture"),
                "cancel_releases_capacity": True,
            },
            ensure_ascii=False,
        )
    )
    if report["completion"].get("cpp14_compiles") is False:
        raise SystemExit("Generated sample failed C++14 syntax checking")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--user", default="developer")
    parser.add_argument("--completion-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("artifacts/smoke.json"))
    asyncio.run(run(parser.parse_args()))
