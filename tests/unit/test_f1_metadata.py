"""Reviewed F1 display metadata: event names and driver registry."""

from panorama_calendar.sources.f1_metadata import (
    load_f1_driver_registry,
    load_f1_event_names,
)


def test_event_names_cover_every_reviewed_circuit() -> None:
    """Every slug with a reviewed timezone also has a reviewed display name."""
    from panorama_calendar.sources.f1_official import load_circuit_timezones

    names = load_f1_event_names()
    assert set(names) == set(load_circuit_timezones())
    for slug, display in names.items():
        assert display.gp_zh.endswith("大奖赛"), slug
        assert display.city_zh
        assert display.city_en, slug


def test_event_names_match_the_published_examples() -> None:
    """Spot-check the three examples from the title-format requirement."""
    names = load_f1_event_names()
    assert names["china"].gp_zh == "中国大奖赛"
    assert (names["china"].city_zh, names["china"].city_en) == ("上海", "Shanghai")
    assert names["brazil"].gp_zh == "巴西大奖赛"
    assert (names["brazil"].city_zh, names["brazil"].city_en) == ("圣保罗", "São Paulo")
    assert names["united-states"].gp_zh == "美国大奖赛"
    assert (names["united-states"].city_zh, names["united-states"].city_en) == (
        "奥斯汀",
        "Austin",
    )


def test_driver_registry_covers_the_2026_grid() -> None:
    """All 22 drivers of the 2026 grid have a Chinese name and a flag."""
    registry = load_f1_driver_registry()
    grid = {
        "ALB",
        "ALO",
        "ANT",
        "BEA",
        "BOR",
        "BOT",
        "COL",
        "GAS",
        "HAD",
        "HAM",
        "HUL",
        "LAW",
        "LEC",
        "LIN",
        "NOR",
        "OCO",
        "PER",
        "PIA",
        "RUS",
        "SAI",
        "STR",
        "VER",
    }
    assert grid <= set(registry)
    for code in grid:
        info = registry[code]
        assert info.zh, code
        assert len(info.flag) == 2, code


def test_driver_registry_spot_checks() -> None:
    """The examples from the report-format requirement stay stable."""
    registry = load_f1_driver_registry()
    assert (registry["LEC"].zh, registry["LEC"].flag) == ("勒克莱尔", "🇲🇨")
    assert (registry["VER"].zh, registry["VER"].flag) == ("维斯塔潘", "🇳🇱")
    assert (registry["HAM"].zh, registry["HAM"].flag) == ("汉密尔顿", "🇬🇧")
    assert (registry["ANT"].zh, registry["ANT"].flag) == ("安东内利", "🇮🇹")
