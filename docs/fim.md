# Fill-in-the-middle completion

The default autocomplete model is `qwen2.5-coder:1.5b-base`, named **Local FIM Completion**
in Continue. Chat uses the separate 7B Instruct model.

FIM works without a repository index. Continue constructs bounded context from the
cursor prefix/suffix, relevant nearby buffers, and available language-server information.
It does not guarantee that the entire enclosing function or file is sent. Chat history
is not automatically FIM context.

## Budgets

| Setting | Value | Meaning |
|---|---:|---|
| `contextLength` | 8192 | Model context policy |
| `maxPromptTokens` | 4096 | Client prompt budget |
| `maxTokens` | 256 | Completion output ceiling |

The server uses `COMPLETION_CONTEXT_LENGTH` and `COMPLETION_MAX_TOKENS` for completion;
`MODEL_CONTEXT_LENGTH` controls chat. Client-only changes do not increase server limits.
Actual suggestions can end well before the output ceiling.

## Update an existing generated client configuration

Copy these public scripts together to the client: `update-client-fim.py`,
`client_config.py`, `fim-profile.json`, and `check-client.py`.

```bash
python3 update-client-fim.py --config ~/.continue/config.yaml
python3 check-client.py --config ~/.continue/config.yaml
```

The updater changes the FIM budgets and enable/cache options, preserves the chat model,
server address, authentication value, and template, and creates a private backup.
It supports block-style YAML with different list indentation and scalar quoting.
Unsupported formats fail before writing. Python 3.10+ standard library is sufficient.

To inspect configured model names and field presence without printing the access key:

```bash
python3 check-client.py --inspect --config ~/.continue/config.yaml
```

## Enable and test

Run **Developer: Reload Window** and select **Local FIM Completion**. Enable:

```json
{
  "continue.enableTabAutocomplete": true,
  "editor.inlineSuggest.enabled": true
}
```

Save a C++ file and place the cursor after a space following `return`:

```cpp
int add(int a, int b) {
    return
}
```

Pause briefly, or run **Continue: Force Autocomplete** from the command palette.
The tested extension binds this command to `Ctrl+Alt+Space` on Linux; `Ctrl+Space`
can instead open the standard IntelliSense list. Close that list with Esc before
forcing an inline suggestion. Desktop/VM shortcuts can also intercept keybindings.
Accept a visible suggestion with Tab.

If the server receives and answers a request but no suggestion is displayed, inspect
client filtering, cancellation, the selected model, inline suggestion settings, and
extension logs. Server delivery does not prove editor display or acceptance.

## Client resource use and central retrieval

In Continue 2.0.0, turn off **User Settings → Indexing → Enable indexing** to avoid its
repository indexing. Existing language-server indexing is separate. FIM still reads
nearby code and prepares prompts on the client.

Central retrieval is currently implemented for chat only. Adding source declarations
and examples to FIM requires a separate integration, including snapshot identity and
current-buffer precedence. Keep context bounded to protect completion latency.

References: [context selection](https://docs.continue.dev/ide-extensions/autocomplete/context-selection),
[configuration](https://docs.continue.dev/reference),
[autocomplete quick start](https://docs.continue.dev/ide-extensions/autocomplete/quick-start).
