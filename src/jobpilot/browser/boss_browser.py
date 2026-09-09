"""Visible, user-controlled BOSS browser lifecycle and Playwright connection."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from typing import Any

from jobpilot.browser.boss_extractor import BossExtractionError, BossExtractor, DiscoveryHaltError
from jobpilot.browser.models import JobDiscoveryResult
from jobpilot.config import PROJECT_ROOT


BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/job"
DEFAULT_CDP_PORT = 9223
DEFAULT_PROFILE_DIR = PROJECT_ROOT / ".browser" / "boss-profile"


class BossBrowserError(RuntimeError):
    """User-safe browser failure."""


class BossLoginRequiredError(BossBrowserError):
    """Raised when no usable BOSS search page is open."""


class HumanVerificationRequired(BossBrowserError, DiscoveryHaltError):
    """Raised when the user must complete a platform security check."""


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _find_chrome() -> Path | None:
    discovered = shutil.which("chrome") or shutil.which("chrome.exe")
    candidates = [
        Path(discovered) if discovered else None,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    return next((path for path in candidates if path and path.is_file()), None)


class BossBrowserManager:
    def __init__(self, *, port: int = DEFAULT_CDP_PORT, profile_dir: Path = DEFAULT_PROFILE_DIR) -> None:
        self.port = port
        self.profile_dir = profile_dir

    def start(self) -> bool:
        """Start a visible dedicated browser, or reuse the existing local session."""
        if _port_open(self.port):
            return False
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        chrome = _find_chrome()
        if chrome is None:
            raise BossBrowserError("未找到 Google Chrome，请先安装后重试。")
        command = [
            str(chrome), f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}", "--new-window", BOSS_SEARCH_URL,
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL, "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(command, **kwargs)
        for _ in range(30):
            if _port_open(self.port):
                return True
            time.sleep(0.25)
        raise BossBrowserError("浏览器未能启动，请确认已安装 Chrome 和 Playwright。")

    def discover_current_page(self, *, limit: int = 20) -> JobDiscoveryResult:
        """Attach to the user-controlled browser and read the current BOSS result page."""
        if not _port_open(self.port):
            raise BossBrowserError("尚未启动 JobPilot BOSS 浏览器。")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BossBrowserError("Playwright 尚未安装。") from exc
        extractor = BossExtractor()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
                pages = [page for context in browser.contexts for page in context.pages]
                page = next((item for item in reversed(pages) if "zhipin.com" in item.url), None)
                if page is None:
                    raise BossLoginRequiredError("请在已打开的浏览器中登录 BOSS 并进入职位搜索结果页。")
                if extractor.verification_visible(page):
                    raise HumanVerificationRequired("检测到验证码或安全验证，请人工完成后再继续。")
                context = page.context

                def load_detail(url: str) -> str:
                    detail = context.new_page()
                    try:
                        detail.goto(url, wait_until="domcontentloaded", timeout=20_000)
                        if extractor.verification_visible(detail):
                            raise HumanVerificationRequired("检测到安全验证，请人工处理后再继续。")
                        return extractor.extract_jd(detail)
                    finally:
                        detail.close()

                return extractor.discover(page, load_detail, limit=limit)
        except (BossBrowserError, HumanVerificationRequired):
            raise
        except BossExtractionError as exc:
            raise BossBrowserError(str(exc)) from exc
        except Exception as exc:
            if not _port_open(self.port):
                raise HumanVerificationRequired(
                    "BOSS 在读取页面时关闭了浏览器连接。请停止抓取并在浏览器中人工确认页面状态；"
                    "JobPilot 不会绕过平台安全验证。"
                ) from exc
            raise BossBrowserError("BOSS 页面暂时无法读取，请确认页面已加载后重试。") from exc
