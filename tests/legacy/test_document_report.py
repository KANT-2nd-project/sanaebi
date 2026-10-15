import unittest

from archive.classification_v1 import artifacts
from archive.classification_v1.evaluation import metrics as evaluation
from archive.classification_v1.evaluation import reporting
from contracts.classification import LABELS


# 예전 라벨은 거부하고 현재 질문 3분류 결과만 보고서에 포함하는지 검사
class ReportLabelTests(unittest.TestCase):
    def test_old_labels_are_not_evaluated(self):
        row = {"question_id": "Q1", "text": "VPN 질문", "label": "it"}
        with self.assertRaisesRegex(ValueError, "라벨"):
            evaluation.evaluate([row], ["hr"])

    def test_only_current_question_reports_are_included(self):
        current = {
            "settings": {
                "labels": list(LABELS),
                "data_split": {"input_fields": ["question"]},
            }
        }
        old = {
            "settings": {
                "labels": [
                    "HR",
                    "IT",
                    "FINANCE_PROCUREMENT",
                    "WORKPLACE",
                    "SECURITY_LEGAL",
                    "COMPANY",
                ],
                "data_split": {"input_fields": ["title", "text"]},
            }
        }
        self.assertTrue(artifacts.is_current_report(current))
        self.assertFalse(artifacts.is_current_report(old))
        with self.assertRaisesRegex(ValueError, "3분류"):
            reporting.render_report(old)


if __name__ == "__main__":
    unittest.main()
