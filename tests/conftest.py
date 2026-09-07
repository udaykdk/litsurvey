import pytest

from litsurvey import history


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    """Never touch the user's real ~/.litsurvey during tests."""
    monkeypatch.setattr(history, "INDEX", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(history, "RUNS", str(tmp_path / "runs"))
    yield
