from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from semantic_navigator import parse_ui_snapshot
from stage_model import parse_stage
from stage_navigator import (
    find_expand_control,
    is_chapter_expand_label,
    next_stage_action,
    node_label,
    recognize_stage_screen,
)


def snapshot_xml(*nodes):
    content = "".join(nodes)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node bounds="[0,0][1080,2400]" enabled="true">'
        f"{content}</node></hierarchy>"
    ).encode("utf-8")


def node(text="", bounds="[0,0][100,100]", clickable="true", checked="false"):
    return (
        f'<node text="{text}" content-desc="" resource-id="" '
        f'class="android.view.View" bounds="{bounds}" clickable="{clickable}" '
        f'checked="{checked}" enabled="true" />'
    )


class StageParseTests(unittest.TestCase):
    def test_parses_memory_and_game_labels(self):
        self.assertEqual(parse_stage("少女5-3").canonical, "少女5-3")
        self.assertEqual(parse_stage("公主12-支2").canonical, "公主12-支2")
        self.assertEqual(parse_stage("公主12-支2").stage_label, "卷 I 12-支2")
        self.assertEqual(parse_stage("卷 I 10-支2", "公主").canonical, "公主10-支2")
        self.assertEqual(parse_stage("15上-3").chapter_label, "第十五章上")


class ExpandLabelTests(unittest.TestCase):
    def test_progress_chip_accepts_partial_and_full(self):
        for label in ("0/12", "1/12", "3/12", "4/12", "6/12", "8/12", "11/12", "12/12", "12 / 12", "5/8", "3/12▼"):
            self.assertTrue(is_chapter_expand_label(label), label)
        self.assertTrue(is_chapter_expand_label(">>>"))
        self.assertFalse(is_chapter_expand_label("完美 12/8"))
        self.assertFalse(is_chapter_expand_label("暂未解锁"))
        self.assertFalse(is_chapter_expand_label("第十二章"))


class StageScreenTests(unittest.TestCase):
    def test_prefers_progress_chip_on_same_row(self):
        snapshot = parse_ui_snapshot(snapshot_xml(
            node("切换章节", "[200,120][880,200]"),
            node("第一卷", "[80,260][280,330]"),
            node("少女", "[700,250][820,340]"),
            node("公主", "[840,250][980,340]", checked="true"),
            node("第十一章", "[80,560][360,650]"),
            node("1/12", "[860,570][1000,640]"),
            node("第十二章", "[80,700][360,790]"),
            node(">>>", "[380,710][480,780]"),
            node("4/12", "[860,710][1000,780]"),
            node("第十三章", "[80,840][360,930]"),
            node("10/12", "[860,850][1000,920]"),
            node("第十四章", "[80,980][360,1070]"),
            node("6/12", "[860,990][1000,1060]"),
            node("第十五章上", "[80,1120][400,1210]"),
            node("暂未解锁", "[80,1130][220,1200]"),
        ))
        expand11 = find_expand_control(snapshot, "第十一章")
        expand12 = find_expand_control(snapshot, "第十二章")
        expand14 = find_expand_control(snapshot, "第十四章")
        self.assertEqual(node_label(expand11), "1/12")
        self.assertEqual(node_label(expand12), "4/12")
        self.assertEqual(node_label(expand14), "6/12")
        self.assertIsNone(find_expand_control(snapshot, "第十五章上"))

    def test_opens_list_then_scrolls_then_expands(self):
        target = parse_stage("公主12-3")
        map_state = recognize_stage_screen(parse_ui_snapshot(snapshot_xml(
            node("第八章 神秘月下城", "[200,80][880,160]"),
            node("切换章节", "[40,2100][240,2280]"),
            node("切换难度", "[40,1980][240,2080]"),
            node("公主", "[60,1860][200,1960]"),
        )))
        self.assertEqual(map_state.kind, "chapter_map")
        self.assertEqual(next_stage_action(map_state, target, parse_ui_snapshot(snapshot_xml())).kind, "tap")

        list_xml = snapshot_xml(
            node("切换章节", "[200,120][880,200]"),
            node("第一卷", "[80,260][280,330]"),
            node("公主", "[840,250][980,340]", checked="true"),
            node("第八章", "[80,700][360,790]"),
            node("12/12", "[860,710][1000,780]"),
            node("第九章", "[80,840][360,930]"),
            node("12/12", "[860,850][1000,920]"),
        )
        list_state = recognize_stage_screen(parse_ui_snapshot(list_xml))
        action = next_stage_action(list_state, target, parse_ui_snapshot(list_xml))
        self.assertEqual(action.kind, "swipe")
        self.assertEqual(action.direction, "up")

        expanded = parse_ui_snapshot(snapshot_xml(
            node("切换章节", "[200,120][880,200]"),
            node("第一卷", "[80,260][280,330]"),
            node("公主", "[840,250][980,340]", checked="true"),
            node("第十二章", "[80,520][360,610]"),
            node("8/12", "[860,530][1000,600]"),
            node("卷 I 12-1", "[80,640][360,720]"),
            node("卷 I 12-2", "[400,640][680,720]"),
            node("卷 I 12-3", "[720,640][1000,720]"),
            node("第十三章", "[80,900][360,990]"),
            node("10/12", "[860,910][1000,980]"),
        ))
        state = recognize_stage_screen(expanded)
        self.assertEqual(state.kind, "chapter_list")
        self.assertEqual(state.expanded_chapter, "第十二章")
        action = next_stage_action(state, target, expanded)
        self.assertEqual(action.kind, "tap_stage")
        self.assertIn("12-3", action.text)

    def test_locked_chapter_is_rejected(self):
        snapshot = parse_ui_snapshot(snapshot_xml(
            node("切换章节", "[200,120][880,200]"),
            node("第一卷", "[80,260][280,330]"),
            node("公主", "[840,250][980,340]", checked="true"),
            node("第十五章上", "[80,700][400,790]"),
            node("暂未解锁", "[80,710][220,780]"),
        ))
        state = recognize_stage_screen(snapshot)
        with self.assertRaises(ValueError):
            next_stage_action(state, parse_stage("公主15上-1"), snapshot)


if __name__ == "__main__":
    unittest.main()
