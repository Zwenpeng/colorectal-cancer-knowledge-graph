#!/usr/bin/env python
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BASE_URL = "https://api-evsrest.nci.nih.gov/api/v1"
OUT_DIR = Path("ncit_colorectal_cancer")


def get_json(path, params=None, retries=4):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def compact_list(values):
    seen = set()
    out = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def concept_url(code):
    return f"https://ncit.nci.nih.gov/ncitbrowser/ConceptReport.jsp?dictionary=NCI_Thesaurus&ns=ncit&code={code}"


def property_values(concept, prop_type):
    return compact_list(
        prop.get("value")
        for prop in concept.get("properties", [])
        if prop.get("type") == prop_type
    )


def definition_texts(concept):
    return compact_list(defn.get("definition") for defn in concept.get("definitions", []))


def synonym_rows(concept, relation_types, relation_groups):
    rows = [
        {
            "concept_code": concept["code"],
            "concept_name": concept["name"],
            "term": concept["name"],
            "term_type": "NAME",
            "synonym_type": "Concept_Name",
            "source": "NCIt",
            "source_code": "",
            "sub_source": "",
            "relation_types_to_colorectal_tree": relation_types,
            "relation_groups_to_colorectal_tree": relation_groups,
            "is_preferred_candidate": "Y",
        }
    ]
    for syn in concept.get("synonyms", []):
        rows.append(
            {
                "concept_code": concept["code"],
                "concept_name": concept["name"],
                "term": syn.get("name", ""),
                "term_type": syn.get("termType", ""),
                "synonym_type": syn.get("type", ""),
                "source": syn.get("source", ""),
                "source_code": syn.get("code", ""),
                "sub_source": syn.get("subSource", ""),
                "relation_types_to_colorectal_tree": relation_types,
                "relation_groups_to_colorectal_tree": relation_groups,
                "is_preferred_candidate": "Y"
                if syn.get("type") in {"Preferred_Name", "Display_Name"} or syn.get("termType") == "PT"
                else "N",
            }
        )
    return rows


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    related_seed = read_csv(OUT_DIR / "related_entities.csv")
    by_code = {row["code"]: row for row in related_seed}
    records = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_code = {
            executor.submit(get_json, f"/concept/ncit/{code}", {"include": "full"}): code
            for code in sorted(by_code)
        }
        for idx, future in enumerate(as_completed(future_to_code), start=1):
            code = future_to_code[future]
            print(f"[{idx}/{len(future_to_code)}] fetched related {code}", flush=True)
            records.append(future.result())

    rows = []
    term_rows = []
    for concept in records:
        seed = by_code[concept["code"]]
        rows.append(
            {
                "code": concept["code"],
                "name": concept["name"],
                "active": concept.get("active", ""),
                "concept_status": concept.get("conceptStatus", ""),
                "semantic_types": "|".join(property_values(concept, "Semantic_Type")),
                "umls_cui": "|".join(property_values(concept, "UMLS_CUI")),
                "relation_types": seed["relation_types"],
                "relation_groups": seed["relation_groups"],
                "definitions": " | ".join(definition_texts(concept)),
                "synonym_count": len(concept.get("synonyms", [])),
                "nci_url": concept_url(concept["code"]),
            }
        )
        term_rows.extend(synonym_rows(concept, seed["relation_types"], seed["relation_groups"]))

    with (OUT_DIR / "related_entities_full.jsonl").open("w", encoding="utf-8") as handle:
        for record in sorted(records, key=lambda item: item["code"]):
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    write_csv(
        OUT_DIR / "related_entities_full.csv",
        sorted(rows, key=lambda row: row["name"]),
        [
            "code",
            "name",
            "active",
            "concept_status",
            "semantic_types",
            "umls_cui",
            "relation_types",
            "relation_groups",
            "definitions",
            "synonym_count",
            "nci_url",
        ],
    )
    write_csv(
        OUT_DIR / "related_terms.csv",
        sorted(term_rows, key=lambda row: (row["concept_name"], row["term"].lower())),
        [
            "concept_code",
            "concept_name",
            "term",
            "term_type",
            "synonym_type",
            "source",
            "source_code",
            "sub_source",
            "relation_types_to_colorectal_tree",
            "relation_groups_to_colorectal_tree",
            "is_preferred_candidate",
        ],
    )

    metadata_path = OUT_DIR / "metadata.json"
    with metadata_path.open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    metadata["related_entity_full_record_count"] = len(rows)
    metadata["related_term_count"] = len(term_rows)
    metadata["all_term_count_tree_plus_related"] = metadata.get("term_count", 0) + len(term_rows)
    metadata["related_entity_enriched_at_local"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)

    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
