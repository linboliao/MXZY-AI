"""Queue administrator-managed server slides for one-time precomputation."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PRECOMPUTE_STATUSES = {"not_analyzed", "outdated"}


def request_json(url, *, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(
        description="Queue unprocessed or outdated server slides for diagnosis"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Web Viewer base URL, for example http://100.76.152.123:5000",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Retry slides whose most recent precomputation failed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List slides that would be queued without creating jobs",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    try:
        slides = request_json(f"{base_url}/api/server-slides").get("slides", [])
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise SystemExit(f"Unable to read the server slide library: {error}") from error

    eligible_statuses = set(PRECOMPUTE_STATUSES)
    if args.include_failed:
        eligible_statuses.add("failed")
    eligible = [slide for slide in slides if slide.get("analysisStatus") in eligible_statuses]

    print(f"Server slides: {len(slides)}")
    print(f"Already ready or active: {len(slides) - len(eligible)}")
    print(f"Eligible for precomputation: {len(eligible)}")

    failures = 0
    for index, slide in enumerate(eligible, 1):
        prefix = f"[{index}/{len(eligible)}] {slide['relativePath']}"
        if args.dry_run:
            print(f"{prefix}: would queue ({slide['analysisStatus']})")
            continue
        try:
            response = request_json(
                f"{base_url}/api/jobs",
                payload={"serverSlideId": slide["id"]},
            )
            job = response["job"]
            action = "reused" if response.get("reused") else "queued"
            print(f"{prefix}: {action} as job {job['id']}")
        except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
            failures += 1
            print(f"{prefix}: failed to queue: {error}")

    if failures:
        raise SystemExit(f"Failed to queue {failures} slide(s)")


if __name__ == "__main__":
    main()
