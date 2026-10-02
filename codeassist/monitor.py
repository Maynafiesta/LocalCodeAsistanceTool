"""Bounded, volatile request inspection. Credentials are never included in traces."""

import asyncio
import codecs
import hmac
import json
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime

SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
TEXT_FIELDS = {"request_body", "model_request", "model_response", "client_response", "output"}


def timestamp():
    return datetime.now(UTC).isoformat()


def safe_headers(headers):
    return {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in headers
        if key.decode("latin-1").lower() not in SENSITIVE_HEADERS
    }


class TraceStore:
    def __init__(self, capacity=64, per_trace_bytes=4_194_304, total_bytes=33_554_432):
        self.capacity = capacity
        self.per_trace_bytes = per_trace_bytes
        self.total_bytes = total_bytes
        self.records = OrderedDict()
        self.bytes = 0
        self.version = 0
        self.listeners = set()

    def changed(self, record=None):
        self.version += 1
        if record is not None:
            record["version"] = self.version
        for listener in self.listeners:
            listener.set()

    def remove(self, identifier):
        record = self.records.pop(identifier)
        self.bytes -= record["stored_bytes"]

    def start(self, scope, user):
        while len(self.records) >= self.capacity:
            candidate = next(
                (key for key, item in self.records.items() if item["finished_at"]),
                next(iter(self.records)),
            )
            self.remove(candidate)
        identifier = uuid.uuid4().hex
        self.records[identifier] = {
            "id": identifier,
            "user": user,
            "method": scope["method"],
            "path": scope["path"],
            "client": (scope.get("client") or ("unknown", 0))[0],
            "received_at": timestamp(),
            "finished_at": None,
            "status": "receiving",
            "http_status": None,
            "model": None,
            "stream": None,
            "stored_bytes": 0,
            "truncated_fields": [],
            "request_headers": safe_headers(scope.get("headers", [])),
            "response_headers": {},
            "events": [{"stage": "received", "at": timestamp()}],
            "model_done": False,
            "response_bytes_sent": 0,
            "ttft_ms": None,
            "duration_ms": None,
            **{name: "" for name in TEXT_FIELDS},
            "query": scope.get("query_string", b"").decode("utf-8", errors="replace"),
        }
        self.changed(self.records[identifier])
        return identifier

    def append(self, identifier, field, text):
        record = self.records.get(identifier)
        if record is None or not text:
            return
        encoded = text.encode("utf-8")
        needed = min(len(encoded), self.per_trace_bytes - record["stored_bytes"])
        while self.bytes + needed > self.total_bytes:
            candidate = next(
                (
                    key
                    for key, item in self.records.items()
                    if key != identifier and item["finished_at"]
                ),
                None,
            )
            if candidate is None:
                break
            self.remove(candidate)
        available = max(0, min(needed, self.total_bytes - self.bytes))
        kept = encoded[:available].decode("utf-8", errors="ignore")
        size = len(kept.encode("utf-8"))
        if size < len(encoded) and field not in record["truncated_fields"]:
            record["truncated_fields"].append(field)
        if kept:
            record[field] += kept
            record["stored_bytes"] += size
            self.bytes += size
        self.changed(record)

    def stage(self, identifier, stage, **fields):
        record = self.records.get(identifier)
        if record is None:
            return
        record.update(fields)
        record["status"] = stage
        record["events"].append({"stage": stage, "at": timestamp()})
        self.changed(record)

    def model_payload(self, identifier, payload):
        self.stage(
            identifier,
            "model_requested",
            model=payload.get("model"),
            stream=payload.get("stream", True),
        )
        self.append(identifier, "model_request", json.dumps(payload, ensure_ascii=False, indent=2))

    def model_event(self, identifier, event, started):
        record = self.records.get(identifier)
        if record is None:
            return
        if event.get("error"):
            self.stage(identifier, "model_error", error=str(event["error"]))
        message = event.get("message")
        output = event.get("response") or (
            message.get("content", "") if isinstance(message, dict) else ""
        )
        if not isinstance(output, str):
            output = ""
        if output and record["ttft_ms"] is None:
            self.stage(
                identifier, "generating", ttft_ms=round((time.monotonic() - started) * 1000, 2)
            )
        self.append(identifier, "output", output)
        if event.get("done"):
            self.stage(
                identifier,
                "model_done",
                model_done=True,
                model_stats={
                    k: event[k]
                    for k in (
                        "eval_count",
                        "prompt_eval_count",
                        "total_duration",
                        "eval_duration",
                        "load_duration",
                        "done_reason",
                    )
                    if k in event
                },
            )

    async def response_chunks(self, identifier, response, started, streaming):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""

        def consume(text, final=False):
            nonlocal buffer
            self.append(identifier, "model_response", text)
            if streaming:
                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            self.model_event(identifier, event, started)
                    except ValueError:
                        pass
                # Bound parser storage independently of trace retention.
                if len(buffer) > self.per_trace_bytes:
                    buffer = ""
            else:
                buffer += text
                if len(buffer) > self.per_trace_bytes:
                    buffer = ""
            if final and buffer.strip():
                try:
                    event = json.loads(buffer)
                    if isinstance(event, dict):
                        self.model_event(identifier, event, started)
                except ValueError:
                    pass

        async for chunk in response.aiter_bytes():
            consume(decoder.decode(chunk))
            yield chunk
        consume(decoder.decode(b"", final=True), final=True)

    def summaries(self):
        fields = (
            "id",
            "version",
            "user",
            "client",
            "method",
            "path",
            "received_at",
            "finished_at",
            "status",
            "http_status",
            "model",
            "stream",
            "ttft_ms",
            "duration_ms",
            "response_bytes_sent",
            "truncated_fields",
        )
        return [{key: record[key] for key in fields} for record in reversed(self.records.values())]

    def clear_finished(self):
        removed = [key for key, record in self.records.items() if record["finished_at"]]
        for key in removed:
            self.remove(key)
        self.changed()
        return len(removed)

    async def events(self):
        signal = asyncio.Event()
        self.listeners.add(signal)
        version = -1
        try:
            while True:
                if version != self.version:
                    version = self.version
                    yield f'event: refresh\ndata: {{"version":{version}}}\n\n'
                    await asyncio.sleep(0.15)
                signal.clear()
                if version != self.version:
                    continue
                try:
                    await asyncio.wait_for(signal.wait(), timeout=10)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.listeners.discard(signal)


class TraceMiddleware:
    def __init__(self, app, store, tokens):
        self.app = app
        self.store = store
        self.tokens = tokens

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(("/api/", "/v1/context/")):
            return await self.app(scope, receive, send)
        authorization = next((v for k, v in scope.get("headers", []) if k == b"authorization"), b"")
        supplied = authorization[7:] if authorization.startswith(b"Bearer ") else b""
        user = next(
            (
                name
                for name, token in self.tokens.items()
                if hmac.compare_digest(supplied, token.encode())
            ),
            "unauthenticated",
        )
        identifier = self.store.start(scope, user)
        scope.setdefault("state", {})["trace_id"] = identifier
        started = time.monotonic()
        decoder_in = codecs.getincrementaldecoder("utf-8")(errors="replace")
        decoder_out = codecs.getincrementaldecoder("utf-8")(errors="replace")
        finished = disconnected = False
        status = 500
        sent_bytes = 0

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.request":
                text = decoder_in.decode(
                    message.get("body", b""), final=not message.get("more_body", False)
                )
                self.store.append(identifier, "request_body", text)
            elif message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal finished, status, sent_bytes
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-codeassist-trace-id", identifier.encode()),
                    ],
                }
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
                self.store.stage(
                    identifier,
                    "sending",
                    http_status=status,
                    response_headers=safe_headers(message.get("headers", [])),
                )
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                sent_bytes += len(chunk)
                record = self.store.records.get(identifier)
                if record is not None:
                    record["response_bytes_sent"] = sent_bytes
                self.store.append(
                    identifier,
                    "client_response",
                    decoder_out.decode(chunk, final=not message.get("more_body", False)),
                )
                finished = not message.get("more_body", False)

        error_type = None
        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as error:
            error_type = type(error).__name__
            if isinstance(error, asyncio.CancelledError):
                disconnected = True
            raise
        finally:
            record = self.store.records.get(identifier, {})
            if disconnected and not finished:
                final_status = "disconnected"
            elif error_type or status >= 500 or record.get("error"):
                final_status = "failed"
            elif status >= 400:
                final_status = "rejected"
            elif finished:
                final_status = "completed"
            else:
                final_status = "disconnected"
            self.store.stage(
                identifier,
                final_status,
                finished_at=timestamp(),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                response_bytes_sent=sent_bytes,
                error_type=error_type,
            )
