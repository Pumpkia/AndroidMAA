from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from semantic_navigator import (
    NamedRegion,
    SemanticExecutor,
    SemanticMap,
    find_region_node,
    normalize_phrase,
    parse_ui_snapshot,
    region_to_job_step,
)


def snapshot_xml(*nodes):
    content = "".join(nodes)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node bounds="[0,0][1080,2400]" enabled="true">'
        f"{content}</node></hierarchy>"
    ).encode("utf-8")


def node(text="", desc="", resource="", bounds="[0,0][100,100]", clickable="true"):
    return (
        f'<node text="{text}" content-desc="{desc}" resource-id="{resource}" '
        f'class="android.view.View" bounds="{bounds}" clickable="{clickable}" enabled="true" />'
    )


def region(region_id, page, name, **values):
    return NamedRegion(id=region_id, page=page, name=name, **values)


class FakeAdb:
    def __init__(self, snapshots):
        self.serial = "device"
        self.snapshots = iter(snapshots)
        self.taps = []

    def shell(self, args):
        if args[0] == "cat":
            return next(self.snapshots)
        if args[:2] == ["input", "tap"]:
            self.taps.append((int(args[2]), int(args[3])))
        return b""


class SnapshotTests(unittest.TestCase):
    def test_parse_nodes_and_match_accessibility_selector(self):
        snapshot = parse_ui_snapshot(snapshot_xml(
            node(text="消息", bounds="[90,2200][180,2260]"),
            node(desc="搜索", resource="com.tencent.mobileqq:id/search", bounds="[0,380][1080,540]"),
        ))
        target = region(
            "search", "消息主页", "搜索", content_desc="搜索",
            resource_id="com.tencent.mobileqq:id/search", class_name="android.view.View",
        )

        matched = find_region_node(target, snapshot)

        self.assertEqual((snapshot.width, snapshot.height), (1080, 2400))
        self.assertIsNotNone(matched)
        self.assertEqual(matched.center, (540, 460))


class CommandAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.home_search = region(
            "home-search", "消息主页", "搜索", aliases=["查找"],
            destination="搜索页", content_desc="搜索", bounds_ratio=[0, .15, 1, .25],
        )
        self.search_back = region(
            "search-back", "搜索页", "返回", destination="消息主页",
            content_desc="返回", bounds_ratio=[0, 0, .1, .1],
        )
        self.settings = region(
            "settings", "设置页", "保存", text="保存", bounds_ratio=[.8, 0, 1, .1],
        )
        self.to_settings = region(
            "to-settings", "消息主页", "设置", destination="设置页",
            text="设置", bounds_ratio=[.8, .8, 1, 1],
        )
        self.semantic_map = SemanticMap([
            self.home_search, self.search_back, self.settings, self.to_settings,
        ])

    def test_command_uses_alias_and_page_hint(self):
        duplicate = region("search-page-search", "搜索页", "搜索", text="搜索")
        self.semantic_map.regions.append(duplicate)

        self.assertEqual(normalize_phrase("请直接打开查找"), "查找")
        self.assertEqual(
            self.semantic_map.resolve_command("点击搜索", "消息主页").id,
            "home-search",
        )
        self.assertEqual(
            self.semantic_map.resolve_command("点击搜索页搜索").id,
            "search-page-search",
        )

    def test_route_uses_named_transition(self):
        route = self.semantic_map.plan_route("消息主页", "设置页")
        self.assertEqual([item.id for item in route], ["to-settings"])

    def test_command_regions_generate_route_and_normalized_job_steps(self):
        regions = self.semantic_map.command_regions("点击保存", "消息主页")
        steps = [region_to_job_step(item, [720, 1600]) for item in regions]

        self.assertEqual([item.name for item in regions], ["设置", "保存"])
        self.assertEqual(
            [step.recognition for step in steps],
            ["DirectHit", "DirectHit"],
        )
        self.assertEqual(steps[0].target, [648, 1440])
        self.assertEqual(steps[1].target, [648, 80])

    def test_executor_scans_routes_and_clicks_target(self):
        home = snapshot_xml(node(text="设置", bounds="[900,2100][1080,2400]"))
        settings = snapshot_xml(node(text="保存", bounds="[860,0][1080,150]"))
        adb = FakeAdb([home, settings])
        messages = []

        result = SemanticExecutor(
            adb, self.semantic_map, messages.append, sleep_fn=lambda _seconds: None,
        ).execute("点击保存", "消息主页")

        self.assertEqual(result.clicks, ["设置", "保存"])
        self.assertEqual(adb.taps, [(990, 2250), (970, 75)])


class PersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_selectors_and_aliases(self):
        original = SemanticMap([
            region(
                "search", "消息主页", "搜索", aliases=["查找"], destination="搜索页",
                content_desc="搜索", resource_id="qq:id/search", bounds_ratio=[0, .1, 1, .2],
            )
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic_map.json"
            original.save(path)
            loaded = SemanticMap.load(path)

        self.assertEqual(loaded.regions[0].aliases, ["查找"])
        self.assertEqual(loaded.regions[0].resource_id, "qq:id/search")
        self.assertEqual(loaded.regions[0].destination, "搜索页")


if __name__ == "__main__":
    unittest.main()
