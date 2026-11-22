"""截止日修订选择与资料装载规则。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence_tool.records import (  # noqa: E402
    DEPARTURE,
    FREE_TO_LEAVE,
    load_bundle,
)

DATA = Path(__file__).resolve().parents[1] / "data"


class RevisionCutoffTest(unittest.TestCase):
    def test_future_revisions_suppressed_at_early_cutoff(self):
        # 2026-06-12 可见的 B 设备校准仍是 rev1；rev2 在 06-12 当天才可见
        early = load_bundle(DATA, as_of="2026-06-11")
        cal = early.calibrations[("2026-06-06", "B")]
        self.assertEqual(cal.revision, 1)
        self.assertGreaterEqual(early.suppressed_rows["calibrations"], 3)

        later = load_bundle(DATA, as_of="2026-06-12")
        cal2 = later.calibrations[("2026-06-06", "B")]
        self.assertEqual(cal2.revision, 2)
        self.assertEqual(cal2.offset_lo, -23)

    def test_event_revision_also_respects_cutoff(self):
        early = load_bundle(DATA, as_of="2026-06-12")
        obs = early.events[("M051", DEPARTURE)]
        # M051 的事件 rev2 在 06-13 才可见
        self.assertEqual(obs.revision, 1)

        full = load_bundle(DATA, as_of="9999-12-31")
        obs2 = full.events[("M051", DEPARTURE)]
        self.assertEqual(obs2.revision, 1)  # 可启程是 B 设备，无 rev2
        revised = full.events[("M051", FREE_TO_LEAVE)]
        self.assertEqual(revised.revision, 2)


if __name__ == "__main__":
    unittest.main()
