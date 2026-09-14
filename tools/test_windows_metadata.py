import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsMetadataContractTests(unittest.TestCase):
    def test_nnmaa_spec_uses_icon_and_version_metadata(self):
        spec = (ROOT / "NnMaa.spec").read_text(encoding="utf-8")
        self.assertIn("icon='assets\\\\icons\\\\nnmaa.ico'", spec)
        self.assertIn("version='assets\\\\windows_version_info.txt'", spec)

    def interface_version(self):
        interface = json.loads(
            (ROOT / "assets" / "interface.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(interface.get("version"), str)
        return interface["version"]

    def metadata_text(self):
        return (ROOT / "assets" / "windows_version_info.txt").read_text(encoding="utf-8")

    def test_version_metadata_identifies_nnmaa(self):
        metadata = self.metadata_text()
        for expected in (
            "StringStruct('FileDescription', 'NnMaa Android Automation Workbench')",
            "StringStruct('OriginalFilename', 'NnMaa.exe')",
            "StringStruct('ProductName', 'NnMaa')",
        ):
            self.assertIn(expected, metadata)

    def test_version_metadata_matches_interface_version(self):
        """版本号以 interface.json 为单一事实源，exe 元数据必须同步。

        这里不断言具体版本串，只断言一致性 —— 升版本时改 interface.json 一处即可，
        但凡忘记同步 windows_version_info.txt，此用例就会失败。
        """
        version = self.interface_version()
        major, minor, patch = version.split(".")
        metadata = self.metadata_text()
        for expected in (
            f"filevers=({major}, {minor}, {patch}, 0)",
            f"prodvers=({major}, {minor}, {patch}, 0)",
            f"StringStruct('FileVersion', '{version}')",
            f"StringStruct('ProductVersion', '{version}')",
        ):
            self.assertIn(expected, metadata)


if __name__ == "__main__":
    unittest.main()
