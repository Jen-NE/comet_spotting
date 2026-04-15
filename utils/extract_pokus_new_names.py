from __future__ import annotations

import csv
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
UNIQUE_NAMES_CSV = ROOT / "data_processed" / "unique_names.csv"
POKUS_TXT = ROOT / "pokus.txt"
OUTPUT_CSV = ROOT / "data_processed" / "pokus_new_names.csv"

OBJECT_ROW_PATTERN = re.compile(r"^\([0-9]+\)\s+.+")


def normalize(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def load_existing_unique_names(path: Path) -> set[str]:
    existing: set[str] = set()
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = str(row.get("name", "")).strip()
            if raw:
                existing.add(normalize(raw))
    return existing


def extract_pokus_names(path: Path) -> list[str]:
    # Input rows are tab-separated. We only need text before first tab.
    names: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            first_col = line.split("\t", 1)[0].strip()
            if not first_col:
                continue
            if normalize(first_col) == "object":
                continue
            if not OBJECT_ROW_PATTERN.match(first_col):
                continue
            names.append(first_col)
    return names


def main() -> int:
    existing = load_existing_unique_names(UNIQUE_NAMES_CSV)
    extracted = extract_pokus_names(POKUS_TXT)

    filtered: list[str] = []
    seen_new: set[str] = set()
    for name in extracted:
        key = normalize(name)
        if key in existing or key in seen_new:
            continue
        seen_new.add(key)
        filtered.append(name)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name"])
        for name in filtered:
            writer.writerow([name])

    print(f"Extracted rows from pokus: {len(extracted)}")
    print(f"New names not in unique_names.csv: {len(filtered)}")
    print(f"Wrote: {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
