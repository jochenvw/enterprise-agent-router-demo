from webui.server import load_agent_cards


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
