"""Slugs resolution on company target list

Entrée  : target-companies.yaml  (name, domain, country)
Sortie  : target-companies.resolved.yaml  (+ ats_type, ats_slug, status, resolved_at)

Every exit path — normal end, 429 abort, unexpected exception, Ctrl-C —
writes the YAML and prints the report. A partial result is still a result.

Usage:
    uv run resolve_ats.py target_companies.yaml -o target_companies.resolved.yaml
    uv run resolve_ats.py ... --retry-unresolved   # retry unresolved
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

import httpx
import yaml

USER_AGENT = "jobagent/0.1 (+contact: amorosothomas.dev@gmail.com)"
TIMEOUT = httpx.Timeout(10.0)
CONCURRENCY = 5
DELAY_BETWEEN_PROBES = 1

MAX_RETRIES = 4
BACKOFF_BASE = 2.0  # 2, 4, 8, 16 s
BACKOFF_MAX = 120.0
ABORT_RATE_LIMIT_RATIO = 0.25  # stop if too many probes get throttled


class Status(StrEnum):
    PENDING = "pending"  # never probed — not a verdict
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"  # probed everywhere, nothing found. Could be a false negative
    ERROR = "error"  # network/server error, to be retried
    RATE_LIMITED = "rate_limited"  # no verdict reached, must be replayed
    # no_public_feed and dead are not included. To be tagged by hand


class Probe(StrEnum):
    HIT = "hit"
    MISS = "miss"  # No valid slug on that ATS
    ERROR = "error"  # 5xx, timeout, DNS
    RATE_LIMITED = "rate_limited"  # still 429 after MAX_RETRIES
    BUG = "bug"  # probe error on our side


# statuses that are not a verdict: always re-probed on the next run
REPLAYABLE = {Status.PENDING, Status.ERROR, Status.RATE_LIMITED}


@dataclass
class Resolution:
    name: str
    domain: str | None
    country: str
    segment: str
    ats_type: str | None = None
    ats_slug: str | None = None
    status: Status = Status.PENDING
    resolved_at: str | None = None
    attempts: list[str] = field(default_factory=list)


@dataclass
class Counters:
    """Run-wide health signals. A resolver that degrades silently is worse
    than one that crashes."""

    probes: int = 0
    rate_limited: int = 0

    @property
    def rate_limit_ratio(self) -> float:
        return self.rate_limited / self.probes if self.probes else 0.0


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
        unicodedata.normalize("NFKD", name).encode(
            "ascii", "ignore").decode().lower()
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
        response_type, parsed_resp = _parse_response(resp.text)
    except ValueError:
        # only an unparsable body is a MISS. Any other exception is a bug
        # on our side and must surface.
        return Probe.MISS
    if response_type == "json":
        return Probe.HIT
    return Probe.HIT if parsed_resp.tag == "workzag-jobs" else Probe.MISS


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
# Rate limiting
# ─────────────────────────────────────────────────────────────────


class HostGate:
    """Shared pause per host"""

    def __init__(self) -> None:
        self._until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        loop = asyncio.get_running_loop()
        while True:
            async with self._lock:
                delay = self._until.get(host, 0.0) - loop.time()
            if delay <= 0:
                return
            await asyncio.sleep(delay)

    async def pause(self, host: str, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._until[host] = max(self._until.get(
                host, 0.0), loop.time() + seconds)


def _backoff(attempt: int, resp: httpx.Response | None) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), BACKOFF_MAX)
            except ValueError:
                pass  # HTTP-date form, ignored here
    jitter = 1 + random.random() * 0.25
    return min(BACKOFF_BASE * 2**attempt, BACKOFF_MAX) * jitter


# ─────────────────────────────────────────────────────────────────
# Resolution loop
# ─────────────────────────────────────────────────────────────────


async def probe(
    client: httpx.AsyncClient,
    gate: HostGate,
    counters: Counters,
    ats: str,
    slug: str,
) -> Probe:
    template = PROBES[ats]
    url = template.format(slug=slug)
    host = httpx.URL(url).host
    is_subdomain = "{slug}." in template
    last = Probe.ERROR

    for attempt in range(MAX_RETRIES + 1):
        await gate.wait(host)
        counters.probes += 1
        try:
            resp = await client.get(url)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # non-existent subdomain (recruitee, personio) = MISS, not an outage.
            # Definitive verdict, no retry.
            return Probe.MISS if is_subdomain else Probe.ERROR
        except httpx.HTTPError:
            last = Probe.ERROR
            await asyncio.sleep(_backoff(attempt, None))
            continue

        if resp.status_code == 429:
            last = Probe.RATE_LIMITED
            counters.rate_limited += 1
            await gate.pause(host, _backoff(attempt, resp))
            continue

        if resp.status_code >= 500:
            last = Probe.ERROR
            await asyncio.sleep(_backoff(attempt, None))
            continue

        result = _hit(resp)
        if result is Probe.BUG:
            raise RuntimeError(
                f"{ats}/{slug}: unexpected {resp.status_code} on {url}")
        return result

    return last


async def resolve_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    gate: HostGate,
    counters: Counters,
    entry: Resolution,
) -> Resolution:
    candidates = slug_candidates(entry.name, entry.domain)
    saw_error = False
    saw_rate_limit = False

    # Probing in alphabetic order but could be more efficient to probe those who yield more results first.
    # To adjust when we'll know the distribution
    for slug in candidates:
        for ats in PROBES:
            async with sem:
                await asyncio.sleep(DELAY_BETWEEN_PROBES)
                result = await probe(client, gate, counters, ats, slug)
            entry.attempts.append(f"{ats}:{slug}={result}")
            if result is Probe.HIT:
                entry.ats_type = ats
                entry.ats_slug = slug
                entry.status = Status.RESOLVED
                entry.resolved_at = datetime.now(timezone.utc).isoformat()
                return entry
            if result is Probe.ERROR:
                saw_error = True
            elif result is Probe.RATE_LIMITED:
                saw_rate_limit = True

    # rate_limited wins over error: a throttled probe means we never got to
    # test that possibility, so "unresolved" would be a lie.
    if saw_rate_limit:
        entry.status = Status.RATE_LIMITED
    elif saw_error:
        entry.status = Status.ERROR
    else:
        entry.status = Status.UNRESOLVED
    return entry


async def run(entries: list[Resolution], out_path: Path, counters: Counters) -> None:
    """Never raises. Whatever happens, the YAML is written before returning."""
    sem = asyncio.Semaphore(CONCURRENCY)
    gate = HostGate()
    headers = {"User-Agent": USER_AGENT}
    stopped: str | None = None

    async with httpx.AsyncClient(
        headers=headers, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        tasks = [
            asyncio.create_task(resolve_one(client, sem, gate, counters, e))
            for e in entries
        ]
        done = 0
        try:
            for coro in asyncio.as_completed(tasks):
                await coro
                done += 1
                if done % 10 == 0:
                    dump(entries, out_path)
                    print(f"{done}/{len(entries)}")
                if (
                    counters.probes > 50
                    and counters.rate_limit_ratio > ABORT_RATE_LIMIT_RATIO
                ):
                    stopped = (
                        f"{counters.rate_limit_ratio:.0%} of probes throttled. "
                        f"Lower CONCURRENCY or raise DELAY_BETWEEN_PROBES, then replay."
                    )
                    break
        except Exception as exc:
            # a single unexpected status must not cost the whole run's output
            stopped = f"{type(exc).__name__}: {exc}"
        finally:
            # KeyboardInterrupt does not inherit from Exception: it passes
            # through, but this block still runs, so Ctrl-C also writes.
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            dump(entries, out_path)

    if stopped:
        print(f"\nRun stopped — {stopped}")


# ─────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────


def load(path: Path, retry_unresolved: bool) -> list[Resolution]:
    raw = yaml.safe_load(path.read_text())
    entries: list[Resolution] = []
    for segment, companies in raw["segments"].items():
        for c in companies:
            stored = c.get("status")
            # never re-probe a resolved entry, nor a hand-tagged dead/no_public_feed
            if stored in {Status.RESOLVED, "dead", "no_public_feed"}:
                continue
            # pending, error and rate_limited are not verdicts: always replayed
            if stored is not None and Status(stored) not in REPLAYABLE:
                if not retry_unresolved:
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
        row = {
            "name": e.name,
            "domain": e.domain,
            "country": e.country,
            "ats_type": e.ats_type,
            "ats_slug": e.ats_slug,
            "status": str(e.status),
            "resolved_at": e.resolved_at,
        }
        # why it failed: which ATS, which slug, which verdict
        if e.status is not Status.RESOLVED and e.attempts:
            row["attempts"] = e.attempts
        by_segment.setdefault(e.segment, []).append(row)
    path.write_text(yaml.safe_dump(
        {"segments": by_segment}, allow_unicode=True))


def report(entries: list[Resolution], counters: Counters) -> None:
    """Le vrai livrable de la session : le taux par segment."""
    print(f"\n{'segment':<26} {'total':>6} {'resolved':>9} {'taux':>6}")
    for segment in sorted({e.segment for e in entries}):
        rows = [e for e in entries if e.segment == segment]
        ok = sum(e.status is Status.RESOLVED for e in rows)
        print(f"{segment:<26} {len(rows):>6} {ok:>9} {ok / len(rows):>6.0%}")

    print(f"\n{'ats':<20} {'n':>5}")
    for ats in sorted({e.ats_type for e in entries if e.ats_type}):
        print(f"{ats:<20} {sum(e.ats_type == ats for e in entries):>5}")

    print(f"\n{'status':<20} {'n':>5}")
    for status in Status:
        n = sum(e.status is status for e in entries)
        if n:
            print(f"{str(status):<20} {n:>5}")

    print(
        f"\nprobes: {counters.probes}  throttled: {counters.rate_limited} "
        f"({counters.rate_limit_ratio:.1%})"
    )
    replayable = sum(e.status in REPLAYABLE for e in entries)
    if replayable:
        print(f"{replayable} entries without a verdict — replay the script.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--retry-unresolved", action="store_true")
    args = p.parse_args()

    entries = load(args.input, args.retry_unresolved)
    print(f"{len(entries)} entreprises à résoudre")

    # counters passed in, not returned: we want them even when run() dies
    counters = Counters()
    try:
        asyncio.run(run(entries, args.output, counters))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        report(entries, counters)


if __name__ == "__main__":
    main()
