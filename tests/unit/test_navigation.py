from jobpilot.ui.navigation import PLANNED_NAVIGATION


def test_navigation_exposes_simplified_core_flow() -> None:
    assert PLANNED_NAVIGATION == (
        "求职看板",
        "我的简历",
        "岗位匹配",
        "求职进度",
    )
    assert "面试准备" not in PLANNED_NAVIGATION
    assert "求职洞察" not in PLANNED_NAVIGATION
