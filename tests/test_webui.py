import os

from webui.server import load_agent_cards, load_reasoning_config, reasoning_available


def test_load_agent_cards() -> None:
    cards = load_agent_cards()

    assert len(cards) == 5
    assert {card["id"] for card in cards} == {
        "capital-projects",
        "project-controls",
        "procurement",
        "investment-planning",
        "consulting",
    }
    assert all(card["owns"] for card in cards)
    assert all(str(card["endpoint"]).endswith("/a2a") for card in cards)
    assert all(str(card["card_url"]).startswith("/cards/") for card in cards)
    assert all(str(card["live_card_url"]).endswith("/.well-known/agent-card.json") for card in cards)


def test_reasoning_requires_both_settings(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test")
    monkeypatch.delenv("AZURE_OPENAI_REASONING_DEPLOYMENT", raising=False)

    assert not reasoning_available()

    monkeypatch.setenv("AZURE_OPENAI_REASONING_DEPLOYMENT", "reasoning-model")
    assert reasoning_available()


def test_load_reasoning_config(monkeypatch, tmp_path) -> None:
    outputs = tmp_path / "infra" / ".deployment-outputs.json"
    outputs.parent.mkdir()
    outputs.write_text(
        '{"openaiEndpoint": {"value": "https://foundry.example.test/"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("webui.server.REPO_ROOT", tmp_path)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REASONING_DEPLOYMENT", raising=False)

    load_reasoning_config()

    assert os.environ["AZURE_OPENAI_ENDPOINT"] == "https://foundry.example.test/"
    assert os.environ["AZURE_OPENAI_REASONING_DEPLOYMENT"] == "gpt-5.4-nano"
