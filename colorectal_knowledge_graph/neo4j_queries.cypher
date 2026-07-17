// 结直肠癌概念-实体知识图谱：Neo4j 常用查询
// 先按 README.md 中的 LOAD CSV 语句导入 kg_nodes.csv 与 kg_edges_research_core.csv。

// 1. 查看根节点的一跳概念/实体邻域
MATCH (root:NCIt {id: "C2955"})-[r:NCIT_REL]-(n:NCIt)
RETURN root.label AS root, type(r) AS neo4j_type, r.type AS relation, n.id AS id, n.label AS label, n.kind AS kind, n.category AS category
ORDER BY relation, label;

// 2. 结直肠癌下所有疾病概念树边
MATCH p = (:NCIt {id: "C2955"})-[:NCIT_REL*1..6]->(n:NCIt)
WHERE ALL(rel IN relationships(p) WHERE rel.type = "is_parent_of")
RETURN p
LIMIT 300;

// 3. 疾病概念 -> 基因/分子异常
MATCH (d:NCIt)-[r:NCIT_REL]->(e:NCIt)
WHERE d.kind = "Concept"
  AND r.type IN [
    "Disease_Mapped_To_Gene",
    "Disease_May_Have_Molecular_Abnormality",
    "Disease_Has_Molecular_Abnormality"
  ]
RETURN d.id AS disease_id, d.label AS disease, r.type AS relation, e.id AS entity_id, e.label AS entity, e.category AS entity_category
ORDER BY disease, relation, entity;

// 4. 指定基因关联到哪些结直肠癌概念
MATCH (g:NCIt)<-[r:NCIT_REL]-(d:NCIt)
WHERE toLower(g.label) CONTAINS "kras"
RETURN g.id AS gene_id, g.label AS gene, r.type AS relation, d.id AS disease_id, d.label AS disease
ORDER BY disease;

// 5. 解剖部位-疾病概念网络
MATCH (d:NCIt)-[r:NCIT_REL]->(a:NCIt)
WHERE r.type IN [
  "Disease_Has_Primary_Anatomic_Site",
  "Disease_Has_Associated_Anatomic_Site",
  "Disease_Has_Metastatic_Anatomic_Site"
]
RETURN d.label AS disease, r.type AS relation, a.label AS anatomic_site
ORDER BY anatomic_site, disease;

// 6. 病理/细胞/组织来源网络
MATCH (d:NCIt)-[r:NCIT_REL]->(e:NCIt)
WHERE r.type IN [
  "Disease_Has_Abnormal_Cell",
  "Disease_Has_Normal_Cell_Origin",
  "Disease_Has_Normal_Tissue_Origin",
  "Disease_Has_Finding",
  "Disease_May_Have_Finding"
]
RETURN d.label AS disease, r.type AS relation, e.label AS entity, e.category AS category
ORDER BY disease, relation, entity;

// 7. 治疗方案适应疾病
MATCH (regimen:NCIt)-[r:NCIT_REL]->(d:NCIt)
WHERE r.type = "Regimen_Has_Accepted_Use_For_Disease"
RETURN regimen.id AS regimen_id, regimen.label AS regimen, d.id AS disease_id, d.label AS disease
ORDER BY regimen;

// 8. 按同义词检索实体/概念
MATCH (n:NCIt)
WHERE toLower(n.aliases) CONTAINS "crc"
RETURN n.id AS id, n.label AS label, n.kind AS kind, n.category AS category, n.aliases AS aliases
LIMIT 50;
