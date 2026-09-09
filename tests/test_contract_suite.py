import json
import unittest
from collections import Counter
from pathlib import Path

from scripts.generate_demo_data import DOCUMENTS, EVALUATION_CASES
from src.contract_suite import FAULT_CASES, build_contract_report, compound_rows, fault_rows
from src.data_schema import EvalTool


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ContractSuiteTests(unittest.TestCase):
    def test_dataset_contracts(self) -> None:
        self.assertEqual(100, len(EVALUATION_CASES))
        counts = Counter(case.expected_tool for case in EVALUATION_CASES)
        self.assertEqual(40, counts[EvalTool.NONE])
        self.assertEqual(30, counts[EvalTool.GET_SERVICE_STATUS])
        self.assertEqual(30, counts[EvalTool.CREATE_TICKET])

        self.assertEqual(30, len(FAULT_CASES))
        self.assertEqual({5}, set(Counter(case.category for case in FAULT_CASES).values()))

    def test_all_contract_cases_pass(self) -> None:
        title_to_doc_id = {document.title: document.doc_id for document in DOCUMENTS}
        report = build_contract_report(EVALUATION_CASES, title_to_doc_id)
        self.assertEqual("PASS", report["status"])
        self.assertEqual((100, 100), (report["compound"]["passed"], report["compound"]["total"]))
        self.assertEqual((30, 30), (report["faults"]["passed"], report["faults"]["total"]))

    def test_committed_fixtures_match_the_generator(self) -> None:
        compound = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "compound_tasks.json").read_text(encoding="utf-8")
        )
        faults = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "fault_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(compound_rows(EVALUATION_CASES), compound)
        self.assertEqual(fault_rows(FAULT_CASES), faults)


if __name__ == "__main__":
    unittest.main()
