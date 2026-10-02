import asyncio
import json
import time

import httpx
import pytest
from test_gateway import TOKEN, client_for

from codeassist.monitor import TraceMiddleware, TraceStore
from codeassist.settings import Settings


async def test_trace_auth_original_payload_policy_output_and_no_credentials(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "return a + b;"}, "done": True})

    async with client_for(tmp_path, handler, monitor_users=("dev",)) as (client, app):
        payload = {
            "model": Settings.chat_model,
            "stream": False,
            "messages": [{"role": "user", "content": "Türkçe toplama <script>1</script>"}],
            "options": {"num_ctx": 90000},
        }
        response = await client.post("/api/chat", json=payload, headers={"Cookie": "secret"})
        identifier = response.headers["x-codeassist-trace-id"]
        listing = (await client.get("/v1/monitor/requests")).json()
        assert listing["requests"][0]["id"] == identifier
        assert len(listing["requests"]) == 1
        detail = await client.get("/v1/monitor/requests/" + identifier)
        record = detail.json()
        assert record["status"] == "completed" and record["http_status"] == 200
        assert json.loads(record["request_body"]) == payload
        forwarded = json.loads(record["model_request"])
        assert forwarded["options"]["num_ctx"] == 4096
        assert "C++14" in forwarded["messages"][0]["content"]
        assert forwarded["messages"][1:] == payload["messages"]
        assert record["output"] == "return a + b;" and record["model_done"]
        assert record["client_response"].encode() == response.content
        assert record["model_response"].encode() == response.content
        assert record["response_bytes_sent"] == len(response.content)
        assert record["ttft_ms"] is not None and record["duration_ms"] is not None
        assert "authorization" not in record["request_headers"]
        assert "cookie" not in record["request_headers"]
        assert TOKEN not in detail.text and '"secret"' not in detail.text
        assert detail.headers["cache-control"] == "no-store"
        app.state.settings.tokens["laptop"] = "l" * 40
        laptop = {"Authorization": "Bearer " + "l" * 40}
        for path in (
            "/v1/monitor/requests",
            "/v1/monitor/requests/" + identifier,
            "/v1/monitor/events",
        ):
            assert (await client.get(path, headers=laptop)).status_code == 403
            assert (await client.get(path, headers={"Authorization": "bad"})).status_code == 401
        assert (await client.delete("/v1/monitor/requests", headers=laptop)).status_code == 403
        assert (await client.get("/monitor", headers={"Authorization": "bad"})).status_code == 200
        assert len(app.state.traces.records) == 1  # Observer traffic never creates traces.
        assert (await client.delete("/v1/monitor/requests")).json() == {"removed": 1}
        assert (await client.get("/v1/monitor/requests/" + identifier)).status_code == 404


class SplitStream(httpx.AsyncByteStream):
    def __init__(self, wire):
        self.wire = wire

    async def __aiter__(self):
        for byte in self.wire:
            yield bytes([byte])


async def test_utf8_stream_is_observed_without_changing_wire(tmp_path):
    wire = (
        '{"message":{"content":"İşlem "},"done":false}\n'
        '{"message":{"content":"tamam ✓"},"done":false}\n'
        '{"done":true,"eval_count":5}\n'
    ).encode()

    def handler(request):
        return httpx.Response(200, stream=SplitStream(wire))

    async with client_for(tmp_path, handler) as (client, app):
        response = await client.post(
            "/api/chat",
            json={"model": Settings.chat_model, "messages": [{"role": "user", "content": "test"}]},
        )
        assert response.content == wire
        record = app.state.traces.records[response.headers["x-codeassist-trace-id"]]
        assert record["output"] == "İşlem tamam ✓"
        assert record["model_response"].encode() == record["client_response"].encode() == wire
        assert record["model_stats"]["eval_count"] == 5
        assert record["status"] == "completed"
        assert app.state.gate.outstanding == 0


async def test_failures_are_visible_and_release_gate(tmp_path):
    def handler(request):
        raise httpx.ConnectError("offline")

    async with client_for(tmp_path, handler) as (client, app):
        response = await client.post(
            "/api/generate", json={"model": Settings.completion_model, "prompt": "test"}
        )
        record = app.state.traces.records[response.headers["x-codeassist-trace-id"]]
        assert record["http_status"] == 502 and record["status"] == "failed"
        assert "unavailable" in record["client_response"]
        response = await client.post("/api/generate", content="invalid")
        record = app.state.traces.records[response.headers["x-codeassist-trace-id"]]
        assert record["request_body"] == "invalid" and record["status"] == "rejected"
        assert record["http_status"] == 400
        assert app.state.gate.outstanding == 0


def scope():
    return {"type": "http", "method": "POST", "path": "/api/chat", "headers": []}


def test_trace_payload_budget_utf8_eviction_and_active_clear():
    store = TraceStore(capacity=2, per_trace_bytes=8, total_bytes=10)
    first = store.start(scope(), "dev")
    store.append(first, "output", "İİİİİ")
    assert store.records[first]["output"] == "İİİİ"
    assert store.records[first]["truncated_fields"] == ["output"]
    store.stage(first, "completed", finished_at="now")
    second = store.start(scope(), "dev")
    store.append(second, "output", "abcdef")
    assert first not in store.records and store.bytes == 6
    third = store.start(scope(), "dev")
    store.append(third, "output", "İİİ")
    assert store.bytes == 10 and store.records[third]["output"] == "İİ"
    assert store.clear_finished() == 0
    store.start(scope(), "dev")
    assert len(store.records) == 2 and store.bytes == 4


async def test_sse_refresh_and_subscriber_cleanup():
    store = TraceStore()
    events = store.events()
    assert '"version":0' in await anext(events)
    assert len(store.listeners) == 1
    store.start(scope(), "dev")
    assert '"version":1' in await asyncio.wait_for(anext(events), 1)
    await events.aclose()
    assert not store.listeners


async def test_failed_write_does_not_count_as_sent():
    store = TraceStore()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"not sent", "more_body": False})

    async def send(message):
        if message["type"] == "http.response.body":
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await TraceMiddleware(app, store, {})(scope(), None, send)
    record = next(iter(store.records.values()))
    assert record["status"] == "disconnected"
    assert record["response_bytes_sent"] == 0 and record["client_response"] == ""


async def test_model_error_and_last_line_without_newline():
    store = TraceStore()
    identifier = store.start(scope(), "dev")
    response = httpx.Response(500, content=b'{"error":"model failed"}')
    async for _ in store.response_chunks(identifier, response, time.monotonic(), streaming=True):
        pass
    assert store.records[identifier]["status"] == "model_error"
    assert store.records[identifier]["error"] == "model failed"


def test_monitor_users_must_be_names(monkeypatch):
    monkeypatch.setenv("CODEASSIST_TOKENS", json.dumps({"dev": TOKEN}))
    for value in ('"dev"', '{"dev":true}', "[1]", "null"):
        monkeypatch.setenv("MONITOR_USERS", value)
        with pytest.raises(ValueError, match="MONITOR_USERS"):
            Settings.from_env()
