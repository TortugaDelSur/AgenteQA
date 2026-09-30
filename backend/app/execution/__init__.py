class ExecutionPaused(Exception):
    """El agente no puede seguir solo: login, app inalcanzable o duda. Un assert que falla NO es esto."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason  # "login" | "question" | "unreachable"
        self.detail = detail
