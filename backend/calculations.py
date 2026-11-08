from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from skyfield.api import Loader, load, wgs84
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2
from skyfield.data import mpc
from skyfield.toposlib import GeographicPosition


_ROOT_DIR = Path(__file__).resolve().parent.parent

_TS = load.timescale()
# JPL DE421 ephemeris, stored at the repository root.
_EPH = Loader(str(_ROOT_DIR))("de421.bsp")
_SUN = _EPH["sun"]
_EARTH = _EPH["earth"]

MIN_VISIBLE_ALTITUDE_DEGREES = 8.0
MAX_SUN_ALTITUDE_DEGREES = -6.0


def _default_orbital_data_path() -> Path:
	base = Path(__file__).resolve().parent.parent / "data_processed"
	candidates = [
		base / "horizons_orbital_data_enriched_combined.csv",
		base / "horizons_orbital_data_enriched.csv",
		base / "horizons_orbital_data_enriched2.csv",
		base / "horizons_orbital_data.csv",
	]

	for candidate in candidates:
		if candidate.exists():
			return candidate

	# Preserve prior behavior with a clear path if nothing exists.
	return candidates[-1]


def _ensure_utc(value: datetime) -> datetime:
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value.astimezone(timezone.utc)


def _tp_jd_to_ymd(tp_jd: float) -> tuple[int, int, float]:
	t = _TS.tt_jd(tp_jd)
	year, month, day, hour, minute, second = t.tt_calendar()
	day_with_fraction = day + ((hour * 3600.0) + (minute * 60.0) + second) / 86400.0
	return int(year), int(month), float(day_with_fraction)


def _build_mpc_row_from_horizons(row: pd.Series) -> pd.Series:
	perihelion_year, perihelion_month, perihelion_day = _tp_jd_to_ymd(float(row["tp"]))
	designation = str(row.get("object", row.get("designation", "")))

	return pd.Series(
		{
			"designation": designation,
			"eccentricity": float(row["eccent"]),
			"perihelion_distance_au": float(row["peri_dist"]),
			"inclination_degrees": float(row["inclin"]),
			"longitude_of_ascending_node_degrees": float(row["long_ascend"]),
			"argument_of_perihelion_degrees": float(row["perihel"]),
			"perihelion_year": perihelion_year,
			"perihelion_month": perihelion_month,
			"perihelion_day": perihelion_day,
		}
	)


def calculate_position_from_elements_skyfield(
	*,
	designation: str,
	tp_jd: float,
	eccentricity: float,
	inclination_deg: float,
	arg_perihelion_deg: float,
	lon_ascending_node_deg: float,
	perihelion_distance_au: float,
	at_time: datetime,
) -> dict[str, float | str]:
	"""Calculate object position at a given time using Skyfield + MPC comet orbit model."""
	mapping = pd.Series(
		{
			"designation": designation,
			"tp": tp_jd,
			"eccent": eccentricity,
			"inclin": inclination_deg,
			"perihel": arg_perihelion_deg,
			"long_ascend": lon_ascending_node_deg,
			"peri_dist": perihelion_distance_au,
		}
	)
	comet_row = _build_mpc_row_from_horizons(mapping)

	t = _TS.from_datetime(_ensure_utc(at_time))
	comet = _SUN + mpc.comet_orbit(comet_row, _TS, GM_SUN_Pitjeva_2005_km3_s2)
	barycentric = comet.at(t)
	bx_au, by_au, bz_au = barycentric.position.au
	sx_au, sy_au, sz_au = _SUN.at(t).position.au
	x_au = float(bx_au - sx_au)
	y_au = float(by_au - sy_au)
	z_au = float(bz_au - sz_au)

	geocentric = (comet - _EARTH).at(t)
	ra, dec, distance = geocentric.radec()

	result: dict[str, float | str] = {
		"object": designation,
		"julian_day_tt": float(t.tt),
		"x_au": x_au,
		"y_au": y_au,
		"z_au": z_au,
		"ra_hours": float(ra.hours),
		"dec_degrees": float(dec.degrees),
		"distance_au": float(distance.au),
	}
	return result


def calculate_object_position(
	object_name: str,
	at_time: datetime,
	orbital_data_path: str | Path | None = None,
) -> dict[str, float | str]:
	"""Find an object in horizons_orbital_data.csv and calculate its Skyfield position."""
	if orbital_data_path is None:
		orbital_data_path = _default_orbital_data_path()

	df = pd.read_csv(orbital_data_path)
	if "object" not in df.columns:
		raise ValueError("Orbital CSV must contain an 'object' column.")

	mask = df["object"].astype(str).str.strip().str.lower() == object_name.strip().lower()
	if not mask.any():
		raise ValueError(f"Object not found in orbital data: {object_name}")

	row = df.loc[mask].iloc[0]
	return calculate_position_from_elements_skyfield(
		designation=str(row["object"]),
		tp_jd=float(row["tp"]),
		eccentricity=float(row["eccent"]),
		inclination_deg=float(row["inclin"]),
		arg_perihelion_deg=float(row["perihel"]),
		lon_ascending_node_deg=float(row["long_ascend"]),
		perihelion_distance_au=float(row["peri_dist"]),
		at_time=at_time,
	)


def create_observer_location(
	latitude_degrees: float,
	longitude_degrees: float,
	elevation_m: float = 0.0,
) -> GeographicPosition:
	"""Create observer location using modern Skyfield wgs84 API."""
	return wgs84.latlon(latitude_degrees, longitude_degrees, elevation_m=elevation_m)


def is_above_horizon(
	object_name: str,
	observer_location: GeographicPosition,
	at_time: datetime,
	orbital_data_path: str | Path | None = None,
	min_visible_altitude_degrees: float = MIN_VISIBLE_ALTITUDE_DEGREES,
	max_sun_altitude_degrees: float = MAX_SUN_ALTITUDE_DEGREES,
) -> bool:
	"""Determine if a named object is above the horizon at the given time and location."""
	if orbital_data_path is None:
		orbital_data_path = _default_orbital_data_path()

	df = pd.read_csv(orbital_data_path)
	mask = df["object"].astype(str).str.strip().str.lower() == object_name.strip().lower()
	if not mask.any():
		raise ValueError(f"Object not found in orbital data: {object_name}")

	row = df.loc[mask].iloc[0]
	return is_above_horizon_from_elements(
		designation=str(row["object"]),
		tp_jd=float(row["tp"]),
		eccentricity=float(row["eccent"]),
		inclination_deg=float(row["inclin"]),
		arg_perihelion_deg=float(row["perihel"]),
		lon_ascending_node_deg=float(row["long_ascend"]),
		perihelion_distance_au=float(row["peri_dist"]),
		observer_location=observer_location,
		at_time=at_time,
		min_visible_altitude_degrees=min_visible_altitude_degrees,
		max_sun_altitude_degrees=max_sun_altitude_degrees,
	)


def is_above_horizon_from_elements(
	*,
	designation: str,
	tp_jd: float,
	eccentricity: float,
	inclination_deg: float,
	arg_perihelion_deg: float,
	lon_ascending_node_deg: float,
	perihelion_distance_au: float,
	observer_location: GeographicPosition,
	at_time: datetime,
	min_visible_altitude_degrees: float = MIN_VISIBLE_ALTITUDE_DEGREES,
	max_sun_altitude_degrees: float = MAX_SUN_ALTITUDE_DEGREES,
) -> bool:
	"""Determine if an object described by orbital elements is above horizon."""
	mapping = pd.Series(
		{
			"designation": designation,
			"tp": tp_jd,
			"eccent": eccentricity,
			"inclin": inclination_deg,
			"perihel": arg_perihelion_deg,
			"long_ascend": lon_ascending_node_deg,
			"peri_dist": perihelion_distance_au,
		}
	)
	comet_row = _build_mpc_row_from_horizons(mapping)
	comet = _SUN + mpc.comet_orbit(comet_row, _TS, GM_SUN_Pitjeva_2005_km3_s2)

	t = _TS.from_datetime(_ensure_utc(at_time))
	observer = _EARTH + observer_location
	astrometric = observer.at(t).observe(comet)
	alt, _, _ = astrometric.apparent().altaz()

	# Treat visibility as practical observation conditions:
	# object should be clearly above horizon and sky should be dark enough.
	sun_alt, _, _ = observer.at(t).observe(_SUN).apparent().altaz()
	return (alt.degrees >= float(min_visible_altitude_degrees)) and (
		sun_alt.degrees <= float(max_sun_altitude_degrees)
	)


def visibility_diagnostics_from_elements(
	*,
	designation: str,
	tp_jd: float,
	eccentricity: float,
	inclination_deg: float,
	arg_perihelion_deg: float,
	lon_ascending_node_deg: float,
	perihelion_distance_au: float,
	observer_location: GeographicPosition,
	at_time: datetime,
) -> dict[str, float]:
	"""Return object and sun altitude for debugging visibility thresholds."""
	mapping = pd.Series(
		{
			"designation": designation,
			"tp": tp_jd,
			"eccent": eccentricity,
			"inclin": inclination_deg,
			"perihel": arg_perihelion_deg,
			"long_ascend": lon_ascending_node_deg,
			"peri_dist": perihelion_distance_au,
		}
	)
	comet_row = _build_mpc_row_from_horizons(mapping)
	comet = _SUN + mpc.comet_orbit(comet_row, _TS, GM_SUN_Pitjeva_2005_km3_s2)

	t = _TS.from_datetime(_ensure_utc(at_time))
	observer = _EARTH + observer_location
	obj_alt, _, _ = observer.at(t).observe(comet).apparent().altaz()
	sun_alt, _, _ = observer.at(t).observe(_SUN).apparent().altaz()
	return {
		"object_altitude_degrees": float(obj_alt.degrees),
		"sun_altitude_degrees": float(sun_alt.degrees),
	}


def visibility_diagnostics(
	object_name: str,
	observer_location: GeographicPosition,
	at_time: datetime,
	orbital_data_path: str | Path | None = None,
) -> dict[str, float]:
	"""Return object and sun altitude by object name for debugging/visibility modes."""
	if orbital_data_path is None:
		orbital_data_path = _default_orbital_data_path()

	df = pd.read_csv(orbital_data_path)
	mask = df["object"].astype(str).str.strip().str.lower() == object_name.strip().lower()
	if not mask.any():
		raise ValueError(f"Object not found in orbital data: {object_name}")

	row = df.loc[mask].iloc[0]
	return visibility_diagnostics_from_elements(
		designation=str(row["object"]),
		tp_jd=float(row["tp"]),
		eccentricity=float(row["eccent"]),
		inclination_deg=float(row["inclin"]),
		arg_perihelion_deg=float(row["perihel"]),
		lon_ascending_node_deg=float(row["long_ascend"]),
		perihelion_distance_au=float(row["peri_dist"]),
		observer_location=observer_location,
		at_time=at_time,
	)