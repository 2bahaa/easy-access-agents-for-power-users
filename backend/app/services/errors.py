"""Domain exceptions raised by services and mapped to HTTP problems in `app.api.errors`."""


class DomainError(Exception):
    status_code = 400
    title = "Bad request"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404
    title = "Not found"


class ConflictError(DomainError):
    status_code = 409
    title = "Conflict"


class DomainValidationError(DomainError):
    status_code = 422
    title = "Validation error"
