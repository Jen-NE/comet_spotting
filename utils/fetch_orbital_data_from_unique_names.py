from __future__ import annotations

import argparse
import asyncio
import csv
import re
import urllib.parse
from pathlib import Path

import aiohttp


OUTPUT_COLUMNS = [
    "object",
    "alternative_name",
    "epoch",
    "tp",
    "eccent",
    "inclin",
    "perihel",
    "long_ascend",
    "peri_dist",
    "aphel_dist",
    "orbit_period",
    "moid",
    "ref",
    "gm",
    "rad",
    "rotper",
    "h",
    "g",
    "b_v",
    "albedo",
    "styp",
    "api_success",
]

API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
DESIGNATION_PATTERN = re.compile(r"DES\s*=\s*([^;\n\r]+);")
INDEX_LINE_PATTERN = re.compile(r"^\s*(\d+)\s+(-?\d+)\s+(\S+)\s+", re.MULTILINE)
SELECTION_PROMPT_PATTERN = re.compile(
    r"^\(\s*\d+\s+matches\.\s+To\s+SELECT,\s+enter\s+record\s+#\s+\(integer\)"
    r"(?:,\s*followed\s+by\s+semi-colon\.)?\s*\)$",
    re.IGNORECASE,
)
VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "EPOCH": re.compile(r"\bEPOCH\s*=\s*([^\s!]+)"),
    "EC": re.compile(r"\bEC\s*=\s*([^\s!]+)"),
    "IN": re.compile(r"\bIN\s*=\s*([^\s!]+)"),
    "W": re.compile(r"\bW\s*=\s*([^\s!]+)"),
    "OM": re.compile(r"\bOM\s*=\s*([^\s!]+)"),
    "QR": re.compile(r"\bQR\s*=\s*([^\s!]+)"),
    "ADIST": re.compile(r"\bADIST\s*=\s*([^\s!]+)"),
    "PER": re.compile(r"\bPER\s*=\s*([^\s!]+)"),
    "MOID": re.compile(r"\bMOID\s*=\s*([^\s!]+)"),
}
TP_PATTERN = re.compile(r"\bTP\s*=\s*([0-9]+(?:\.[0-9]+)?)")
REF_PATTERN = re.compile(r"soln ref\.\s*=\s*([^,\n\r]+)", flags=re.IGNORECASE)
ALT_NAME_PATTERN = re.compile(r"^\s*JPL/HORIZONS\s+\S+\s+\(([^)]+)\)", re.MULTILINE)

ASTEROID_PHYSICAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "gm": re.compile(r"\bGM\s*=\s*([^\s]+)"),
    "rad": re.compile(r"\bRAD\s*=\s*([^\s]+)"),
    "rotper": re.compile(r"\bROTPER\s*=\s*([^\s]+)"),
    "h": re.compile(r"\bH\s*=\s*([^\s]+)"),
    "g": re.compile(r"\bG\s*=\s*([^\s]+)"),
    "b_v": re.compile(r"\bB-V\s*=\s*([^\s]+)"),
    "albedo": re.compile(r"\bALBEDO\s*=\s*([^\s]+)"),
    "styp": re.compile(r"\bSTYP\s*=\s*([^\s]+)"),
}

PAREN_NUMBER_PATTERN = re.compile(r"^\((\d+)\)(?:\s+.*)?$")


def normalize_designation(value: str) -> str:
    return value.strip().upper()


def build_designation_candidates(requested_designation: str) -> set[str]:
    raw = normalize_designation(requested_designation)
    if not raw:
        return set()

    candidates = {raw}

    no_paren = raw.split("(", 1)[0].strip()
    if no_paren:
        candidates.add(no_paren)

    first_token = no_paren.split()[0] if no_paren else ""
    if first_token:
        candidates.add(first_token)

    if "/" in no_paren:
        left = no_paren.split("/", 1)[0].strip()
        if left:
            candidates.add(left)

    return {candidate for candidate in candidates if candidate}


def build_query_fallbacks(comet_id: str) -> list[str]:
    raw = comet_id.strip()
    if not raw:
        return []

    paren_number = PAREN_NUMBER_PATTERN.match(raw)
    if paren_number:
        return [paren_number.group(1)]

    variants: list[str] = [raw]
    no_paren = raw.split("(", 1)[0].strip()
    if no_paren and no_paren not in variants:
        variants.append(no_paren)

    if "/" in no_paren:
        left = no_paren.split("/", 1)[0].strip()
        if left and left not in variants:
            variants.append(left)

    first_token = no_paren.split()[0] if no_paren else ""
    if first_token and first_token not in variants:
        variants.append(first_token)

    return variants


def build_horizons_url(command_value: str, quote_command: bool = True) -> str:
    command_str = f"'{command_value}'" if quote_command else command_value
    encoded_command = urllib.parse.quote(command_str)

    return (
        f"{API_URL}"
        f"?format=json"
        f"&COMMAND={encoded_command}"
        f"&OBJ_DATA=YES"
        f"&MAKE_EPHEM=NO"
    )


async def get_horizons_result_text(
    session: aiohttp.ClientSession,
    command_value: str,
    timeout: int = 30,
    retries: int = 2,
    quote_command: bool = True,
) -> tuple[str, str]:
    url = build_horizons_url(command_value, quote_command=quote_command)

    for attempt in range(retries + 1):
        try:
            request_timeout = aiohttp.ClientTimeout(total=timeout)
            async with session.get(url, timeout=request_timeout) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
                if isinstance(data, dict):
                    result = data.get("result", "")
                    if result:
                        return result, "ok"
                    api_message = str(data.get("message", "")).strip()
                    if api_message:
                        return "", f"api_message: {api_message}"
                    return "", "could_not_parse"
                return "", "invalid_json_payload"
        except aiohttp.ClientResponseError as error:
            if attempt >= retries:
                if error.status == 429:
                    return "", "too_many_requests"
                return "", f"http_{error.status}"
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        except asyncio.TimeoutError:
            if attempt >= retries:
                return "", "timeout"
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        except aiohttp.ClientError:
            if attempt >= retries:
                return "", "connection_error"
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
        except ValueError:
            if attempt >= retries:
                return "", "invalid_json"
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    return "", "request_failed"


def is_index_search_response(result_text: str) -> bool:
    lines = [line.strip() for line in result_text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    closing_star_line_index = None
    for idx in range(len(lines) - 1, -1, -1):
        if set(lines[idx]) == {"*"}:
            closing_star_line_index = idx
            break

    if closing_star_line_index is None or closing_star_line_index == 0:
        return False

    line_before_closing = lines[closing_star_line_index - 1]
    return bool(SELECTION_PROMPT_PATTERN.match(line_before_closing))


def extract_requested_designation(result_text: str) -> str:
    match = DESIGNATION_PATTERN.search(result_text)
    return match.group(1).strip() if match else ""


def select_best_record_number(result_text: str) -> str:
    requested_desig = extract_requested_designation(result_text)
    designation_candidates = build_designation_candidates(requested_desig)
    best_record_number = ""
    best_epoch_year: int | None = None
    fallback_record_number = ""
    fallback_best_epoch_year: int | None = None

    for match in INDEX_LINE_PATTERN.finditer(result_text):
        record_number, epoch_year_text, match_desig = match.groups()
        normalized_match_desig = normalize_designation(match_desig)
        epoch_year = int(epoch_year_text)

        if fallback_best_epoch_year is None or epoch_year > fallback_best_epoch_year:
            fallback_best_epoch_year = epoch_year
            fallback_record_number = record_number

        if designation_candidates and normalized_match_desig not in designation_candidates:
            continue

        if best_epoch_year is None or epoch_year > best_epoch_year:
            best_epoch_year = epoch_year
            best_record_number = record_number

    if best_record_number:
        return best_record_number

    return fallback_record_number


def has_orbital_elements(result_text: str) -> bool:
    return bool(
        VALUE_PATTERNS["EPOCH"].search(result_text)
        and VALUE_PATTERNS["EC"].search(result_text)
        and VALUE_PATTERNS["IN"].search(result_text)
    )


async def resolve_index_response(
    session: aiohttp.ClientSession,
    result_text: str,
    timeout: int,
    retries: int,
) -> tuple[str, str]:
    if not is_index_search_response(result_text):
        return result_text, "ok"

    record_number = select_best_record_number(result_text)
    if not record_number:
        return result_text, "could_not_parse"

    second_text, second_status = await get_horizons_result_text(
        session,
        f"{record_number};",
        timeout=timeout,
        retries=retries,
        quote_command=False,
    )
    if second_status == "ok" and second_text:
        return second_text, "ok"

    return result_text, second_status


async def get_resolved_horizons_result_text(
    session: aiohttp.ClientSession,
    comet_id: str,
    timeout: int = 30,
    retries: int = 2,
) -> tuple[str, str]:
    fallback_queries = build_query_fallbacks(comet_id)
    last_status = "request_failed"

    for query in fallback_queries:
        result_text, status = await get_horizons_result_text(
            session,
            query,
            timeout=timeout,
            retries=retries,
        )
        if status != "ok" or not result_text:
            last_status = status
            continue

        resolved_text, resolved_status = await resolve_index_response(
            session,
            result_text,
            timeout=timeout,
            retries=retries,
        )
        if resolved_status == "ok" and resolved_text and has_orbital_elements(resolved_text):
            return resolved_text, "ok"

        if resolved_status != "ok":
            last_status = resolved_status
        else:
            last_status = "could_not_parse"

    return "", last_status


def extract_value(label: str, text: str) -> str:
    pattern = VALUE_PATTERNS.get(label)
    if pattern is None:
        return ""
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def extract_tp_numeric(text: str) -> str:
    # There can be two TP values; we want the numeric Julian date.
    match = TP_PATTERN.search(text)
    return match.group(1).strip() if match else ""


def extract_ref(text: str) -> str:
    match = REF_PATTERN.search(text)
    return match.group(1).strip() if match else ""


def extract_alternative_name(text: str) -> str:
    match = ALT_NAME_PATTERN.search(text)
    return match.group(1).strip() if match else ""


def extract_asteroid_physical_fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, pattern in ASTEROID_PHYSICAL_PATTERNS.items():
        match = pattern.search(text)
        out[key] = match.group(1).strip() if match else ""
    return out


def parse_orbital_fields(result_text: str) -> dict[str, str]:
    asteroid_physical = extract_asteroid_physical_fields(result_text)
    return {
        "alternative_name": extract_alternative_name(result_text),
        "epoch": extract_value("EPOCH", result_text),
        "tp": extract_tp_numeric(result_text),
        "eccent": extract_value("EC", result_text),
        "inclin": extract_value("IN", result_text),
        "perihel": extract_value("W", result_text),
        "long_ascend": extract_value("OM", result_text),
        "peri_dist": extract_value("QR", result_text),
        "aphel_dist": extract_value("ADIST", result_text),
        "orbit_period": extract_value("PER", result_text),
        "moid": extract_value("MOID", result_text),
        "ref": extract_ref(result_text),
        "gm": asteroid_physical.get("gm", ""),
        "rad": asteroid_physical.get("rad", ""),
        "rotper": asteroid_physical.get("rotper", ""),
        "h": asteroid_physical.get("h", ""),
        "g": asteroid_physical.get("g", ""),
        "b_v": asteroid_physical.get("b_v", ""),
        "albedo": asteroid_physical.get("albedo", ""),
        "styp": asteroid_physical.get("styp", ""),
    }


def load_names(input_csv: Path) -> list[str]:
    names: list[str] = []
    with input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"Input file has no header row: {input_csv}")

        preferred_column = "name" if "name" in reader.fieldnames else "object"
        if preferred_column not in reader.fieldnames:
            raise SystemExit(
                f"Input file must contain a 'name' or 'object' column: {input_csv}"
            )

        for row in reader:
            name = (row.get(preferred_column) or "").strip()
            if name:
                names.append(name)

    return names


def write_rows(output_csv: Path, rows: list[dict[str, str]]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


async def process_name(
    index: int,
    name: str,
    session: aiohttp.ClientSession,
    timeout: int,
    retries: int,
) -> tuple[int, dict[str, str]]:
    result_text, api_status = await get_resolved_horizons_result_text(
        session,
        name,
        timeout=timeout,
        retries=retries,
    )
    parsed = parse_orbital_fields(result_text) if result_text else {}

    row = {
        "object": name,
        "alternative_name": parsed.get("alternative_name", ""),
        "epoch": parsed.get("epoch", ""),
        "tp": parsed.get("tp", ""),
        "eccent": parsed.get("eccent", ""),
        "inclin": parsed.get("inclin", ""),
        "perihel": parsed.get("perihel", ""),
        "long_ascend": parsed.get("long_ascend", ""),
        "peri_dist": parsed.get("peri_dist", ""),
        "aphel_dist": parsed.get("aphel_dist", ""),
        "orbit_period": parsed.get("orbit_period", ""),
        "moid": parsed.get("moid", ""),
        "ref": parsed.get("ref", ""),
        "gm": parsed.get("gm", ""),
        "rad": parsed.get("rad", ""),
        "rotper": parsed.get("rotper", ""),
        "h": parsed.get("h", ""),
        "g": parsed.get("g", ""),
        "b_v": parsed.get("b_v", ""),
        "albedo": parsed.get("albedo", ""),
        "styp": parsed.get("styp", ""),
        "api_success": api_status,
    }
    return index, row


async def run_pipeline(args: argparse.Namespace) -> None:
    input_csv = Path(args.input).resolve()
    output_csv = Path(args.output).resolve()

    if not input_csv.exists():
        raise SystemExit(f"Input file not found: {input_csv}")

    names = load_names(input_csv)
    if args.limit and args.limit > 0:
        names = names[: args.limit]

    if not names:
        write_rows(output_csv, [])
        print(f"Saved 0 rows to: {output_csv}")
        return

    connector = aiohttp.TCPConnector(limit=args.concurrency, ttl_dns_cache=300)
    rows: list[dict[str, str] | None] = [None] * len(names)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(
                process_name(
                    index=i,
                    name=name,
                    session=session,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            )
            for i, name in enumerate(names)
        ]

        completed = 0
        for future in asyncio.as_completed(tasks):
            index, row = await future
            rows[index] = row
            completed += 1
            if completed % 100 == 0 or completed == len(names):
                print(f"Processed {completed}/{len(names)}")

    output_rows = [row for row in rows if row is not None]
    write_rows(output_csv, output_rows)
    print(f"Saved {len(output_rows)} rows to: {output_csv}")


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    default_input = project_root / "data_processed" / "unique_names.csv"
    default_output = project_root / "data_processed" / "horizons_orbital_data.csv"

    parser = argparse.ArgumentParser(
        description=(
            "Fetch orbital data from NASA JPL Horizons for each name in unique_names.csv "
            "and save into a CSV."
        )
    )
    parser.add_argument(
        "--input",
        default=str(default_input),
        help="Input CSV file with a 'name' column.",
    )
    parser.add_argument(
        "--output",
        default=str(default_output),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit for number of names to process (0 = all).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent API requests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry count for failed API requests.",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")
    if args.timeout < 1:
        raise SystemExit("--timeout must be at least 1 second")
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
