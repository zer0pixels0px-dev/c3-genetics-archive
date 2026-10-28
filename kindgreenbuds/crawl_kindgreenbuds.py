#!/usr/bin/env python3
"""Archive les profils de cultivars listés par Kind Green Buds.

Usage:
  python3 crawl_kindgreenbuds.py --inventory-only
  python3 crawl_kindgreenbuds.py --limit 3
  python3 crawl_kindgreenbuds.py
  python3 crawl_kindgreenbuds.py --export-only

The archive preserves source URL, canonical URL, retrieval time, response and
extracted-content hashes for each record. It obeys robots.txt, limits requests
to one in flight per domain, and uses a 1.5-second minimum delay plus
AutoThrottle. It does not use login credentials, proxies, or access-control
bypasses.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from scrapling.parser import Selector
from scrapling.spiders import Spider, Response

BASE_DIR = Path(__file__).resolve().parent
INDEX_URL = "https://kindgreenbuds.com/marijuana-strain-library/"
INDEX_HTML = BASE_DIR / "raw_pages" / "index_source.html"
INVENTORY_FILE = BASE_DIR / "metadata" / "profile_inventory.json"
RECORDS_DIR = BASE_DIR / "records"
STATE_FILE = BASE_DIR / "metadata" / "crawl_state.json"
MANIFEST_FILE = BASE_DIR / "metadata" / "manifest.json"
JSONL_FILE = BASE_DIR / "records" / "all_records.jsonl"
CSV_FILE = BASE_DIR / "records" / "all_records.csv"

KNOWN_FIELDS = [
    "Strain Type", "Genetics", "Breeder", "THC Content", "CBD Content",
    "Terpene Profile", "Primary Flavors", "Flowering Time (Indoor)",
    "Outdoor Harvest Time", "Indoor Yield", "Outdoor Yield", "Grow Difficulty",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def slug_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-.")
    return slug or "unknown-cultivar"


def load_index_metadata() -> dict:
    path = BASE_DIR / "metadata" / "index_capture.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"source_name": "Kind Green Buds", "source_url": INDEX_URL}


def build_inventory() -> list[dict]:
    if not INDEX_HTML.exists():
        raise FileNotFoundError(f"Index capture not found: {INDEX_HTML}")
    raw = INDEX_HTML.read_bytes()
    page = Selector(raw, url=INDEX_URL)
    entries: list[dict] = []
    seen: set[str] = set()
    for node in page.css("ul#lcp_instance_0 a"):
        name = " ".join(node.get_all_text(strip=True).split())
        href = (node.attrib.get("href") or "").strip()
        full_url = urljoin(INDEX_URL, href)
        parsed = urlparse(full_url)
        if (not name or parsed.hostname not in {"kindgreenbuds.com", "www.kindgreenbuds.com"}
                or not parsed.path.startswith("/marijuana-strains/")):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        entries.append({
            "cultivar_name_as_listed": name,
            "source_url": full_url,
            "record_slug": slug_from_url(full_url),
        })
    if not entries:
        raise RuntimeError("No profile links found in ul#lcp_instance_0; inspect the index capture.")
    metadata = load_index_metadata()
    inventory = {
        "source_name": "Kind Green Buds",
        "source_index_url": INDEX_URL,
        "source_index_capture_sha256": metadata.get("sha256"),
        "inventory_created_at_utc": now_utc(),
        "selector": "ul#lcp_instance_0 a",
        "profile_count": len(entries),
        "profiles": entries,
    }
    INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_FILE.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Inventory saved: {len(entries)} unique profile URLs -> {INVENTORY_FILE}", flush=True)
    return entries


def load_inventory() -> list[dict]:
    if not INVENTORY_FILE.exists():
        return build_inventory()
    data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
    return data["profiles"]


def extract_text(node) -> str:
    return " ".join(node.get_all_text(strip=True).split())


def extract_fields(entry) -> dict:
    values: dict[str, list[str]] = {}
    for node in entry.css("li"):
        text = extract_text(node)
        for label in KNOWN_FIELDS:
            prefix = label + ":"
            if text.casefold().startswith(prefix.casefold()):
                value = text[len(prefix):].strip()
                if value:
                    values.setdefault(label, []).append(value)
                break
    return {key: vals[0] if len(vals) == 1 else vals for key, vals in values.items()}


def make_record(response: Response, listed: dict) -> dict:
    raw = response.body
    if not isinstance(raw, bytes):
        raw = str(raw).encode("utf-8", "replace")
    entries = response.css("article .entry-content")
    if not entries:
        entries = response.css(".entry-content")
    entry = entries[0] if entries else None
    content_html = entry.get() if entry else ""
    content_blocks: list[dict] = []
    if entry:
        for node in entry.css("h1, h2, h3, h4, p, li, blockquote, figcaption"):
            text = extract_text(node)
            if text:
                tag = getattr(node, "tag", "text")
                content_blocks.append({"tag": str(tag), "text": text})
    article_text = "\n".join(block["text"] for block in content_blocks)
    if not article_text and entry:
        article_text = extract_text(entry)
    headings = [extract_text(node) for node in (entry.css("h1, h2, h3, h4") if entry else [])]
    outbound_links = []
    if entry:
        for node in entry.css("a"):
            href = (node.attrib.get("href") or "").strip()
            if href:
                outbound_links.append({"text": extract_text(node), "url": urljoin(response.url, href)})
    images = []
    if entry:
        for node in entry.css("img"):
            images.append({
                "alt": node.attrib.get("alt", ""),
                "src": urljoin(response.url, node.attrib.get("src", "")) if node.attrib.get("src") else "",
                "srcset": node.attrib.get("srcset", ""),
            })
    canonical = response.css('link[rel="canonical"]::attr(href)').get("")
    title = response.css("title::text").get("")
    description = response.css('meta[name="description"]::attr(content)').get("")
    published = response.css('meta[property="article:published_time"]::attr(content)').get("")
    modified = response.css('meta[property="article:modified_time"]::attr(content)').get("")
    classes = []
    article_nodes = response.css("article")
    if article_nodes:
        classes = (article_nodes[0].attrib.get("class", "")).split()
    slug = listed.get("record_slug") or slug_from_url(listed["source_url"])
    record = {
        "record_id": f"kindgreenbuds:{slug}",
        "cultivar_name_as_listed": listed["cultivar_name_as_listed"],
        "page_title": title,
        "source_name": "Kind Green Buds",
        "source_dataset": "Marijuana Strain Library",
        "source_url": listed["source_url"],
        "final_response_url": response.url,
        "canonical_url": canonical,
        "retrieved_at_utc": now_utc(),
        "http_status": response.status,
        "extraction_status": "success" if entry and article_text else "article_content_missing",
        "source_page_metadata": {
            "description": description,
            "published_time": published,
            "modified_time": modified,
            "article_classes": classes,
        },
        "fields_reported_by_source": extract_fields(entry) if entry else {},
        "section_headings": headings,
        "article_blocks": content_blocks,
        "article_text": article_text,
        "outbound_links_in_article": outbound_links,
        "images_in_article": images,
        "provenance": {
            "source_label": "Kind Green Buds — source distincte; les données ne confirment pas à elles seules une culture ou une vente par C3 Industries.",
            "source_index_url": INDEX_URL,
            "index_selector": "ul#lcp_instance_0 a",
            "scraper": "Scrapling Spider / Response, version 0.5",
            "response_sha256": sha256(raw),
            "extracted_article_fragment_sha256": sha256(content_html),
            "article_fragment_saved": False,
            "note": "Les empreintes sont des contrôles d’intégrité calculés localement; elles ne constituent pas une signature numérique du site. Le lien source/canonical reste le point de vérification d’origine.",
        },
    }
    return record


def save_record(record: dict) -> None:
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    slug = slug_from_url(record.get("source_url", ""))
    path = RECORDS_DIR / f"{slug}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def existing_success_slugs() -> set[str]:
    done = set()
    if RECORDS_DIR.exists():
        for path in RECORDS_DIR.glob("*.json"):
            if path.name == "manifest.json":
                continue
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if rec.get("extraction_status") == "success" and rec.get("source_url"):
                    done.add(slug_from_url(rec["source_url"]))
            except Exception:
                continue
    return done


def export_archive(inventory: list[dict], crawl_stats: dict | None = None) -> dict:
    records = []
    for path in sorted(RECORDS_DIR.glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    JSONL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_FILE.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    columns = [
        "record_id", "cultivar_name_as_listed", "page_title", "source_name",
        "source_url", "canonical_url", "retrieved_at_utc", "http_status",
        "extraction_status", "strain_type", "genetics", "breeder", "thc_content",
        "cbd_content", "terpene_profile", "primary_flavors", "flowering_time_indoor",
        "outdoor_harvest_time", "indoor_yield", "outdoor_yield", "grow_difficulty",
        "section_headings_json", "article_text", "response_sha256",
    ]
    key_map = {
        "strain_type": "Strain Type", "genetics": "Genetics", "breeder": "Breeder",
        "thc_content": "THC Content", "cbd_content": "CBD Content",
        "terpene_profile": "Terpene Profile", "primary_flavors": "Primary Flavors",
        "flowering_time_indoor": "Flowering Time (Indoor)",
        "outdoor_harvest_time": "Outdoor Harvest Time", "indoor_yield": "Indoor Yield",
        "outdoor_yield": "Outdoor Yield", "grow_difficulty": "Grow Difficulty",
    }
    with CSV_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in columns}
            fields = record.get("fields_reported_by_source", {})
            for target, original in key_map.items():
                val = fields.get(original, "")
                row[target] = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else val
            row["section_headings_json"] = json.dumps(record.get("section_headings", []), ensure_ascii=False)
            row["response_sha256"] = record.get("provenance", {}).get("response_sha256", "")
            writer.writerow(row)
    counts = {}
    for record in records:
        status = record.get("extraction_status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    manifest = {
        "archive_name": "Kind Green Buds Marijuana Strain Library — isolated source archive",
        "source_name": "Kind Green Buds",
        "source_index_url": INDEX_URL,
        "source_index_capture": "raw_pages/index_source.html",
        "source_index_capture_sha256": load_index_metadata().get("sha256"),
        "inventory_file": "metadata/profile_inventory.json",
        "inventory_unique_profile_urls": len(inventory),
        "records_archived": len(records),
        "record_status_counts": counts,
        "crawl_stats": crawl_stats or {},
        "last_updated_at_utc": now_utc(),
        "collection_method": "Scrapling 0.5 static Spider; robots_txt_obey=true; one request in flight per domain; 1.5 s minimum download delay; AutoThrottle enabled; no login, proxy or access-control bypass.",
        "provenance_policy": "Every record has its own source_url, final_response_url, canonical_url, retrieval timestamp, HTTP status, source metadata and SHA-256 fingerprints. Source is never silently merged with C3, SQDC, OCS or social platforms.",
        "scope_note": "This index is a general cultivar reference library. Listing a cultivar here does not prove that C3 Industries grew, sold or supplied it.",
        "integrity_note": "Local hashes are integrity fingerprints, not a publisher-issued digital signature or proof of authorship.",
        "files": ["records/all_records.jsonl", "records/all_records.csv", "README.md", "crawl_kindgreenbuds.py"],
    }
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class KindGreenBudsSpider(Spider):
    name = "kindgreenbuds-strain-library"
    start_urls: list[str] = []
    allowed_domains = {"kindgreenbuds.com", "www.kindgreenbuds.com"}
    robots_txt_obey = True
    concurrent_requests = 1
    concurrent_requests_per_domain = 1
    download_delay = 1.5
    autothrottle_enabled = True
    autothrottle_start_delay = 2.0
    autothrottle_max_delay = 60.0
    autothrottle_target_concurrency = 1
    autothrottle_block_backoff = True
    logging_level = 20
    log_file = str(BASE_DIR / "logs" / "crawl.log")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completed_profiles = 0

    async def parse(self, response: Response):
        listed = getattr(response.request, "meta", {}) or {}
        # Spider start URLs are passed in inventory order; the request URL is the stable identity.
        source_url = response.url
        candidate = next((x for x in self._active_inventory if x["source_url"] == source_url), None)
        if candidate is None:
            candidate = {"cultivar_name_as_listed": "", "source_url": source_url, "record_slug": slug_from_url(source_url)}
        try:
            record = make_record(response, candidate)
            save_record(record)
            self.completed_profiles += 1
            if self.completed_profiles % 25 == 0:
                state = {
                    "source_name": "Kind Green Buds",
                    "last_progress_at_utc": now_utc(),
                    "completed_this_run": self.completed_profiles,
                    "current_url": source_url,
                }
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                self.logger.info("Progress: %s profiles extracted", self.completed_profiles)
            yield record
        except Exception as exc:
            error_record = {
                "record_id": f"kindgreenbuds:{slug_from_url(source_url)}",
                "cultivar_name_as_listed": candidate.get("cultivar_name_as_listed", ""),
                "source_name": "Kind Green Buds",
                "source_url": source_url,
                "final_response_url": response.url,
                "retrieved_at_utc": now_utc(),
                "http_status": getattr(response, "status", None),
                "extraction_status": "extraction_error",
                "error": f"{type(exc).__name__}: {exc}",
                "provenance": {"source_index_url": INDEX_URL, "scraper": "Scrapling Spider 0.5"},
            }
            save_record(error_record)
            self.logger.error("Extraction error for %s: %s", source_url, exc)
            yield error_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-only", action="store_true", help="Build inventory from archived index, no network requests")
    parser.add_argument("--export-only", action="store_true", help="Rebuild CSV/JSONL/manifest from record files")
    parser.add_argument("--limit", type=int, default=0, help="Limit crawl to the first N pending profiles; 0 means all")
    parser.add_argument("--force", action="store_true", help="Re-fetch profiles that already have a successful record")
    args = parser.parse_args()

    inventory = build_inventory()
    if args.inventory_only:
        return 0
    if args.export_only:
        manifest = export_archive(inventory)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    done = set() if args.force else existing_success_slugs()
    pending = [x for x in inventory if x["record_slug"] not in done]
    if args.limit:
        pending = pending[:max(0, args.limit)]
    print(f"Source: {INDEX_URL}\nInventory: {len(inventory)} profiles\nAlready archived: {len(done)}\nThis run: {len(pending)}\n", flush=True)
    if not pending:
        manifest = export_archive(inventory)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    KindGreenBudsSpider.start_urls = [x["source_url"] for x in pending]
    KindGreenBudsSpider._active_inventory = pending
    crawler = KindGreenBudsSpider()
    result = crawler.start()
    stats = result.stats.to_dict() if hasattr(result.stats, "to_dict") else str(result.stats)
    manifest = export_archive(inventory, crawl_stats=stats)
    print("\nCrawl finished.")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Spider completed:", getattr(result, "completed", "unknown"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
