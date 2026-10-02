# Live request monitor

Open `/monitor` on the gateway, for example `http://127.0.0.1:8080/monitor`.
Enter the operator's private access key from the generated configuration, without the
`Bearer ` prefix. The browser keeps it only in tab memory; it is not placed in the URL
or persistent browser storage. Disconnect clears the key and displayed data.

The monitor shows chat/completion requests, forwarded model payloads, streaming output,
raw model/client responses, status/timing information, and inference counters.
Filters keep autocomplete traffic separate from chat. `completed` means the ASGI server
wrote the response to the connection; it does not prove editor display or acceptance.

## Access and retention

`MONITOR_USERS` in the private `.env` lists allowed operators; the default is `developer`.
Other authenticated users receive HTTP 403 from monitor data endpoints. The HTML shell
is public, but all data APIs require authentication and operator access.

Trace content is volatile: 64 records, 4 MiB of text per record, and 32 MiB total text.
Finished records are evicted first; the oldest active record may be evicted when no
finished record is available. Truncation applies to the monitor copy, not inference
responses. Metadata and parser buffers are additional overhead. Restart clears traces.

Authentication/cookie headers are excluded. Request body contents are not redacted;
source code containing embedded credentials can appear in operator-visible RAM traces.
Do not export real request captures to a public repository.

## REST and SSE

| Method | Endpoint | Result |
|---|---|---|
| GET | `/v1/monitor/requests` | Summaries, counters, retention information |
| GET | `/v1/monitor/requests/{id}` | Full retained trace |
| GET | `/v1/monitor/events` | SSE refresh notifications |
| DELETE | `/v1/monitor/requests` | Clear finished records |

These APIs require the operator's bearer authorization header. SSE events contain
refresh/version notifications rather than source text; the browser reads details through
REST. Notifications are coalesced around 150 ms and idle heartbeats occur every 10 seconds.
`X-CodeAssist-Trace-Id` links an inference response to its trace.

Only `/api/*` and `/v1/context/*` are traced. Health, metrics, and monitor API requests
are excluded. Unread bodies of rejected requests are not captured. One worker is required
because retention and admission counters are process-local.
