# Comet Spotting

Interactive comet tracking app with:
- Python backend API in backend/server.py
- Static frontend in frontend for map + sky + 3D view

## GitHub Pages Deployment

This repository is configured to deploy the frontend folder to GitHub Pages automatically using GitHub Actions.

After pushing to the main branch:
1. Open repository settings on GitHub.
2. Go to Pages.
3. Set Source to GitHub Actions.
4. Wait for the Deploy Frontend To GitHub Pages workflow to complete.

Your site URL will be:
https://<your-username>.github.io/<your-repo-name>/

## Backend URL For GitHub Pages

GitHub Pages hosts static files only. The API backend must run elsewhere.

Set your backend base URL in frontend/config.js:

window.COMET_API_BASE_URL = "https://your-backend-domain";

For local development, keep it empty:

window.COMET_API_BASE_URL = "";

## Local Run

Start backend:

/home/jen/Documents/comet_spotting/.venv/bin/python backend/server.py

Open:
http://127.0.0.1:8000
