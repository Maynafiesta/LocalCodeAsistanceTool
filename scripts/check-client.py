"""Run on the laptop to verify LAN, credentials and both local models without a project index."""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from client_config import credentials, inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--inspect", action="store_true", help="List configured models; never print keys")
    args = parser.parse_args()
    try:
        content = args.config.read_text(encoding="utf-8")
        if args.inspect:
            print("Config: " + str(args.config.resolve()))
            print(json.dumps(inspect(content), indent=2))
            return
        base, authorization = credentials(content)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, payload=None, authenticated=True):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": authorization} if authenticated else {}),
            },
        )
        with opener.open(request, timeout=150) as response:
            return json.load(response)

    print(f"Server: {base}", flush=True)
    try:
        assert call("/health/live", authenticated=False)["status"] == "ok"
        print("LAN HTTP connection: OK", flush=True)
        assert call("/health/ready")["status"] == "ready"
        print("Client credentials and model readiness: OK", flush=True)
        tags = call("/api/tags")
        print("Available models: " + ", ".join(m["name"] for m in tags["models"]), flush=True)
        call("/api/show", {"model": "qwen2.5-coder:1.5b-base"})
        result = call(
            "/api/generate",
            {
                "model": "qwen2.5-coder:1.5b-base",
                "stream": False,
                "prompt": "// Return the sum of two integers.\nint add(int a, int b) {\n    return ",
                "suffix": ";\n}\n\nint subtract(int a, int b) {\n    return a - b;\n}\n",
                "options": {"temperature": 0, "num_predict": 32},
            },
        )
        assert result.get("done") and result.get("response", "").strip()
        print("Completion: OK -> " + result["response"].strip(), flush=True)
        result = call(
            "/api/chat",
            {
                "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": "In C++14, write a function adding two integers. Return only code.",
                    }
                ],
                "options": {"temperature": 0, "num_predict": 128},
            },
        )
        assert result.get("done") and result.get("message", {}).get("content", "").strip()
        print("Chat: OK\n" + result["message"]["content"], flush=True)
        print("Client API checks passed. Next, test chat and inline completion in Continue.")
    except urllib.error.HTTPError as error:
        print(
            f"HTTP {error.code}: check credentials (401), model readiness (503), or server logs.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(
            f"Network error: {error}. Check same LAN, server address and port 8080.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except (AssertionError, ValueError, KeyError):
        raise SystemExit("Unexpected or empty model response; check server logs")


if __name__ == "__main__":
    main()
