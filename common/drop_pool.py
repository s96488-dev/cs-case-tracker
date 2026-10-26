"""История активного дропа обычных кейсов и прогноз, когда кейс уйдёт из активного дропа.

Даты ухода (перевод в редкий дроп или удаление из дропа) — история пула на skinory.io
(https://skinory.io/en/cs2-droppool-now/history). Даты выхода — фактические релизы по патчноутам.
Прогноз для кейса в активном дропе: дата выхода + средний срок жизни прошлых обычных кейсов.
Операционные, eSports, Winter Offensive, CS20, первые три Weapon Case и кейсы Armory (Gallery, Fever)
в расчёт не входят и линии не получают.
"""
from datetime import date, timedelta
from statistics import mean

# Кейс: (вышел, ушёл из активного дропа или None, если ещё в нём).
CASES: dict[str, tuple[str, str | None]] = {
    "Huntsman Weapon Case": ("2014-05-01", "2015-04-15"),
    "Chroma Case": ("2015-01-08", "2015-09-17"),
    "Chroma 2 Case": ("2015-04-15", "2017-03-15"),
    "Falchion Case": ("2015-05-26", "2016-06-15"),
    "Shadow Case": ("2015-09-17", "2016-08-18"),
    "Revolver Case": ("2015-12-08", "2021-06-03"),
    "Chroma 3 Case": ("2016-04-27", "2021-06-03"),
    "Gamma Case": ("2016-06-15", "2018-02-15"),
    "Gamma 2 Case": ("2016-08-18", "2021-06-03"),
    "Glove Case": ("2016-11-28", "2018-12-06"),
    "Spectrum Case": ("2017-03-15", "2019-03-13"),
    "Spectrum 2 Case": ("2017-09-14", "2021-06-03"),
    "Clutch Case": ("2018-02-15", "2023-04-08"),
    "Horizon Case": ("2018-08-02", "2021-06-03"),
    "Danger Zone Case": ("2018-12-06", "2022-01-18"),
    "Prisma Case": ("2019-03-13", "2021-05-03"),
    "Prisma 2 Case": ("2020-03-31", "2022-07-01"),
    "Fracture Case": ("2020-08-06", "2025-09-17"),
    "Snakebite Case": ("2021-05-03", "2024-02-07"),
    "Recoil Case": ("2022-07-01", "2026-03-12"),  # убран из дропа совсем, минуя редкий
    "Dreams & Nightmares Case": ("2022-01-20", None),
    "Revolution Case": ("2023-02-09", None),
    "Kilowatt Case": ("2024-02-06", None),
}


def _days(released: str, left: str) -> int:
    return (date.fromisoformat(left) - date.fromisoformat(released)).days


MEAN_DAYS = round(mean(_days(r, l) for r, l in CASES.values() if l))


def info(name: str) -> dict | None:
    """Для обычного кейса: дата выхода, дата ухода из активного дропа (или прогноз) и средний срок."""
    if name not in CASES:
        return None
    released, left = CASES[name]
    out = {"released": released, "left_active": left, "mean_days": MEAN_DAYS, "forecast": None}
    if not left:
        out["forecast"] = (date.fromisoformat(released) + timedelta(days=MEAN_DAYS)).isoformat()
    return out
