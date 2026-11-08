# Comet Spotting

A web app that shows when a comet can be seen from any place on Earth, and a 3D view of 3,930 comets and asteroids around the Sun. Orbital data comes from NASA JPL Horizons. Positions are computed with Skyfield.

**Live demo:** https://comet-spotting.onrender.com
(It runs on Render's free plan, so the first load after a period of inactivity can take up to a minute.)

## Features

- **Visibility Planner:** pick a location on the map or search for a city, then choose a comet and a date. The app computes the times on that date when the comet is at least 8° above the horizon and the Sun is at least 6° below it, and tracks the comet live in an interactive night-sky view.
- **Solar System 3D:** shows all objects at a chosen date. Filters: name, famous comets, Earth-impact watch (based on MOID), distance from Earth, and visibility within a date range. Statistics are shown for the filtered set.

## Tech stack

- **Backend:** Python, Skyfield, pandas, NumPy. The API runs on the standard-library `http.server`, without a web framework, to keep dependencies minimal.
- **Frontend:** vanilla JavaScript with Leaflet, Three.js and VirtualSky, loaded from CDNs. No build step.
- **Deployment:** Render ([render.yaml](render.yaml)).

## Run locally

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python backend/server.py
```

Open http://127.0.0.1:8000. The server provides both the API and the frontend. To use a different port, set the `PORT` environment variable. Stop the server with `Ctrl+C`.

## Project structure

```
backend/          API server (server.py) and orbit/visibility calculations (calculations.py)
frontend/         static UI (index.html, app.js, styles.css, config.js)
data/             source object lists (COBS comet exports, near-Earth comet and asteroid lists)
data_processed/   dataset used by the app (horizons_orbital_data_enriched.csv)
utils/            data pipeline scripts
de421.bsp         JPL DE421 planetary ephemeris
```

## Data pipeline

The dataset was built once with the scripts in `utils/` (install their dependency with `pip install -r utils/requirements.txt`):

1. `collect_unique_names.py`: collects object names from the CSV files in `data/` into `data_processed/unique_names.csv`. A further list of about 2,500 asteroids (not included in the repo) was added to this file.
2. `fetch_orbital_data_from_unique_names.py`: downloads orbital elements and physical parameters for each name from the JPL Horizons API.
3. `filter_objects_with_api_not_ok.py`, `merge_fixed_into_horizons.py`: list the failed lookups and merge the corrected rows back in.
4. `enrich_horizons_metadata.py`: adds the designation class, popular names and an Earth-impact watch flag, producing `horizons_orbital_data_enriched.csv`.

## Data sources

- [COBS Comet Observation Database](https://cobs.si): comet lists in `data/cobs_*.csv` (renamed, contents unchanged), licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- [CNEOS Close Approach Data](https://cneos.jpl.nasa.gov/ca/) and the NASA near-Earth object API: near-Earth asteroid and comet lists.
- [NASA JPL Horizons](https://ssd.jpl.nasa.gov/horizons/): orbital elements and physical parameters.
- JPL DE421 ephemeris, loaded through [Skyfield](https://rhodesmill.org/skyfield/).
- Map tiles and city search: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (Nominatim).

## License

The code is released under the MIT License, see [LICENSE](LICENSE). The COBS data files are under CC BY-NC-SA 4.0.
