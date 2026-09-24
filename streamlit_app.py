"""Streamlit front end for the RTL Word Collator.

Run locally:   streamlit run streamlit_app.py
"""

from html import escape
from pathlib import Path

import streamlit as st

import word_collator as wc

QR_FILE = Path(__file__).with_name("rtl-word-collator-qr.png")

st.set_page_config(page_title="RTL Word Collator", page_icon="📝", layout="centered")

st.markdown(
    """
    <style>
    .word-list { list-style: none; padding: 0; margin: 0.5rem 0 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.45rem 0.8rem; }
    @media (max-width: 640px) { .word-list { grid-template-columns: minmax(0, 1fr); } }
    .word-list li {
        display: flex; align-items: center; gap: 0.9rem;
        padding: 0.7rem 1rem;
        border: 1px solid rgba(128, 128, 128, 0.25); border-radius: 0.6rem;
        font-size: 1.15rem;
    }
    .word-list .word { overflow-wrap: anywhere; }
    .word-list .idx { opacity: 0.5; min-width: 2rem; font-variant-numeric: tabular-nums; }
    .word-list .word { flex: 1; font-weight: 600; }
    .word-list .count {
        min-width: 2.6rem; text-align: center; font-weight: 700;
        padding: 0.15rem 0.7rem; border-radius: 999px;
        background: rgba(217, 95, 63, 0.14); color: #D95F3F;
    }
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

    items = "".join(
        f'<li><span class="idx">{i}.</span>'
        f'<span class="word">{escape(word)}</span>'
        f'<span class="count">{count}</span></li>'
        for i, (word, count) in enumerate(results, 1)
    )
    st.markdown(f'<ul class="word-list">{items}</ul>', unsafe_allow_html=True)


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
