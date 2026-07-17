#!/usr/bin/env python
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://api-evsrest.nci.nih.gov/api/v1"
ROOT_CODE = "C2955"
ROOT_NAME = "Colorectal Carcinoma"
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


def semantic_types(concept):
    return compact_list(
        prop.get("value")
        for prop in concept.get("properties", [])
        if prop.get("type") == "Semantic_Type"
    )


def property_values(concept, prop_type):
    return compact_list(
        prop.get("value")
        for prop in concept.get("properties", [])
        if prop.get("type") == prop_type
    )


def definition_texts(concept):
    return compact_list(defn.get("definition") for defn in concept.get("definitions", []))


def synonym_rows(concept):
    rows = []
    rows.append(
        {
            "concept_code": concept["code"],
            "concept_name": concept["name"],
            "term": concept["name"],
            "term_type": "NAME",
            "synonym_type": "Concept_Name",
            "source": "NCIt",
            "source_code": "",
            "sub_source": "",
            "is_preferred_candidate": "Y",
        }
    )
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
                "is_preferred_candidate": "Y"
                if syn.get("type") in {"Preferred_Name", "Display_Name"} or syn.get("termType") == "PT"
                else "N",
            }
        )
    return rows


def edge_rows(concept):
    rows = []
    source_code = concept["code"]
    source_name = concept["name"]

    for parent in concept.get("parents", []):
        rows.append(
            {
                "source_code": parent.get("code", ""),
                "source_name": parent.get("name", ""),
                "relation_code": "is_parent_of",
                "relation_type": "is_parent_of",
                "target_code": source_code,
                "target_name": source_name,
                "relation_group": "hierarchy",
                "direction": "parent_to_child",
            }
        )

    for child in concept.get("children", []):
        rows.append(
            {
                "source_code": source_code,
                "source_name": source_name,
                "relation_code": "is_parent_of",
                "relation_type": "is_parent_of",
                "target_code": child.get("code", ""),
                "target_name": child.get("name", ""),
                "relation_group": "hierarchy",
                "direction": "parent_to_child",
            }
        )

    for key, group, direction in [
        ("associations", "association", "out"),
        ("inverseAssociations", "association", "in"),
        ("roles", "role", "out"),
        ("inverseRoles", "role", "in"),
    ]:
        for rel in concept.get(key, []):
            rows.append(
                {
                    "source_code": source_code if direction == "out" else rel.get("relatedCode", ""),
                    "source_name": source_name if direction == "out" else rel.get("relatedName", ""),
                    "relation_code": rel.get("code", ""),
                    "relation_type": rel.get("type", ""),
                    "target_code": rel.get("relatedCode", "") if direction == "out" else source_code,
                    "target_name": rel.get("relatedName", "") if direction == "out" else source_name,
                    "relation_group": group,
                    "direction": direction,
                }
            )
    return rows


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    OUT_DIR.mkdir(exist_ok=True)

    root = get_json(f"/concept/ncit/{ROOT_CODE}", {"include": "full"})
    descendants = get_json(
        f"/concept/ncit/{ROOT_CODE}/descendants",
        {"include": "summary", "fromRecord": 0, "pageSize": 10000, "maxLevel": 10000},
    )
    metadata = get_json("/metadata/ncit")
    version = root.get("version", "")

    codes = [ROOT_CODE] + [item["code"] for item in descendants]
    full_records = []
    for idx, code in enumerate(codes, start=1):
        print(f"[{idx}/{len(codes)}] fetching {code}", flush=True)
        full_records.append(get_json(f"/concept/ncit/{code}", {"include": "full"}))

    descendant_by_code = {item["code"]: item for item in descendants}
    depth_by_code = {ROOT_CODE: 0}
    depth_by_code.update({code: item.get("level", "") for code, item in descendant_by_code.items()})

    tree_codes = {record["code"] for record in full_records}
    concept_rows = []
    term_rows = []
    edge_rows_all = []

    for concept in full_records:
        concept_rows.append(
            {
                "code": concept["code"],
                "name": concept["name"],
                "root_code": ROOT_CODE,
                "root_name": ROOT_NAME,
                "depth_from_root": depth_by_code.get(concept["code"], ""),
                "leaf": concept.get("leaf", ""),
                "active": concept.get("active", ""),
                "concept_status": concept.get("conceptStatus", ""),
                "semantic_types": "|".join(semantic_types(concept)),
                "neoplastic_status": "|".join(property_values(concept, "Neoplastic_Status")),
                "umls_cui": "|".join(property_values(concept, "UMLS_CUI")),
                "icd_o_3_code": "|".join(property_values(concept, "ICD-O-3_Code")),
                "legacy_concept_name": "|".join(property_values(concept, "Legacy Concept Name")),
                "definitions": " | ".join(definition_texts(concept)),
                "synonym_count": len(concept.get("synonyms", [])),
                "parent_codes": "|".join(parent.get("code", "") for parent in concept.get("parents", [])),
                "parent_names": "|".join(parent.get("name", "") for parent in concept.get("parents", [])),
                "child_codes": "|".join(child.get("code", "") for child in concept.get("children", [])),
                "nci_url": concept_url(concept["code"]),
            }
        )
        term_rows.extend(synonym_rows(concept))
        edge_rows_all.extend(edge_rows(concept))

    # 去重，保留树外但被 NCIt 关系明确连接的实体。
    related_entities = {}
    for edge in edge_rows_all:
        for side in ["source", "target"]:
            code = edge[f"{side}_code"]
            name = edge[f"{side}_name"]
            if not code or code in tree_codes:
                continue
            related_entities.setdefault(
                code,
                {
                    "code": code,
                    "name": name,
                    "in_colorectal_tree": "N",
                    "relation_types": set(),
                    "relation_groups": set(),
                    "nci_url": concept_url(code),
                },
            )
            related_entities[code]["relation_types"].add(edge["relation_type"])
            related_entities[code]["relation_groups"].add(edge["relation_group"])

    related_rows = []
    for entity in related_entities.values():
        related_rows.append(
            {
                "code": entity["code"],
                "name": entity["name"],
                "in_colorectal_tree": entity["in_colorectal_tree"],
                "relation_types": "|".join(sorted(entity["relation_types"])),
                "relation_groups": "|".join(sorted(entity["relation_groups"])),
                "nci_url": entity["nci_url"],
            }
        )

    all_entity_rows = [
        {
            "code": row["code"],
            "name": row["name"],
            "in_colorectal_tree": "Y",
            "relation_types": "descendant_of_root",
            "relation_groups": "hierarchy",
            "nci_url": row["nci_url"],
        }
        for row in concept_rows
    ] + related_rows

    with (OUT_DIR / "concepts_full.jsonl").open("w", encoding="utf-8") as handle:
        for record in full_records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    with (OUT_DIR / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "source": "NCI EVSRESTAPI",
                "terminology": "ncit",
                "version": version,
                "root_code": ROOT_CODE,
                "root_name": ROOT_NAME,
                "root_query_term": "Colorectal Cancer",
                "concept_tree_count_including_root": len(concept_rows),
                "descendant_count": len(descendants),
                "term_count": len(term_rows),
                "edge_count": len(edge_rows_all),
                "related_entity_count_outside_tree": len(related_rows),
                "all_entity_count_tree_plus_related": len(all_entity_rows),
                "api_base_url": BASE_URL,
                "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
                "metadata_role_count": len(metadata.get("roles", [])),
                "metadata_association_count": len(metadata.get("associations", [])),
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    write_csv(
        OUT_DIR / "concepts.csv",
        sorted(concept_rows, key=lambda row: (int(row["depth_from_root"] or 0), row["name"])),
        [
            "code",
            "name",
            "root_code",
            "root_name",
            "depth_from_root",
            "leaf",
            "active",
            "concept_status",
            "semantic_types",
            "neoplastic_status",
            "umls_cui",
            "icd_o_3_code",
            "legacy_concept_name",
            "definitions",
            "synonym_count",
            "parent_codes",
            "parent_names",
            "child_codes",
            "nci_url",
        ],
    )
    write_csv(
        OUT_DIR / "terms.csv",
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
            "is_preferred_candidate",
        ],
    )
    write_csv(
        OUT_DIR / "edges.csv",
        sorted(edge_rows_all, key=lambda row: (row["source_name"], row["relation_type"], row["target_name"])),
        [
            "source_code",
            "source_name",
            "relation_code",
            "relation_type",
            "target_code",
            "target_name",
            "relation_group",
            "direction",
        ],
    )
    write_csv(
        OUT_DIR / "related_entities.csv",
        sorted(related_rows, key=lambda row: row["name"]),
        ["code", "name", "in_colorectal_tree", "relation_types", "relation_groups", "nci_url"],
    )
    write_csv(
        OUT_DIR / "all_entities.csv",
        sorted(all_entity_rows, key=lambda row: (row["in_colorectal_tree"], row["name"])),
        ["code", "name", "in_colorectal_tree", "relation_types", "relation_groups", "nci_url"],
    )

    print(json.dumps(json.load((OUT_DIR / "metadata.json").open(encoding="utf-8")), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
