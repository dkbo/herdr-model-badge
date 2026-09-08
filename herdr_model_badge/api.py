"""Minimal client for the herdr socket API: newline-delimited JSON over a UNIX socket.

Talking to the socket directly rather than shelling out to ``herdr`` keeps an event
hook down to a single round trip, which matters because hooks run on every agent
state change.
"""

import errno
import json
import os
import socket

DEFAULT_TIMEOUT = 3.0


class HerdrError(RuntimeError):
    """The server accepted the request and answered with an error."""

    def __init__(self, method, payload):
        self.method = method
        self.payload = payload
        code = (payload or {}).get("code") or "error"
        message = (payload or {}).get("message") or "request failed"
        super().__init__("%s: %s (%s)" % (method, message, code))


class Client:
    """One short-lived connection per call, which is all a hook ever needs."""

    def __init__(self, socket_path=None, timeout=DEFAULT_TIMEOUT):
        self.socket_path = socket_path or os.environ.get("HERDR_SOCKET_PATH")
        self.timeout = timeout
        self._counter = 0

    def available(self):
        return bool(self.socket_path) and os.path.exists(self.socket_path)

    def call(self, method, params=None):
        if not self.socket_path:
            raise HerdrError(method, {"code": "no_socket", "message": "HERDR_SOCKET_PATH is unset"})
        self._counter += 1
        request = {
            "id": "herdr-model-badge:%d:%d" % (os.getpid(), self._counter),
            "method": method,
            "params": params or {},
        }
        response = self._roundtrip(method, request)
        if "error" in response:
            raise HerdrError(method, response["error"])
        return response.get("result") or {}

    def _roundtrip(self, method, request):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout)
                client.connect(self.socket_path)
                client.sendall((json.dumps(request) + "\n").encode("utf-8"))
                line = self._read_line(client)
        except OSError as exc:
            raise HerdrError(
                method,
                {"code": errno.errorcode.get(exc.errno, "io_error"), "message": str(exc)},
            ) from exc
        try:
            return json.loads(line)
        except ValueError as exc:
            raise HerdrError(method, {"code": "bad_response", "message": str(exc)}) from exc

    @staticmethod
    def _read_line(client):
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        return b"".join(chunks).split(b"\n", 1)[0].decode("utf-8", "replace")

    # -- the three calls this plugin makes ---------------------------------------

    def agents(self):
        return self.call("agent.list").get("agents") or []

    def agent(self, pane_id):
        # agent.get takes a resolvable target: a pane id or a live agent name.
        return self.call("agent.get", {"target": pane_id}).get("agent") or {}

    def report(self, pane_id, source, tokens, ttl_ms=None):
        params = {"pane_id": pane_id, "source": source, "tokens": tokens}
        if ttl_ms is not None:
            # herdr drops the whole report when this runs out, which is how a value
            # that goes wrong on its own disappears without a hook to notice.
            params["ttl_ms"] = ttl_ms
        return self.call("pane.report_metadata", params)

    def notify(self, title, body=None):
        params = {"title": title}
        if body:
            params["body"] = body
        return self.call("notification.show", params)
