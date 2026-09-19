"""Domain-level exceptions. Services translate these into user-facing messages."""


class DomainError(Exception):
    """Base class for every rule violation raised by the domain layer."""


class TagLimitExceededError(DomainError):
    def __init__(self, limit: int, attempted: int) -> None:
        super().__init__(f"At most {limit} tags are allowed; attempted {attempted}.")
        self.limit = limit
        self.attempted = attempted


class InvalidTagHierarchyError(DomainError):
    """A tag would become its own ancestor."""


class ValidationError(DomainError):
    """A field value is outside what the domain accepts."""


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: int) -> None:
        super().__init__(f"{entity} #{entity_id} does not exist.")
        self.entity = entity
        self.entity_id = entity_id
