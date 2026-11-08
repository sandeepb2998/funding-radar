"""Build an allowlisted public site, never copying the repository or contacts."""

import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RECORD_FIELDS = ("id", "company", "amount", "currency", "stage", "published_at",
                 "first_seen_at", "last_seen_at", "headline", "quality")
SOURCE_FIELDS = ("name", "url", "status", "items_read", "accepted", "invalid",
                 "excluded", "pending", "index_days", "oldest_indexed_on", "next_page")


def public_data(data):
    result = {k: data[k] for k in ("schema_version", "last_attempt_at", "last_success_at", "status")}
    result["sources"] = [{k: s[k] for k in SOURCE_FIELDS if k in s} for s in data["sources"]]
    result["records"] = []
    for record in data["records"]:
        safe = {k: record[k] for k in RECORD_FIELDS}
        safe["kind"] = record.get("kind", "news")
        safe["sources"] = [{"name": s["name"], "url": s["url"]} for s in record["sources"]]
        for field, allowed in (
            ("announcement", ("date", "status", "source_url", "note", "checked_at", "check_status")),
            ("location", ("country", "country_code", "region", "status", "source_url", "note")),
            ("filing", ("accession", "cik", "form", "filed_on", "first_sale_on", "industry", "amount_basis", "provider")),
        ):
            safe[field] = {k: record[field][k] for k in allowed if k in record.get(field, {})}
        result["records"].append(safe)
    return result


def build(output, data_path):
    # Refuse to publish into an existing directory containing unreviewed files.
    permitted = {"index.html", "styles.css", "app.js", "data.json", ".nojekyll"}
    if output.exists() and any(p.name not in permitted or not p.is_file() for p in output.iterdir()):
        raise ValueError("Output directory contains files outside the public allowlist")
    output.mkdir(parents=True, exist_ok=True)
    data = public_data(json.loads(data_path.read_text()))
    for filename in ("index.html", "styles.css", "app.js"):
        shutil.copyfile(ROOT / "web" / filename, output / filename)
    (output / "data.json").write_text(json.dumps(data, ensure_ascii=True) + "\n")
    (output / ".nojekyll").touch()
    print(f"Built {output} with {len(data['records'])} public funding signals.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    parser.add_argument("--data", type=Path, default=ROOT / "data/funding.json")
    args = parser.parse_args()
    build(args.output, args.data)
