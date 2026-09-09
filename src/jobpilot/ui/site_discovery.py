"""Recruitment-site discovery UI, separate from the screening workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st
from pydantic import ValidationError

from jobpilot.browser import (
    DiscoveryMode,
    ExtensionBridgeError,
    ExtensionBridgeServer,
    JobDiscoveryResult,
    require_discovery_mode,
)
from jobpilot.config import PROJECT_ROOT


@st.cache_resource
def _cached_extension_bridge() -> ExtensionBridgeServer:
    """Retain one bridge object for the whole Streamlit server lifecycle."""
    # Bump only when the server-level bridge contract changes. Ordinary
    # Streamlit reruns keep this cached instance, token, inbox, and task channel.
    bridge_generation = 4
    _ = bridge_generation
    return ExtensionBridgeServer()


def get_extension_bridge() -> ExtensionBridgeServer:
    """Return the singleton and retry a previously blocked local bind."""
    bridge = _cached_extension_bridge()
    if bridge.running:
        return bridge
    try:
        bridge.start()
    except ExtensionBridgeError:
        # The same object, token, inbox and task channel survive. A later rerun
        # can recover automatically after a transient port conflict disappears.
        pass
    return bridge


def _build_received_result(items: list[Any]) -> JobDiscoveryResult:
    """Revalidate across Streamlit hot reloads without relying on class identity."""
    normalized = [
        item.model_dump(mode="python") if hasattr(item, "model_dump") else item
        for item in items
    ]
    return JobDiscoveryResult(
        items=normalized,
        failures=[],
        discovered_count=len(normalized),
        failed_count=0,
    )


def _discovery_key(item: Any) -> str:
    url = str(getattr(item, "source_url", "") or "").strip().casefold()
    if url:
        return f"url:{url}"
    company = str(getattr(item, "company", "") or "").strip().casefold()
    title = str(getattr(item, "job_title", "") or "").strip().casefold()
    return f"name:{company}|{title}"


def mark_discovery_items_screened(items: list[Any]) -> None:
    """Exclude one completed import from later cumulative extension snapshots."""
    keys = set(st.session_state.get("screened_discovery_keys", set()))
    keys.update(_discovery_key(item) for item in items)
    st.session_state.screened_discovery_keys = keys


def _store_received_jobs(items: list[Any]) -> None:
    screened = set(st.session_state.get("screened_discovery_keys", set()))
    current_items = [item for item in items if _discovery_key(item) not in screened]
    st.session_state.boss_discovery_result = _build_received_result(current_items)
    st.session_state.boss_discovery_error = None


@st.fragment(run_every="2s")
def _poll_received_jobs(bridge: ExtensionBridgeServer) -> None:
    """Poll only the local inbox; this fragment never invokes the AI pipeline."""
    revision, received = bridge.inbox.snapshot()
    if revision == st.session_state.get("boss_inbox_revision_seen", -1):
        return
    st.session_state.boss_inbox_revision_seen = revision
    if not received:
        st.caption("等待扩展连续采集岗位……")
        return
    try:
        _store_received_jobs(received)
    except (ValidationError, TypeError, ValueError):
        st.session_state.boss_discovery_error = "扩展岗位数据暂时无法读取。"
    current = st.session_state.get("boss_discovery_result")
    if current is not None and current.discovered_count:
        st.success(f"已获取 {current.discovered_count} 个新岗位。")
    st.rerun(scope="app")


def render_site_discovery(
    *,
    bridge_factory: Callable[[], ExtensionBridgeServer] = get_extension_bridge,
) -> None:
    """Render the explicitly routed BOSS extension flow."""
    capability = require_discovery_mode("boss", DiscoveryMode.EXTENSION)
    bridge = bridge_factory()
    if not bridge.running and not getattr(bridge, "startup_error", None):
        try:
            bridge.start()
        except ExtensionBridgeError:
            pass
    with st.expander("从招聘网站获取岗位", expanded=False):
        st.write("**BOSS 直聘 · Chrome Extension**")
        st.caption("连接后在扩展中开启一次连续采集；之后正常点击 BOSS 岗位即可自动累计。")
        st.caption("JobPilot 不会自动登录，也不会绕过验证码或安全验证。")
        st.code(str(PROJECT_ROOT / "extension"), language=None)
        st.caption("在 Chrome 扩展管理页启用开发者模式，选择“加载已解压的扩展程序”并打开以上目录。")

        if bridge.running:
            st.success("本地连接已自动启动，仅监听 127.0.0.1。")
            st.caption("将连接令牌复制到 Extension；服务完整重启后令牌才会变化。")
            if st.button(
                "生成新令牌",
                key="extension_bridge_rotate_token",
                icon=":material/key:",
                help="立即废弃旧令牌，并清空尚未导入的扩展岗位。",
            ):
                bridge.rotate_token()
                st.session_state.boss_discovery_result = None
                st.session_state.boss_discovery_error = None
                st.session_state.extension_bridge_token_version = (
                    st.session_state.get("extension_bridge_token_version", 0) + 1
                )
                st.success("新令牌已生成。请复制并覆盖扩展中的旧令牌。")
            with st.expander("显示连接令牌", expanded=False):
                st.text_input(
                    "本地连接令牌",
                    value=bridge.token,
                    type="password",
                    key=(
                        "extension_bridge_token_"
                        f"{st.session_state.get('extension_bridge_token_version', 0)}"
                    ),
                )
            _poll_received_jobs(bridge)

        result: JobDiscoveryResult | None = st.session_state.get("boss_discovery_result")
        error = st.session_state.get("boss_discovery_error")
        if error:
            st.warning(error)
        elif not bridge.running:
            st.error(getattr(bridge, "startup_error", None) or "本地 Bridge 未能启动。")
        elif result is None:
            st.info("等待扩展连续采集岗位。")
        else:
            st.success(f"已接收 {result.discovered_count} 个岗位。")
            for item in result.items:
                with st.container(border=True):
                    st.write(
                        f"**{item.company or '未提供公司'} · "
                        f"{item.job_title or '未命名岗位'}**"
                    )
                    st.caption(
                        f"{item.location or '地点未提供'}　·　"
                        f"{item.salary or '薪资未提供'}"
                    )
                    st.caption(
                        f"JD 已获取 · {len(item.jd_text)} 字　·　岗位链接已获取"
                    )
                    with st.expander("查看 JD 摘要", expanded=False):
                        st.text(item.jd_text[:500])
                        st.link_button(
                            "查看原岗位",
                            item.source_url,
                            icon=":material/open_in_new:",
                        )
