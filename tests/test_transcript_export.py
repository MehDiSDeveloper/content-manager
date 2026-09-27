"""Whisper segments merged into paragraphs for pasting elsewhere."""

from podcast_workspace.domain.entities import TranscriptSegment
from podcast_workspace.domain.transcript_export import (
    HARD_MAX_CHARS,
    PAUSE_MS,
    SOFT_MAX_CHARS,
    Paragraph,
    paragraphs,
    render,
)


def seg(start_s: float, end_s: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(int(start_s * 1000), int(end_s * 1000), text)


def test_close_segments_join_into_one_paragraph():
    result = paragraphs([seg(0, 2, "سلام"), seg(2.3, 4, "به برنامه"), seg(4.1, 6, "خوش آمدید")])
    assert result == [Paragraph(0, "سلام به برنامه خوش آمدید")]


def test_a_pause_starts_a_new_paragraph():
    gap = PAUSE_MS / 1000
    result = paragraphs([seg(0, 2, "یک"), seg(2 + gap, 5, "دو"), seg(5.2, 6, "سه")])
    assert result == [Paragraph(0, "یک"), Paragraph(int((2 + gap) * 1000), "دو سه")]


def test_a_long_paragraph_closes_at_the_next_sentence_end():
    long = "و" * SOFT_MAX_CHARS
    result = paragraphs([seg(0, 1, long), seg(1, 2, "ادامه."), seg(2, 3, "بعدی")])
    assert [p.text for p in result] == [f"{long} ادامه.", "بعدی"]


def test_a_long_paragraph_without_a_sentence_end_waits_until_the_hard_limit():
    piece = "و" * 100
    count = HARD_MAX_CHARS // 100 + 2
    result = paragraphs([seg(i, i + 1, piece) for i in range(count)])
    assert len(result) == 2
    assert len(result[0].text) >= HARD_MAX_CHARS


def test_no_segments_no_paragraphs():
    assert paragraphs([]) == []


def test_render_with_header_and_times():
    items = [Paragraph(0, "یک"), Paragraph(65_000, "دو")]
    text = render(items, header=["عنوان", "تاریخ"], clock=lambda ms: f"{ms // 1000}s")
    assert text == "عنوان\nتاریخ\n\n[0s] یک\n\n[65s] دو"


def test_render_plain():
    assert render([Paragraph(0, "یک"), Paragraph(5, "دو")]) == "یک\n\nدو"
