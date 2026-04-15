from __future__ import annotations

import argparse
import csv
from pathlib import Path


DEFAULT_INPUT = "data_processed/horizons_orbital_data.csv"
DEFAULT_OUTPUT = "data_processed/objects_api_not_ok.csv"


def value_is_ok(value: str) -> bool:
    return value.strip().lower() == "ok"


def filter_object_names(
    input_file: Path,
    output_file: Path,
    object_column: str = "object",
    status_column: str = "api_success",
) -> tuple[int, int]:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    seen_names: set[str] = set()
    written = 0
    scanned = 0

    with input_file.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"Input file has no header: {input_file}")

        missing_columns = [
            col for col in (object_column, status_column) if col not in reader.fieldnames
        ]
        if missing_columns:
            missing_text = ", ".join(missing_columns)
            raise ValueError(
                f"Input file is missing required columns: {missing_text}. "
                f"Found columns: {', '.join(reader.fieldnames)}"
            )

        with output_file.open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerow([object_column])

            for row in reader:
                scanned += 1
                name = (row.get(object_column) or "").strip()
                status = (row.get(status_column) or "").strip()

                if not name:
                    continue
                if value_is_ok(status):
                    continue
                if name in seen_names:
                    continue

                seen_names.add(name)
                writer.writerow([name])
                written += 1

    return scanned, written


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description=(
            "Write object names to a CSV when their api_success value is not 'ok'."
        )
    )
    parser.add_argument(
        "--input",
        default=str(project_root / DEFAULT_INPUT),
        help="Path to source orbital data CSV.",
    )
    parser.add_argument(
        "--output",
        default=str(project_root / DEFAULT_OUTPUT),
        help="Path to output CSV file.",
    )
    parser.add_argument(
        "--object-column",
        default="object",
        help="Column name containing object names.",
    )
    parser.add_argument(
        "--status-column",
        default="api_success",
        help="Column name containing API status values.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    if not input_path.exists():
        raise SystemExit(f"Input CSV not found: {input_path}")

    scanned, written = filter_object_names(
        input_path,
        output_path,
        object_column=args.object_column,
        status_column=args.status_column,
    )

    print(f"Scanned rows: {scanned}")
    print(f"Objects written: {written}")
    print(f"Saved file: {output_path}")


if __name__ == "__main__":
    main()
