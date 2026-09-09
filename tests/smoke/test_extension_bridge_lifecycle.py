from streamlit.testing.v1 import AppTest


def _bridge_identity_app() -> None:
    import streamlit as st

    from jobpilot.ui.site_discovery import get_extension_bridge

    bridge = get_extension_bridge()
    st.session_state.setdefault("first_bridge_id", id(bridge))
    st.session_state.setdefault("first_bridge_token", bridge.token)
    st.session_state["current_bridge_id"] = id(bridge)
    st.write(id(bridge))


def test_streamlit_rerun_does_not_recreate_bridge_or_rotate_token() -> None:
    app = AppTest.from_function(_bridge_identity_app).run()
    first_id = app.session_state["first_bridge_id"]
    first_token = app.session_state["first_bridge_token"]

    app.run()

    assert app.session_state["current_bridge_id"] == first_id
    assert app.session_state["first_bridge_token"] == first_token
