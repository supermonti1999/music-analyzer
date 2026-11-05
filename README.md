# Spotify Charts Explorer (Melotech case study)

Companion data explorer for the case answer. Streamlit + DuckDB over the processed chart tables (72 countries, Jan 2017 to Oct 2026), about 70 MB of data.

## Run locally
    pip install -r requirements.txt
    streamlit run app.py

Put an access code in `.streamlit/secrets.toml` (see `secrets.example.toml`); without the file the app opens without a code.

## Deploy on Streamlit Community Cloud (about 10 minutes)
1. Create a GitHub repository (private is fine) and push this folder: `git init`, `git add .`, `git commit -m "explorer"`, then push. `.streamlit/secrets.toml` is ignored by git on purpose.
2. Go to share.streamlit.io, sign in with GitHub, click "Create app", pick the repository, branch `main`, main file `app.py`.
3. Under "Advanced settings" choose Python 3.12 or 3.13 and paste into "Secrets":
       APP_PASSWORD = "your-code"
4. Deploy. The first build takes 2 to 4 minutes. The URL looks like `https://<name>.streamlit.app`.
5. Open the URL once yourself before sending it: a sleeping app takes about a minute to wake up.

Send the URL and the access code in the submission e-mail.

## Alternative: Hugging Face Space
Create a Space with the Streamlit SDK, upload the folder (drag and drop or `git push`), add `APP_PASSWORD` under Settings > Variables and secrets as a secret. Same app, same code.

## Data and attribution
Spotify Daily Top 200 from the Kaggle export "Spotify Charts Daily Updated" (gonzalopezgil, CC BY-SA 4.0); genre labels from Wikidata and Deezer; Spotify Premium prices from the official country pages; catalogue demand in the matrix from kworb.net. All derived numbers are our own calculation. The large daily table (249 MB) is not needed by the app and is not included.
