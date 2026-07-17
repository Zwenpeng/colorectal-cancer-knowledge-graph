# Colorectal Cancer Knowledge Graph

[中文](#中文说明) | [English](#english-summary)

## English Summary

This repository contains a local, research-oriented knowledge graph for colorectal carcinoma. It is rooted at the NCI Thesaurus (NCIt) concept `C2955 / Colorectal Carcinoma` and connects the disease taxonomy to explicitly related NCIt concepts, including genes, molecular abnormalities, anatomical sites, pathological findings, stages, and treatment regimens.

The repository also provides a local incremental workflow for extracting concepts and relations from new materials, reviewing candidate entities, producing a separate updated graph, and answering graph-grounded questions with optional PubMed and LLM support.

## 中文说明

这是一个面向结直肠癌研究的本地知识图谱系统。图谱以 NCIt `C2955 / Colorectal Carcinoma` 为根，保留其疾病概念树，并纳入通过 NCIt role 或 association 明确关联的基因、分子异常、解剖部位、细胞/组织、临床 finding、分期和治疗方案。

系统坚持以下数据模型：概念和实体是节点；NCIt 原始关系是边；同义词、定义、UMLS CUI、ICD-O-3、来源和证据句是属性。它用于术语整理、知识浏览、资料增量整理、研究问答和假设生成，不用于替代个体化临床诊疗判断。

## Repository Contents

```text
.
├─ extract_ncit_colorectal.py          # 从 NCIt EVSREST API 获取 C2955 概念树
├─ enrich_related_ncit_entities.py     # 补全树外关联 NCIt 对象及其同义词
├─ build_colorectal_kg.py              # 生成主图谱、HTML、GraphML、Cytoscape JSON
├─ ncit_colorectal_cancer/             # NCIt 原始/中间数据快照
├─ colorectal_knowledge_graph/         # 主知识图谱产物
├─ kg_update_system/                   # 新资料抽取、合并、问答与本地 GUI
├─ scripts/validate_release.py         # 发布数据完整性检查
├─ DATA_PROVENANCE.md                  # 数据来源、版本与边界
├─ CITATION.cff                        # 引用信息
├─ CODE_OF_CONDUCT.md                  # 协作行为规范
└─ SECURITY.md                         # 安全与密钥处理规则
```

## Data Snapshot

| Item | Value |
|---|---|
| Source terminology | NCI Thesaurus (NCIt) |
| API source | NCI EVSREST API |
| Root concept | `C2955 / Colorectal Carcinoma` |
| NCIt version | `26.04d` |
| Snapshot generated | 2026-05-14 |
| Disease-tree concepts | 285 |
| Related external NCIt entities | 463 |
| Total graph nodes | 748 |

Detailed provenance and semantic boundaries are documented in [DATA_PROVENANCE.md](DATA_PROVENANCE.md).

## Documentation Languages

The main README is bilingual. Chinese counterparts are available for the operational documents below:

| English | 中文版 |
|---|---|
| [Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md) |
| [Data Provenance and Scope](DATA_PROVENANCE.md) | [数据来源与范围](DATA_PROVENANCE.zh-CN.md) |
| [Security Policy](SECURITY.md) | [安全策略](SECURITY.zh-CN.md) |
| [Code of Conduct](CODE_OF_CONDUCT.md) | [协作行为规范](CODE_OF_CONDUCT.zh-CN.md) |
| [Changelog](CHANGELOG.md) | [版本记录](CHANGELOG.zh-CN.md) |

`LICENSE` and `CITATION.cff` retain their standard international formats. Their scope and use are explained in the Chinese sections of this README and the Chinese data-provenance document.

## Quick Start

Core graph construction uses Python's standard library.

```powershell
python .\build_colorectal_kg.py
python .\kg_update_system\kg_gui.py
```

Open `http://127.0.0.1:8765` when the GUI starts. The generated main graph can also be opened directly from:

```text
colorectal_knowledge_graph/kg_browser.html
colorectal_knowledge_graph/kg_tree.html
```

Run the release-integrity check:

```powershell
python .\scripts\validate_release.py
```

## Rebuild the NCIt Graph

The bundled data are a versioned snapshot. To refresh it from NCIt, run the following commands in order:

```powershell
python .\extract_ncit_colorectal.py
python .\enrich_related_ncit_entities.py
python .\build_colorectal_kg.py
```

This operation accesses the official NCIt EVSREST API and may change node counts and relationships when NCIt releases a new version.

## Incremental Material Workflow

```powershell
python .\kg_update_system\kg_incremental.py extract `
  --input .\kg_update_system\sample_materials `
  --kg-dir .\colorectal_knowledge_graph `
  --output .\kg_update_system\runs\sample_mini

python .\kg_update_system\kg_incremental.py merge `
  --base-kg .\colorectal_knowledge_graph `
  --mini .\kg_update_system\runs\sample_mini `
  --output .\kg_update_system\runs\updated_kg
```

The merge command writes a new graph directory and does not overwrite `colorectal_knowledge_graph`. New candidate entities require explicit review and `--accept-candidates` before inclusion.

## Optional LLM Configuration

Copy the safe template before enabling LLM-enhanced extraction or answers:

```powershell
Copy-Item .\kg_update_system\config.example.json .\kg_update_system\config.deepseek.json
$env:KG_LLM_API_KEY="your-provider-key"
```

The local AI configuration is intentionally excluded from Git. Do not commit API keys, clinical records, or unredacted sensitive materials.

## Citation

If this repository supports your work, cite the software metadata in [CITATION.cff](CITATION.cff) and cite NCIt as the upstream terminology source. See [DATA_PROVENANCE.md](DATA_PROVENANCE.md) for the exact snapshot details.

## Contributing

Contribution conventions are described in [CONTRIBUTING.md](CONTRIBUTING.md). Please also follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and avoid submitting patient-identifiable data, API keys, or unredacted clinical materials.

## Limitations

- NCIt role and association relations are terminology assertions, not patient-specific clinical recommendations.
- `Disease_May_Have_*` describes a possible relationship; it does not mean every patient has that feature.
- LLM-extracted candidate entities and relations require human review against source evidence.
- The repository contains no patient-level data; users must not add identifiable medical information to a public fork.

## License

Project code is released under the [MIT License](LICENSE). Upstream NCIt data retain their own provenance and usage conditions; the repository license does not supersede those conditions.
