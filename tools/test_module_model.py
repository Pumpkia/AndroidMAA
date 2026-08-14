import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_model import JobDocument, JobStep
from module_model import ModuleDefinition, ModuleRegistry


class ModuleModelTests(unittest.TestCase):
    def test_custom_module_round_trip_and_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ModuleRegistry(Path(directory) / "modules.json")
            module = ModuleDefinition(
                id="qq_login_custom",
                name="QQ 登录扩展",
                description="统一登录前置与校验",
                allowed_purposes=["click", "check"],
                allowed_actions=["Click", "DoNothing"],
            )
            registry.upsert(module)
            loaded = ModuleRegistry(Path(directory) / "modules.json")
        self.assertEqual(loaded.get(module.id), module)

    def test_builtin_module_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ModuleRegistry(Path(directory) / "modules.json")
            with self.assertRaises(ValueError):
                registry.upsert(ModuleDefinition(id="semantic", name="替换"))

    def test_invalid_definition_is_rejected(self):
        module = ModuleDefinition(id="Bad ID", name="")
        errors = module.validate()
        self.assertTrue(any("模块 ID" in error for error in errors))
        self.assertTrue(any("模块名称" in error for error in errors))

    def test_module_restricts_document_purposes_and_actions(self):
        module = ModuleDefinition(
            id="checks_only",
            name="检查模块",
            allowed_purposes=["check"],
            allowed_actions=["DoNothing"],
        )
        document = JobDocument(
            module_id="checks_only",
            steps=[JobStep(name="点击", recognition="OCR", action="Click", expected="点击", roi=[0, 0, 10, 10], target=[1, 2], semantic_purpose="click")],
        )
        errors = module.validate_document(document)
        self.assertTrue(any("语义用途" in error for error in errors))
        self.assertTrue(any("动作" in error for error in errors))

    def test_document_module_version_must_match_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ModuleRegistry(Path(directory) / "modules.json")
            document = JobDocument(module_id="semantic", module_version=2)
            errors = registry.validate_document(document)
        self.assertTrue(any("版本" in error for error in errors))

    def test_malformed_registry_payload_is_reported_without_crashing(self):
        for payload in ([], {"format_version": 1, "modules": {}}, {"format_version": 1, "modules": ["bad"]}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "modules.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                registry = ModuleRegistry(path)
                self.assertTrue(registry.load_error)
                self.assertIsNotNone(registry.get("semantic"))

    def test_duplicate_module_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modules.json"
            payload = {
                "format_version": 1,
                "modules": [
                    {"id": "custom_one", "name": "One"},
                    {"id": "custom_one", "name": "Again"},
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            registry = ModuleRegistry(path)
        self.assertIn("重复", registry.load_error)
        self.assertIsNone(registry.get("custom_one"))

    def test_disabled_custom_module_is_persisted_but_not_bindable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modules.json"
            registry = ModuleRegistry(path)
            registry.upsert(ModuleDefinition(id="disabled_flow", name="Disabled", enabled=False))
            loaded = ModuleRegistry(path)
            self.assertIsNotNone(loaded.get("disabled_flow"))
            self.assertNotIn("disabled_flow", {item.id for item in loaded.list()})
            errors = loaded.validate_document(JobDocument(module_id="disabled_flow"))
        self.assertTrue(any("停用" in error for error in errors))

    def test_unknown_module_binding_returns_error_instead_of_version_crash(self):
        registry = ModuleRegistry(Path("does-not-exist/modules.json"))
        errors = registry.validate_document(JobDocument(module_id="missing_module", module_version=99))
        self.assertTrue(any("找不到" in error for error in errors))
    def test_job_document_persists_module_binding(self):
        document = JobDocument(name="关联用例", module_id="semantic", module_version=2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            document.save(path)
            loaded = JobDocument.load(path)
        self.assertEqual(loaded, document)


if __name__ == "__main__":
    unittest.main()
