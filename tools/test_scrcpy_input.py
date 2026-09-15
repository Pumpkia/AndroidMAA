from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrcpy_input import (
    child_window_exstyle,
    child_window_style,
    ensure_running,
    is_running,
    launch_args,
    map_device_to_client,
    overlay_window_exstyle,
    overlay_window_style,
    parse_scrcpy_version,
    _WS_CAPTION,
    _WS_CHILD,
    _WS_EX_APPWINDOW,
    _WS_POPUP,
)


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

    def test_child_style_makes_window_embeddable(self):
        style = child_window_style(_WS_POPUP | _WS_CAPTION | 0x10000000)
        self.assertTrue(style & _WS_CHILD)
        self.assertFalse(style & _WS_POPUP)
        self.assertFalse(style & _WS_CAPTION)
        self.assertFalse(child_window_exstyle(_WS_EX_APPWINDOW) & _WS_EX_APPWINDOW)
        overlay = overlay_window_style(_WS_CAPTION | _WS_CHILD)
        self.assertTrue(overlay & _WS_POPUP)
        self.assertFalse(overlay & _WS_CAPTION)
        self.assertFalse(overlay & _WS_CHILD)
        self.assertFalse(overlay_window_exstyle(_WS_EX_APPWINDOW) & _WS_EX_APPWINDOW)

    @patch("scrcpy_input.read_scrcpy_version", return_value=(3, 2))
    def test_launch_args_are_borderless_for_embed(self, _version):
        args = launch_args(Path("scrcpy.exe"), "41292426", 360, 800, 40, 80)
        self.assertIn("--window-borderless", args)
        self.assertIn("--no-audio", args)
        self.assertIn("--window-width=360", args)
        self.assertIn("--window-height=800", args)
        self.assertIn("--window-x=40", args)
        self.assertIn("--window-y=80", args)
        self.assertNotIn("--mouse=uhid", args)
        self.assertNotIn("--keyboard=uhid", args)
        self.assertIn("--window-title=NnMaa-41292426", args)

    @patch("scrcpy_input.read_scrcpy_version", return_value=(2, 0))
    def test_launch_args_stay_borderless_on_old_scrcpy(self, _version):
        args = launch_args(Path("scrcpy.exe"), "abc")
        self.assertIn("--window-borderless", args)
        self.assertNotIn("--mouse=uhid", args)

    def test_is_running_keeps_embedded_process(self):
        from scrcpy_input import _PROCS

        proc = Mock()
        proc.poll.return_value = None
        _PROCS["abc"] = proc
        try:
            with patch("scrcpy_input._hwnd_for", return_value=0):
                self.assertTrue(is_running("abc"))
                self.assertFalse(is_running(""))
        finally:
            _PROCS.pop("abc", None)

    def test_ensure_running_skips_launch_when_window_exists(self):
        from scrcpy_input import _PROCS

        proc = Mock()
        proc.poll.return_value = None
        _PROCS["abc"] = proc
        try:
            with patch("scrcpy_input._hwnd_for", return_value=42), patch(
                "scrcpy_input._hide_pid_consoles"
            ), patch("scrcpy_input.ensure_installed") as installed:
                ensure_running("abc")
                installed.assert_not_called()
        finally:
            _PROCS.pop("abc", None)


if __name__ == "__main__":
    unittest.main()
