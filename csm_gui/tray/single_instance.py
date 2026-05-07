"""Single-instance lock via QLocalServer/Socket.

Usage in app.py:
    inst = SingleInstance("csm-app-singleton")
    if not inst.try_acquire():
        inst.send_show()
        sys.exit(0)
    # main process keeps `inst` alive; connect inst.show_requested to MainWindow.
"""
from __future__ import annotations
from PyQt6.QtCore import QObject, QCoreApplication, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_SHOW_MSG = b"show\n"
_TIMEOUT_MS = 2000


class SingleInstance(QObject):
    """Bind a named local socket; second instance detects and notifies first.

    The chosen ``server_name`` must be unique to the app + user — Windows
    pipe names live in a shared namespace within a logon session.
    """

    show_requested = pyqtSignal()

    def __init__(self, server_name: str = "csm-app-singleton",
                 parent: QObject | None = None):
        super().__init__(parent)
        self._name = server_name
        self._server: QLocalServer | None = None
        self._acquired = False

    def try_acquire(self) -> bool:
        """Attempt to bind the server. Return True iff this is the first process.

        If a stale socket file remains from a crashed prior process,
        ``QLocalServer.removeServer`` clears it and we try again.
        """
        # Quick probe: try to connect as client. If a real server answers,
        # this process is NOT first.
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(_TIMEOUT_MS):
            probe.disconnectFromServer()
            return False
        probe.abort()

        # No server answering — clean any stale name then bind.
        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        if not self._server.listen(self._name):
            self._server = None
            return False
        self._server.newConnection.connect(self._on_new_connection)
        self._acquired = True
        return True

    def _on_new_connection(self) -> None:
        assert self._server is not None
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        if sock.waitForReadyRead(_TIMEOUT_MS):
            data = bytes(sock.readAll())
            if data.strip() == b"show":
                self.show_requested.emit()
        sock.disconnectFromServer()
        sock.deleteLater()

    def send_show(self) -> bool:
        """Send a 'show' command to an existing instance. Return True on success."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(_TIMEOUT_MS):
            return False
        sock.write(_SHOW_MSG)
        ok = sock.waitForBytesWritten(_TIMEOUT_MS)
        sock.disconnectFromServer()
        # Allow the server's Qt event loop to process the newConnection/readyRead
        # signals before we return (important for in-process tests).
        QCoreApplication.processEvents()
        return ok

    def release(self) -> None:
        """Close the server. Safe to call multiple times."""
        if self._server is not None:
            self._server.close()
            self._server = None
        self._acquired = False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass
