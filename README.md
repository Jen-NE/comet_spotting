# Comet Spotting

## Local Setup

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

## Run Locally

Start the backend server located:

backend/server.py

Open:
http://127.0.0.1:8000

The backend serves both the API and the frontend UI, so there is no separate frontend build step.

## Frontend Libraries

The frontend is a static app and loads its UI libraries directly from CDNs:

- Leaflet for the Earth map
- Three.js for the 3D solar system view
- VirtualSky for the night sky view
- StuQuery as a VirtualSky dependency

Because of that, there is no `npm install` or separate frontend build command for local development.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for the full text.

## Stop

Press `Ctrl+C` in the terminal running the server.

## 