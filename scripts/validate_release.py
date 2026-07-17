#!/usr/bin/env python
"""Validate the versioned NCIt snapshot and the derived graph before release."""

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ncit_colorectal_cancer"
GRAPH = ROOT / "colorectal_knowledge_graph"


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    required = [
        SOURCE / "metadata.json",
        SOURCE / "concepts.csv",
        SOURCE / "edges.csv",
        SOURCE / "related_entities_full.csv",
        GRAPH / "kg_nodes.csv",
        GRAPH / "kg_edges.csv",
        GRAPH / "kg_summary.json",
        GRAPH / "kg_browser.html",
        GRAPH / "kg_tree.html",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    require(not missing, "Missing release files: " + ", ".join(missing))

    metadata = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((GRAPH / "kg_summary.json").read_text(encoding="utf-8"))
    nodes = read_csv(GRAPH / "kg_nodes.csv")
    edges = read_csv(GRAPH / "kg_edges.csv")
    node_ids = {row["id"] for row in nodes}

    require(metadata["root_code"] == "C2955", "Unexpected NCIt root code")
    require("C2955" in node_ids, "Root concept C2955 is missing")
    require(len(node_ids) == len(nodes), "Duplicate node identifiers detected")
    require(summary["node_count"] == len(nodes), "kg_summary node count mismatch")
    require(summary["edge_count_full"] == len(edges), "kg_summary edge count mismatch")

    invalid = [
        row for row in edges
        if row["source"] not in node_ids or row["target"] not in node_ids
    ]
    require(not invalid, "Graph edges reference missing nodes")

    print(
        "Release validation passed: "
        f"{len(nodes)} nodes, {len(edges)} edges, NCIt {metadata['version']}."
    )


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
