"""Slugs resolution on company target list

Entrée  : target-companies.yaml  (name, domain, country)
Sortie  : target-companies.resolved.yaml  (+ ats_type, ats_slug, status, resolved_at)

Usage:
    uv run resolve_ats.py target-companies.yaml -o target-companies.resolved.yaml
    uv run resolve_ats.py ... --retry-unresolved   # retry unresolved
"""

from __future__ import annotations

import argparse
import asyncio
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

import httpx
import yaml
import json
import xml.etree.ElementTree as ET


USER_AGENT = "jobagent/0.1 (+contact: amorosothomas.dev@gmail.com)"
TIMEOUT = httpx.Timeout(10.0)
CONCURRENCY = 5
DELAY_BETWEEN_PROBES = 1


class Status(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"  # could be false negative
    ERROR = "error"  # network/server error, to be retried
    # no_public_feed and dead are not included. To be tagged by hand


class Probe(StrEnum):
    HIT = "hit"
    MISS = "miss"  # No valid slug on that ATS
    ERROR = "error"  # 5xx, timeout, DNS
    BUG = "bug"  # probe error on our side


@dataclass
class Resolution:
    name: str
    domain: str | None
    country: str
    segment: str
    ats_type: str | None = None
    ats_slug: str | None = None
    status: Status = Status.UNRESOLVED
    resolved_at: str | None = None
    attempts: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Slugs candidat generation
# ─────────────────────────────────────────────────────────────────

def slug_candidates(name: str, domain: str | None) -> list[str]:
    """Possible slugs candidat generation, most to least probable"""
    out: list[str] = []

    if domain:
        # welcometothejungle.com -> welcometothejungle ; group.bnpparibas -> bnpparibas
        host = domain.split("/")[0].removeprefix("www.")
        parts = host.split(".")
        base = parts[0] if len(parts) <= 2 else parts[-2]
        out.append(base)
        if "-" in base:
            out.append(base.replace("-", ""))

    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    compact = "".join(c for c in ascii_name if c.isalnum())
    hyphened = "-".join(ascii_name.split())
    out += [compact, hyphened]

    seen: set[str] = set()
    return [s for s in out if s and not (s in seen or seen.add(s))]


# ─────────────────────────────────────────────────────────────────
# Probe
# 200 status code with empty results could be normal
# ─────────────────────────────────────────────────────────────────

def _parse_response(raw: str):
    try:
        return "json", json.loads(raw)
    except json.JSONDecodeError:
        pass

    try:
        return "xml", ET.fromstring(raw)
    except ET.ParseError:
        pass

    raise ValueError("Unknown response type")


def _hit(resp: httpx.Response) -> Probe:
    if resp.status_code == 404:
        return Probe.MISS
    if resp.status_code >= 500:
        return Probe.ERROR
    if resp.status_code != 200:
        return Probe.BUG
    try:
        response_type, parsed_resp = _parse_response(resp)
        if response_type == "json":
            return Probe.HIT
        if response_type == "xml":
            return Probe.HIT if parsed_resp.tag == 'workzag-jobs' else Probe.MISS
    except:
        return Probe.MISS


PROBES: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "smartrecruiters":
        # Case sensitive slug. We normalize to lower case. Watch for false negative on first run
        "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "personio": "https://{slug}.jobs.personio.de/xml?language=en",
    # No workday because, automated slug resolution is much more complicated and will not be worth.
}


# ─────────────────────────────────────────────────────────────────
# Resolution loop
# ─────────────────────────────────────────────────────────────────

async def probe(
    client: httpx.AsyncClient, ats: str, slug: str
) -> Probe:
    template = PROBES[ats]
    url = template.format(slug=slug)
    try:
        resp = await client.get(url)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # sous-domaine inexistant (recruitee, personio) = MISS, pas une panne
        return Probe.MISS if "{slug}." in template else Probe.ERROR
    except httpx.HTTPError:
        return Probe.ERROR
    result = _hit(resp)
    if result is Probe.BUG:
        raise RuntimeError(
            f"{ats}/{slug}: unexpected {resp.status_code} on {url}")
    return result


async def resolve_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, entry: Resolution
) -> Resolution:
    candidates = slug_candidates(entry.name, entry.domain)
    saw_error = False

    # Probing in alphabetic order but could be more efficient to probe those who yield more results first.
    # To adjust when we'll know the distribution
    for slug in candidates:
        for ats in PROBES:
            async with sem:
                await asyncio.sleep(DELAY_BETWEEN_PROBES)
                result = await probe(client, ats, slug)
            entry.attempts.append(f"{ats}:{slug}={result}")
            if result is Probe.HIT:
                entry.ats_type = ats
                entry.ats_slug = slug
                entry.status = Status.RESOLVED
                entry.resolved_at = datetime.now(timezone.utc).isoformat()
                return entry
            if result is Probe.ERROR:
                saw_error = True

    entry.status = Status.ERROR if saw_error else Status.UNRESOLVED
    return entry


async def run(entries: list[Resolution], out_path: Path) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        tasks = [resolve_one(client, sem, e) for e in entries]
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 10 == 0:
                dump(entries, out_path)
                print(f"{done}/{len(entries)}")
    dump(entries, out_path)


# ─────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────

def load(path: Path, retry_unresolved: bool) -> list[Resolution]:
    raw = yaml.safe_load(path.read_text())
    entries: list[Resolution] = []
    for segment, companies in raw["segments"].items():
        for c in companies:
            status = Status(c.get("status", Status.UNRESOLVED))
            # on ne re-sonde jamais un resolved, ni un dead/no_public_feed
            if status is Status.RESOLVED or c.get("status") in {
                "dead",
                "no_public_feed",
            }:
                continue
            if status is Status.UNRESOLVED and not retry_unresolved and "status" in c:
                continue
            entries.append(
                Resolution(
                    name=c["name"],
                    domain=c.get("domain"),
                    country=c.get("country", ""),
                    segment=segment,
                )
            )
    return entries


def dump(entries: list[Resolution], path: Path) -> None:
    by_segment: dict[str, list[dict]] = {}
    for e in entries:
        by_segment.setdefault(e.segment, []).append(
            {
                "name": e.name,
                "domain": e.domain,
                "country": e.country,
                "ats_type": e.ats_type,
                "ats_slug": e.ats_slug,
                "status": str(e.status),
                "resolved_at": e.resolved_at,
            }
        )
    path.write_text(yaml.safe_dump(
        {"segments": by_segment}, allow_unicode=True))


def report(entries: list[Resolution]) -> None:
    """Le vrai livrable de la session : le taux par segment."""
    print(f"\n{'segment':<26} {'total':>6} {'resolved':>9} {'taux':>6}")
    for segment in sorted({e.segment for e in entries}):
        rows = [e for e in entries if e.segment == segment]
        ok = sum(e.status is Status.RESOLVED for e in rows)
        print(f"{segment:<26} {len(rows):>6} {ok:>9} {ok / len(rows):>6.0%}")

    print(f"\n{'ats':<20} {'n':>5}")
    for ats in sorted({e.ats_type for e in entries if e.ats_type}):
        print(f"{ats:<20} {sum(e.ats_type == ats for e in entries):>5}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--retry-unresolved", action="store_true")
    args = p.parse_args()

    entries = load(args.input, args.retry_unresolved)
    print(f"{len(entries)} entreprises à résoudre")
    asyncio.run(run(entries, args.output))
    report(entries)


if __name__ == "__main__":
    main()
