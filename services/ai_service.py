# services/ai_service.py
from typing import Literal
from pathlib import Path
from numbers import Real
import re
import unicodedata
import numpy as np
from pydantic import BaseModel, Field, ValidationError, field_validator

from core.config import get_settings
from core.errors import ServiceUnavailable
from services.text_sanitizer import sanitize_text

class RiskAssessment(BaseModel):
    # use 'medio' sem acento para evitar problemas de encoding
    risk_level: Literal["baixo", "medio", "alto"] = Field(
        description="Escolha EXATAMENTE UM: 'baixo', 'medio' ou 'alto'."
    )
    explanation: str = Field(
        description="Resumo técnico conciso (3-6 frases) em PT-BR justificando a classificação final."
    )

    @field_validator("explanation")
    @classmethod
    def require_explanation(cls, value):
        clean = sanitize_text(value, field_name="explanation")
        if not clean or not clean.strip():
            raise ValueError("Required explanation is empty")
        return clean


def _classification_text(value):
    return ''.join(char for char in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(char))


def _calculated_class(value):
    if not isinstance(value, str):
        raise ServiceUnavailable('AI_UNAVAILABLE')
    level = _classification_text(value).strip()
    if level not in {'baixo', 'medio', 'alto'}:
        raise ServiceUnavailable('AI_UNAVAILABLE')
    return level


# Recognize direct classification declarations, not arbitrary adjectives such as
# "alta declividade". This is a bounded contradiction guard, not a semantic proof.
_CLASSIFICATION_CLAIM = re.compile(
    r'\b(?:classificacao(?:\s+final)?(?:\s+de\s+risco)?|'
    r'nivel(?:\s+final)?\s+de\s+risco|risco\s+final)\s*'
    r'(?:[:=]\s*|(?:e|esta|foi|permanece|como|de)\s+)?'
    r'(baix[oa]|medi[oa]|alt[oa])\b'
)


def _require_calculated_class(assessment, expected):
    if assessment.risk_level != expected:
        raise ServiceUnavailable('AI_UNAVAILABLE')
    for claim in _CLASSIFICATION_CLAIM.findall(_classification_text(assessment.explanation)):
        if claim[:-1] + 'o' != expected:
            raise ServiceUnavailable('AI_UNAVAILABLE')


def get_ai_assessment(question: str, *, expected_risk_level=None) -> RiskAssessment:
    expected = _calculated_class(expected_risk_level) if expected_risk_level is not None else None
    key = get_settings().openai_api_key
    if not key or not key.strip():
        raise ServiceUnavailable("CONFIG_UNAVAILABLE")

    from openai import OpenAIError
    from langchain_core.exceptions import OutputParserException

    try:
        result = _get_ai_assessment(question, key, expected_risk_level=expected)
        if expected is not None:
            _require_calculated_class(result, expected)
        return result
    except (OpenAIError, OutputParserException, ValidationError, OSError):
        raise ServiceUnavailable("AI_UNAVAILABLE") from None


def _get_ai_assessment(question: str, key: str, *, expected_risk_level=None) -> RiskAssessment:
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.prompts import PromptTemplate
    from langchain_core.runnables import RunnablePassthrough, RunnableLambda
    from langchain_openai.chat_models.base import OpenAIRefusalError

    # ===== RAG básico (igual ao seu get_ai_answer) =====
    data_dir = Path(__file__).resolve().parents[1] / "data"
    with open(data_dir / "flood_risk_brazil.txt", encoding="utf-8") as f1:
        txt1 = f1.read()
    with open(data_dir / "bart_flood_model.txt", encoding="utf-8") as f2:
        txt2 = f2.read()
    if not txt1.strip() or not txt2.strip():
        raise ServiceUnavailable("AI_UNAVAILABLE")

    from langchain_core.documents import Document
    docs = [Document(page_content=txt1), Document(page_content=txt2)]
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    docs = splitter.split_documents(docs)
    doc_texts = [d.page_content for d in docs]

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", api_key=key)
    vectors = _embedding_array(embeddings.embed_documents(doc_texts), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(doc_texts) or vectors.shape[1] == 0:
        raise ServiceUnavailable("AI_UNAVAILABLE")
    with np.errstate(over="ignore", invalid="ignore"):
        norms = np.linalg.norm(vectors, axis=1)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise ServiceUnavailable("AI_UNAVAILABLE")

    def retrieve_context(q):
        qvec = _embedding_array(embeddings.embed_query(q))
        if qvec.ndim != 1 or qvec.shape[0] != vectors.shape[1]:
            raise ServiceUnavailable("AI_UNAVAILABLE")
        with np.errstate(over="ignore", invalid="ignore"):
            qnorm = np.linalg.norm(qvec)
        if not np.isfinite(qnorm) or qnorm == 0:
            raise ServiceUnavailable("AI_UNAVAILABLE")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            sims = np.dot(vectors, qvec) / (norms * qnorm)
        if not np.all(np.isfinite(sims)):
            raise ServiceUnavailable("AI_UNAVAILABLE")
        top_k = np.argsort(-sims)[:3]
        return "\n\n".join([doc_texts[i] for i in top_k])
    # ===================================================

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, api_key=key)

    # Enforce JSON estruturado com o schema do Pydantic
    structured_llm = llm.with_structured_output(RiskAssessment)

    def assess(prompt_value):
        try:
            return structured_llm.invoke(prompt_value)
        except (OpenAIRefusalError, ValueError):
            # LangChain's structured-output parser raises ValueError if neither
            # a parsed answer nor a refusal is returned. Scope to that boundary.
            raise ServiceUnavailable("AI_UNAVAILABLE") from None

    if expected_risk_level is None:
        task = "Você é um hidrólogo. Use o contexto para decidir um NÍVEL ÚNICO de risco final."
        level_rule = "- No campo 'risk_level', escolha EXATAMENTE UM entre: 'baixo', 'medio', 'alto'."
        decision_rule = "- A decisão final deve considerar a distância ao rio, queda relativa e o contexto técnico."
    else:
        task = "Você é um hidrólogo. Explique a classificação calculada informada; não reclassifique o risco."
        level_rule = f"- No campo 'risk_level', use EXATAMENTE '{expected_risk_level}', a classificação já calculada."
        decision_rule = "- A explicação deve manter essa classificação e os valores fornecidos, sem propor outra classe."

    prompt = PromptTemplate(
        input_variables=["context", "question"],
        template=(
            task + "\n\nRegras:\n" + level_rule + "\n" + decision_rule + "\n"
            "- No campo 'explanation', explique de forma técnica e objetiva (3-6 frases), em PT-BR.\n"
            "- Não inclua nenhum texto fora do JSON.\n\n"
            "Contexto técnico:\n{context}\n\n"
            "Pergunta:\n{question}\n"
        )
    )

    chain = (
        {"context": RunnableLambda(retrieve_context), "question": RunnablePassthrough()}
        | prompt
        | RunnableLambda(assess)
    )

    result = chain.invoke(question)
    # Validate dictionaries too; structured providers may return no parsed answer.
    if isinstance(result, RiskAssessment):
        result = result.model_dump()
    return RiskAssessment.model_validate(result)


def _embedding_array(value, dtype=None):
    try:
        # Object dtype preserves raw booleans/text in mixed lists before NumPy
        # could coerce them into otherwise valid numeric vectors.
        raw = np.array(value, dtype=object)
        if any(isinstance(item, (bool, np.bool_)) or not isinstance(item, Real)
               for item in raw.flat):
            raise ServiceUnavailable("AI_UNAVAILABLE")
        with np.errstate(over="ignore", invalid="ignore"):
            vector = np.array(value, dtype=dtype)
        if vector.dtype.kind not in "fiu" or not np.all(np.isfinite(vector)):
            raise ServiceUnavailable("AI_UNAVAILABLE")
        return vector
    except (TypeError, ValueError, OverflowError):
        raise ServiceUnavailable("AI_UNAVAILABLE") from None
