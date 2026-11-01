"""Exercise the original RAG chain with only the external model boundaries doubled."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch, mock_open
from offline_guard import offline_boundaries

with offline_boundaries() as import_attempts:
    from services.ai_service import get_ai_assessment, RiskAssessment
    from core.errors import ServiceUnavailable, MESSAGES
    from main import create_app
assert not import_attempts

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda
from openai import OpenAIError


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-unused'}, clear=True))
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.embeddings = self.enterContext(patch('langchain_openai.OpenAIEmbeddings'))
        self.chat = self.enterContext(patch('langchain_openai.ChatOpenAI'))
        self.documents = []
        self.prompts = []
        self.output = {'risk_level': 'medio', 'explanation': 'Parecer técnico baseado no contexto.'}
        self.embeddings.return_value.embed_documents.side_effect = self.embed_documents
        self.embeddings.return_value.embed_query.return_value = [1.0, 0.0]
        self.chat.return_value.with_structured_output.return_value = RunnableLambda(self.respond)

    def embed_documents(self, documents):
        self.documents = documents
        # Known distinct similarities; real retrieval must choose the first three.
        return [[1.0, float(i)] for i in range(len(documents))]

    def respond(self, prompt):
        self.prompts.append(prompt.to_string())
        return self.output

    def test_original_rag_models_parameters_prompt_and_corpus_work_from_other_cwd(self):
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document
        root = Path(__file__).resolve().parents[1]
        old_cwd = Path.cwd()
        try:
            os.chdir(root / 'tests')
            result = get_ai_assessment('Pergunta de teste')
        finally:
            os.chdir(old_cwd)
        self.assertIsInstance(result, RiskAssessment)
        self.assertEqual(result.model_dump(), self.output)
        self.embeddings.assert_called_once_with(model='text-embedding-3-small', api_key='unit-test-unused')
        self.chat.assert_called_once_with(model='gpt-4o-mini', temperature=0.1, api_key='unit-test-unused')
        self.chat.return_value.with_structured_output.assert_called_once_with(RiskAssessment)
        expected_docs = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200).split_documents([
            Document(page_content=(root / 'data' / name).read_text(encoding='utf-8'))
            for name in ('flood_risk_brazil.txt', 'bart_flood_model.txt')])
        self.assertEqual(self.documents, [doc.page_content for doc in expected_docs])
        self.assertGreater(len(self.documents), 3)
        context = '\n\n'.join(self.documents[:3])
        self.assertEqual(self.prompts, [
            'Você é um hidrólogo. Use o contexto para decidir um NÍVEL ÚNICO de risco final.\n\n'
            'Regras:\n'
            "- No campo 'risk_level', escolha EXATAMENTE UM entre: 'baixo', 'medio', 'alto'.\n"
            '- A decisão final deve considerar a distância ao rio, queda relativa e o contexto técnico.\n'
            "- No campo 'explanation', explique de forma técnica e objetiva (3-6 frases), em PT-BR.\n"
            '- Não inclua nenhum texto fora do JSON.\n\n'
            f'Contexto técnico:\n{context}\n\nPergunta:\nPergunta de teste\n'])

    def test_missing_key_fails_before_any_model_construction(self):
        for key in ('', '   '):
            with self.subTest(key=repr(key)), patch.dict(os.environ, {'OPENAI_API_KEY': key}):
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'CONFIG_UNAVAILABLE')
        self.embeddings.assert_not_called()
        self.chat.assert_not_called()

    def test_invalid_required_explanation_or_classification_is_not_a_narrative_fallback(self):
        for output in (None, {}, {'risk_level': 'medio', 'explanation': None},
                       {'risk_level': 'medio', 'explanation': ''},
                       {'risk_level': 'medio', 'explanation': ' \n\t'},
                       {'risk_level': 'medio', 'explanation': '\x00\u200b'},
                       {'risk_level': 'medio', 'explanation': True},
                       {'risk_level': 'invalid', 'explanation': 'Text'}):
            with self.subTest(output=output):
                self.output = output
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')

    def test_sdk_errors_at_each_external_stage_are_safe(self):
        for target in (self.embeddings, self.embeddings.return_value.embed_documents,
                       self.embeddings.return_value.embed_query, self.chat):
            with self.subTest(stage=target._mock_name):
                previous = target.side_effect
                target.side_effect = OpenAIError('private token / prompt / URL')
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
                self.assertNotIn('private', str(caught.exception))
                target.side_effect = previous
        def failed_chat(prompt):
            raise OpenAIError('private response')
        self.chat.return_value.with_structured_output.return_value = RunnableLambda(failed_chat)
        with self.assertRaises(ServiceUnavailable):
            get_ai_assessment('unused')

    def test_missing_corpus_is_unavailable_before_models(self):
        with patch('builtins.open', side_effect=FileNotFoundError('private path')):
            with self.assertRaises(ServiceUnavailable) as caught:
                get_ai_assessment('unused')
        self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.embeddings.assert_not_called()
        self.chat.assert_not_called()

    def test_refused_or_unparsed_structured_output_fails_safely(self):
        from langchain_openai.chat_models.base import OpenAIRefusalError
        from langchain_core.exceptions import OutputParserException
        for failure in (OpenAIRefusalError('private refusal'),
                        ValueError('private missing parsed field'),
                        OutputParserException('private malformed output')):
            def fail(prompt):
                raise failure
            with self.subTest(error=type(failure).__name__):
                self.chat.return_value.with_structured_output.return_value = RunnableLambda(fail)
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')

    def test_empty_corpus_cannot_produce_an_ungrounded_answer(self):
        with patch('builtins.open', mock_open(read_data=' \n')):
            with self.assertRaises(ServiceUnavailable) as caught:
                get_ai_assessment('unused')
        self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.embeddings.assert_not_called()
        self.chat.assert_not_called()

    def test_invalid_document_embeddings_stop_before_chat(self):
        for value in (None, [], [[0, 0]], [[float('nan'), 0]], [[float('inf'), 0]],
                      [['bad', 0]], [[1, 0], [1]]):
            with self.subTest(value=value):
                self.embeddings.return_value.embed_documents.side_effect = None
                self.embeddings.return_value.embed_documents.return_value = value
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.chat.assert_not_called()

    def test_invalid_query_embeddings_stop_before_answer(self):
        for value in (None, [], [0, 0], [float('nan'), 0], [float('inf'), 0],
                      ['bad', 0], [1, 2, 3], [[1, 0]]):
            with self.subTest(value=value):
                self.embeddings.return_value.embed_query.return_value = value
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.assertEqual(self.prompts, [])

    def test_raw_boolean_and_text_document_embeddings_fail_before_chat(self):
        for row in ([True, False], ['1', '0'], [True, 0.0], [1.0, '0']):
            with self.subTest(document=row):
                self.embeddings.return_value.embed_documents.side_effect = lambda docs: [row for _ in docs]
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.chat.assert_not_called()

    def test_raw_boolean_and_text_query_embeddings_fail_before_llm_answer(self):
        for row in ([True, 0.0], [1.0, False], ['1', 0.0], [1.0, '0']):
            with self.subTest(query=row):
                self.embeddings.return_value.embed_query.return_value = row
                with self.assertRaises(ServiceUnavailable) as caught:
                    get_ai_assessment('unused')
                self.assertEqual(caught.exception.code, 'AI_UNAVAILABLE')
        self.assertEqual(self.prompts, [])

    def test_ask_ai_preserves_success_shape_and_safe_failure(self):
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.post('/ai/ask-ai', json={'pergunta': 'Teste'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'resposta': self.output})
        self.output = {'risk_level': 'baixo', 'explanation': ''}
        response = client.post('/ai/ask-ai', json={'pergunta': 'Teste'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': {'code': 'AI_UNAVAILABLE',
                                                     'message': MESSAGES['AI_UNAVAILABLE']}})
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            response = client.post('/ai/ask-ai', json={'pergunta': 'Teste'})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'detail': {'code': 'CONFIG_UNAVAILABLE',
                                                         'message': MESSAGES['CONFIG_UNAVAILABLE']}})

        self.embeddings.side_effect = RuntimeError('private programming bug')
        response = client.post('/ai/ask-ai', json={'pergunta': 'Teste'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private', response.text)

    def test_programming_error_is_not_disguised_as_provider_unavailability(self):
        self.embeddings.side_effect = RuntimeError('bug')
        with self.assertRaisesRegex(RuntimeError, 'bug'):
            get_ai_assessment('unused')
