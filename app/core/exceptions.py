from typing import Any


class AppException(Exception):
    def __init__(self, *, code: str, status_code: int = 400, detail: str | None = None,
                 params: dict[str, Any] | None = None):
        super().__init__(detail or code)
        self.status_code = status_code
        self.detail = {"code": code, "i18n_key": f"errors.{code}",
                       "params": params or {}, "message": detail or code}


class NotFoundError(AppException):
    def __init__(self, entity: str, detail: str | None = None):
        super().__init__(code=f"{entity}_not_found", status_code=404, detail=detail or f"{entity} not found")


class ConflictError(AppException):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code=code, status_code=409, detail=detail)


class UpstreamError(AppException):
    def __init__(self, service: str, detail: str | None = None):
        super().__init__(code=f"{service}_unavailable", status_code=502, detail=detail)


class ForbiddenError(AppException):
    def __init__(self, detail: str = "Not allowed"):
        super().__init__(code="forbidden", status_code=403, detail=detail)
