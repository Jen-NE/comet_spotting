from __future__ import annotations

import errno
from datetime import datetime, time, timedelta, timezone
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import math
import threading
import uuid
from typing import Any, cast

import numpy as np
import pandas as pd
from skyfield.api import load
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2
from skyfield.data import mpc
from skyfield.toposlib import GeographicPosition

from calculations import (
    MAX_SUN_ALTITUDE_DEGREES,
    MIN_VISIBLE_ALTITUDE_DEGREES,
    calculate_position_from_elements_skyfield,
    create_observer_location,
    visibility_diagnostics_from_elements,
    is_above_horizon_from_elements,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

_TS = load.timescale()
_EPH = load("de421.bsp")
_SUN = _EPH["sun"]

_VISIBILITY_JOBS: dict[str, dict[str, object]] = {}
_VISIBILITY_JOBS_LOCK = threading.Lock()

MIN_SOLAR_ELONGATION_DEGREES = 15.0
MAX_HELIOCENTRIC_DISTANCE_AU = 4.0
MAX_GEOCENTRIC_DISTANCE_AU = 3.0

PLANET_BODIES = [
    ("Mercury", "mercury", "#b0b0b0", 0.26),
    ("Venus", "venus", "#d9c38a", 0.36),
    ("Earth", "earth", "#3b82f6", 0.38),
    ("Mars", "mars", "#b64828", 0.30),
    ("Jupiter", "jupiter barycenter", "#d2b48c", 0.74),
    ("Saturn", "saturn barycenter", "#e5d0a9", 0.66),
    ("Uranus", "uranus barycenter", "#9ad1d4", 0.54),
    ("Neptune", "neptune barycenter", "#5c8ed6", 0.52),
]


def parse_date(value: str | None) -> datetime:
    if value:
        return _parse_iso_datetime_utc(value)
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def build_night_window(base_date: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(base_date.date(), time(18, 0), tzinfo=timezone.utc)
    end = start + timedelta(hours=12)
    return start, end


def comet_night_path(
    comet_name: str,
    latitude: float,
    longitude: float,
    date_text: str | None,
    interval_hours: int,
) -> dict[str, object]:
    if interval_hours <= 0:
        raise ValueError("interval_hours must be positive")

    night_date = parse_date(date_text)
    start, end = build_night_window(night_date)
    observer = create_observer_location(latitude, longitude)

    df = pd.read_csv(default_orbital_csv_path())
    mask = df["object"].astype(str).str.strip().str.lower() == comet_name.strip().lower()
    if not mask.any():
        raise ValueError(f"Object not found in orbital data: {comet_name}")
    row = df.loc[mask].iloc[0]

    designation = str(row["object"])
    tp_jd = float(row["tp"])
    eccent = float(row["eccent"])
    inclin = float(row["inclin"])
    perihel = float(row["perihel"])
    long_ascend = float(row["long_ascend"])
    peri_dist = float(row["peri_dist"])

    samples: list[dict[str, object]] = []
    current = start
    while current <= end:
        position = calculate_position_from_elements_skyfield(
            designation=designation,
            tp_jd=tp_jd,
            eccentricity=eccent,
            inclination_deg=inclin,
            arg_perihelion_deg=perihel,
            lon_ascending_node_deg=long_ascend,
            perihelion_distance_au=peri_dist,
            at_time=current,
        )
        diagnostics = visibility_diagnostics_from_elements(
            designation=designation,
            tp_jd=tp_jd,
            eccentricity=eccent,
            inclination_deg=inclin,
            arg_perihelion_deg=perihel,
            lon_ascending_node_deg=long_ascend,
            perihelion_distance_au=peri_dist,
            observer_location=observer,
            at_time=current,
        )
        visible_practical = bool(
            is_above_horizon_from_elements(
                designation=designation,
                tp_jd=tp_jd,
                eccentricity=eccent,
                inclination_deg=inclin,
                arg_perihelion_deg=perihel,
                lon_ascending_node_deg=long_ascend,
                perihelion_distance_au=peri_dist,
                observer_location=observer,
                at_time=current,
            )
        )

        # Match map behavior: visible if geometrically above horizon.
        visible = bool(float(diagnostics["object_altitude_degrees"]) >= 0.0)
        samples.append(
            {
                "iso_time": current.isoformat(),
                "visible": visible,
                "visible_practical": visible_practical,
                "ra_hours": position["ra_hours"],
                "dec_degrees": position["dec_degrees"],
                "distance_au": position["distance_au"],
                "object_altitude_degrees": diagnostics["object_altitude_degrees"],
                "sun_altitude_degrees": diagnostics["sun_altitude_degrees"],
            }
        )
        current += timedelta(hours=interval_hours)

    visible_any = any(bool(s["visible"]) for s in samples)
    message = (
        f"{comet_name} is visible during this night window."
        if visible_any
        else f"{comet_name} is not visible during this night window."
    )

    return {
        "comet": designation,
        "latitude": latitude,
        "longitude": longitude,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "interval_hours": interval_hours,
        "visible": visible_any,
        "message": message,
        "samples": samples,
    }


def comet_position_at_time(
    comet_name: str,
    latitude: float,
    longitude: float,
    datetime_text: str | None,
) -> dict[str, object]:
    at_time = parse_datetime(datetime_text)
    observer = create_observer_location(latitude, longitude)

    df = pd.read_csv(default_orbital_csv_path())
    mask = df["object"].astype(str).str.strip().str.lower() == comet_name.strip().lower()
    if not mask.any():
        raise ValueError(f"Object not found in orbital data: {comet_name}")
    row = df.loc[mask].iloc[0]

    designation = str(row["object"])
    tp_jd = float(row["tp"])
    eccent = float(row["eccent"])
    inclin = float(row["inclin"])
    perihel = float(row["perihel"])
    long_ascend = float(row["long_ascend"])
    peri_dist = float(row["peri_dist"])

    position = calculate_position_from_elements_skyfield(
        designation=designation,
        tp_jd=tp_jd,
        eccentricity=eccent,
        inclination_deg=inclin,
        arg_perihelion_deg=perihel,
        lon_ascending_node_deg=long_ascend,
        perihelion_distance_au=peri_dist,
        at_time=at_time,
    )
    diagnostics = visibility_diagnostics_from_elements(
        designation=designation,
        tp_jd=tp_jd,
        eccentricity=eccent,
        inclination_deg=inclin,
        arg_perihelion_deg=perihel,
        lon_ascending_node_deg=long_ascend,
        perihelion_distance_au=peri_dist,
        observer_location=observer,
        at_time=at_time,
    )
    visible_practical = bool(
        is_above_horizon_from_elements(
            designation=designation,
            tp_jd=tp_jd,
            eccentricity=eccent,
            inclination_deg=inclin,
            arg_perihelion_deg=perihel,
            lon_ascending_node_deg=long_ascend,
            perihelion_distance_au=peri_dist,
            observer_location=observer,
            at_time=at_time,
        )
    )

    visible = bool(float(diagnostics["object_altitude_degrees"]) >= 0.0)
    return {
        "comet": designation,
        "iso_time": at_time.isoformat(),
        "latitude": latitude,
        "longitude": longitude,
        "visible": visible,
        "visible_practical": visible_practical,
        "ra_hours": position["ra_hours"],
        "dec_degrees": position["dec_degrees"],
        "distance_au": position["distance_au"],
        "object_altitude_degrees": diagnostics["object_altitude_degrees"],
        "sun_altitude_degrees": diagnostics["sun_altitude_degrees"],
    }


def parse_datetime(value: str | None) -> datetime:
    if value:
        return _parse_iso_datetime_utc(value)
    return datetime.now(timezone.utc)


def default_orbital_csv_path() -> Path:
    base = ROOT_DIR / "data_processed"
    candidates = [
        base / "horizons_orbital_data_enriched_combined.csv",
        base / "horizons_orbital_data_enriched.csv",
        base / "horizons_orbital_data_enriched2.csv",
        base / "horizons_orbital_data.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def parse_date_only(value: str) -> datetime:
    return _parse_iso_datetime_utc(value)


def _parse_iso_datetime_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _optional_float(value: object) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _merge_visibility_windows(
    samples: list[dict[str, object]],
    *,
    key: str,
    step_minutes: int,
) -> list[dict[str, object]]:
    if not samples:
        return []

    windows: list[dict[str, object]] = []
    active_start: datetime | None = None
    last_true_time: datetime | None = None

    for sample in samples:
        t = datetime.fromisoformat(str(sample["iso_time"]))
        is_visible = bool(sample.get(key, False))

        if is_visible:
            if active_start is None:
                active_start = t
            last_true_time = t
            continue

        if active_start is not None and last_true_time is not None:
            end = last_true_time + timedelta(minutes=step_minutes)
            windows.append(
                {
                    "start": active_start.isoformat(),
                    "end": end.isoformat(),
                    "duration_minutes": int((end - active_start).total_seconds() // 60),
                }
            )
            active_start = None
            last_true_time = None

    if active_start is not None and last_true_time is not None:
        end = last_true_time + timedelta(minutes=step_minutes)
        windows.append(
            {
                "start": active_start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": int((end - active_start).total_seconds() // 60),
            }
        )

    return windows


def _daily_visibility_windows_from_row(
    row: pd.Series,
    observer: GeographicPosition,
    day_start: datetime,
    interval_minutes: int,
) -> dict[str, list[dict[str, object]]]:
    designation = str(row["object"])
    tp_jd = float(row["tp"])
    eccent = float(row["eccent"])
    inclin = float(row["inclin"])
    perihel = float(row["perihel"])
    long_ascend = float(row["long_ascend"])
    peri_dist = float(row["peri_dist"])

    t_tp = _TS.tt_jd(tp_jd)
    year, month, day, hour, minute, second = t_tp.tt_calendar()
    perihelion_day = day + ((hour * 3600.0) + (minute * 60.0) + second) / 86400.0
    comet_row = pd.Series(
        {
            "designation": designation,
            "eccentricity": eccent,
            "perihelion_distance_au": peri_dist,
            "inclination_degrees": inclin,
            "longitude_of_ascending_node_degrees": long_ascend,
            "argument_of_perihelion_degrees": perihel,
            "perihelion_year": int(year),
            "perihelion_month": int(month),
            "perihelion_day": float(perihelion_day),
        }
    )

    comet = _SUN + mpc.comet_orbit(comet_row, _TS, GM_SUN_Pitjeva_2005_km3_s2)
    earth_target = cast(Any, _EPH["earth"])
    observer_target = earth_target + observer

    sample_minutes = np.arange(0, 24 * 60, interval_minutes, dtype=int)
    sample_datetimes = [
        day_start + timedelta(minutes=int(minute_offset))
        for minute_offset in sample_minutes
    ]
    t = _TS.from_datetimes(sample_datetimes)

    obj_apparent = observer_target.at(t).observe(comet).apparent()
    obj_alt, _, _ = obj_apparent.altaz()
    sun_apparent = observer_target.at(t).observe(_SUN).apparent()
    sun_alt, _, _ = sun_apparent.altaz()

    obj_alt_deg = np.asarray(obj_alt.degrees, dtype=float)
    sun_alt_deg = np.asarray(sun_alt.degrees, dtype=float)
    visible_geometric = obj_alt_deg >= 0.0
    visible_practical = (obj_alt_deg >= float(MIN_VISIBLE_ALTITUDE_DEGREES)) & (
        sun_alt_deg <= float(MAX_SUN_ALTITUDE_DEGREES)
    )

    samples: list[dict[str, object]] = []
    for idx, sample_time in enumerate(sample_datetimes):
        samples.append(
            {
                "iso_time": sample_time.isoformat(),
                "visible": bool(visible_geometric[idx]),
                "visible_practical": bool(visible_practical[idx]),
                "object_altitude_degrees": float(obj_alt_deg[idx]),
                "sun_altitude_degrees": float(sun_alt_deg[idx]),
            }
        )

    geometric_windows = _merge_visibility_windows(samples, key="visible", step_minutes=interval_minutes)
    practical_windows = _merge_visibility_windows(samples, key="visible_practical", step_minutes=interval_minutes)
    return {
        "geometric_windows": geometric_windows,
        "practical_windows": practical_windows,
    }


def _passes_quick_visibility_prefilters(
    row: pd.Series,
    *,
    observer_latitude: float,
    midpoint: datetime,
) -> bool:
    """Fast geocentric prefilters to skip obviously unobservable objects."""
    try:
        designation = str(row["object"])
        tp_jd = float(row["tp"])
        eccent = float(row["eccent"])
        inclin = float(row["inclin"])
        perihel = float(row["perihel"])
        long_ascend = float(row["long_ascend"])
        peri_dist = float(row["peri_dist"])

        t_tp = _TS.tt_jd(tp_jd)
        year, month, day, hour, minute, second = t_tp.tt_calendar()
        perihelion_day = day + ((hour * 3600.0) + (minute * 60.0) + second) / 86400.0
        comet_row = pd.Series(
            {
                "designation": designation,
                "eccentricity": eccent,
                "perihelion_distance_au": peri_dist,
                "inclination_degrees": inclin,
                "longitude_of_ascending_node_degrees": long_ascend,
                "argument_of_perihelion_degrees": perihel,
                "perihelion_year": int(year),
                "perihelion_month": int(month),
                "perihelion_day": float(perihelion_day),
            }
        )

        comet = _SUN + mpc.comet_orbit(comet_row, _TS, GM_SUN_Pitjeva_2005_km3_s2)
        t_mid = _TS.from_datetime(midpoint)

        # 1) Declination visibility bounds for latitude.
        _, dec, delta = (comet - _EPH["earth"]).at(t_mid).radec()
        dec_deg = float(dec.degrees)
        lat_deg = float(observer_latitude)
        if dec_deg < (lat_deg - 90.0) or dec_deg > (lat_deg + 90.0):
            return False

        # 2) Solar elongation at midpoint.
        earth_target = cast(Any, _EPH["earth"])
        earth_at = earth_target.at(t_mid)
        sun_app = earth_at.observe(_SUN).apparent()
        comet_app = earth_at.observe(comet).apparent()
        elong_deg = float(sun_app.separation_from(comet_app).degrees)
        if elong_deg < MIN_SOLAR_ELONGATION_DEGREES:
            return False

        # 3) Very faint/far prefilter.
        heliocentric_r_au = float(comet.at(t_mid).distance().au)
        geocentric_delta_au = float(delta.au)
        if heliocentric_r_au > MAX_HELIOCENTRIC_DISTANCE_AU and geocentric_delta_au > MAX_GEOCENTRIC_DISTANCE_AU:
            return False

        return True
    except Exception:
        # If quick filter fails unexpectedly, do not drop the object.
        return True


def comet_visibility_window(
    comet_name: str,
    latitude: float,
    longitude: float,
    date_text: str | None,
    interval_minutes: int,
) -> dict[str, object]:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")

    day = parse_date(date_text)
    day_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    observer = create_observer_location(latitude, longitude)

    df = pd.read_csv(default_orbital_csv_path())
    mask = df["object"].astype(str).str.strip().str.lower() == comet_name.strip().lower()
    if not mask.any():
        raise ValueError(f"Object not found in orbital data: {comet_name}")
    row = df.loc[mask].iloc[0]
    designation = str(row["object"])

    windows = _daily_visibility_windows_from_row(row, observer, day_start, interval_minutes)
    geometric_windows = windows["geometric_windows"]
    practical_windows = windows["practical_windows"]

    return {
        "comet": designation,
        "date": day_start.date().isoformat(),
        "latitude": latitude,
        "longitude": longitude,
        "interval_minutes": interval_minutes,
        "geometric_windows": geometric_windows,
        "practical_windows": practical_windows,
        "sample_count": int((24 * 60) / interval_minutes),
    }


def _build_day_list(start_date: datetime, end_date: datetime) -> list[datetime]:
    days: list[datetime] = []
    current = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=timezone.utc)
    end = datetime(end_date.year, end_date.month, end_date.day, 0, 0, tzinfo=timezone.utc)
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _set_visibility_job(job_id: str, **updates: object) -> None:
    with _VISIBILITY_JOBS_LOCK:
        job = _VISIBILITY_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)


def _run_visibility_batch_job(
    *,
    job_id: str,
    object_names: list[str],
    latitude: float,
    longitude: float,
    start_date_text: str,
    end_date_text: str,
    interval_minutes: int,
) -> None:
    try:
        start_date = parse_date_only(start_date_text)
        end_date = parse_date_only(end_date_text)
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        days = _build_day_list(start_date, end_date)
        observer = create_observer_location(latitude, longitude)
        midpoint = start_date + ((end_date - start_date) / 2)
        midpoint = midpoint.replace(tzinfo=timezone.utc)

        df = pd.read_csv(default_orbital_csv_path())
        row_by_name: dict[str, pd.Series] = {}
        for _, row in df.iterrows():
            key = str(row.get("object", "")).strip().lower()
            if key and key not in row_by_name:
                row_by_name[key] = row

        total = len(object_names) * len(days)
        processed = 0
        visible_objects: list[str] = []

        _set_visibility_job(
            job_id,
            state="running",
            total=total,
            processed=0,
            message="Processing visibility windows...",
        )

        for original_name in object_names:
            key = str(original_name).strip().lower()
            row = row_by_name.get(key)
            if row is None:
                processed += len(days)
                _set_visibility_job(job_id, processed=processed)
                continue

            if not _passes_quick_visibility_prefilters(
                row,
                observer_latitude=latitude,
                midpoint=midpoint,
            ):
                processed += len(days)
                _set_visibility_job(job_id, processed=processed)
                continue

            kept = False
            for day_idx, day_start in enumerate(days):
                windows = _daily_visibility_windows_from_row(row, observer, day_start, interval_minutes)
                processed += 1

                if windows["practical_windows"]:
                    visible_objects.append(str(row["object"]))
                    kept = True
                    remaining_for_object = len(days) - (day_idx + 1)
                    processed += remaining_for_object
                    break

                _set_visibility_job(job_id, processed=processed)

            if kept:
                _set_visibility_job(job_id, processed=processed)

        _set_visibility_job(
            job_id,
            state="completed",
            processed=processed,
            total=total,
            visible_objects=visible_objects,
            message=f"Done. {len(visible_objects)} of {len(object_names)} objects have visibility windows.",
        )
    except Exception as exc:
        _set_visibility_job(job_id, state="failed", error=str(exc), message=f"Failed: {exc}")


def start_visibility_batch_job(
    *,
    object_names: list[str],
    latitude: float,
    longitude: float,
    start_date_text: str,
    end_date_text: str,
    interval_minutes: int,
) -> dict[str, object]:
    cleaned_names = [str(v).strip() for v in object_names if str(v).strip()]
    if not cleaned_names:
        raise ValueError("object_names must contain at least one name")
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")

    job_id = uuid.uuid4().hex
    with _VISIBILITY_JOBS_LOCK:
        _VISIBILITY_JOBS[job_id] = {
            "job_id": job_id,
            "state": "queued",
            "processed": 0,
            "total": 0,
            "visible_objects": [],
            "message": "Queued",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    worker = threading.Thread(
        target=_run_visibility_batch_job,
        kwargs={
            "job_id": job_id,
            "object_names": cleaned_names,
            "latitude": latitude,
            "longitude": longitude,
            "start_date_text": start_date_text,
            "end_date_text": end_date_text,
            "interval_minutes": interval_minutes,
        },
        daemon=True,
    )
    worker.start()

    return {
        "job_id": job_id,
        "state": "queued",
        "processed": 0,
        "total": 0,
        "message": "Queued",
    }


def visibility_batch_job_status(job_id: str) -> dict[str, object]:
    with _VISIBILITY_JOBS_LOCK:
        job = _VISIBILITY_JOBS.get(job_id)
        if job is None:
            raise ValueError("Unknown job_id")
        return dict(job)


def build_night_samples(start_date: datetime, end_date: datetime, interval_hours: int) -> list[datetime]:
    if interval_hours <= 0:
        raise ValueError("interval_hours must be positive")

    samples: list[datetime] = []
    start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, tzinfo=timezone.utc)

    t = start_dt
    while t <= end_dt:
        samples.append(t)
        t += timedelta(hours=interval_hours)

    return samples


def visible_objects_in_nights(
    object_names: list[str],
    latitude: float,
    longitude: float,
    start_date_text: str,
    end_date_text: str,
    interval_hours: int,
) -> dict[str, object]:
    if not object_names:
        return {"visible_objects": [], "checked_count": 0, "visible_count": 0}

    start_date = parse_date_only(start_date_text)
    end_date = parse_date_only(end_date_text)
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    observer = create_observer_location(latitude, longitude)
    samples = build_night_samples(start_date, end_date, interval_hours)

    df = pd.read_csv(default_orbital_csv_path())
    row_by_name: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        key = str(row.get("object", "")).strip().lower()
        if key and key not in row_by_name:
            row_by_name[key] = row

    visible_objects: list[str] = []
    for original_name in object_names:
        key = str(original_name).strip().lower()
        row = row_by_name.get(key)
        if row is None:
            continue

        is_visible = False
        for sample_time in samples:
            try:
                diagnostics = visibility_diagnostics_from_elements(
                    designation=str(row["object"]),
                    tp_jd=float(row["tp"]),
                    eccentricity=float(row["eccent"]),
                    inclination_deg=float(row["inclin"]),
                    arg_perihelion_deg=float(row["perihel"]),
                    lon_ascending_node_deg=float(row["long_ascend"]),
                    perihelion_distance_au=float(row["peri_dist"]),
                    observer_location=observer,
                    at_time=sample_time,
                )
                # Keep 3D visibility filter consistent with planner/map behavior.
                is_visible = float(diagnostics["object_altitude_degrees"]) >= 0.0
            except Exception:
                is_visible = False

            if is_visible:
                visible_objects.append(str(row["object"]))
                break

    return {
        "visible_objects": visible_objects,
        "checked_count": len(object_names),
        "visible_count": len(visible_objects),
        "start_date": start_date_text,
        "end_date": end_date_text,
        "interval_hours": interval_hours,
        "visibility_mode": "geometric_horizon",
    }


def solar_system_snapshot(
    iso_datetime: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, object]:
    at_time = parse_datetime(iso_datetime)
    t = _TS.from_datetime(at_time)
    csv_path = default_orbital_csv_path()
    df = pd.read_csv(csv_path)

    if limit is not None and limit <= 0:
        raise ValueError("limit must be a positive integer")
    if offset < 0:
        raise ValueError("offset must be zero or a positive integer")

    required_cols = ["object", "tp", "eccent", "inclin", "perihel", "long_ascend", "peri_dist"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing column in orbital dataset: {col}")

    total_rows = len(df)
    if limit is None:
        limited_df = df.iloc[offset:]
    else:
        limited_df = df.iloc[offset : offset + limit]

    objects: list[dict[str, object]] = []
    skipped = 0

    def as_bool(value: object) -> bool:
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "y"}

    def scene_coord(value_au: float) -> float:
        return math.asinh(value_au) * 12.0

    planets: list[dict[str, object]] = []
    for planet_name, eph_key, color, marker_size in PLANET_BODIES:
        try:
            planet_target = cast(Any, _EPH[eph_key])
            sun_target = cast(Any, _SUN)
            p_xyz = planet_target.at(t).position.au
            s_xyz = sun_target.at(t).position.au
            px = float(p_xyz[0] - s_xyz[0])
            py = float(p_xyz[1] - s_xyz[1])
            pz = float(p_xyz[2] - s_xyz[2])
        except Exception:
            continue

        planets.append(
            {
                "name": planet_name,
                "x_au": px,
                "y_au": py,
                "z_au": pz,
                "scene_x": scene_coord(px),
                "scene_y": scene_coord(py),
                "scene_z": scene_coord(pz),
                "color": color,
                "size": marker_size,
            }
        )

    for _, row in limited_df.iterrows():
        name = str(row.get("object", "")).strip()
        if not name:
            skipped += 1
            continue

        try:
            position = calculate_position_from_elements_skyfield(
                designation=name,
                tp_jd=float(row["tp"]),
                eccentricity=float(row["eccent"]),
                inclination_deg=float(row["inclin"]),
                arg_perihelion_deg=float(row["perihel"]),
                lon_ascending_node_deg=float(row["long_ascend"]),
                perihelion_distance_au=float(row["peri_dist"]),
                at_time=at_time,
            )
        except Exception:
            skipped += 1
            continue

        x = float(position["x_au"])
        y = float(position["y_au"])
        z = float(position["z_au"])
        radius = math.sqrt((x * x) + (y * y) + (z * z))

        objects.append(
            {
                "object": name,
                "x_au": x,
                "y_au": y,
                "z_au": z,
                "scene_x": scene_coord(x),
                "scene_y": scene_coord(y),
                "scene_z": scene_coord(z),
                "distance_au": float(position["distance_au"]),
                "radius_au": radius,
                "epoch_jd": float(row["epoch"]),
                "tp_jd": float(row["tp"]),
                "eccent": float(row["eccent"]),
                "inclin": float(row["inclin"]),
                "perihel": float(row["perihel"]),
                "long_ascend": float(row["long_ascend"]),
                "peri_dist": float(row["peri_dist"]),
                "designation_class": str(row.get("designation_class", "")) or "U",
                "designation_class_description": str(
                    row.get("designation_class_description", "Unknown designation class")
                ),
                "is_asteroid_designation": as_bool(row.get("is_asteroid_designation", False)),
                "is_famous": as_bool(row.get("is_famous", False)),
                "popular_name": str(row.get("popular_name", "")),
                "fame_note": str(row.get("fame_note", "")),
                "alternative_name": str(row.get("alternative_name", "")),
                "earth_impact_watch": as_bool(row.get("earth_impact_watch", False)),
                "earth_impact_risk_band": str(row.get("earth_impact_risk_band", "unknown")),
                "earth_impact_note": str(row.get("earth_impact_note", "")),
                "moid_au": _optional_float(row.get("moid")),
                "absolute_mag_h": _optional_float(row.get("h")),
                "slope_g": _optional_float(row.get("g")),
                "color_bv": _optional_float(row.get("b_v")),
                "albedo": _optional_float(row.get("albedo")),
                "radius_km": _optional_float(row.get("rad")),
                "rotation_period_hours": _optional_float(row.get("rotper")),
                "gm": _optional_float(row.get("gm")),
                "spectral_type": str(row.get("styp", "")).strip(),
                "color": "#ff2b2b",
                "size": 0.14,
            }
        )

    returned_count = len(limited_df)
    next_offset = offset + returned_count
    has_more = next_offset < total_rows

    return {
        "iso_time": at_time.isoformat(),
        "requested_limit": limit,
        "requested_offset": offset,
        "dataset_total": total_rows,
        "object_count": len(objects),
        "skipped_count": skipped,
        "returned_count": returned_count,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
        "planets": planets,
        "objects": objects,
    }


def object_stats_lookup(object_name: str) -> dict[str, object]:
    normalized = object_name.strip()
    if not normalized:
        raise ValueError("object must be provided")

    df = pd.read_csv(default_orbital_csv_path())
    mask = df["object"].astype(str).str.strip().str.lower() == normalized.lower()
    if not mask.any():
        raise ValueError(f"Object not found in dataset: {object_name}")

    row = df.loc[mask].iloc[0]

    def as_bool(value: object) -> bool:
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "y"}

    alternative_name_raw = str(row.get("alternative_name", "")).strip()
    alternative_name = (
        alternative_name_raw
        if alternative_name_raw.lower() not in {"", "nan", "none", "null"}
        else ""
    )

    return {
        "object": str(row.get("object", "")),
        "display_name": alternative_name or str(row.get("object", "")),
        "alternative_name": alternative_name,
        "designation_class": str(row.get("designation_class", "")) or "U",
        "designation_class_description": str(
            row.get("designation_class_description", "Unknown designation class")
        ),
        "is_asteroid_designation": as_bool(row.get("is_asteroid_designation", False)),
        "is_famous": as_bool(row.get("is_famous", False)),
        "popular_name": str(row.get("popular_name", "")),
        "fame_note": str(row.get("fame_note", "")),
        "earth_impact_watch": as_bool(row.get("earth_impact_watch", False)),
        "earth_impact_risk_band": str(row.get("earth_impact_risk_band", "unknown")),
        "earth_impact_note": str(row.get("earth_impact_note", "")),
        "epoch_jd": float(row.get("epoch", 0.0)),
        "tp_jd": float(row.get("tp", 0.0)),
        "eccent": float(row.get("eccent", 0.0)),
        "inclin": float(row.get("inclin", 0.0)),
        "perihel": float(row.get("perihel", 0.0)),
        "long_ascend": float(row.get("long_ascend", 0.0)),
        "peri_dist": float(row.get("peri_dist", 0.0)),
        "moid_au": _optional_float(row.get("moid")),
        "absolute_mag_h": _optional_float(row.get("h")),
        "slope_g": _optional_float(row.get("g")),
        "color_bv": _optional_float(row.get("b_v")),
        "albedo": _optional_float(row.get("albedo")),
        "radius_km": _optional_float(row.get("rad")),
        "rotation_period_hours": _optional_float(row.get("rotper")),
        "gm": _optional_float(row.get("gm")),
        "spectral_type": str(row.get("styp", "")).strip(),
    }


class Handler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as exc:
            if exc.errno not in {errno.EPIPE, errno.ECONNRESET}:
                raise

    def _serve_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as exc:
            if exc.errno not in {errno.EPIPE, errno.ECONNRESET}:
                raise

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/api/visibility-batch/start":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise ValueError("Request body is required.")

                payload_raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(payload_raw)
                if not isinstance(payload, dict):
                    raise ValueError("Body must be a JSON object.")

                names = payload.get("object_names", [])
                if not isinstance(names, list):
                    raise ValueError("object_names must be a list.")

                start_date = str(payload.get("start_date", "")).strip()
                end_date = str(payload.get("end_date", "")).strip()
                if not start_date or not end_date:
                    raise ValueError("start_date and end_date are required.")

                lat_raw = payload.get("lat")
                lon_raw = payload.get("lon")
                if lat_raw is None or lon_raw is None:
                    raise ValueError("lat and lon are required.")

                lat = float(lat_raw)
                lon = float(lon_raw)
                interval_minutes = int(payload.get("interval_minutes", 15))

                result = start_visibility_batch_job(
                    object_names=[str(v).strip() for v in names if str(v).strip()],
                    latitude=lat,
                    longitude=lon,
                    start_date_text=start_date,
                    end_date_text=end_date,
                    interval_minutes=interval_minutes,
                )
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/visibility-filter":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise ValueError("Request body is required.")

                payload_raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(payload_raw)
                if not isinstance(payload, dict):
                    raise ValueError("Body must be a JSON object.")

                names = payload.get("object_names", [])
                if not isinstance(names, list):
                    raise ValueError("object_names must be a list.")

                start_date = str(payload.get("start_date", "")).strip()
                end_date = str(payload.get("end_date", "")).strip()
                if not start_date or not end_date:
                    raise ValueError("start_date and end_date are required.")

                lat_raw = payload.get("lat")
                lon_raw = payload.get("lon")
                if lat_raw is None or lon_raw is None:
                    raise ValueError("lat and lon are required.")

                lat = float(lat_raw)
                lon = float(lon_raw)
                interval_hours = int(payload.get("interval_hours", 2))

                result = visible_objects_in_nights(
                    object_names=[str(v).strip() for v in names if str(v).strip()],
                    latitude=lat,
                    longitude=lon,
                    start_date_text=start_date,
                    end_date_text=end_date,
                    interval_hours=interval_hours,
                )
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/api/visibility-batch/status":
            try:
                query = parse_qs(parsed.query)
                job_id = (query.get("job_id", [""])[0] or "").strip()
                if not job_id:
                    raise ValueError("Missing query parameter: job_id")

                payload = visibility_batch_job_status(job_id)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/comet-position":
            try:
                query = parse_qs(parsed.query)
                comet = (query.get("comet", [""])[0] or "").strip()
                if not comet:
                    raise ValueError("Missing query parameter: comet")

                lat = float(query.get("lat", [""])[0])
                lon = float(query.get("lon", [""])[0])
                dt_text = (query.get("datetime", [""])[0] or "").strip() or None

                payload = comet_position_at_time(comet, lat, lon, dt_text)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/comet-night":
            try:
                query = parse_qs(parsed.query)
                comet = (query.get("comet", [""])[0] or "").strip()
                if not comet:
                    raise ValueError("Missing query parameter: comet")

                lat = float(query.get("lat", [""])[0])
                lon = float(query.get("lon", [""])[0])
                interval = int(query.get("interval_hours", ["2"])[0])
                date_text = (query.get("date", [""])[0] or "").strip() or None

                payload = comet_night_path(comet, lat, lon, date_text, interval)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/comet-visibility-window":
            try:
                query = parse_qs(parsed.query)
                comet = (query.get("comet", [""])[0] or "").strip()
                if not comet:
                    raise ValueError("Missing query parameter: comet")

                lat = float(query.get("lat", [""])[0])
                lon = float(query.get("lon", [""])[0])
                date_text = (query.get("date", [""])[0] or "").strip() or None
                interval_minutes_text = (query.get("interval_minutes", ["15"])[0] or "15").strip()
                interval_minutes = int(interval_minutes_text)

                payload = comet_visibility_window(comet, lat, lon, date_text, interval_minutes)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/object-stats":
            try:
                query = parse_qs(parsed.query)
                object_name = (query.get("object", [""])[0] or "").strip()
                if not object_name:
                    raise ValueError("Missing query parameter: object")

                payload = object_stats_lookup(object_name)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path == "/api/solar-system":
            try:
                query = parse_qs(parsed.query)
                iso_dt = (query.get("datetime", [""])[0] or "").strip() or None
                limit_text = (query.get("limit", [""])[0] or "").strip()
                offset_text = (query.get("offset", ["0"])[0] or "0").strip()
                limit_value = int(limit_text) if limit_text else None
                offset_value = int(offset_text) if offset_text else 0
                payload = solar_system_snapshot(iso_dt, limit_value, offset_value)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - simple server error path
                self._send_json({"error": f"Unexpected server error: {exc}"}, status=500)
            return

        if parsed.path in ("/", "/index.html"):
            self._serve_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/app.js":
            self._serve_file(FRONTEND_DIR / "app.js", "application/javascript; charset=utf-8")
            return

        if parsed.path == "/styles.css":
            self._serve_file(FRONTEND_DIR / "styles.css", "text/css; charset=utf-8")
            return

        if parsed.path == "/config.js":
            self._serve_file(FRONTEND_DIR / "config.js", "application/javascript; charset=utf-8")
            return

        self.send_response(404)
        self.end_headers()


def run() -> None:
    import os

    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Server running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
