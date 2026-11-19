"""Public errors use a fixed allowlist; never expose upstream exception text."""
MESSAGES = {
    "DEMO_UNAVAILABLE": "Demo temporariamente indisponivel. Tente novamente mais tarde.",
    "INPUT_INVALID": "Área de análise inválida. Revise a seleção.",
    "CONFIG_UNAVAILABLE": "Serviço de análise indisponível. Tente novamente mais tarde.",
    "DATA_UNAVAILABLE": "Dados necessários à análise estão indisponíveis. Tente novamente mais tarde.",
    "DATABASE_UNAVAILABLE": "Não foi possível concluir a análise. Tente novamente mais tarde.",
    "AI_UNAVAILABLE": "Parecer técnico indisponível. Tente novamente mais tarde.",
}


class ServiceUnavailable(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])

    @property
    def detail(self):
        return {"code": self.code, "message": MESSAGES[self.code]}
