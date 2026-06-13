from sonar.ui import owner_colors, ownership_strip


def test_owner_colors_stable_and_distinct():
    c = owner_colors(["B", "A", "A", None, "C"])
    assert set(c) == {"A", "B", "C"}
    assert len({c["A"], c["B"], c["C"]}) == 3  # distinct within palette size
    # sorted assignment => deterministic across calls
    assert owner_colors(["A", "B", "C"]) == c


def test_ownership_strip_marks_idle_grey():
    colors = owner_colors(["alpha"])
    strip = ownership_strip([90, 1, 90], ["alpha", "alpha", None], colors, width=3)
    styles = [str(sp.style) for sp in strip.spans]
    # middle block is idle (util<5) -> grey; others colored
    assert "grey30" in styles[1]
    assert "grey30" not in styles[0]
