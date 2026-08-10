import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsMetadataContractTests(unittest.TestCase):
    def test_qdd_spec_uses_icon_and_version_metadata(self):
        spec = (ROOT / "Qdd.spec").read_text(encoding="utf-8")
        self.assertIn("icon='assets\\\\icons\\\\qdd.ico'", spec)
        self.assertIn("version='assets\\\\windows_version_info.txt'", spec)

    def test_version_metadata_identifies_qdd(self):
        metadata = (ROOT / "assets" / "windows_version_info.txt").read_text(encoding="utf-8")
        for expected in (
            "StringStruct('FileDescription', 'Qdd Android Automation Workbench')",
            "StringStruct('FileVersion', '2.1.0')",
            "StringStruct('OriginalFilename', 'Qdd.exe')",
            "StringStruct('ProductName', 'Qdd')",
            "StringStruct('ProductVersion', '2.1.0')",
        ):
            self.assertIn(expected, metadata)


if __name__ == "__main__":
    unittest.main()
