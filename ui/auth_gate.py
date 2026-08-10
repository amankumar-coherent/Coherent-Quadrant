"""Streamlit email login gate (24h session in st.session_state).

OTP email codes can be skipped temporarily with AUTH_SKIP_OTP=true.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from vendor_intel.auth.config import get_auth_settings
from vendor_intel.auth.db import init_db
from vendor_intel.auth.service import (
    AuthError,
    list_auth_events,
    login_without_otp,
    logout,
    request_otp,
    validate_session,
    verify_otp,
)


def _ensure_db() -> None:
    if st.session_state.get("_auth_db_ready"):
        return
    init_db()
    st.session_state["_auth_db_ready"] = True


def current_user() -> dict | None:
    """Return session user dict if valid; clear state if expired."""
    token = st.session_state.get("auth_token")
    if not token:
        return None
    try:
        _ensure_db()
        user = validate_session(token)
        return {
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role,
            "expires_at": user.expires_at,
        }
    except AuthError:
        for k in ("auth_token", "auth_email", "auth_user_id", "auth_role", "auth_expires_at"):
            st.session_state.pop(k, None)
        return None


def _store_session(info) -> None:
    st.session_state["auth_token"] = info.token
    st.session_state["auth_email"] = info.email
    st.session_state["auth_user_id"] = info.user_id
    st.session_state["auth_role"] = info.role
    st.session_state["auth_expires_at"] = info.expires_at.isoformat()
    st.session_state["auth_step"] = "email"
    st.session_state.pop("auth_pending_email", None)


def require_login() -> dict | None:
    """
    Show login UI until authenticated.
    Returns user dict when signed in; otherwise None (caller should stop rendering).
    """
    _ensure_db()
    user = current_user()
    if user:
        _render_session_bar(user)
        return user

    settings = get_auth_settings()
    skip_otp = settings.skip_otp

    if skip_otp:
        st.markdown(
            '<div class="hero"><h1>Sign in</h1>'
            "<p>Enter your work email to continue. "
            "Sessions last 24 hours. <em>(OTP email codes temporarily off.)</em></p></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="hero"><h1>Sign in</h1>'
            "<p>Enter your work email. We’ll send a one-time code. "
            "Sessions last 24 hours, then you sign in again.</p></div>",
            unsafe_allow_html=True,
        )

    step = st.session_state.get("auth_step", "email")
    email_default = st.session_state.get("auth_pending_email", "")

    if skip_otp or step == "email":
        email = st.text_input(
            "Work email",
            value=email_default,
            placeholder="username@coherentmarketinsights.com",
            key="login_email",
        )
        st.caption(
            "Recommended format: `username@coherentmarketinsights.com` "
            "(only this domain can sign in)."
        )
        btn = "Sign in" if skip_otp else "Send login code"
        if st.button(btn, type="primary", width="stretch"):
            try:
                if skip_otp:
                    info = login_without_otp(email)
                    _store_session(info)
                    st.rerun()
                else:
                    request_otp(email)
                    st.session_state["auth_pending_email"] = email.strip().lower()
                    st.session_state["auth_step"] = "otp"
                    st.success("Code sent — check your email (or the terminal if console mode).")
                    st.rerun()
            except AuthError as e:
                st.error(e.message)
            except Exception as e:
                st.error(f"Auth database unavailable: {e}")
                st.info(
                    "Set DATABASE_URL to a hosted Postgres (Neon/Supabase) in Streamlit Secrets "
                    "or local `.env`. Tables are created on first load via init_db()."
                )
        return None

    # OTP step (only when AUTH_SKIP_OTP is false)
    st.markdown(f"Code sent to **{st.session_state.get('auth_pending_email', '')}**")
    code = st.text_input("6-digit code", max_chars=6, placeholder="123456", key="login_otp")
    st.caption("Recommended format: 6 digits from the email, e.g. `482193`.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Different email", width="stretch"):
            st.session_state["auth_step"] = "email"
            st.rerun()
    with c2:
        if st.button("Verify & sign in", type="primary", width="stretch"):
            try:
                info = verify_otp(
                    st.session_state.get("auth_pending_email", ""),
                    code,
                )
                _store_session(info)
                st.rerun()
            except AuthError as e:
                st.error(e.message)

    if st.button("Resend code"):
        try:
            request_otp(st.session_state.get("auth_pending_email", ""))
            st.success("A new code was sent.")
        except AuthError as e:
            st.error(e.message)
    return None


def _render_session_bar(user: dict) -> None:
    expires = user.get("expires_at")
    if isinstance(expires, datetime):
        exp_txt = expires.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:
        exp_txt = str(expires or "")
    left, right = st.columns([4, 1])
    with left:
        st.caption(f"Signed in as **{user['email']}** · session ends {exp_txt}")
    with right:
        if st.button("Log out", key="auth_logout"):
            token = st.session_state.get("auth_token")
            if token:
                try:
                    logout(token)
                except Exception:
                    pass
            for k in list(st.session_state.keys()):
                if k.startswith("auth_") or k in ("auth_token",):
                    st.session_state.pop(k, None)
            st.rerun()

    if user.get("role") == "admin":
        with st.expander("Auth audit (admin)", expanded=False):
            try:
                events = list_auth_events(limit=50)
                st.dataframe(events, hide_index=True, width="stretch")
            except Exception as e:
                st.warning(str(e))
