"""Streamlit front end for the RTL Word Collator.

Run locally:   streamlit run streamlit_app.py
"""

from html import escape
from pathlib import Path

import streamlit as st

import word_collator as wc

QR_FILE = Path(__file__).with_name("rtl-word-collator-qr.png")

st.set_page_config(page_title="RTL Word Collator", page_icon="📙", layout="centered")

st.markdown(
    """
    <style>
    [data-testid="stCode"] pre { padding: 1.2rem 1.5rem !important; }
    [data-testid="stCode"] pre, [data-testid="stCode"] code {
        font-size: 1.6rem !important; line-height: 1.7 !important; font-weight: 600;
    }
    /* keep the copy button visible, not just on hover */
    [data-testid="stCode"] div:has([data-testid="stElementToolbarButton"]),
    [data-testid="stCode"] [data-testid="stElementToolbarButton"] {
        opacity: 1 !important; visibility: visible !important;
    }
    [data-testid="stMetric"] { text-align: center; }
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
        justify-content: center; justify-items: center;
    }
    [data-testid="stMetricLabel"] { grid-template-columns: auto; }
    [data-testid="stMetricLabel"] p { font-size: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


class PendingDecision(Exception):
    def __init__(self, pair):
        self.pair = pair


def init_state():
    st.session_state.setdefault("rows", None)
    st.session_state.setdefault("decisions", {})
    st.session_state.setdefault("flash", None)


@st.cache_resource(show_spinner=False)
def get_service():
    return wc.get_service()


def decide_from_state(pair):
    decisions = st.session_state.decisions
    if pair["key"] not in decisions:
        raise PendingDecision(pair)
    return decisions[pair["key"]]


# ------------------------------------------------------------ actions --


def on_update():
    st.session_state.flash = None
    try:
        st.session_state.rows = wc.fetch_rows(get_service())
        st.session_state.decisions = {}
    except wc.ConfigError as e:
        st.session_state.flash = ("error", f"Configuration problem: {e}")
    except Exception as e:
        st.session_state.flash = ("error", f"Could not fetch responses: {e}")


@st.dialog("Reset responses?")
def reset_dialog():
    st.write(
        "This clears all response rows from the Sheet. The form itself and "
        "its questions stay intact, and it keeps accepting new submissions."
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        cancel = st.button("Cancel", width="content")
        confirm = st.button("Yes, clear responses", type="primary", width="content")
    if cancel:
        st.rerun()
    if confirm:
        try:
            wc.clear_rows(get_service())
            st.session_state.rows = None
            st.session_state.decisions = {}
            st.session_state.flash = ("success", "Cleared. Ready for the next round.")
        except Exception as e:
            st.session_state.flash = ("error", f"Could not clear responses: {e}")
        st.rerun()


def on_decide(key, same):
    st.session_state.decisions[key] = same


# ---------------------------------------------------------------- UI --


def render_results(results):
    total = sum(count for _, count in results)
    c1, c2 = st.columns(2)
    c1.metric("Unique words", len(results))
    c2.metric("Total mentions", total)

    text = "\n".join(f"{word} ({count})" for word, count in results)
    st.code(text, language=None, wrap_lines=True)


def render_pending(pair):
    st.subheader("Are these the same word?")
    st.caption(f"{len(st.session_state.decisions)} similar spelling(s) reviewed so far")
    with st.container(border=True):
        a, b = st.columns(2)
        a.markdown(f"### {escape(pair['label_a'])}\n{pair['count_a']} mention(s)")
        b.markdown(f"### {escape(pair['label_b'])}\n{pair['count_b']} mention(s)")
        if pair["suggestion"]:
            st.info(f'Spellcheck says **"{pair["suggestion"]}"** is the correct spelling.')
        yes, no = st.columns(2)
        yes.button("Same word — merge", key=f"same-{pair['key']}", type="primary",
                   width="stretch", on_click=on_decide, args=(pair["key"], True))
        no.button("Different words", key=f"diff-{pair['key']}",
                  width="stretch", on_click=on_decide, args=(pair["key"], False))


def word_collator_tab():
    with st.container(horizontal=True, horizontal_alignment="right"):
        st.button("Update", type="primary", width="content", on_click=on_update)
        if st.button("Reset", width="content"):
            st.session_state.flash = None
            reset_dialog()

    if st.session_state.flash:
        kind, msg = st.session_state.flash
        getattr(st, kind)(msg)

    rows = st.session_state.rows
    if rows is None:
        if not st.session_state.flash:
            st.caption("Press **Update** to pull the latest responses.")
        return
    if len(rows) <= 1:
        st.info("No responses yet.")
        return

    try:
        results = wc.collate(rows, decide_from_state)
    except PendingDecision as p:
        render_pending(p.pair)
        return
    render_results(results)


def qr_tab():
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        if QR_FILE.exists():
            st.image(str(QR_FILE), caption="Scan this QR code to enter your responses", width="stretch")
        else:
            st.error("rtl-word-collator-qr.png not found.")


init_state()
st.title("RTL Word Collator")
collator, qr = st.tabs(["Word Collator", "QR Code"])
with collator:
    word_collator_tab()
with qr:
    qr_tab()
