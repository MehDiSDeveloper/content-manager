"""Qt side of the Bale bot: relays worker-thread callbacks to the GUI thread as signals."""

from PySide6.QtCore import QObject, Signal

from podcast_workspace.services.bale_bot import BaleBotService, BotStatus, ItemRef


class BotController(QObject):
    status_changed = Signal(object, str)  # BotStatus, detail
    item_received = Signal(object)  # ItemRef

    def __init__(self, service: BaleBotService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service

    @property
    def status(self) -> BotStatus:
        return self._service.status

    def restart(self) -> None:
        """(Re)start from current settings; stops quietly if disabled or no token."""
        # Emitting from the worker thread is safe: receivers live in the GUI thread, so
        # Qt queues the calls.
        started = self._service.start(self.status_changed.emit, self._on_item)
        if not started:
            self.status_changed.emit(BotStatus.STOPPED, "")

    def stop(self) -> None:
        self._service.stop()

    def _on_item(self, ref: ItemRef) -> None:
        self.item_received.emit(ref)
