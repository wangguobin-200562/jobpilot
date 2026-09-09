"""Authenticated localhost-only bridge for the JobPilot Chrome extension."""

from __future__ import annotations

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import re
import secrets
import socket
import threading
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from pydantic import Field, model_validator

from jobpilot.browser.apply_channel import ApplyTaskChannel
from jobpilot.browser.models import JobDiscoveryItem
from jobpilot.browser.job_identity import canonical_job_key
from jobpilot.models import ApplyResultReport, ExtensionHeartbeat, ProfileModel


logger = logging.getLogger(__name__)
BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8765
BRIDGE_PATH = "/v1/discovery"
APPLY_NEXT_PATH = "/v1/apply/tasks/next"
APPLY_RESULT_PATH = "/v1/apply/results"
APPLY_HEARTBEAT_PATH = "/v1/apply/heartbeat"
BRIDGE_HEALTH_PATH = "/v1/health"
MAX_PAYLOAD_BYTES = 1_000_000
_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


class ExtensionBridgeError(RuntimeError):
    """Safe local bridge lifecycle error."""


class ExtensionPayload(ProfileModel):
    site: Literal["boss"]
    jobs: list[JobDiscoveryItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_boss_jobs(self) -> "ExtensionPayload":
        unique: list[JobDiscoveryItem] = []
        seen: set[str] = set()
        for job in self.jobs:
            parsed = urlparse(job.source_url)
            if job.source != self.site:
                raise ValueError("job source must match payload site")
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or not parsed.hostname.endswith("zhipin.com")
            ):
                raise ValueError("BOSS job URLs must use the zhipin.com HTTPS origin")
            identity = canonical_job_key(job.source_url, job.company, job.job_title)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(job)
        self.jobs = unique
        return self


class ExtensionInbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[JobDiscoveryItem] = []
        self._revision = 0

    def publish(self, items: list[JobDiscoveryItem]) -> int:
        with self._lock:
            self._items = [item.model_copy(deep=True) for item in items]
            self._revision += 1
            return self._revision

    def snapshot(self) -> tuple[int, list[JobDiscoveryItem]]:
        with self._lock:
            return self._revision, [item.model_copy(deep=True) for item in self._items]

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._revision += 1


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Never let two JobPilot processes silently own the same localhost port.
    # That would split the token/task channel from the UI that created it.
    allow_reuse_address = False

    def server_bind(self) -> None:
        # Windows can safely reclaim a recently closed listener while still
        # preventing a second live process from sharing the Bridge port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        super().server_bind()


class ExtensionBridgeServer:
    """A narrow POST-only receiver bound exclusively to loopback."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_BRIDGE_PORT,
        token: str | None = None,
        inbox: ExtensionInbox | None = None,
        apply_channel: ApplyTaskChannel | None = None,
    ) -> None:
        self.host = BRIDGE_HOST
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.inbox = inbox or ExtensionInbox()
        self.apply_channel = apply_channel or ApplyTaskChannel()
        self._server: _BridgeHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.startup_error: str | None = None

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def endpoint(self) -> str:
        active_port = self._server.server_port if self._server else self.port
        return f"http://{self.host}:{active_port}{BRIDGE_PATH}"

    def __repr__(self) -> str:
        return (
            f"ExtensionBridgeServer(host={self.host!r}, port={self.port!r}, "
            f"running={self.running!r}, token='***')"
        )

    def start(self) -> "ExtensionBridgeServer":
        if self.running:
            return self
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "JobPilotBridge/1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def _origin(self) -> str | None:
                value = self.headers.get("Origin")
                normalized = value.rstrip("/") if value else None
                return (
                    normalized
                    if normalized and _EXTENSION_ORIGIN.fullmatch(normalized)
                    else None
                )

            def _origin_is_allowed(self) -> bool:
                """Allow MV3 worker requests that omit Origin, never a web origin."""
                supplied = self.headers.get("Origin")
                return supplied is None or self._origin() is not None

            def _cors_headers(self, origin: str) -> None:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

            def _json_response(self, status: int, payload: dict[str, object]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                origin = self._origin()
                if origin:
                    self._cors_headers(origin)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _discard_small_request_body(self) -> None:
                """Avoid a Windows TCP reset when rejecting a small POST early."""
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return
                if 0 < length <= MAX_PAYLOAD_BYTES:
                    self.rfile.read(length)

            def _authenticated(self) -> tuple[bool, str | None]:
                if not self._origin_is_allowed():
                    return False, "InvalidExtensionOrigin"
                if self.headers.get("Cookie") is not None:
                    return False, "CookieHeaderPresent"
                if self.headers.get("Authorization") is not None:
                    return False, "AuthorizationHeaderPresent"
                supplied = self.headers.get("X-JobPilot-Bridge-Token", "")
                if not hmac.compare_digest(supplied, bridge.token):
                    return False, "BridgeTokenMismatch"
                return True, None

            def _reject_auth(self, rejection_type: str, *, discard: bool) -> None:
                logger.warning(
                    "extension_bridge status=rejected error_type=%s",
                    rejection_type,
                )
                if discard:
                    self._discard_small_request_body()
                status = (
                    "invalid_token"
                    if rejection_type == "BridgeTokenMismatch"
                    else "invalid_extension_origin"
                    if rejection_type == "InvalidExtensionOrigin"
                    else "rejected"
                )
                self._json_response(403, {"status": status})

            def do_OPTIONS(self) -> None:
                origin = self._origin()
                if self.path not in {
                    BRIDGE_PATH,
                    APPLY_NEXT_PATH,
                    APPLY_RESULT_PATH,
                    APPLY_HEARTBEAT_PATH,
                } or origin is None:
                    self._json_response(403, {"status": "rejected"})
                    return
                self.send_response(204)
                self._cors_headers(origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-JobPilot-Bridge-Token",
                )
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def do_POST(self) -> None:
                if self.path not in {
                    BRIDGE_PATH,
                    APPLY_RESULT_PATH,
                    APPLY_HEARTBEAT_PATH,
                }:
                    self._discard_small_request_body()
                    self._json_response(404, {"status": "rejected"})
                    return
                authenticated, rejection_type = self._authenticated()
                if not authenticated:
                    self._reject_auth(rejection_type or "AuthenticationError", discard=True)
                    return
                if self.headers.get_content_type() != "application/json":
                    self._json_response(415, {"status": "rejected"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_PAYLOAD_BYTES:
                    self._json_response(413, {"status": "rejected"})
                    return
                raw = self.rfile.read(length)
                fingerprint = sha256(raw).hexdigest()[:12]
                if self.path == APPLY_HEARTBEAT_PATH:
                    try:
                        heartbeat = ExtensionHeartbeat.model_validate_json(raw)
                        diagnostics = bridge.apply_channel.heartbeat(heartbeat)
                    except Exception as exc:
                        logger.warning(
                            "extension_bridge channel=heartbeat status=rejected "
                            "error_type=%s",
                            type(exc).__name__,
                        )
                        self._json_response(422, {"status": "rejected"})
                        return
                    self._json_response(
                        202,
                        {
                            "status": "connected",
                            "execution_id": diagnostics.execution_id,
                            "pending": diagnostics.pending_count,
                            "processing": diagnostics.processing_count,
                            "completed": diagnostics.completed_count,
                        },
                    )
                    return
                if self.path == APPLY_RESULT_PATH:
                    try:
                        report = ApplyResultReport.model_validate_json(raw)
                        if report.status.value in {"contacted", "already_contacted"}:
                            item = bridge.apply_channel.reconcile_contact_result(report)
                        else:
                            item = bridge.apply_channel.report(report)
                    except Exception as exc:
                        logger.warning(
                            "extension_bridge channel=apply status=rejected "
                            "fingerprint_prefix=%s error_type=%s",
                            fingerprint,
                            type(exc).__name__,
                        )
                        self._json_response(422, {"status": "rejected"})
                        return
                    logger.info(
                        "extension_bridge channel=apply status=received task_id_prefix=%s",
                        item.task_id[:12],
                    )
                    self._json_response(202, {"status": "received"})
                    return
                try:
                    payload = ExtensionPayload.model_validate_json(raw)
                except Exception as exc:
                    logger.warning(
                        "extension_bridge site=unknown status=rejected "
                        "fingerprint_prefix=%s error_type=%s",
                        fingerprint,
                        type(exc).__name__,
                    )
                    self._json_response(422, {"status": "rejected"})
                    return
                revision = bridge.inbox.publish(payload.jobs)
                logger.info(
                    "extension_bridge site=%s job_count=%d status=received "
                    "fingerprint_prefix=%s",
                    payload.site,
                    len(payload.jobs),
                    fingerprint,
                )
                self._json_response(
                    202,
                    {"status": "received", "job_count": len(payload.jobs), "revision": revision},
                )

            def do_GET(self) -> None:
                if self.path == BRIDGE_HEALTH_PATH:
                    self._json_response(
                        200,
                        {"service": "jobpilot-extension-bridge", "status": "ok"},
                    )
                    return
                if self.path != APPLY_NEXT_PATH:
                    self._json_response(405, {"status": "method_not_allowed"})
                    return
                authenticated, rejection_type = self._authenticated()
                if not authenticated:
                    self._reject_auth(rejection_type or "AuthenticationError", discard=False)
                    return
                state, task = bridge.apply_channel.next_task()
                if state == "task" and task is not None:
                    self._json_response(
                        200,
                        {"status": "task", "task": task.model_dump(mode="json")},
                    )
                elif state in {"manual_required", "busy"}:
                    self._json_response(409, {"status": state})
                else:
                    self._json_response(200, {"status": state})

        try:
            self._server = _BridgeHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            self._server = None
            if self._existing_jobpilot_bridge():
                message = (
                    f"另一个 JobPilot 实例已占用本地 Bridge 端口 {self.port}。"
                    "请关闭重复运行的 JobPilot，只保留当前页面对应的服务。"
                )
            else:
                message = f"本地 Bridge 端口 {self.port} 被其他程序占用。"
            self.startup_error = message
            raise ExtensionBridgeError(message) from exc
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="jobpilot-extension-bridge",
            daemon=True,
        )
        self._thread.start()
        self.startup_error = None
        return self

    def _existing_jobpilot_bridge(self) -> bool:
        """Identify an existing JobPilot listener without exposing its token."""
        try:
            with urlopen(
                f"http://{self.host}:{self.port}{BRIDGE_HEALTH_PATH}", timeout=0.4
            ) as response:
                payload = json.loads(response.read(512).decode("utf-8"))
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return False
        return payload.get("service") == "jobpilot-extension-bridge"

    def rotate_token(self) -> str:
        """Invalidate the previous pairing token and discard stale inbox data."""
        self.token = secrets.token_urlsafe(24)
        self.inbox.clear()
        self.apply_channel.pause_active()
        return self.token

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
