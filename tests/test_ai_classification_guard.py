"""Focal offline regression for the captured narrative/classification conflict."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from test_ai_service import AIServiceTests
from risk_support import RiskTestCase
from services.ai_service import get_ai_assessment, RiskAssessment
from core.errors import ServiceUnavailable

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/ai_classification_conflict.json').read_text(encoding='utf-8'))


class CalculatedClassificationTests(unittest.TestCase):
    setUp = AIServiceTests.setUp
    embed_documents = AIServiceTests.embed_documents
    respond = AIServiceTests.respond

    def test_calculated_mode_explains_the_given_class_without_reclassifying(self):
        self.output = {'risk_level': 'medio', 'explanation': 'A classificação final é média. Há limitações nos dados.'}
        result = get_ai_assessment('Dados calculados: score 0,64.', expected_risk_level='Médio')
        self.assertEqual(result.model_dump(), self.output)
        self.assertIn("use EXATAMENTE 'medio'", self.prompts[0])
        self.assertIn('não reclassifique', self.prompts[0])
        self.assertNotIn('decidir um NÍVEL ÚNICO', self.prompts[0])
        self.chat.return_value.with_structured_output.assert_called_once_with(RiskAssessment)

    def test_generated_enum_must_match_calculated_class(self):
        for generated in ('baixo', 'alto'):
            with self.subTest(generated=generated):
                self.output = {'risk_level': generated, 'explanation': 'Parecer sobre os fatores observados.'}
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('Dados', expected_risk_level='Médio')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')

    def test_captured_conflict_is_refused_even_if_synthetic_enum_agrees(self):
        self.assertIsNone(FIXTURE['upstreamModelRiskLevel'])
        for synthetic_enum in ('alto', 'medio'):
            with self.subTest(synthetic_enum=synthetic_enum):
                self.output = {'risk_level': synthetic_enum, 'explanation': FIXTURE['observedExplanation']}
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('Dados', expected_risk_level=FIXTURE['observedCalculatedRiskLevel'])
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
                self.assertNotIn(FIXTURE['observedExplanation'], str(caught.exception))

    def test_explicit_classification_clauses_cannot_disagree(self):
        for text in ('A classificação de risco é alta.', 'A classificação final como alto é justificada.',
                     'O nível de risco é baixo.', 'Risco final: ALTO.', 'A classificação final é média. A classificação de risco é alta.'):
            with self.subTest(text=text):
                self.output = {'risk_level': 'medio', 'explanation': text}
                with self.assertRaises(ServiceUnavailable):
                    get_ai_assessment('Dados', expected_risk_level='Médio')

    def test_legitimate_high_slope_low_permeability_and_text_are_preserved(self):
        text = 'A alta declividade a montante e a baixa permeabilidade exigem atenção. A classificação final é média; isso não certifica segurança.'
        self.output = {'risk_level': 'medio', 'explanation': text}
        result = get_ai_assessment('Dados', expected_risk_level='Médio')
        self.assertEqual(result.explanation, text)
        self.assertEqual(result.risk_level, 'medio')

    def test_invalid_authoritative_class_fails_before_external_boundaries(self):
        for value in ('', 'crítico', 0.64, True):
            with self.subTest(value=value), self.assertRaises(ServiceUnavailable) as caught:
                get_ai_assessment('Dados', expected_risk_level=value)
            self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.embeddings.assert_not_called()
        self.chat.assert_not_called()


class ClassificationRouteTests(RiskTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict('os.environ', {'OPENAI_API_KEY': 'unit-test-unused'}))
        self.ai.side_effect = get_ai_assessment
        self.model = self.enterContext(patch('services.ai_service._get_ai_assessment'))
        self.elevation.side_effect = [0, 0]
        self.db.query.return_value.order_by.return_value.first.return_value = (
            type('River', (), {'name': 'Córrego Verde I', 'type': 'stream'})(), 74.15047209,
            'POINT(-46.6859516532941 -23.562699712539864)')
        self.provider.get_soil_data.return_value = {'class_id': 24, 'class_name': 'Área Urbanizada', 'is_permeable': False}
        self.provider.get_water_frequency.return_value = {'frequency_years': 1, 'confidence': 1}

    def test_captured_conflict_returns_safe_503_before_history_write(self):
        # Enum was not captured historically; matching 'medio' is deliberately synthetic.
        self.model.return_value = RiskAssessment(risk_level='medio', explanation=FIXTURE['observedExplanation'])
        response = self.post_risk()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['detail']['code'], 'AI_UNAVAILABLE')
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()
        self.db.rollback.assert_called_once()
        self.db.close.assert_called_once()
        self.ai.assert_called_once()
        self.assertEqual(self.ai.call_args.kwargs, {'expected_risk_level': 'Médio'})

    def test_coherent_narrative_keeps_score_class_and_original_text(self):
        text = 'A classificação final é média. A alta declividade local não foi inferida dos dados disponíveis.'
        self.model.return_value = RiskAssessment(risk_level='medio', explanation=text)
        response = self.post_risk()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body['risk_level'], body['risk_calculation']['total_score']), ('Médio', 0.64))
        self.assertEqual(body['resposta_ia'], text)
        assessment = self.db.add.call_args.args[0]
        self.assertEqual((assessment.risk_level, assessment.explanation), ('Médio', text))
        self.db.commit.assert_called_once()
