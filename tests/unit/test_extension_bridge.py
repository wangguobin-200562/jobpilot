from contextlib import contextmanager
from http.client import HTTPConnection
import json

import pytest

from jobpilot.browser import ExtensionBridgeError, ExtensionBridgeServer
from jobpilot.models import (
    ApplyExecutionStatus,
    BatchApplyExecution,
    BatchApplyExecutionItem,
)


ORIGIN = "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN = "test-bridge-token"


def _job(index: int = 1) -> dict:
    return {
        "company": "虚构公司",
        "job_title": f"虚构岗位{index}",
        "location": None,
        "salary": None,
        "source": "boss",
        "source_url": f"https://www.zhipin.com/job_detail/fake-{index}.html",
        "jd_text": "完整虚构岗位描述",
    }


@contextmanager
def _bridge():
    server = ExtensionBridgeServer(port=0, token=TOKEN).start()
    try:
        yield server
    finally:
        server.stop()


def _post(
    server, payload, *, token=TOKEN, origin=ORIGIN, extra_headers=None,
    path="/v1/discovery",
):
    body = json.dumps(payload).encode()
    connection = HTTPConnection(server.host, server._server.server_port, timeout=3)
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "X-JobPilot-Bridge-Token": token,
    }
    if origin is not None:
        headers["Origin"] = origin
    headers.update(extra_headers or {})
    connection.request(
        "POST",
        path,
        body=body,
        headers=headers,
    )
    response = connection.getresponse()
    response.read()
    connection.close()
    return response.status


def _get(server, *, token=TOKEN, origin=ORIGIN, path="/v1/apply/tasks/next"):
    connection = HTTPConnection(server.host, server._server.server_port, timeout=3)
    headers = {"X-JobPilot-Bridge-Token": token}
    if origin is not None:
        headers["Origin"] = origin
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, json.loads(body) if body else {}


def _execution():
    return BatchApplyExecution(
        execution_id="execution-bridge-test",
        items=[
            BatchApplyExecutionItem(
                task_id="task-bridge-test",
                company="虚构公司",
                job_title="虚构岗位",
                source_url="https://www.zhipin.com/job_detail/bridge-fake.html",
                status=ApplyExecutionStatus.PENDING,
            )
        ],
    )


def test_bridge_binds_loopback_only() -> None:
    with _bridge() as server:
        assert server.host == "127.0.0.1"
        assert server._server.server_address[0] == "127.0.0.1"


def test_health_endpoint_identifies_jobpilot_without_auth_or_secrets() -> None:
    with _bridge() as server:
        status, payload = _get(server, token="", origin=None, path="/v1/health")
        assert status == 200
        assert payload == {"service": "jobpilot-extension-bridge", "status": "ok"}
        assert TOKEN not in json.dumps(payload)


def test_second_process_bridge_reports_existing_jobpilot_port() -> None:
    with _bridge() as server:
        duplicate = ExtensionBridgeServer(port=server._server.server_port)
        with pytest.raises(ExtensionBridgeError, match="另一个 JobPilot 实例"):
            duplicate.start()
        assert duplicate.running is False
        assert "另一个 JobPilot 实例" in duplicate.startup_error


def test_valid_payload_is_received_as_job_discovery_item() -> None:
    with _bridge() as server:
        assert _post(server, {"site": "boss", "jobs": [_job()]}) == 202
        revision, items = server.inbox.snapshot()
        assert revision == 1
        assert items[0].company == "虚构公司"


@pytest.mark.parametrize(
    "payload",
    [
        {"site": "boss", "jobs": [{**_job(), "jd_text": ""}]},
        {"site": "boss", "jobs": [_job(i) for i in range(21)]},
        {"site": "boss", "jobs": [{**_job(), "cookie": "private"}]},
        {"site": "boss", "jobs": [{**_job(), "token": "private"}]},
        {"site": "boss", "jobs": [_job()], "command": "apply"},
        {"command": "apply", "jobs": []},
    ],
)
def test_invalid_oversized_sensitive_or_command_payload_is_rejected(payload) -> None:
    with _bridge() as server:
        assert _post(server, payload) == 422
        assert server.inbox.snapshot() == (0, [])


def test_explicit_web_origin_is_rejected_and_mv3_missing_origin_is_supported() -> None:
    with _bridge() as server:
        payload = {"site": "boss", "jobs": [_job()]}
        assert _post(server, payload, origin="https://www.zhipin.com") == 403
        assert _post(server, payload, origin=None) == 202
        assert _post(server, payload, token="wrong") == 403


def test_extension_origin_with_trailing_slash_is_supported() -> None:
    with _bridge() as server:
        payload = {"site": "boss", "jobs": [_job()]}
        assert _post(server, payload, origin=ORIGIN + "/") == 202


def test_cookie_and_authorization_headers_are_rejected() -> None:
    with _bridge() as server:
        payload = {"site": "boss", "jobs": [_job()]}
        assert _post(server, payload, extra_headers={"Cookie": "private=1"}) == 403
        assert _post(server, payload, extra_headers={"Authorization": "Bearer private"}) == 403


def test_credential_header_diagnostics_never_log_values(caplog) -> None:
    payload = {"site": "boss", "jobs": [_job()]}
    with _bridge() as server:
        assert _post(server, payload, extra_headers={"Cookie": "private-cookie"}) == 403
        assert _post(
            server,
            payload,
            extra_headers={"Authorization": "Bearer test"},
        ) == 403
    assert "CookieHeaderPresent" in caplog.text
    assert "AuthorizationHeaderPresent" in caplog.text
    assert "private-cookie" not in caplog.text
    assert "Bearer test" not in caplog.text


def test_bridge_deduplicates_untrusted_extension_payload() -> None:
    with _bridge() as server:
        assert _post(server, {"site": "boss", "jobs": [_job(), _job()]}) == 202
        assert len(server.inbox.snapshot()[1]) == 1


def test_rotating_token_invalidates_old_token_and_clears_inbox() -> None:
    with _bridge() as server:
        payload = {"site": "boss", "jobs": [_job()]}
        assert _post(server, payload) == 202
        new_token = server.rotate_token()
        assert new_token != TOKEN
        assert server.inbox.snapshot()[1] == []
        assert _post(server, payload) == 403
        assert _post(server, payload, token=new_token) == 202


def test_rejection_diagnostic_contains_only_safe_error_type(caplog) -> None:
    with _bridge() as server:
        assert _post(
            server,
            {"site": "boss", "jobs": [_job()]},
            token="private-wrong-token",
        ) == 403
    assert "BridgeTokenMismatch" in caplog.text
    assert "private-wrong-token" not in caplog.text


def test_bridge_repr_and_logs_do_not_expose_payload_or_token(caplog) -> None:
    private_jd = "不应出现在日志中的完整虚构JD"
    with _bridge() as server:
        assert TOKEN not in repr(server)
        assert _post(
            server,
            {"site": "boss", "jobs": [{**_job(), "jd_text": private_jd}]},
        ) == 202
    assert TOKEN not in caplog.text
    assert private_jd not in caplog.text


def test_apply_channel_requires_local_token_and_extension_origin() -> None:
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        invalid_status, invalid_payload = _get(server, token="wrong")
        assert invalid_status == 403
        assert invalid_payload == {"status": "invalid_token"}
        assert _get(server, origin="https://www.zhipin.com")[0] == 403
        status, payload = _get(server)
        assert status == 200
        assert payload["status"] == "task"
        assert set(payload["task"]) == {
            "task_id", "application_id", "company", "job_title", "source_url", "action"
        }


def test_apply_result_accepts_only_predefined_schema_and_rejects_commands() -> None:
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        _get(server)
        assert _post(
            server,
            {
                "task_id": "task-bridge-test",
                "status": "contacted",
                "message": "已建立沟通会话。",
                "contact_button_clicked": True,
                "contact_success_detected": True,
                "conversation_found": True,
            },
            path="/v1/apply/results",
        ) == 202
        assert server.apply_channel.snapshot().items[0].status is ApplyExecutionStatus.CONTACTED
        assert _post(
            server,
            {"command": "execute_javascript", "script": "private"},
            path="/v1/apply/results",
        ) == 422


def test_boss_contact_task_rejects_applied_without_resume_submission() -> None:
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        _get(server)
        assert _post(
            server,
            {
                "task_id": "task-bridge-test",
                "status": "applied",
                "message": "不应被接受。",
            },
            path="/v1/apply/results",
        ) == 422
        assert server.apply_channel.snapshot().items[0].status is ApplyExecutionStatus.PROCESSING


def test_contact_result_rejects_and_never_logs_chat_body(caplog) -> None:
    private_chat_body = "不应被接收或记录的虚构聊天正文"
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        _get(server)
        assert _post(
            server,
            {
                "task_id": "task-bridge-test",
                "status": "contacted",
                "message": "已建立沟通会话。",
                "contact_button_clicked": True,
                "contact_success_detected": True,
                "conversation_found": True,
                "chat_body": private_chat_body,
            },
            path="/v1/apply/results",
        ) == 422
        assert server.apply_channel.snapshot().items[0].status is ApplyExecutionStatus.PROCESSING
    assert private_chat_body not in caplog.text


def test_apply_protocol_never_accepts_cookie_or_authorization_headers() -> None:
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        assert _post(
            server,
            {"task_id": "task-bridge-test", "status": "failed", "message": "x"},
            path="/v1/apply/results",
            extra_headers={"Cookie": "private=1"},
        ) == 403
        assert _post(
            server,
            {"task_id": "task-bridge-test", "status": "failed", "message": "x"},
            path="/v1/apply/results",
            extra_headers={"Authorization": "Bearer private"},
        ) == 403


def test_two_tasks_are_fetched_in_order_and_empty_is_explicit() -> None:
    execution = _execution()
    execution.items.append(
        BatchApplyExecutionItem(
            task_id="task-bridge-second",
            company="虚构公司2",
            job_title="虚构岗位2",
            source_url="https://www.zhipin.com/job_detail/bridge-fake-2.html",
            status=ApplyExecutionStatus.PENDING,
        )
    )
    with _bridge() as server:
        server.apply_channel.publish(execution)
        _, first = _get(server)
        assert first["task"]["task_id"] == "task-bridge-test"
        assert _post(
            server,
            {"task_id": "task-bridge-test", "status": "skipped", "message": "测试完成。"},
            path="/v1/apply/results",
        ) == 202
        _, second = _get(server)
        assert second["task"]["task_id"] == "task-bridge-second"
        assert _post(
            server,
            {"task_id": "task-bridge-second", "status": "failed", "message": "虚构错误。"},
            path="/v1/apply/results",
        ) == 202
        _, empty = _get(server)
        assert empty == {"status": "no_pending_task"}


def test_heartbeat_updates_safe_channel_diagnostics() -> None:
    with _bridge() as server:
        server.apply_channel.publish(_execution())
        assert _post(
            server,
            {"extension_connected": True, "execution_id": "execution-bridge-test"},
            path="/v1/apply/heartbeat",
        ) == 202
        diagnostics = server.apply_channel.diagnostics()
        assert diagnostics.extension_connected is True
        assert diagnostics.last_heartbeat_at is not None


def test_bridge_restart_preserves_token_and_pending_channel() -> None:
    server = ExtensionBridgeServer(port=0, token=TOKEN).start()
    try:
        server.apply_channel.publish(_execution())
        server.stop()
        server.start()
        assert server.token == TOKEN
        assert server.apply_channel.diagnostics().pending_count == 1
    finally:
        server.stop()


def test_invalid_token_response_is_explicit() -> None:
    with _bridge() as server:
        status, payload = _get(server, token="wrong")
        assert status == 403
        assert payload == {"status": "invalid_token"}
