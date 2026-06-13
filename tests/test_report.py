from sonar.report import summarize
from sonar.util import human_duration


def _rec(ts, util, project):
    return {"ts": ts, "util": util, "top_project": project}


def test_summarize_empty():
    s = summarize([])
    assert s.samples == 0 and s.active_seconds == 0


def test_summarize_attributes_time_to_projects():
    # 1s spacing: alpha active for ~4 ticks, beta for ~2, one idle tick.
    recs = [
        _rec(0, 90, "monorepo/alpha"),
        _rec(1, 92, "monorepo/alpha"),
        _rec(2, 88, "monorepo/alpha"),
        _rec(3, 0, None),            # idle gap
        _rec(4, 80, "monorepo/beta"),
        _rec(5, 85, "monorepo/beta"),
    ]
    s = summarize(recs)
    by = {p.project: p.seconds for p in s.projects}
    assert by["monorepo/alpha"] > by["monorepo/beta"] > 0
    assert s.idle_seconds >= 1.0
    assert s.projects[0].project == "monorepo/alpha"  # sorted desc
    assert s.samples == 6


def test_summarize_clamps_long_gaps():
    # Realistic session: many 1s samples, then a huge gap (sonar/laptop off),
    # then a few more. The gap must not be charged as continuous GPU time.
    recs = [_rec(t, 90, "A") for t in range(30)]
    recs.append(_rec(100000, 90, "A"))           # giant gap
    recs += [_rec(100000 + t, 90, "A") for t in range(1, 6)]
    s = summarize(recs)
    # median delta ~1s, cap = 5s; without clamping this would be ~100000s.
    assert s.projects[0].seconds < 60


def test_idle_util_not_attributed():
    recs = [_rec(0, 2, "A"), _rec(1, 3, "A")]
    s = summarize(recs)
    assert not s.projects
    assert s.idle_seconds > 0


def test_human_duration():
    assert human_duration(None) == "-"
    assert human_duration(45) == "45s"
    assert human_duration(60) == "1m"
    assert human_duration(3600) == "1h"
    assert human_duration(3660) == "1h01m"
    assert human_duration(90061).startswith("1d")
