"""Public errors contain fixed codes only, never provider payloads."""


class GroqError(Exception):
    """Expected integration failure safe to report without patient data."""

    def __init__(self, code: str = "provider_error") -> None:
        self.code = code
        super().__init__(code)


class GroqTimeout(GroqError):
    def __init__(self) -> None:
        super().__init__("timeout")


class InvalidResponse(GroqError):
    def __init__(self) -> None:
        super().__init__("invalid_response")
