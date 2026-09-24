# RTL-Word-Collator

Streamlit app that collates words from the "RTL word collator" Google Form responses.

- **Word Collator** tab: **Update** pulls and collates responses (asks you to confirm near-identical spellings), **Reset** clears the response rows.
- **QR Code** tab: shows `rtl-word-collator-qr.png`.

## Configuration

Set these as Streamlit secrets (or environment variables). See `.streamlit/secrets.toml.example`.

| Name | Value |
| --- | --- |
| `SPREADSHEET_ID` | ID of the responses spreadsheet |
| `GOOGLE_TOKEN_JSON` | contents of `token.json` (must include `refresh_token`) |
| `GOOGLE_CREDENTIALS_JSON` | contents of `credentials.json` |

`token.json` is created by running `python word_collator.py check` once locally (browser sign-in).

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (`token.json`, `credentials.json` and `.streamlit/secrets.toml` are git-ignored).
2. On share.streamlit.io, create an app with main file `streamlit_app.py`.
3. Paste the contents of your local `.streamlit/secrets.toml` into **Advanced settings → Secrets**.
