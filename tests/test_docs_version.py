"""The landing page's family version: the release label of the pull request on top of raptor's newest tag."""

import pathlib
import sys
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import docs_version as dv  # noqa: E402


class ReleasedAs(unittest.TestCase):
    def test_a_release_label_bumps_the_newest_tag(self):
        self.assertEqual(dv._released_as("v0.7.2", "release:patch"), "0.7.3")
        self.assertEqual(dv._released_as("v0.7.2", "docs release:minor"), "0.8.0")
        self.assertEqual(dv._released_as("v0.7.2", "release:0.7.4"), "0.7.4")

    def test_no_release_label_shows_the_newest_tag(self):
        self.assertEqual(dv._released_as("v0.7.2", ""), "0.7.2")
        self.assertEqual(dv._released_as("v0.7.2", "docs ci"), "0.7.2")


if __name__ == "__main__":
    unittest.main()
