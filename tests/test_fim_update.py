import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("fim_update", ROOT / "scripts/update-client-fim.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
PROFILE = json.loads((ROOT / "scripts/fim-profile.json").read_text())


def config():
    return (
        (ROOT / "codeassist/continue.yaml.template")
        .read_text()
        .replace("SERVER_URL_JSON", '"http://127.0.0.1:8080"')
        .replace("AUTH_HEADER_JSON", '"Bearer private-key-preserved"')
        .replace("contextLength: 8192", "contextLength: 4096")
        .replace("maxTokens: 256", "maxTokens: 128")
        .replace("maxPromptTokens: 4096", "maxPromptTokens: 1536")
        .replace("disable: false", "disable: true")
    )


def test_update_preserves_chat_auth_rules_and_other_fim_options(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(config())
    before = yaml.safe_load(path.read_text())
    backup = updater.update(path, PROFILE)
    after = yaml.safe_load(path.read_text())
    assert after["models"][0] == before["models"][0]
    assert after["rules"] == before["rules"]
    fim = after["models"][1]
    assert fim["requestOptions"] == before["models"][1]["requestOptions"]
    assert fim["defaultCompletionOptions"]["contextLength"] == 8192
    assert fim["defaultCompletionOptions"]["maxTokens"] == 256
    assert fim["autocompleteOptions"]["maxPromptTokens"] == 4096
    assert not fim["autocompleteOptions"]["disable"]
    assert (
        fim["autocompleteOptions"]["template"]
        == before["models"][1]["autocompleteOptions"]["template"]
    )
    assert Path(backup).read_text() == config()
    assert Path(backup).stat().st_mode & 0o777 == path.stat().st_mode & 0o777 == 0o600
    assert updater.update(path, PROFILE) is None


def test_update_requires_model_and_does_not_touch_file_on_failure(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("models: []\n")
    with pytest.raises(ValueError, match="exactly one"):
        updater.update(path, PROFILE)
    assert path.read_text() == "models: []\n"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("indent", [2, 4])
def test_update_reformatted_yaml_preserves_credentials_and_chat(tmp_path, indent):
    from client_config import credentials, inspect

    before = yaml.safe_load(config())
    # PyYAML emits unquoted strings, indentless lists and reordered first keys.
    rendered = yaml.safe_dump(before, sort_keys=True, indent=indent)
    path = tmp_path / "config.yaml"
    path.write_text(rendered)
    updater.update(path, PROFILE)
    after = yaml.safe_load(path.read_text())
    assert after["models"][0] == before["models"][0]
    assert after["rules"] == before["rules"]
    assert after["models"][1]["requestOptions"] == before["models"][1]["requestOptions"]
    assert after["models"][1]["defaultCompletionOptions"]["contextLength"] == 8192
    assert after["models"][1]["autocompleteOptions"]["maxPromptTokens"] == 4096
    assert credentials(rendered) == ("http://127.0.0.1:8080", "Bearer private-key-preserved")
    assert all(model["has_apiBase"] and model["has_Authorization"] for model in inspect(rendered))
    assert updater.update(path, PROFILE) is None


def test_single_quotes_comments_and_key_free_inspection():
    from client_config import credentials, inspect

    rendered = config().replace('"http://127.0.0.1:8080"', "'http://127.0.0.1:8080' # local")
    rendered = rendered.replace('"Bearer private-key-preserved"', "'Bearer private-key-preserved'")
    assert credentials(rendered) == ("http://127.0.0.1:8080", "Bearer private-key-preserved")
    summary = json.dumps(inspect(rendered))
    assert "private-key-preserved" not in summary
    assert "qwen2.5-coder:1.5b-base" in summary


def test_model_first_list_entry_and_missing_options():
    rendered = (
        "name: main\nmodels:\n"
        "  - model: 'qwen2.5-coder:1.5b-base' # local\n"
        "    name: FIM\n    provider: ollama\n    roles: [autocomplete]\n"
        "rules:\n  - Keep C++14\n"
    )
    result = updater.patched_config(rendered, PROFILE)
    after = yaml.safe_load(result)
    assert after["models"][0]["defaultCompletionOptions"] == PROFILE["defaultCompletionOptions"]
    assert after["models"][0]["autocompleteOptions"] == PROFILE["autocompleteOptions"]
    assert after["rules"] == ["Keep C++14"]
    assert updater.patched_config(result, PROFILE) == result


def test_unsupported_sections_fail_without_changing_file(tmp_path):
    path = tmp_path / "config.yaml"
    original = config().replace("    defaultCompletionOptions:\n", "    defaultCompletionOptions: {}\n")
    path.write_text(original)
    with pytest.raises(ValueError, match="block-style"):
        updater.update(path, PROFILE)
    assert path.read_text() == original
    assert len(list(tmp_path.iterdir())) == 1
