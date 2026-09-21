"""Domain-level exceptions. Services translate these into user-facing messages."""


class DomainError(Exception):
    """Base class for every rule violation raised by the domain layer."""


class TagLimitExceededError(DomainError):
    def __init__(self, limit: int, attempted: int) -> None:
        super().__init__(f"At most {limit} tags are allowed; attempted {attempted}.")
        self.limit = limit
        self.attempted = attempted


class ValidationError(DomainError):
    """A field value is outside what the domain accepts."""


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: int) -> None:
        super().__init__(f"{entity} #{entity_id} does not exist.")
        self.entity = entity
        self.entity_id = entity_id


class DuplicateTagError(DomainError):
    """A tag with the same (normalized) name already exists."""

    def __init__(self, existing_name: str, existing_id: int) -> None:
        super().__init__(f"Tag {existing_name!r} already exists.")
        self.existing_name = existing_name
        self.existing_id = existing_id


class NearDuplicateTagError(DomainError):
    """Similar tags exist; the caller must confirm before creating another."""

    def __init__(self, similar_names: list[str]) -> None:
        super().__init__(f"Similar tags exist: {', '.join(similar_names)}")
        self.similar_names = similar_names
