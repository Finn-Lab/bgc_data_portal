#!/usr/bin/env python
"""Regenerate ``django/discovery/services/data/go_slim_map.json``.

Standalone script — does NOT import Django. Run it locally with just
``goatools`` installed:

    python scripts/refresh_go_slim_map.py --download

Reads ``go-basic.obo`` and a GO-slim OBO (default ``goslim_metagenomics``),
runs :func:`goatools.mapslim.mapslim` for every term in the basic ontology,
keeps the ``direct_anc`` ancestors restricted to a single aspect (default
``molecular_function``), and writes the resulting GO id → slim term names
map to the JSON file the Discovery runtime reads via
``discovery.services.go_slim``.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import urllib.request
from pathlib import Path

# The OBO PURL redirects to hosts (e.g. release.geneontology.org) that 403
# requests without a recognisable User-Agent. Pretend to be a regular client.
USER_AGENT = "refresh_go_slim_map/1.0 (+https://github.com/Finn-Lab/bgc_data_portal)"

log = logging.getLogger("refresh_go_slim_map")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "django" / "discovery" / "services" / "data" / "go_slim_map.json"

OBO_URLS: dict[str, str] = {
    "go-basic.obo": "http://purl.obolibrary.org/obo/go/go-basic.obo",
    "goslim_metagenomics.obo": "http://current.geneontology.org/ontology/subsets/goslim_metagenomics.obo",
    "goslim_generic.obo": "http://current.geneontology.org/ontology/subsets/goslim_generic.obo",
    "goslim_agr.obo": "http://current.geneontology.org/ontology/subsets/goslim_agr.obo",
}

ASPECT_TO_NAMESPACE = {
    "molecular_function": "molecular_function",
    "biological_process": "biological_process",
    "cellular_component": "cellular_component",
}


def _capitalise(name: str) -> str:
    if not name:
        return ""
    return name[0].upper() + name[1:]


def _download(url: str, dest: Path) -> None:
    """``urlretrieve`` with a User-Agent header — required by PURL redirects."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--obo-dir",
        type=Path,
        default=Path("/tmp/go_obo"),
        help="Directory holding (or to receive) the OBO files. Default: /tmp/go_obo",
    )
    parser.add_argument(
        "--slim",
        default="goslim_metagenomics",
        help="Slim name (matches OBO filename without .obo). Default: goslim_metagenomics",
    )
    parser.add_argument(
        "--aspect",
        default="molecular_function",
        choices=tuple(ASPECT_TO_NAMESPACE.keys()) + ("all",),
        help="Restrict slim hits to this GO aspect. Use 'all' for MF+BP+CC.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download OBO files into --obo-dir if missing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output JSON path. Default: {OUTPUT_PATH}",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        from goatools.mapslim import mapslim
        from goatools.obo_parser import GODag
    except ImportError:
        print(
            "goatools is required to regenerate the slim map.\n"
            "Install it: pip install goatools",
            file=sys.stderr,
        )
        return 2

    obo_dir: Path = args.obo_dir
    obo_dir.mkdir(parents=True, exist_ok=True)
    basic_obo = obo_dir / "go-basic.obo"
    slim_obo = obo_dir / f"{args.slim}.obo"

    if args.download:
        for path, key in ((basic_obo, "go-basic.obo"), (slim_obo, f"{args.slim}.obo")):
            if path.exists():
                continue
            url = OBO_URLS.get(key)
            if not url:
                print(
                    f"No download URL configured for {key}. Place it under --obo-dir manually.",
                    file=sys.stderr,
                )
                return 2
            log.info("Downloading %s → %s", url, path)
            _download(url, path)

    for path in (basic_obo, slim_obo):
        if not path.exists():
            print(
                f"Missing OBO file: {path}. Use --download or place it manually.",
                file=sys.stderr,
            )
            return 2

    log.info("Loading %s …", basic_obo)
    godag = GODag(str(basic_obo))
    log.info("Loading %s …", slim_obo)
    goslim = GODag(str(slim_obo))

    keep_namespaces = (
        set(ASPECT_TO_NAMESPACE.values())
        if args.aspect == "all"
        else {ASPECT_TO_NAMESPACE[args.aspect]}
    )

    mapping: dict[str, list[str]] = {}
    total = 0
    mapped = 0
    for go_id, term in godag.items():
        total += 1
        if term.is_obsolete:
            continue
        if term.namespace not in keep_namespaces:
            continue
        try:
            direct, _all_anc = mapslim(go_id, godag, goslim)
        except Exception as exc:  # noqa: BLE001
            log.warning("mapslim failed for %s: %s", go_id, exc)
            continue
        if not direct:
            continue
        names = sorted({_capitalise(goslim[s].name) for s in direct if s in goslim})
        if not names:
            continue
        mapping[go_id] = names
        mapped += 1

    out_path: Path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": f"{basic_obo.name}+{slim_obo.name}",
        "aspect": args.aspect,
        "slim": args.slim,
        "map": mapping,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    log.info("✔ wrote %s — %d/%d GO terms mapped to slim names", out_path, mapped, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
