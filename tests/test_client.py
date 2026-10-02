import sys

import pytest
import yaml

from codeassist.client import main


def test_client_configs_are_private_valid_and_do_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["client", "dev1", "dev2", "--output", str(tmp_path)])
    main()
    first = (tmp_path / "dev1/config.yaml").read_text()
    config = yaml.safe_load(first)
    assert config["models"][0]["provider"] == "ollama"
    assert config["models"][1]["roles"] == ["autocomplete"]
    assert "SERVER_URL_JSON" not in first
    assert (tmp_path / "server.env").stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit):
        main()
    assert first == (tmp_path / "dev1/config.yaml").read_text()
