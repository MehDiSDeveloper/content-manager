"""Back: which page it lands on, and with which snapshot."""

from podcast_workspace.ui.navigation import NavEntry, NavigationHistory


class FakePage:
    """Stands in for a stacked page. Only identity and the state protocol matter."""

    def __init__(self, name: str, state: object = None, fail: bool = False) -> None:
        self.nav_title = name
        self._state = state
        self._fail = fail
        self.restored: list[object] = []

    def nav_state(self) -> object:
        return self._state

    def restore_nav_state(self, state: object) -> None:
        if self._fail:
            raise RuntimeError("the rows it named are gone")
        self.restored.append(state)


class PlainPage:
    """A page with nothing worth restoring still has to be reachable by Back."""

    nav_title = "ساده"


def test_back_returns_the_previous_page_with_its_snapshot() -> None:
    history = NavigationHistory()
    tags = FakePage("برچسب‌ها", state="tag-7")
    ideas = PlainPage()
    history.push(tags)

    entry = history.pop_before(ideas)
    assert entry is not None
    assert entry.page is tags
    assert entry.title == "برچسب‌ها"
    entry.restore()
    assert tags.restored == ["tag-7"]


def test_the_snapshot_is_taken_on_the_way_out_not_on_the_way_back() -> None:
    history = NavigationHistory()
    tags = FakePage("برچسب‌ها", state="tag-7")
    history.push(tags)
    tags._state = "tag-99"  # the page moved on after the user left it

    entry = history.pop_before(PlainPage())
    assert entry is not None and entry.state == "tag-7"


def test_back_skips_the_page_already_in_front() -> None:
    history = NavigationHistory()
    episodes, voices = PlainPage(), PlainPage()
    history.push(episodes)
    history.push(voices)

    entry = history.pop_before(voices)  # already on voices: one press must leave it
    assert entry is not None and entry.page is episodes


def test_pushing_the_same_page_twice_keeps_one_step() -> None:
    history = NavigationHistory()
    tags = FakePage("برچسب‌ها", state="a")
    history.push(tags)
    tags._state = "b"
    history.push(tags)  # refreshes the snapshot instead of stacking a second step

    assert len(history) == 1
    entry = history.pop_before(PlainPage())
    assert entry is not None and entry.state == "b"


def test_history_is_capped() -> None:
    history = NavigationHistory(limit=3)
    pages = [PlainPage() for _ in range(6)]
    for page in pages:
        history.push(page)

    assert len(history) == 3
    assert [history.pop_before(PlainPage()).page for _ in range(3)] == pages[:2:-1]


def test_nothing_to_go_back_to() -> None:
    history = NavigationHistory()
    current = PlainPage()
    assert not history
    assert history.pop_before(current) is None

    history.push(current)  # only the page we are already on
    assert history.pop_before(current) is None


def test_peek_does_not_consume() -> None:
    history = NavigationHistory()
    tags = FakePage("برچسب‌ها")
    history.push(tags)

    assert history.peek_before(PlainPage()).title == "برچسب‌ها"
    assert len(history) == 1


def test_a_page_with_no_state_still_navigates() -> None:
    entry = NavEntry(PlainPage())
    entry.restore()  # must not raise


def test_a_failed_restore_never_blocks_the_navigation() -> None:
    page = FakePage("خراب", state="x", fail=True)
    NavEntry(page, "x").restore()
    assert page.restored == []
