from pathlib import Path
import os
import sys
import tempfile
import unittest

os.environ["NNMAA_USE_SCRCPY"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from semantic_navigator import (
    NamedRegion,
    SemanticExecutor,
    SemanticMap,
    bounds_ratio,
    command_purpose,
    find_region_node,
    node_action_bounds_ratio,
    normalize_phrase,
    parse_ui_snapshot,
    ratio_to_rect,
    region_point,
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


def clickable_container(child, bounds="[0,0][1080,200]", resource=""):
    return (
        f'<node text="" content-desc="" resource-id="{resource}" '
        f'class="android.view.ViewGroup" bounds="{bounds}" clickable="true" enabled="true">'
        f"{child}</node>"
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

    def test_text_node_inherits_nearest_clickable_parent_as_action_region(self):
        snapshot = parse_ui_snapshot(snapshot_xml(clickable_container(
            node(text="登录", bounds="[450,350][630,410]", clickable="false"),
            bounds="[0,300][1080,500]",
            resource="qq:id/login_row",
        )))
        target = region("login", "登录页", "登录", text="登录")

        matched = find_region_node(target, snapshot)

        self.assertIsNotNone(matched)
        self.assertEqual(matched.bounds, (450, 350, 630, 410))
        self.assertEqual(matched.click_bounds, (0, 300, 1080, 500))
        self.assertEqual(matched.center, (540, 380))
        self.assertEqual(matched.action_center, (540, 400))
        self.assertEqual(region_point(target, snapshot), (540, 400))

    def test_text_and_action_bounds_scale_independently_between_devices(self):
        snapshot = parse_ui_snapshot(snapshot_xml(clickable_container(
            node(text="登录", bounds="[450,360][630,480]", clickable="false"),
            bounds="[270,240][810,600]",
        )))
        text_node = next(item for item in snapshot.nodes if item.text == "登录")
        text_ratio = bounds_ratio(text_node, snapshot)
        action_ratio = node_action_bounds_ratio(text_node, snapshot)

        self.assertEqual(text_ratio, [0.416667, 0.15, 0.583333, 0.2])
        self.assertEqual(action_ratio, [0.25, 0.1, 0.75, 0.25])
        self.assertEqual(ratio_to_rect(text_ratio, [720, 1600]), [300, 240, 120, 80])
        self.assertEqual(ratio_to_rect(action_ratio, [720, 1600]), [180, 160, 360, 240])
        self.assertEqual(ratio_to_rect(text_ratio, [1080, 2400]), [450, 360, 180, 120])
        self.assertEqual(ratio_to_rect(text_ratio, [720, 1280]), [300, 192, 120, 64])
        self.assertEqual(ratio_to_rect(action_ratio, [720, 1280]), [180, 128, 360, 192])
        self.assertEqual(ratio_to_rect(action_ratio, [1080, 2400]), [270, 240, 540, 360])


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

    def test_command_prefix_selects_click_check_or_recognize_purpose(self):
        regions = SemanticMap([
            region("login-click", "登录页", "登录", action="click", text="登录"),
            region("login-check", "登录页", "登录", action="check", text="登录"),
            region("login-recognize", "登录页", "登录", action="recognize", text="登录"),
        ])

        self.assertEqual(command_purpose("请点击登录"), "click")
        self.assertEqual(command_purpose("检查登录"), "check")
        self.assertEqual(command_purpose("识别登录"), "recognize")
        self.assertEqual(regions.resolve_command("点击登录", "登录页").id, "login-click")
        self.assertEqual(regions.resolve_command("检查登录", "登录页").id, "login-check")
        self.assertEqual(
            regions.resolve_command("识别登录", "登录页").id,
            "login-recognize",
        )
        with self.assertRaisesRegex(ValueError, "同时匹配多个区域"):
            regions.resolve_command("登录", "登录页")

    def test_route_uses_named_transition(self):
        route = self.semantic_map.plan_route("消息主页", "设置页")
        self.assertEqual([item.id for item in route], ["to-settings"])

    def test_command_regions_generate_route_and_normalized_job_steps(self):
        regions = self.semantic_map.command_regions("点击保存", "消息主页")
        steps = [region_to_job_step(item, [720, 1600]) for item in regions]

        self.assertEqual([item.name for item in regions], ["设置", "保存"])
        self.assertEqual([step.recognition for step in steps], ["OCR", "OCR"])
        self.assertEqual([step.expected for step in steps], ["设置", "保存"])
        self.assertEqual([step.action for step in steps], ["Click", "Click"])
        self.assertEqual(steps[0].roi, [576, 1280, 144, 320])
        self.assertEqual(steps[0].target, [576, 1280, 144, 320])
        self.assertEqual(steps[1].roi, [576, 0, 144, 160])
        self.assertEqual(steps[1].target, [576, 0, 144, 160])

    def test_job_steps_use_ocr_for_click_check_and_recognize(self):
        values = {
            "text": "登录",
            "bounds_ratio": [.4, .2, .6, .25],
            "action_bounds_ratio": [.25, .15, .75, .3],
        }

        click = region_to_job_step(
            region("click", "登录页", "登录", action="click", **values),
            [720, 1600],
        )
        check = region_to_job_step(
            region("check", "登录页", "登录", action="check", **values),
            [720, 1600],
        )
        recognize = region_to_job_step(
            region("recognize", "登录页", "登录", action="recognize", **values),
            [720, 1600],
        )

        self.assertEqual((click.recognition, click.action), ("OCR", "Click"))
        self.assertEqual(click.expected, "登录")
        self.assertEqual(click.roi, [288, 320, 144, 80])
        self.assertEqual(click.target, [180, 240, 360, 240])
        self.assertEqual(click.roi_ratio, [.4, .2, .6, .25])
        self.assertEqual(click.target_ratio, [.25, .15, .75, .3])
        self.assertEqual(check.roi_ratio, [.4, .2, .6, .25])
        self.assertIsNone(check.target_ratio)
        self.assertEqual(click.semantic_purpose, "click")
        for step, purpose in ((check, "check"), (recognize, "recognize")):
            with self.subTest(purpose=purpose):
                self.assertEqual((step.recognition, step.action), ("OCR", "DoNothing"))
                self.assertEqual(step.expected, "登录")
                self.assertEqual(step.roi, [288, 320, 144, 80])
                self.assertIsNone(step.target)
                self.assertEqual(step.semantic_purpose, purpose)

        with self.assertRaisesRegex(ValueError, "OCR"):
            region_to_job_step(
                region(
                    "description-only", "登录页", "登录", content_desc="登录",
                    bounds_ratio=[.4, .2, .6, .25],
                ),
                [720, 1600],
            )

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

    def test_check_and_recognize_succeed_without_tapping(self):
        for purpose, command, expected_event in (
            ("check", "检查登录", "检查 登录"),
            ("recognize", "识别登录", "识别 登录"),
        ):
            with self.subTest(purpose=purpose):
                target = region(
                    f"login-{purpose}", "登录页", "登录",
                    action=purpose, text="登录", bounds_ratio=[.4, .2, .6, .25],
                )
                adb = FakeAdb([
                    snapshot_xml(node(text="登录", bounds="[430,480][650,600]")),
                ])
                messages = []

                result = SemanticExecutor(
                    adb, SemanticMap([target]), messages.append,
                    sleep_fn=lambda _seconds: None,
                ).execute(command, "登录页")

                self.assertEqual(result.clicks, [])
                self.assertEqual(result.events, [expected_event])
                self.assertEqual(adb.taps, [])
                self.assertTrue(any("成功" in message for message in messages))

    def test_required_semantic_purposes_stop_without_tapping_when_not_recognized(self):
        for purpose, command in (
            ("click", "点击登录"),
            ("check", "检查登录"),
            ("recognize", "识别登录"),
        ):
            with self.subTest(purpose=purpose):
                target = region(
                    f"login-{purpose}", "登录页", "登录",
                    action=purpose, text="登录", bounds_ratio=[.4, .2, .6, .25],
                )
                adb = FakeAdb([snapshot_xml(node(text="注册"))])

                with self.assertRaisesRegex(RuntimeError, "已停止后续操作"):
                    SemanticExecutor(
                        adb, SemanticMap([target]), lambda _message: None,
                        sleep_fn=lambda _seconds: None,
                    ).execute(command, "登录页")

                self.assertEqual(adb.taps, [])


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

    def test_round_trip_preserves_three_purposes_and_both_coordinate_regions(self):
        original = SemanticMap([
            region(
                "click", "登录页", "登录", action="click", destination="主页",
                text="登录", bounds_ratio=[.4, .2, .6, .25],
                action_bounds_ratio=[.25, .15, .75, .3],
            ),
            region(
                "check", "登录页", "服务条款", action="check", destination="不应保留",
                text="服务条款", bounds_ratio=[.1, .8, .4, .85],
                action_bounds_ratio=[.05, .75, .5, .9],
            ),
            region(
                "recognize", "登录页", "登录页标题", action="recognize",
                text="QQ", bounds_ratio=[.4, .05, .6, .1],
                action_bounds_ratio=[.35, .02, .65, .12],
            ),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic_map.json"
            original.save(path)
            loaded = SemanticMap.load(path)

        self.assertEqual(
            [item.action for item in loaded.regions],
            ["click", "check", "recognize"],
        )
        self.assertEqual(loaded.regions[0].destination, "主页")
        self.assertEqual(loaded.regions[1].destination, "")
        self.assertEqual(loaded.regions[2].destination, "")
        self.assertEqual(loaded.regions[0].bounds_ratio, [.4, .2, .6, .25])
        self.assertEqual(
            loaded.regions[0].action_bounds_ratio,
            [.25, .15, .75, .3],
        )

    def test_legacy_anchor_and_missing_action_bounds_are_migrated(self):
        loaded = NamedRegion.from_payload({
            "id": "legacy",
            "page": "登录页",
            "name": "标题",
            "action": "anchor",
            "selector": {"text": "QQ"},
            "bounds_ratio": [.4, .05, .6, .1],
        })

        self.assertEqual(loaded.action, "recognize")
        self.assertEqual(loaded.action_bounds_ratio, loaded.bounds_ratio)


if __name__ == "__main__":
    unittest.main()