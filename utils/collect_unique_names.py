from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable


PRIMARY_NAME_HEADERS = ("name", "object")
FALLBACK_NAME_HINTS = ("name",)


def normalize_header(value: str) -> str:
    return value.strip().lower()


def find_name_column(header: list[str]) -> int | None:
    normalized = [normalize_header(cell) for cell in header]

    for preferred in PRIMARY_NAME_HEADERS:
        if preferred in normalized:
            return normalized.index(preferred)

    for index, col in enumerate(normalized):
        if any(hint in col for hint in FALLBACK_NAME_HINTS):
            return index

    return None


def normalize_name(raw_name: str) -> str:
    name = raw_name.strip()

    wrapped_match = re.fullmatch(r"\(([^()]*)\)", name)
    if wrapped_match:
        name = wrapped_match.group(1).strip()

    name = re.sub(r"\s+\([^()]*\)$", "", name).strip()
    return name


def extract_names_from_csv(file_path: Path) -> list[str]:
    names: list[str] = []

    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    if not rows:
        return names

    header_index = None
    name_index = None

    for idx, row in enumerate(rows):
        if not row:
            continue

        candidate_index = find_name_column(row)
        if candidate_index is not None:
            header_index = idx
            name_index = candidate_index
            break

    if header_index is None or name_index is None:
        return names

    for row in rows[header_index + 1 :]:
        if name_index >= len(row):
            continue

        value = normalize_name(row[name_index])
        if value:
            names.append(value)

    return names


def iter_csv_files(data_dir: Path, output_file: Path) -> Iterable[Path]:
    for csv_path in sorted(data_dir.glob("*.csv")):
        if csv_path.resolve() == output_file.resolve():
            continue
        yield csv_path


def write_unique_names(output_file: Path, unique_names: list[str]) -> None:
    with output_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name"])
        for name in unique_names:
            writer.writerow([name])


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    processed_dir = project_root / "data_processed"

    parser = argparse.ArgumentParser(
        description="Collect unique names from all CSV files in a data folder."
    )
    parser.add_argument(
        "--data-dir",
        default=str(project_root / "data"),
        help="Directory containing input CSV files.",
    )
    parser.add_argument(
        "--output",
        default="unique_names.csv",
        help="Output CSV filename (saved in data_processed by default) or full path.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists() or not data_dir.is_dir():
        raise SystemExit(f"Data directory not found: {data_dir}")

    output_file = Path(args.output)
    if not output_file.is_absolute():
        output_file = processed_dir / output_file

    output_file.parent.mkdir(parents=True, exist_ok=True)

    all_names: set[str] = set()
    processed_files = 0

    for csv_file in iter_csv_files(data_dir, output_file):
        processed_files += 1
        for name in extract_names_from_csv(csv_file):
            all_names.add(name)

    unique_names = sorted(all_names)
    write_unique_names(output_file, unique_names)

    print(f"Processed {processed_files} CSV files.")
    print(f"Found {len(unique_names)} unique names.")
    print(f"Saved output to: {output_file}")


if __name__ == "__main__":
    main()
