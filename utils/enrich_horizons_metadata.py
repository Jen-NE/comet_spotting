from __future__ import annotations

import argparse
import csv
from pathlib import Path


CLASS_DESCRIPTIONS = {
    "P": "Periodic comet (orbital period under ~200 years)",
    "C": "Non-periodic comet (long-period or first observed passage)",
    "D": "Disappeared or lost comet",
    "A": "Object initially reported as comet, later identified as asteroid",
    "X": "Comet with uncertain or poorly determined orbit",
    "I": "Interstellar object",
    "U": "Unknown designation class",
}


# Keys can be exact names or prefixes (for fragmented objects).
FAMOUS_OBJECTS: list[tuple[str, dict[str, str | bool]]] = [
    (
        "1P/Halley",
        {
            "popular_name": "Halley's Comet",
            "is_famous": True,
            "fame_note": "Most famous periodic comet visible from Earth every ~76 years.",
        },
    ),
    (
        "2P/Encke",
        {
            "popular_name": "Encke's Comet",
            "is_famous": True,
            "fame_note": "Shortest-period major comet (~3.3 years).",
        },
    ),
    (
        "55P/Tempel-Tuttle",
        {
            "popular_name": "Tempel-Tuttle",
            "is_famous": True,
            "fame_note": "Parent body of the Leonid meteor shower.",
        },
    ),
    (
        "67P/Churyumov-Gerasimenko",
        {
            "popular_name": "67P / Rosetta comet",
            "is_famous": True,
            "fame_note": "Visited by ESA Rosetta mission and Philae lander.",
        },
    ),
    (
        "73P/Schwassmann-Wachmann 3",
        {
            "popular_name": "Comet Schwassmann-Wachmann 3",
            "is_famous": True,
            "fame_note": "Known for fragmentation into many observed pieces.",
        },
    ),
    (
        "C/1995 O1",
        {
            "popular_name": "Hale-Bopp",
            "is_famous": True,
            "fame_note": "Exceptionally bright long-period comet of the 1990s.",
        },
    ),
    (
        "C/1996 B2",
        {
            "popular_name": "Hyakutake",
            "is_famous": True,
            "fame_note": "Very bright comet with a long apparent tail in 1996.",
        },
    ),
    (
        "C/2020 F3",
        {
            "popular_name": "NEOWISE",
            "is_famous": True,
            "fame_note": "Naked-eye comet widely observed in 2020.",
        },
    ),
    (
        "3D/Biela",
        {
            "popular_name": "Biela's Comet",
            "is_famous": True,
            "fame_note": "Historic split comet linked to strong meteor storms.",
        },
    ),
    (
        "D/1993 F2",
        {
            "popular_name": "Shoemaker-Levy 9 fragments",
            "is_famous": True,
            "fame_note": "Fragments that impacted Jupiter in 1994.",
        },
    ),
    (
        "A/2017 U1",
        {
            "popular_name": "Oumuamua",
            "is_famous": True,
            "fame_note": "First detected interstellar object; asteroid-like designation.",
        },
    ),
]


def designation_class(name: str) -> str:
    for ch in name:
        if ch.isalpha():
            up = ch.upper()
            if up in CLASS_DESCRIPTIONS:
                return up
            return "U"
    return "U"


def match_famous_record(name: str) -> dict[str, str | bool] | None:
    for key, record in FAMOUS_OBJECTS:
        if name == key or name.startswith(f"{key}-"):
            return record
    return None


def risk_band_from_moid(moid_au: float | None) -> tuple[bool, str, str]:
    if moid_au is None:
        return (False, "unknown", "No MOID value available in dataset.")

    if moid_au <= 0.01:
        return (
            True,
            "very_high_watch",
            "MOID <= 0.01 AU. Very close Earth-approach geometry; monitor as high-interest object.",
        )
    if moid_au <= 0.05:
        return (
            True,
            "watch",
            "MOID <= 0.05 AU. Close Earth-approach geometry; useful impact-watch filter.",
        )
    return (
        False,
        "low",
        "MOID > 0.05 AU. Not in close-approach watch bucket from this orbital indicator.",
    )


def enrich_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []

    for row in rows:
        name = str(row.get("object", "")).strip()
        kind = designation_class(name)
        desc = CLASS_DESCRIPTIONS[kind]

        famous = match_famous_record(name)
        is_famous = bool(famous and famous.get("is_famous"))
        popular_name = str(famous.get("popular_name", "")) if famous else ""
        fame_note = str(famous.get("fame_note", "")) if famous else ""

        moid_raw = row.get("moid", "")
        try:
            moid_au = float(moid_raw) if str(moid_raw).strip() else None
        except ValueError:
            moid_au = None

        watch, risk_band, risk_note = risk_band_from_moid(moid_au)

        out = dict(row)
        out["designation_class"] = kind
        out["designation_class_description"] = desc
        out["is_asteroid_designation"] = "true" if kind == "A" else "false"
        out["is_famous"] = "true" if is_famous else "false"
        out["popular_name"] = popular_name
        out["fame_note"] = fame_note
        out["earth_impact_watch"] = "true" if watch else "false"
        out["earth_impact_risk_band"] = risk_band
        out["earth_impact_note"] = risk_note
        enriched.append(out)

    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich horizons orbital CSV with metadata filters.")
    parser.add_argument(
        "--input",
        default="data_processed/horizons_orbital_data.csv",
        help="Input horizons CSV path.",
    )
    parser.add_argument(
        "--output",
        default="data_processed/horizons_orbital_data_enriched.csv",
        help="Output enriched CSV path.",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    with in_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        if not rows:
            raise ValueError(f"Input CSV is empty: {in_path}")

    enriched = enrich_rows(rows)
    fieldnames = list(enriched[0].keys())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    famous_count = sum(1 for r in enriched if r.get("is_famous") == "true")
    watch_count = sum(1 for r in enriched if r.get("earth_impact_watch") == "true")

    print(f"Wrote {len(enriched)} rows to {out_path}")
    print(f"Famous flagged rows: {famous_count}")
    print(f"Earth-impact watch rows: {watch_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())