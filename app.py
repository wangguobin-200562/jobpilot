import sys
from pathlib import Path

import streamlit as st


SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jobpilot.ui.navigation import create_navigation  # noqa: E402
from jobpilot.ui.state import initialize_session_state  # noqa: E402
from jobpilot.storage import DatabaseError, initialize_database  # noqa: E402
from jobpilot.ui.site_discovery import get_extension_bridge  # noqa: E402


st.set_page_config(
    page_title="JobPilot",
    page_icon=":material/send:",
    layout="wide",
    initial_sidebar_state="expanded",
)
initialize_session_state()
# This server-level resource must exist independently of the active page.
get_extension_bridge()
try:
    initialize_database()
except DatabaseError:
    st.error("本地投递数据暂时无法初始化，请检查 data 目录后重试。")
    st.stop()
create_navigation().run()
