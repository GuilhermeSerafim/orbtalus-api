import ast
import unittest
from pathlib import Path


class AIServiceModelTests(unittest.TestCase):
    def test_default_chat_model_is_cost_optimized_for_mvp(self):
        source_path = Path(__file__).resolve().parents[1] / "services" / "ai_service.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        chat_models = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "ChatOpenAI":
                continue
            for keyword in node.keywords:
                if keyword.arg == "model" and isinstance(keyword.value, ast.Constant):
                    chat_models.append(keyword.value.value)

        self.assertEqual(chat_models, ["gpt-4o-mini"])
