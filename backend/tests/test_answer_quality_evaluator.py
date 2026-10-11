import unittest

from services.evaluation.answer_quality_evaluator import AnswerQualityEvaluator


class TestAnswerQualityEvaluator(unittest.TestCase):
    def setUp(self):
        self.evaluator = AnswerQualityEvaluator()

    def test_returns_expected_keys(self):
        query = "How much did I invest in HDFC this month?"
        answer = "You invested 50000 in HDFC this month, based on your recorded transaction."
        citations = [
            {
                "source": "graph",
                "retrieval_score": 0.88,
                "snippet": "Transaction: invested 50000 in HDFC Mutual Fund this month",
                "properties": {"amount": 50000, "name": "HDFC Mutual Fund"},
            }
        ]
        metrics = {"retrieval_ms": 120.0, "llm_generation_ms": 820.0}

        result = self.evaluator.evaluate(query, answer, citations, metrics)

        expected_keys = {
            "overall_score",
            "quality_label",
            "groundedness_score",
            "citation_quality_score",
            "relevance_score",
            "completeness_score",
            "hallucination_risk",
            "supported_claim_ratio",
            "unsupported_claim_ratio",
            "citation_count",
            "graph_citation_count",
            "vector_citation_count",
            "avg_citation_score",
            "numeric_claim_support_ratio",
            "latency_penalty",
            "summary",
        }

        self.assertTrue(expected_keys.issubset(result.keys()))
        self.assertGreaterEqual(result["overall_score"], 0.0)
        self.assertLessEqual(result["overall_score"], 1.0)

    def test_no_citations_increases_risk(self):
        query = "What are my assets?"
        answer = "You own several assets including equity and debt instruments."

        result = self.evaluator.evaluate(
            query, answer, [], {"retrieval_ms": 60.0, "llm_generation_ms": 300.0})

        self.assertEqual(result["citation_count"], 0)
        self.assertGreaterEqual(result["hallucination_risk"], 0.4)


if __name__ == "__main__":
    unittest.main()
