# Data Provenance and Scope

## Upstream source

The graph is derived from the National Cancer Institute Thesaurus (NCIt) through the NCI EVSREST API:

```text
https://api-evsrest.nci.nih.gov/api/v1
```

The released snapshot was generated on `2026-05-14` from NCIt version `26.04d`, using `C2955 / Colorectal Carcinoma` as the root concept.

## Extraction boundary

1. Retrieve the complete `C2955` record.
2. Retrieve all descendants of `C2955`.
3. Retrieve the full NCIt record for the root and every descendant.
4. Preserve parent/child hierarchy, roles, associations, inverse roles, and inverse associations.
5. Identify tree-external NCIt concepts directly connected to a tree concept and retrieve their full records.

The result contains 285 in-tree disease concepts and 463 directly connected external NCIt entities.

## Project-level terminology

NCIt stores all records as concepts. This project uses two operational labels:

- `Concept`: an NCIt concept inside the `C2955` descendant tree.
- `Entity`: an NCIt concept outside that tree but directly connected through an NCIt role or association.

This distinction is a graph-boundary convention, not an assertion that NCIt has two incompatible ontological object types.

## Relationship interpretation

- `is_parent_of`: standardized parent-to-child taxonomy edge.
- `role`: NCIt semantic relation such as disease-to-gene, disease-to-stage, or regimen-to-disease.
- `association`: terminology or data-model association; it is not automatically biomedical evidence.

Raw directions are retained. For example, `Regimen_Has_Accepted_Use_For_Disease` is represented as regimen to disease. Graph queries may traverse an edge in either direction, but the stored NCIt assertion is not reversed.

## Derived files

`ncit_colorectal_cancer/` contains the NCIt snapshot and normalized CSV/JSONL tables. `colorectal_knowledge_graph/` is a derived representation that deduplicates exact relation triples, assigns research-facing categories, and produces visualization/export formats.

## Data-use boundary

This repository does not redistribute patient-level records. The project MIT license applies to project-authored code and documentation only. Users are responsible for complying with NCI/NCIt source terms and all applicable rules when reusing upstream terminology or adding their own materials.
