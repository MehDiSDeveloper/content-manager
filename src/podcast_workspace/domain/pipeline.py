"""Episode pipeline rules: column order and the stale marker."""

from datetime import datetime, timedelta

from podcast_workspace.domain.entities import Episode, EpisodeStatus

PIPELINE: tuple[EpisodeStatus, ...] = tuple(EpisodeStatus)
STALE_AFTER = timedelta(days=10)


def days_untouched(episode: Episode, now: datetime) -> int:
    return max(0, (now - episode.updated_at).days)


def is_stale(episode: Episode, now: datetime) -> bool:
    """Untouched (no edit, note, link or status change) for more than 10 days.
    Published episodes are finished work, never stale."""
    if episode.status is EpisodeStatus.PUBLISHED:
        return False
    return now - episode.updated_at > STALE_AFTER


def neighbour_status(status: EpisodeStatus, step: int) -> EpisodeStatus | None:
    index = PIPELINE.index(status) + step
    return PIPELINE[index] if 0 <= index < len(PIPELINE) else None
