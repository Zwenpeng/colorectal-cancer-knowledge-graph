# 结直肠癌概念-实体知识图谱说明

## 1. 图谱边界

本图谱以 NCIt `C2955 / Colorectal Carcinoma` 为根节点构建。核心单位只有两类：

- **Concept**：`C2955` 下的结直肠癌概念树节点，例如病理亚型、解剖部位亚型、AJCC 分期、复发/转移/可切除状态等。
- **Entity**：与这些概念通过 NCIt role/association 明确连接的实体，例如基因、分子异常、解剖部位、细胞/组织、finding、治疗方案、相关疾病。

同义词、缩写、定义、UMLS CUI、ICD-O-3、NCIt URL 是节点属性，不作为独立节点。这样做的本质是保持图谱的研究对象为“医学概念/实体”，而不是把词表展开成噪声网络。

## 2. 文件结构

| 文件 | 用途 |
|---|---|
| `kg_nodes.csv` | 核心节点表，适合筛选、实体识别词表构建、Neo4j 导入 |
| `kg_edges.csv` | 全量关系边，保留父子、role、association |
| `kg_edges_research_core.csv` | 研究核心边，去除 subset/GDC 元数据和 excludes 类约束 |
| `kg_cytoscape.json` | Cytoscape.js / Cytoscape Desktop 可读结构 |
| `kg_graph.graphml` | Gephi、yEd、NetworkX 可读结构 |
| `kg_browser.html` | 本地交互式图谱浏览器 |
| `kg_summary.json` | 节点、边、类别统计 |

## 3. 当前规模

- 节点总数：748
- Concept 节点：285
- Entity 节点：463
- 全量边：12741
- 研究核心边：10095

## 4. 节点字段

| 字段 | 含义 |
|---|---|
| `id` | NCIt code，图谱主键 |
| `label` | NCIt preferred concept name |
| `node_kind` | `Concept` 或 `Entity` |
| `in_colorectal_tree` | 是否属于 `C2955` 下位概念树 |
| `category` | 为研究浏览重新归类的节点类别 |
| `research_axis` | 研究轴：疾病分类、分子遗传、病理细胞学、解剖、治疗等 |
| `semantic_types` | NCIt/UMLS 语义类型 |
| `definition` | NCIt 定义，已压缩空白 |
| `aliases` | 同义词、缩写、显示名、来源词，使用 `|` 分隔 |
| `nci_url` | NCIt 原始页面 |

## 5. 边字段

| 字段 | 含义 |
|---|---|
| `source` / `target` | 起点/终点 NCIt code |
| `relation_type` | NCIt 原始关系名 |
| `relation_label_cn` | 中文便读标签 |
| `relation_group` | `hierarchy`、`role`、`association` |
| `research_tier` | `tree`、`biomedical`、`supporting`、`constraint`、`metadata` |

## 6. 研究使用方式

### 6.1 疾病谱系

从 `C2955` 沿 `is_parent_of` 向下走，可得到结直肠癌疾病概念树。适合回答：

- 结直肠癌有哪些病理亚型？
- colon、rectal、rectosigmoid 分支如何组织？
- AJCC v6/v7/v8 分期概念如何挂接？

### 6.2 分子机制

筛选以下关系：

- `Disease_Mapped_To_Gene`
- `Gene_Associated_With_Disease`
- `Gene_Involved_In_Pathogenesis_Of_Disease`
- `Disease_May_Have_Molecular_Abnormality`
- `Disease_Has_Molecular_Abnormality`

可构建“疾病亚型-基因-分子异常”子图，用于候选 biomarker、突变谱、机制综述。

### 6.3 解剖与病理来源

筛选以下关系：

- `Disease_Has_Primary_Anatomic_Site`
- `Disease_Has_Associated_Anatomic_Site`
- `Disease_Has_Normal_Cell_Origin`
- `Disease_Has_Normal_Tissue_Origin`
- `Disease_Has_Abnormal_Cell`

可得到“疾病-部位-组织-细胞”路径，适合病理标注体系和实体抽取规则设计。

### 6.4 治疗方案网络

筛选：

- `Regimen_Has_Accepted_Use_For_Disease`

注意该关系在 NCIt 中常以“方案 -> 疾病”方向出现。若做推荐或检索系统，可在查询层把它视为双向邻接，但不要在原始图中反转覆盖证据方向。

## 7. 如何按你的需求修改

### 7.1 只看某一类节点

直接在 `kg_nodes.csv` 按 `category` 或 `research_axis` 过滤。例如只要分子相关实体：

```powershell
Import-Csv .\colorectal_knowledge_graph\kg_nodes.csv |
  Where-Object { $_.research_axis -eq 'Molecular genetics' } |
  Export-Csv .\colorectal_knowledge_graph\molecular_nodes.csv -NoTypeInformation -Encoding UTF8
```

### 7.2 只保留某些关系

例如只保留疾病-基因-分子异常边：

```powershell
$keep = @(
  'Disease_Mapped_To_Gene',
  'Gene_Associated_With_Disease',
  'Gene_Involved_In_Pathogenesis_Of_Disease',
  'Disease_May_Have_Molecular_Abnormality',
  'Disease_Has_Molecular_Abnormality'
)
Import-Csv .\colorectal_knowledge_graph\kg_edges.csv |
  Where-Object { $keep -contains $_.relation_type } |
  Export-Csv .\colorectal_knowledge_graph\molecular_edges.csv -NoTypeInformation -Encoding UTF8
```

### 7.3 改分类规则

修改 `build_colorectal_kg.py` 中两个函数：

- `concept_category()`：控制树内疾病概念如何分成 Histology、Stage/Grade、Clinical Course 等。
- `entity_category()`：控制树外实体如何分成 Gene、Anatomic Site、Treatment Regimen 等。

改完后重新运行：

```powershell
python .\build_colorectal_kg.py
```

### 7.4 改“研究核心图”的边界

修改脚本顶部：

- `NOISE_RELATIONS`：默认排除 subset/GDC 这类元数据关系。
- `VISUAL_EXCLUDED_PREFIXES`：默认从浏览图中排除 `Disease_Excludes_*` 约束边。
- `IMPORTANT_RELATION_PREFIXES`：控制哪些关系进入 `biomedical` 层。

### 7.5 导入 Neo4j

把 `kg_nodes.csv` 和 `kg_edges_research_core.csv` 放入 Neo4j import 目录后执行：

```cypher
LOAD CSV WITH HEADERS FROM 'file:///kg_nodes.csv' AS row
MERGE (n:NCIt {id: row.id})
SET n.label = row.label,
    n.kind = row.node_kind,
    n.category = row.category,
    n.axis = row.research_axis,
    n.aliases = row.aliases,
    n.definition = row.definition,
    n.url = row.nci_url;

LOAD CSV WITH HEADERS FROM 'file:///kg_edges_research_core.csv' AS row
MATCH (s:NCIt {id: row.source})
MATCH (t:NCIt {id: row.target})
MERGE (s)-[r:NCIT_REL {type: row.relation_type}]->(t)
SET r.label_cn = row.relation_label_cn,
    r.group = row.relation_group,
    r.tier = row.research_tier;
```

## 8. 当前类别统计

```json
{
  "Stage/Grade": 112,
  "Associated Disease/Neoplasm": 107,
  "Gene/Genome": 99,
  "Finding/Clinical Attribute": 93,
  "Clinical Course": 81,
  "Histology": 72,
  "Treatment Regimen": 53,
  "Terminology/Data Model": 39,
  "Cell": 36,
  "Anatomic Site": 21,
  "Disease Concept": 14,
  "Molecular Abnormality": 9,
  "Molecular Disease Subtype": 5,
  "Tissue": 5,
  "Root Concept": 1,
  "Other Entity": 1
}
```

## 9. 当前研究轴统计

```json
{
  "Clinical stage/course": 193,
  "Pathology/cytology": 113,
  "Molecular genetics": 113,
  "Associated conditions": 107,
  "Phenotype/finding": 93,
  "Therapy": 53,
  "Terminology/data model": 39,
  "Anatomy": 21,
  "Disease taxonomy": 15,
  "Other": 1
}
```

## 10. 高频关系

```json
{
  "Disease_May_Have_Molecular_Abnormality": 1503,
  "Disease_Has_Associated_Anatomic_Site": 1438,
  "Disease_Has_Abnormal_Cell": 1392,
  "Disease_Excludes_Finding": 1298,
  "Disease_Has_Finding": 1191,
  "Disease_Mapped_To_Gene": 1140,
  "Disease_Has_Primary_Anatomic_Site": 793,
  "Disease_Excludes_Abnormal_Cell": 777,
  "Disease_Has_Normal_Tissue_Origin": 660,
  "is_parent_of": 571,
  "Concept_In_Subset": 526,
  "Disease_May_Have_Finding": 515,
  "Disease_Has_Normal_Cell_Origin": 387,
  "Disease_Is_Stage": 268,
  "Gene_Associated_With_Disease": 69,
  "Regimen_Has_Accepted_Use_For_Disease": 53,
  "Disease_Is_Grade": 23,
  "Disease_May_Have_Associated_Disease": 22,
  "Disease_Has_Associated_Disease": 21,
  "Gene_Product_Malfunction_Associated_With_Disease": 19,
  "Disease_Excludes_Primary_Anatomic_Site": 18,
  "Disease_Excludes_Normal_Cell_Origin": 17,
  "Disease_Has_Metastatic_Anatomic_Site": 12,
  "Gene_Involved_In_Pathogenesis_Of_Disease": 9,
  "Disease_Has_Molecular_Abnormality": 6,
  "Is_Value_For_GDC_Property": 5,
  "Has_GDC_Value": 5,
  "Gene_Is_Biomarker_Of": 2,
  "Neoplasm_Has_Special_Category": 1
}
```
