from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maa_ocr import OcrHit, hits_from_detail, joined_text, recognize_text


class MaaOcrParseTests(unittest.TestCase):
    def test_hits_from_detail_keep_text_score_and_box(self):
        detail = SimpleNamespace(
            all_results=[
                SimpleNamespace(text=" 登录 ", score=0.91, box=[10, 20, 80, 30]),
                SimpleNamespace(text="", score=0.2, box=[0, 0, 1, 1]),
                SimpleNamespace(text="登录", score=0.91, box=[10, 20, 80, 30]),
            ],
            filtered_results=[],
            best_result=None,
        )
        hits = hits_from_detail(detail)
        self.assertEqual(hits, [OcrHit("登录", 0.91, (10, 20, 80, 30))])
        self.assertEqual(joined_text(hits), "登录")

    def test_recognize_text_reads_task_nodes(self):
        hit = OcrHit("大厅", 0.8, (1, 2, 3, 4))
        detail = SimpleNamespace(
            nodes=[SimpleNamespace(recognition=SimpleNamespace(
                all_results=[SimpleNamespace(text="大厅", score=0.8, box=(1, 2, 3, 4))],
            ))]
        )
        job = SimpleNamespace(wait=lambda: None, succeeded=True, get=lambda: detail)

        class FakeSession(dict):
            pass

        session = FakeSession(
            JOCR=lambda **kwargs: kwargs,
            JRecognitionType=SimpleNamespace(OCR="OCR"),
            tasker=SimpleNamespace(post_recognition=lambda *_args, **_kwargs: job),
        )
        import maa_ocr

        original = maa_ocr._SESSION
        maa_ocr._SESSION = session
        try:
            hits = recognize_text([[1, 2], [3, 4]], [0, 0, 10, 10])
        finally:
            maa_ocr._SESSION = original
        self.assertEqual(hits, [hit])


if __name__ == "__main__":
    unittest.main()
