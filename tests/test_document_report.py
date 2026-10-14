import unittest

from classification import model_report


class ReportLabelTests(unittest.TestCase):
    def test_old_labels_are_not_evaluated(self):
        row = {"question_id": "Q1", "text": "VPN 질문", "label": "it"}
        with self.assertRaisesRegex(ValueError, "라벨"):
            model_report.evaluate([row], ["hr"])

    def test_only_current_question_reports_are_included(self):
        current = {
            "settings": {
                "labels": model_report.LABELS,
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
        self.assertTrue(model_report.is_current_report(current))
        self.assertFalse(model_report.is_current_report(old))
        with self.assertRaisesRegex(ValueError, "3분류"):
            model_report.write_report("old", old)


if __name__ == "__main__":
    unittest.main()
