"""Состав кейсов и шансы выпадения каждой позиции маркета Steam (с износом и StatTrak).

Источник состава — открытый набор ByMykel/CSGO-API (собран из файлов игры Valve, в нём есть и ножи с
перчатками каждого кейса, которых нет в публичных файлах игры). Цены отсюда не берутся, только состав.

Шансы:
- редкость — официальные шансы Valve: Mil-Spec 79,92%, Restricted 15,98%, Classified 3,2%,
  Covert 0,64%, нож/перчатки 0,26%; внутри редкости все предметы равновероятны;
- StatTrak — 10% (у ножей тоже, у перчаток StatTrak не бывает);
- износ — модель выпадения float, выведенная сообществом по миллионам открытий: сначала выбирается
  значение 0…1 с весами по участкам (0–0,07: 3%, 0,07–0,15: 24%, 0,15–0,38: 33%, 0,38–0,45: 24%,
  0,45–1: 16%, внутри участка равномерно), потом оно переносится в диапазон скина [min_float, max_float].
  Это приближение, официальной формулы Valve не публикует.
"""
from collections import defaultdict

CRATES_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/crates.json"
SKINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"

RARITY_ODDS = {
    "rarity_rare_weapon": 0.7992,       # Mil-Spec
    "rarity_mythical_weapon": 0.1598,   # Restricted
    "rarity_legendary_weapon": 0.0320,  # Classified
    "rarity_ancient_weapon": 0.0064,    # Covert
    "rare_special": 0.0026,             # ножи и перчатки
}
STATTRAK_ODDS = 0.10
WEARS = [("Factory New", 0.0, 0.07), ("Minimal Wear", 0.07, 0.15), ("Field-Tested", 0.15, 0.38),
         ("Well-Worn", 0.38, 0.45), ("Battle-Scarred", 0.45, 1.0)]


FLOAT_WEIGHTS = [(0.0, 0.07, 0.03), (0.07, 0.15, 0.24), (0.15, 0.38, 0.33), (0.38, 0.45, 0.24), (0.45, 1.0, 0.16)]


def wear_odds(min_float: float, max_float: float) -> dict[str, float]:
    span = max_float - min_float
    if span <= 0:
        return {}
    out: dict[str, float] = {}
    for a, b, weight in FLOAT_WEIGHTS:
        lo, hi = min_float + a * span, min_float + b * span  # участок после переноса в диапазон скина
        for name, wlo, whi in WEARS:
            part = max(0.0, min(hi, whi) - max(lo, wlo)) / (hi - lo)
            if part > 0:
                out[name] = out.get(name, 0) + weight * part
    return out


def _variants(skin: dict | None, base_name: str, stattrak_ok: bool) -> dict[str, float]:
    """Позиции маркета одного предмета и их доли (сумма 1)."""
    st = STATTRAK_ODDS if stattrak_ok else 0.0
    wears = wear_odds(skin["min_float"], skin["max_float"]) if skin and skin.get("min_float") is not None \
        and skin.get("max_float") is not None and "|" in base_name else {}
    out: dict[str, float] = {}
    for prefix, p in (("", 1 - st), ("StatTrak™ ", st)):
        if p <= 0:
            continue
        name = base_name.replace("★ ", "★ " + prefix) if base_name.startswith("★ ") else prefix + base_name
        if not wears:  # ванильный нож без раскраски: износа у него нет
            out[name] = out.get(name, 0) + p
        for w, q in wears.items():
            out[f"{name} ({w})"] = out.get(f"{name} ({w})", 0) + p * q
    return out


def build(crates: list[dict], skins: list[dict]) -> dict[str, dict[str, float]]:
    """{название кейса: {market_hash_name: шанс выпадения}}. Сумма шансов по кейсу — 1."""
    by_name = {}
    for s in skins:
        by_name.setdefault(s["name"], s)  # фазы Doppler — один скин маркета
    result = {}
    for c in crates:
        if c.get("type") != "Case" or not c.get("contains"):
            continue
        groups: dict[str, list[str]] = defaultdict(list)
        for it in c["contains"]:
            groups[it["rarity"]["id"]].append(it["name"])
        for it in c.get("contains_rare") or []:
            groups["rare_special"].append(it["name"])
        total = sum(RARITY_ODDS.get(g, 0) for g in groups)
        if not total:
            continue
        probs: dict[str, float] = defaultdict(float)
        for g, names in groups.items():
            share = RARITY_ODDS.get(g, 0) / total / len(names)
            for n in names:
                skin = by_name.get(n)
                gloves = bool(skin) and skin.get("category", {}).get("name") == "Gloves"
                stattrak_ok = (skin or {}).get("stattrak", g != "rare_special") and not gloves
                for mhn, p in _variants(skin, n, stattrak_ok).items():
                    probs[mhn] += share * p
        result[c["name"]] = dict(probs)
    return result
