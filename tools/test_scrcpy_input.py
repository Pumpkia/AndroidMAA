from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrcpy_input import map_device_to_client, parse_scrcpy_version


class ScrcpyMappingTests(unittest.TestCase):
    def test_maps_device_point_into_letterboxed_window(self):
        x, y = map_device_to_client(540, 1170, 1080, 2340, 540, 1170)
        self.assertEqual((x, y), (270, 585))

    def test_keeps_aspect_and_centers(self):
        x, y = map_device_to_client(0, 0, 1080, 2340, 1080, 2340)
        self.assertEqual((x, y), (0, 0))
        x, y = map_device_to_client(1080, 2340, 1080, 2340, 540, 1400)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(y, 1400)

    def test_parses_version_and_omits_uhid_before_2_4(self):
        self.assertEqual(parse_scrcpy_version("scrcpy 2.0 <https://github.com/Genymobile/scrcpy>"), (2, 0))
        self.assertEqual(parse_scrcpy_version("scrcpy 2.4"), (2, 4))
        from scrcpy_input import version_from_tag

        self.assertEqual(version_from_tag("v3.2.1"), (3, 2))
        self.assertTrue(version_from_tag("v3.2.1") > version_from_tag("v2.0"))


if __name__ == "__main__":
    unittest.main()
