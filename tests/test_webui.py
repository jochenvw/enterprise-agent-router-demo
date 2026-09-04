from webui.server import load_agent_cards, reasoning_available


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
    assert all(str(card["card_url"]).endswith("/.well-known/agent-card.json") for card in cards)


def test_reasoning_requires_both_settings(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test")
    monkeypatch.delenv("AZURE_OPENAI_REASONING_DEPLOYMENT", raising=False)

    assert not reasoning_available()

    monkeypatch.setenv("AZURE_OPENAI_REASONING_DEPLOYMENT", "reasoning-model")
    assert reasoning_available()
