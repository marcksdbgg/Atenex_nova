"""Atenex Nova — Base exception hierarchy.

All custom exceptions inherit from AtenexError to allow broad catch patterns.
Domain errors are separate from infrastructure errors per hexagonal architecture.
"""


class AtenexError(Exception):
    """Base exception for all Atenex Nova errors."""

    def __init__(self, message: str = "", code: str = "ATENEX_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


class DomainError(AtenexError):
    """Error raised by the domain layer."""

    def __init__(self, message: str = "", code: str = "DOMAIN_ERROR") -> None:
        super().__init__(message=message, code=code)


class EntityNotFoundError(DomainError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_type} with id '{entity_id}' not found",
            code="ENTITY_NOT_FOUND",
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class InvalidStateTransitionError(DomainError):
    """Raised when a document state transition is not allowed."""

    def __init__(self, entity_type: str, current: str, target: str) -> None:
        super().__init__(
            message=f"Cannot transition {entity_type} from '{current}' to '{target}'",
            code="INVALID_STATE_TRANSITION",
        )


class ValidationError(DomainError):
    """Raised for domain validation failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="VALIDATION_ERROR")


class InfrastructureError(AtenexError):
    """Error raised by the infrastructure layer."""

    def __init__(self, message: str = "", code: str = "INFRA_ERROR") -> None:
        super().__init__(message=message, code=code)


class DatabaseError(InfrastructureError):
    """Raised for database operation failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="DATABASE_ERROR")


class ExternalServiceError(InfrastructureError):
    """Raised when an external service (Qdrant, LLM, etc.) fails."""

    def __init__(self, service: str, message: str) -> None:
        super().__init__(
            message=f"External service '{service}' error: {message}",
            code="EXTERNAL_SERVICE_ERROR",
        )
        self.service = service


class BlobStoreError(InfrastructureError):
    """Raised for file storage failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="BLOB_STORE_ERROR")
