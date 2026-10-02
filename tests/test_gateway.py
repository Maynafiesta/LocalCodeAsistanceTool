import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import HTTPException

from codeassist.app import ManagedResponse, create_app
from codeassist.context import index_project
from codeassist.limits import InferenceGate
from codeassist.settings import Settings

TOKEN = "x" * 40


@asynccontextmanager
async def client_for(tmp_path, handler, **overrides):
    settings = Settings(
        tokens={"dev": TOKEN}, index_path=str(tmp_path / "context.sqlite"), **overrides
    )
    app = create_app(settings, transport=httpx.MockTransport(handler))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        yield client, app


async def test_auth_allowlists_validation_and_memory_policy(tmp_path):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "return value;", "done": True})

    async with client_for(tmp_path, handler, max_body_bytes=1000) as (client, app):
        assert (await client.get("/metrics", headers={"Authorization": "bad"})).status_code == 401
        payload = {
            "model": app.state.settings.completion_model,
            "prompt": "int x = ",
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": 1000000, "num_predict": -1, "num_gpu": 0},
        }
        assert (await client.post("/api/generate", json=payload)).status_code == 200
        assert captured[0]["options"] == {"num_ctx": 8192, "num_predict": 256}
        assert captured[0]["keep_alive"] == "15m"
        assert (await client.post("/api/pull", json=payload)).status_code == 404
        assert (
            await client.post("/api/generate", json={**payload, "model": "cloud"})
        ).status_code == 403
        assert (
            await client.post("/api/generate", json={**payload, "model": []})
        ).status_code == 422
        assert (await client.post("/api/show", json={"model": []})).status_code == 422
        assert (
            await client.post("/api/generate", json={**payload, "stream": "false"})
        ).status_code == 422
        assert (await client.post("/api/generate", content=b"x" * 1001)).status_code == 413
        assert (await client.post("/api/generate", content=b"[]")).status_code == 422
        assert (await client.post("/api/generate", content=b"{")).status_code == 400
        assert app.state.gate.active == app.state.gate.outstanding == 0


async def test_completion_budget_is_configurable_and_independent_of_chat(tmp_path):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "a + b", "done": True})

    async with client_for(
        tmp_path, handler, completion_context_length=16384, completion_max_tokens=512
    ) as (client, app):
        for requested in (256, 2000):
            response = await client.post(
                "/api/generate",
                json={
                    "model": app.state.settings.completion_model,
                    "prompt": "return ",
                    "stream": False,
                    "options": {"num_ctx": 999999, "num_predict": requested},
                },
            )
            assert response.status_code == 200
            assert captured[-1]["options"] == {"num_ctx": 16384, "num_predict": min(requested, 512)}
        response = await client.post(
            "/api/chat",
            json={
                "model": app.state.settings.chat_model,
                "stream": False,
                "messages": [{"role": "user", "content": "test"}],
                "options": {"num_ctx": 16384, "num_predict": 2000},
            },
        )
        assert response.status_code == 200
        assert captured[-1]["options"] == {"num_ctx": 4096, "num_predict": 1024}


async def test_chat_retrieval_preserves_history_and_stream_protocol(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "serial.cpp").write_text("void SerialDevice::readFrame() { /* partial read */ }")
    index_project(project, tmp_path / "context.sqlite")
    captured = []
    wire = b'{"message":{"content":"C++14"},"done":false}\n{"done":true}\n'

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=wire, headers={"Content-Type": "application/x-ndjson"})

    async with client_for(tmp_path, handler) as (client, app):
        messages = [
            {"role": "system", "content": "team rules"},
            {"role": "user", "content": "SerialDevice readFrame açıkla"},
        ]
        response = await client.post(
            "/api/chat", json={"model": app.state.settings.chat_model, "messages": messages}
        )
        assert response.content == wire
        assert "serial.cpp:1-1" in captured[0]["messages"][0]["content"]
        assert captured[0]["messages"][1:] == messages
        assert app.state.gate.active == app.state.gate.outstanding == 0
        hits = await client.get("/v1/context/search", params={"q": "readFrame"})
        assert hits.json()["results"][0]["path"] == "serial.cpp"


@pytest.mark.parametrize(
    "error,status", [(httpx.ConnectError("down"), 502), (httpx.ReadTimeout("slow"), 504)]
)
async def test_upstream_failures_release_capacity(tmp_path, error, status):
    def handler(request):
        raise error

    async with client_for(tmp_path, handler) as (client, app):
        response = await client.post(
            "/api/generate",
            json={"model": app.state.settings.completion_model, "prompt": "int x = "},
        )
        assert response.status_code == status
        assert app.state.gate.outstanding == app.state.gate.active == 0


async def test_readiness_requires_both_models_and_tags_hide_other_models(tmp_path):
    def handler(request):
        return httpx.Response(
            200, json={"models": [{"name": Settings.chat_model}, {"name": "other"}]}
        )

    async with client_for(tmp_path, handler) as (client, _app):
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 503
        assert len((await client.get("/api/tags")).json()["models"]) == 1


async def test_gate_queue_full_timeout_and_cancel_do_not_leak():
    gate = InferenceGate(1, 1)
    async with gate.slot(1):
        waiter = asyncio.create_task(gate.slot(10).__aenter__())
        await asyncio.sleep(0)
        with pytest.raises(HTTPException) as full:
            async with gate.slot(1):
                pass
        assert full.value.status_code == 429
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        with pytest.raises(HTTPException) as timed_out:
            async with gate.slot(0.01):
                pass
        assert timed_out.value.status_code == 429
        assert gate.outstanding == gate.active == 1
    assert gate.outstanding == gate.active == 0
    async with gate.slot(1):
        assert gate.active == 1


async def test_gate_enforces_concurrency():
    gate = InferenceGate(3, 15)
    peak = 0

    async def operation():
        nonlocal peak
        async with gate.slot(1):
            peak = max(peak, gate.active)
            await asyncio.sleep(0.01)

    await asyncio.gather(*(operation() for _ in range(15)))
    assert peak == 3
    assert gate.completed == 15
    assert gate.outstanding == 0


async def test_response_cleanup_when_cancelled_before_first_byte():
    gate = InferenceGate(1, 0)
    lease = gate.slot(1)
    await lease.__aenter__()

    class CancelledResponse:
        status_code = 200

        async def __call__(self, scope, receive, send):
            raise asyncio.CancelledError()

    async def cleanup():
        await lease.__aexit__(None, None, None)

    with pytest.raises(asyncio.CancelledError):
        await ManagedResponse(CancelledResponse(), cleanup)({}, None, None)
    assert gate.outstanding == gate.active == 0
