import pytest

from common.case_contents import RARITY_ODDS, build, wear_odds


@pytest.mark.parametrize("lo,hi", [(0.0, 1.0), (0.0, 0.08), (0.06, 0.8), (0.1, 0.2)])
def test_wear_odds_sum_to_one(lo, hi):
    assert sum(wear_odds(lo, hi).values()) == pytest.approx(1.0)


def test_wear_odds_respect_float_range():
    odds = wear_odds(0.0, 0.08)        # can only be Factory New or Minimal Wear
    assert set(odds) == {"Factory New", "Minimal Wear"}
    assert wear_odds(0.5, 0.5) == {}


CRATES = [
    {"name": "Test Case", "type": "Case",
     "contains": [{"name": "AK-47 | Blue", "rarity": {"id": "rarity_rare_weapon"}},
                  {"name": "M4A4 | Red", "rarity": {"id": "rarity_ancient_weapon"}}],
     "contains_rare": [{"name": "★ Karambit"}, {"name": "★ Sport Gloves | Vice"}]},
    {"name": "Some Capsule", "type": "Sticker Capsule", "contains": [{"name": "x", "rarity": {"id": "r"}}]},
]
SKINS = [
    {"name": "AK-47 | Blue", "min_float": 0.0, "max_float": 1.0, "stattrak": True},
    {"name": "M4A4 | Red", "min_float": 0.0, "max_float": 0.08, "stattrak": True},
    {"name": "★ Karambit", "stattrak": True},
    {"name": "★ Sport Gloves | Vice", "min_float": 0.06, "max_float": 0.8, "category": {"name": "Gloves"}},
]


def test_build_probabilities():
    contents = build(CRATES, SKINS)
    assert list(contents) == ["Test Case"]
    probs = contents["Test Case"]
    assert sum(probs.values()) == pytest.approx(1.0)
    total = RARITY_ODDS["rarity_rare_weapon"] + RARITY_ODDS["rarity_ancient_weapon"] + RARITY_ODDS["rare_special"]
    ak = sum(p for n, p in probs.items() if "AK-47" in n)
    assert ak == pytest.approx(RARITY_ODDS["rarity_rare_weapon"] / total)
    st = sum(p for n, p in probs.items() if n.startswith("StatTrak™ AK-47"))
    assert st == pytest.approx(ak * 0.1)
    # vanilla knife has no wear, StatTrak goes after the star
    assert "★ Karambit" in probs and "★ StatTrak™ Karambit" in probs
    # gloves never have StatTrak
    assert not any("StatTrak" in n and "Gloves" in n for n in probs)
    assert "★ Sport Gloves | Vice (Field-Tested)" in probs
