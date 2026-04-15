from __future__ import annotations

import argparse
import csv
from pathlib import Path


def normalize(value: str) -> str:
    return (value or "").strip()


def load_fixed_rows(fixed_csv: Path, key_column: str) -> dict[str, dict[str, str]]:
    with fixed_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or key_column not in reader.fieldnames:
            raise ValueError(f"Missing required key column '{key_column}' in {fixed_csv}")

        out: dict[str, dict[str, str]] = {}
        for row in reader:
            key = normalize(row.get(key_column, ""))
            if not key:
                continue
            out[key] = row
        return out


def merge_rows(
    horizons_csv: Path,
    fixed_map: dict[str, dict[str, str]],
    key_column: str,
    status_column: str,
) -> tuple[int, int, int, list[dict[str, str]], list[str]]:
    with horizons_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"No header found in {horizons_csv}")
        if key_column not in reader.fieldnames or status_column not in reader.fieldnames:
            raise ValueError(
                f"Missing required columns in {horizons_csv}. "
                f"Need: {key_column}, {status_column}"
            )

        rows = list(reader)
        headers = list(reader.fieldnames)

    scanned = 0
    replaced = 0
    missing_match = 0

    for i, row in enumerate(rows):
        scanned += 1
        status = normalize(row.get(status_column, "")).lower()
        if status == "ok":
            continue

        key = normalize(row.get(key_column, ""))
        if not key:
            continue

        fixed_row = fixed_map.get(key)
        if fixed_row is None:
            missing_match += 1
            continue

        # Keep only horizons header columns to preserve file shape.
        merged_row = {h: normalize(fixed_row.get(h, row.get(h, ""))) for h in headers}
        rows[i] = merged_row
        replaced += 1

    return scanned, replaced, missing_match, rows, headers


def write_rows(csv_path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Replace non-ok rows in horizons CSV using rows from fixed CSV matched by object."
    )
    parser.add_argument(
        "--horizons",
        default=str(project_root / "data_processed/horizons_orbital_data.csv"),
        help="Path to horizons orbital CSV.",
    )
    parser.add_argument(
        "--fixed",
        default=str(project_root / "fixed_objects.csv"),
        help="Path to fixed objects CSV.",
    )
    parser.add_argument(
        "--key-column",
        default="object",
        help="Column used to match rows between files.",
    )
    parser.add_argument(
        "--status-column",
        default="api_success",
        help="Status column in horizons CSV.",
    )
    args = parser.parse_args()

    horizons_path = Path(args.horizons).resolve()
    fixed_path = Path(args.fixed).resolve()

    if not horizons_path.exists():
        raise SystemExit(f"Horizons file not found: {horizons_path}")
    if not fixed_path.exists():
        raise SystemExit(f"Fixed file not found: {fixed_path}")

    fixed_map = load_fixed_rows(fixed_path, args.key_column)
    scanned, replaced, missing_match, merged_rows, headers = merge_rows(
        horizons_path,
        fixed_map,
        args.key_column,
        args.status_column,
    )
    write_rows(horizons_path, merged_rows, headers)

    print(f"Scanned horizons rows: {scanned}")
    print(f"Rows replaced from fixed file: {replaced}")
    print(f"Non-ok rows without a fixed match: {missing_match}")
    print(f"Updated file: {horizons_path}")


if __name__ == "__main__":
    main()
