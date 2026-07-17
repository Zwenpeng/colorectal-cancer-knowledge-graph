#!/usr/bin/env python
import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape


SRC_DIR = Path("ncit_colorectal_cancer")
OUT_DIR = Path("colorectal_knowledge_graph")


NOISE_RELATIONS = {
    "Concept_In_Subset",
    "Has_GDC_Value",
    "Is_Value_For_GDC_Property",
}

VISUAL_EXCLUDED_PREFIXES = (
    "Disease_Excludes_",
)

IMPORTANT_RELATION_PREFIXES = (
    "Disease_Has_",
    "Disease_May_Have_",
    "Disease_Is_",
    "Disease_Mapped_To_Gene",
    "Gene_",
    "Regimen_Has_Accepted_Use_For_Disease",
    "Neoplasm_Has_Special_Category",
)

CATEGORY_COLORS = {
    "Root Concept": "#b91c1c",
    "Disease Concept": "#e11d48",
    "Histology": "#f97316",
    "Anatomic Disease Subtype": "#2563eb",
    "Stage/Grade": "#7c3aed",
    "Clinical Course": "#0891b2",
    "Molecular Disease Subtype": "#16a34a",
    "Gene/Genome": "#0f766e",
    "Molecular Abnormality": "#65a30d",
    "Protein/Gene Product": "#15803d",
    "Anatomic Site": "#1d4ed8",
    "Cell": "#c2410c",
    "Tissue": "#a16207",
    "Finding/Clinical Attribute": "#9333ea",
    "Treatment Regimen": "#be123c",
    "Associated Disease/Neoplasm": "#db2777",
    "Terminology/Data Model": "#64748b",
    "Other Entity": "#475569",
}


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def compact(values, limit=None):
    seen = set()
    out = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if limit and len(out) >= limit:
            break
    return out


def clean_text(text, max_len=900):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def concept_category(name, code, depth):
    lower = name.lower()
    if code == "C2955":
        return "Root Concept", "Disease taxonomy"
    if "ajcc" in lower or "stage" in lower or "tnm" in lower or "grade" in lower:
        return "Stage/Grade", "Clinical stage/course"
    if any(token in lower for token in ["metastatic", "recurrent", "refractory", "resectable", "unresectable", "localized", "advanced", "early stage"]):
        return "Clinical Course", "Clinical stage/course"
    if any(token in lower for token in ["microsatellite", "mismatch repair", "hypermutated", "mutation", "molecular"]):
        return "Molecular Disease Subtype", "Molecular genetics"
    if any(token in lower for token in ["colon", "rectal", "rectosigmoid", "cecum", "sigmoid", "ascending", "transverse", "descending"]):
        if not any(token in lower for token in ["adenocarcinoma", "carcinoma", "sarcoma", "neuroendocrine", "squamous", "mucinous", "signet"]):
            return "Anatomic Disease Subtype", "Anatomy"
    if any(token in lower for token in ["adenocarcinoma", "squamous", "neuroendocrine", "mucinous", "signet", "sarcomatoid", "undifferentiated", "adenosquamous", "in situ", "goblet", "small cell", "large cell"]):
        return "Histology", "Pathology/cytology"
    if depth and str(depth) != "0":
        return "Disease Concept", "Disease taxonomy"
    return "Disease Concept", "Disease taxonomy"


def entity_category(semantic_types, relation_types, name):
    sem = semantic_types.lower()
    rel = relation_types.lower()
    lower = name.lower()
    if "therapeutic or preventive procedure" in sem or "regimen_has_accepted_use" in rel or "regimen" in lower:
        return "Treatment Regimen", "Therapy"
    if "gene or genome" in sem or "gene_" in rel or lower.endswith(" gene"):
        return "Gene/Genome", "Molecular genetics"
    if "molecular dysfunction" in sem or "molecular_abnormality" in rel or "mutation" in lower or "amplification" in lower or "inactivation" in lower:
        return "Molecular Abnormality", "Molecular genetics"
    if "amino acid, peptide, or protein" in sem or "gene_product" in rel:
        return "Protein/Gene Product", "Molecular genetics"
    if "body part" in sem or "anatomical structure" in sem or "body system" in sem or "body location" in sem or "body space" in sem:
        return "Anatomic Site", "Anatomy"
    if "tissue" in sem:
        return "Tissue", "Pathology/cytology"
    if sem == "cell" or "cell" in sem:
        return "Cell", "Pathology/cytology"
    if "finding" in sem or "clinical attribute" in sem or "laboratory or test result" in sem or "sign or symptom" in sem:
        return "Finding/Clinical Attribute", "Phenotype/finding"
    if "disease or syndrome" in sem or "neoplastic process" in sem or "pathologic function" in sem:
        return "Associated Disease/Neoplasm", "Associated conditions"
    if "intellectual product" in sem or "classification" in sem or "terminology" in lower:
        return "Terminology/Data Model", "Terminology/data model"
    return "Other Entity", "Other"


def edge_research_tier(relation_type):
    if relation_type == "is_parent_of":
        return "tree"
    if relation_type in NOISE_RELATIONS:
        return "metadata"
    if relation_type.startswith(VISUAL_EXCLUDED_PREFIXES):
        return "constraint"
    if relation_type.startswith(IMPORTANT_RELATION_PREFIXES):
        return "biomedical"
    return "supporting"


def edge_label(relation_type):
    labels = {
        "is_parent_of": "父类-子类",
        "Disease_Mapped_To_Gene": "疾病-基因映射",
        "Disease_May_Have_Molecular_Abnormality": "可伴随分子异常",
        "Disease_Has_Molecular_Abnormality": "具有分子异常",
        "Disease_Has_Associated_Anatomic_Site": "相关解剖部位",
        "Disease_Has_Primary_Anatomic_Site": "原发解剖部位",
        "Disease_Has_Metastatic_Anatomic_Site": "转移解剖部位",
        "Disease_Has_Abnormal_Cell": "异常细胞",
        "Disease_Has_Normal_Cell_Origin": "正常细胞来源",
        "Disease_Has_Normal_Tissue_Origin": "正常组织来源",
        "Disease_Has_Finding": "伴随 finding",
        "Disease_May_Have_Finding": "可伴随 finding",
        "Disease_Is_Stage": "疾病分期",
        "Disease_Is_Grade": "疾病分级",
        "Disease_Has_Associated_Disease": "相关疾病",
        "Disease_May_Have_Associated_Disease": "可相关疾病",
        "Regimen_Has_Accepted_Use_For_Disease": "治疗方案适应疾病",
        "Gene_Associated_With_Disease": "基因相关疾病",
        "Gene_Involved_In_Pathogenesis_Of_Disease": "致病机制基因",
        "Gene_Product_Malfunction_Associated_With_Disease": "蛋白功能异常相关疾病",
        "Gene_Is_Biomarker_Of": "生物标志物",
        "Neoplasm_Has_Special_Category": "肿瘤特殊类别",
    }
    return labels.get(relation_type, relation_type)


def load_aliases():
    aliases = defaultdict(list)
    for path in [SRC_DIR / "terms.csv", SRC_DIR / "related_terms.csv"]:
        for row in read_csv(path):
            aliases[row["concept_code"]].append(row["term"])
    return {code: compact(values, limit=40) for code, values in aliases.items()}


def build_nodes():
    aliases = load_aliases()
    nodes = {}

    for row in read_csv(SRC_DIR / "concepts.csv"):
        category, axis = concept_category(row["name"], row["code"], row["depth_from_root"])
        nodes[row["code"]] = {
            "id": row["code"],
            "label": row["name"],
            "node_kind": "Concept",
            "in_colorectal_tree": "Y",
            "category": category,
            "research_axis": axis,
            "semantic_types": row["semantic_types"],
            "depth_from_root": row["depth_from_root"],
            "active": row["active"],
            "concept_status": row["concept_status"],
            "umls_cui": row["umls_cui"],
            "icd_o_3_code": row["icd_o_3_code"],
            "definition": clean_text(row["definitions"]),
            "aliases": "|".join(aliases.get(row["code"], [])),
            "alias_count": str(len(aliases.get(row["code"], []))),
            "nci_url": row["nci_url"],
        }

    for row in read_csv(SRC_DIR / "related_entities_full.csv"):
        category, axis = entity_category(row["semantic_types"], row["relation_types"], row["name"])
        nodes[row["code"]] = {
            "id": row["code"],
            "label": row["name"],
            "node_kind": "Entity",
            "in_colorectal_tree": "N",
            "category": category,
            "research_axis": axis,
            "semantic_types": row["semantic_types"],
            "depth_from_root": "",
            "active": row["active"],
            "concept_status": row["concept_status"],
            "umls_cui": row["umls_cui"],
            "icd_o_3_code": "",
            "definition": clean_text(row["definitions"]),
            "aliases": "|".join(aliases.get(row["code"], [])),
            "alias_count": str(len(aliases.get(row["code"], []))),
            "nci_url": row["nci_url"],
        }
    return nodes


def build_edges(nodes):
    seen = set()
    out = []
    for row in read_csv(SRC_DIR / "edges.csv"):
        source = row["source_code"]
        target = row["target_code"]
        if not source or not target or source not in nodes or target not in nodes:
            continue
        relation_type = row["relation_type"]
        key = (source, relation_type, target)
        if key in seen:
            continue
        seen.add(key)
        tier = edge_research_tier(relation_type)
        out.append(
            {
                "source": source,
                "source_label": nodes[source]["label"],
                "relation_code": row["relation_code"],
                "relation_type": relation_type,
                "relation_label_cn": edge_label(relation_type),
                "target": target,
                "target_label": nodes[target]["label"],
                "relation_group": row["relation_group"],
                "direction": row["direction"],
                "research_tier": tier,
            }
        )
    return out


def write_graphml(nodes, edges, path):
    node_keys = [
        "label",
        "node_kind",
        "in_colorectal_tree",
        "category",
        "research_axis",
        "semantic_types",
        "umls_cui",
        "definition",
        "aliases",
        "nci_url",
    ]
    edge_keys = ["relation_type", "relation_label_cn", "relation_group", "research_tier"]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for key in node_keys:
        lines.append(f'<key id="n_{key}" for="node" attr.name="{key}" attr.type="string"/>')
    for key in edge_keys:
        lines.append(f'<key id="e_{key}" for="edge" attr.name="{key}" attr.type="string"/>')
    lines.append('<graph id="ColorectalCancerKG" edgedefault="directed">')
    for node in nodes.values():
        lines.append(f'<node id="{escape(node["id"])}">')
        for key in node_keys:
            lines.append(f'<data key="n_{key}">{escape(str(node.get(key, "")))}</data>')
        lines.append("</node>")
    for idx, edge in enumerate(edges):
        lines.append(f'<edge id="e{idx}" source="{escape(edge["source"])}" target="{escape(edge["target"])}">')
        for key in edge_keys:
            lines.append(f'<data key="e_{key}">{escape(str(edge.get(key, "")))}</data>')
        lines.append("</edge>")
    lines.append("</graph>")
    lines.append("</graphml>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cytoscape(nodes, edges, path):
    elements = {
        "nodes": [{"data": node} for node in nodes.values()],
        "edges": [
            {
                "data": {
                    "id": f"{edge['source']}__{edge['relation_type']}__{edge['target']}",
                    **edge,
                }
            }
            for edge in edges
        ],
    }
    path.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")


def write_html(nodes, edges, path):
    visible_edges = [
        edge for edge in edges
        if edge["research_tier"] in {"tree", "biomedical", "supporting"}
        and edge["relation_type"] not in NOISE_RELATIONS
        and not edge["relation_type"].startswith(VISUAL_EXCLUDED_PREFIXES)
    ]
    visible_node_ids = {edge["source"] for edge in visible_edges} | {edge["target"] for edge in visible_edges} | {"C2955"}
    visible_nodes = [node for node in nodes.values() if node["id"] in visible_node_ids]
    degree = Counter()
    for edge in visible_edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    graph = {
        "nodes": [
            {
                "id": node["id"],
                "label": node["label"],
                "kind": node["node_kind"],
                "category": node["category"],
                "axis": node["research_axis"],
                "semantic": node["semantic_types"],
                "definition": node["definition"],
                "aliases": node["aliases"],
                "url": node["nci_url"],
                "color": CATEGORY_COLORS.get(node["category"], "#475569"),
                "degree": degree[node["id"]],
            }
            for node in visible_nodes
        ],
        "edges": [
            {
                "source": edge["source"],
                "target": edge["target"],
                "type": edge["relation_type"],
                "label": edge["relation_label_cn"],
                "tier": edge["research_tier"],
            }
            for edge in visible_edges
        ],
    }
    categories = sorted({node["category"] for node in visible_nodes})
    relations = sorted({edge["relation_type"] for edge in visible_edges})
    template = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Colorectal Cancer Knowledge Graph</title>
<style>
  body {{ margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; color: #0f172a; background: #f8fafc; }}
  header {{ height: 56px; display: flex; align-items: center; gap: 16px; padding: 0 18px; background: #ffffff; border-bottom: 1px solid #e2e8f0; }}
  h1 {{ font-size: 17px; margin: 0; white-space: nowrap; }}
  input, select, button {{ border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; padding: 7px 9px; font-size: 13px; }}
  button {{ cursor: pointer; }}
  main {{ display: grid; grid-template-columns: 280px 1fr 340px; height: calc(100vh - 56px); }}
  aside {{ overflow: auto; background: #fff; border-right: 1px solid #e2e8f0; padding: 14px; }}
  #details {{ border-left: 1px solid #e2e8f0; border-right: 0; }}
  canvas {{ width: 100%; height: 100%; display: block; background: #f8fafc; }}
  .section {{ margin-bottom: 16px; }}
  .section h2 {{ font-size: 13px; margin: 0 0 8px; color: #334155; }}
  .check {{ display: flex; align-items: center; gap: 7px; margin: 6px 0; font-size: 12px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: 0 0 auto; }}
  .muted {{ color: #64748b; font-size: 12px; line-height: 1.5; }}
  .kv {{ font-size: 12px; margin: 7px 0; line-height: 1.55; }}
  .kv b {{ color: #334155; }}
  .pill {{ display: inline-block; margin: 3px 4px 3px 0; padding: 2px 6px; border-radius: 999px; background: #e2e8f0; font-size: 11px; }}
  a {{ color: #2563eb; text-decoration: none; }}
</style>
</head>
<body>
<header>
  <h1>结直肠癌概念-实体知识图谱</h1>
  <input id="search" placeholder="搜索 NCIt code / 名称 / 同义词" style="width: 300px"/>
  <select id="relationFilter"><option value="">全部关系</option></select>
  <button id="resetBtn">重置视图</button>
  <span class="muted" id="stats"></span>
</header>
<main>
  <aside>
    <div class="section">
      <h2>节点类型</h2>
      <div id="categoryFilters"></div>
    </div>
    <div class="section">
      <h2>使用要点</h2>
      <div class="muted">节点是概念或实体；同义词被压缩为节点属性。拖拽节点可固定位置，点击节点查看定义、别名、NCIt 链接。</div>
    </div>
  </aside>
  <canvas id="graph"></canvas>
  <aside id="details">
    <div class="section">
      <h2>节点详情</h2>
      <div id="nodeDetails" class="muted">点击一个节点。</div>
    </div>
  </aside>
</main>
<script>
const graph = {json.dumps(graph, ensure_ascii=False)};
const categories = {json.dumps(categories, ensure_ascii=False)};
const relations = {json.dumps(relations, ensure_ascii=False)};
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const search = document.getElementById('search');
const relationFilter = document.getElementById('relationFilter');
const categoryFilters = document.getElementById('categoryFilters');
const nodeDetails = document.getElementById('nodeDetails');
const stats = document.getElementById('stats');
let width = 0, height = 0, scale = 1, offsetX = 0, offsetY = 0;
let dragging = null, panning = false, last = null, selected = null;
let activeCategories = new Set(categories);
const nodeById = new Map(graph.nodes.map(n => [n.id, n]));
const adjacency = new Map();
graph.nodes.forEach(n => adjacency.set(n.id, []));
graph.edges.forEach(e => {{ adjacency.get(e.source)?.push(e); adjacency.get(e.target)?.push(e); }});

function init() {{
  relations.forEach(r => {{ const o = document.createElement('option'); o.value = r; o.textContent = r; relationFilter.appendChild(o); }});
  categories.forEach(c => {{
    const label = document.createElement('label');
    label.className = 'check';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true; cb.value = c;
    cb.onchange = () => {{ cb.checked ? activeCategories.add(c) : activeCategories.delete(c); }};
    const dot = document.createElement('span'); dot.className = 'legend-dot'; dot.style.background = colorFor(c);
    label.append(cb, dot, document.createTextNode(c));
    categoryFilters.appendChild(label);
  }});
  graph.nodes.forEach((n, i) => {{
    const angle = i * 2.399963;
    const radius = 40 + Math.sqrt(i) * 18;
    n.x = width / 2 + Math.cos(angle) * radius;
    n.y = height / 2 + Math.sin(angle) * radius;
    n.vx = 0; n.vy = 0; n.fixed = n.id === 'C2955';
    if (n.id === 'C2955') {{ n.x = width / 2; n.y = height / 2; }}
  }});
  resetView();
  requestAnimationFrame(tick);
}}

function colorFor(category) {{
  const n = graph.nodes.find(x => x.category === category);
  return n ? n.color : '#475569';
}}

function resize() {{
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  width = rect.width; height = rect.height;
}}
window.addEventListener('resize', resize);

function passes(n) {{
  if (!activeCategories.has(n.category)) return false;
  const q = search.value.trim().toLowerCase();
  if (!q) return true;
  return (n.id + ' ' + n.label + ' ' + n.aliases).toLowerCase().includes(q);
}}

function visibleEdges() {{
  const rel = relationFilter.value;
  return graph.edges.filter(e => (!rel || e.type === rel) && passes(nodeById.get(e.source)) && passes(nodeById.get(e.target)));
}}

function simulate(edges) {{
  const visibleIds = new Set();
  edges.forEach(e => {{ visibleIds.add(e.source); visibleIds.add(e.target); }});
  graph.nodes.forEach(n => {{ if (passes(n)) visibleIds.add(n.id); }});
  const visible = graph.nodes.filter(n => visibleIds.has(n.id));
  for (let i = 0; i < visible.length; i++) {{
    for (let j = i + 1; j < visible.length; j++) {{
      const a = visible[i], b = visible[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy + 0.01;
      if (d2 > 90000) continue;
      const f = Math.min(1800 / d2, 2.2);
      const d = Math.sqrt(d2);
      dx /= d; dy /= d;
      if (!a.fixed) {{ a.vx += dx * f; a.vy += dy * f; }}
      if (!b.fixed) {{ b.vx -= dx * f; b.vy -= dy * f; }}
    }}
  }}
  edges.forEach(e => {{
    const a = nodeById.get(e.source), b = nodeById.get(e.target);
    let dx = b.x - a.x, dy = b.y - a.y;
    let d = Math.sqrt(dx * dx + dy * dy) || 1;
    const target = e.type === 'is_parent_of' ? 85 : 125;
    const f = (d - target) * 0.012;
    dx /= d; dy /= d;
    if (!a.fixed) {{ a.vx += dx * f; a.vy += dy * f; }}
    if (!b.fixed) {{ b.vx -= dx * f; b.vy -= dy * f; }}
  }});
  graph.nodes.forEach(n => {{
    if (n.fixed) return;
    n.vx += (width / 2 - n.x) * 0.0008;
    n.vy += (height / 2 - n.y) * 0.0008;
    n.vx *= 0.86; n.vy *= 0.86;
    n.x += n.vx; n.y += n.vy;
  }});
}}

function draw(edges) {{
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.translate(offsetX, offsetY);
  ctx.scale(scale, scale);
  ctx.lineWidth = 1 / scale;
  edges.forEach(e => {{
    const a = nodeById.get(e.source), b = nodeById.get(e.target);
    ctx.strokeStyle = e.type === 'is_parent_of' ? 'rgba(51,65,85,.32)' : 'rgba(100,116,139,.18)';
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }});
  const visibleIds = new Set();
  edges.forEach(e => {{ visibleIds.add(e.source); visibleIds.add(e.target); }});
  graph.nodes.filter(n => passes(n) && (visibleIds.has(n.id) || search.value)).forEach(n => {{
    const r = n.id === 'C2955' ? 13 : Math.max(5, Math.min(11, 4 + Math.sqrt(n.degree || 1)));
    ctx.beginPath();
    ctx.fillStyle = n.color;
    ctx.strokeStyle = selected && selected.id === n.id ? '#0f172a' : '#ffffff';
    ctx.lineWidth = selected && selected.id === n.id ? 3 / scale : 1.5 / scale;
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fill(); ctx.stroke();
    if (scale > 0.55 || n.id === 'C2955' || (selected && selected.id === n.id)) {{
      ctx.font = `${{11 / scale}}px Arial`;
      ctx.fillStyle = '#0f172a';
      ctx.fillText(n.label.slice(0, 42), n.x + r + 3, n.y + 4);
    }}
  }});
  ctx.restore();
  stats.textContent = `${{graph.nodes.length}} 节点 / ${{graph.edges.length}} 边；当前显示 ${{edges.length}} 边`;
}}

function tick() {{
  const edges = visibleEdges();
  simulate(edges);
  draw(edges);
  requestAnimationFrame(tick);
}}

function toWorld(evt) {{
  const rect = canvas.getBoundingClientRect();
  return {{ x: (evt.clientX - rect.left - offsetX) / scale, y: (evt.clientY - rect.top - offsetY) / scale }};
}}

function hitTest(point) {{
  let best = null, bestD = 18 / scale;
  graph.nodes.forEach(n => {{
    if (!passes(n)) return;
    const d = Math.hypot(n.x - point.x, n.y - point.y);
    if (d < bestD) {{ best = n; bestD = d; }}
  }});
  return best;
}}

canvas.addEventListener('mousedown', evt => {{
  const p = toWorld(evt);
  const n = hitTest(p);
  last = {{ x: evt.clientX, y: evt.clientY }};
  if (n) {{ dragging = n; n.fixed = true; selected = n; showNode(n); }}
  else {{ panning = true; }}
}});
canvas.addEventListener('mousemove', evt => {{
  if (dragging) {{ const p = toWorld(evt); dragging.x = p.x; dragging.y = p.y; }}
  else if (panning && last) {{ offsetX += evt.clientX - last.x; offsetY += evt.clientY - last.y; last = {{ x: evt.clientX, y: evt.clientY }}; }}
}});
window.addEventListener('mouseup', () => {{ dragging = null; panning = false; }});
canvas.addEventListener('wheel', evt => {{
  evt.preventDefault();
  const old = scale;
  scale *= evt.deltaY < 0 ? 1.12 : 0.89;
  scale = Math.max(0.18, Math.min(3.5, scale));
  const rect = canvas.getBoundingClientRect();
  const mx = evt.clientX - rect.left, my = evt.clientY - rect.top;
  offsetX = mx - (mx - offsetX) * (scale / old);
  offsetY = my - (my - offsetY) * (scale / old);
}});

function showNode(n) {{
  const rels = adjacency.get(n.id).slice(0, 18).map(e => `<span class="pill">${{e.label}}</span>`).join('');
  const aliasText = n.aliases ? n.aliases.split('|').slice(0, 18).map(a => `<span class="pill">${{escapeHtml(a)}}</span>`).join('') : '';
  nodeDetails.innerHTML = `
    <div class="kv"><b>${{escapeHtml(n.label)}}</b> <span class="muted">${{n.id}}</span></div>
    <div class="kv"><b>类型：</b>${{escapeHtml(n.kind)}} / ${{escapeHtml(n.category)}}</div>
    <div class="kv"><b>研究轴：</b>${{escapeHtml(n.axis)}}</div>
    <div class="kv"><b>语义类型：</b>${{escapeHtml(n.semantic || '')}}</div>
    <div class="kv"><b>定义：</b>${{escapeHtml(n.definition || '')}}</div>
    <div class="kv"><b>别名：</b><br/>${{aliasText}}</div>
    <div class="kv"><b>邻接关系：</b><br/>${{rels}}</div>
    <div class="kv"><a href="${{n.url}}" target="_blank">打开 NCIt 页面</a></div>`;
}}
function escapeHtml(s) {{ return String(s).replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m])); }}
function resetView() {{ scale = 0.72; offsetX = width / 2 - (width / 2) * scale; offsetY = height / 2 - (height / 2) * scale; }}
document.getElementById('resetBtn').onclick = resetView;
search.oninput = () => {{}};
relationFilter.onchange = () => {{}};
resize();
init();
</script>
</body>
</html>"""
    path.write_text(template, encoding="utf-8")


def write_readme(nodes, edges, core_edges):
    category_counts = Counter(node["category"] for node in nodes.values())
    relation_counts = Counter(edge["relation_type"] for edge in edges)
    axis_counts = Counter(node["research_axis"] for node in nodes.values())
    readme = f"""# 结直肠癌概念-实体知识图谱说明

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

- 节点总数：{len(nodes)}
- Concept 节点：{sum(1 for node in nodes.values() if node["node_kind"] == "Concept")}
- Entity 节点：{sum(1 for node in nodes.values() if node["node_kind"] == "Entity")}
- 全量边：{len(edges)}
- 研究核心边：{len(core_edges)}

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
Import-Csv .\\colorectal_knowledge_graph\\kg_nodes.csv |
  Where-Object {{ $_.research_axis -eq 'Molecular genetics' }} |
  Export-Csv .\\colorectal_knowledge_graph\\molecular_nodes.csv -NoTypeInformation -Encoding UTF8
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
Import-Csv .\\colorectal_knowledge_graph\\kg_edges.csv |
  Where-Object {{ $keep -contains $_.relation_type }} |
  Export-Csv .\\colorectal_knowledge_graph\\molecular_edges.csv -NoTypeInformation -Encoding UTF8
```

### 7.3 改分类规则

修改 `build_colorectal_kg.py` 中两个函数：

- `concept_category()`：控制树内疾病概念如何分成 Histology、Stage/Grade、Clinical Course 等。
- `entity_category()`：控制树外实体如何分成 Gene、Anatomic Site、Treatment Regimen 等。

改完后重新运行：

```powershell
python .\\build_colorectal_kg.py
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
MERGE (n:NCIt {{id: row.id}})
SET n.label = row.label,
    n.kind = row.node_kind,
    n.category = row.category,
    n.axis = row.research_axis,
    n.aliases = row.aliases,
    n.definition = row.definition,
    n.url = row.nci_url;

LOAD CSV WITH HEADERS FROM 'file:///kg_edges_research_core.csv' AS row
MATCH (s:NCIt {{id: row.source}})
MATCH (t:NCIt {{id: row.target}})
MERGE (s)-[r:NCIT_REL {{type: row.relation_type}}]->(t)
SET r.label_cn = row.relation_label_cn,
    r.group = row.relation_group,
    r.tier = row.research_tier;
```

## 8. 当前类别统计

```json
{json.dumps(dict(category_counts.most_common()), ensure_ascii=False, indent=2)}
```

## 9. 当前研究轴统计

```json
{json.dumps(dict(axis_counts.most_common()), ensure_ascii=False, indent=2)}
```

## 10. 高频关系

```json
{json.dumps(dict(relation_counts.most_common(30)), ensure_ascii=False, indent=2)}
```
"""
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8")


def write_friendly_html(nodes, edges, path):
    degree = Counter()
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1

    graph = {
        "nodes": [
            {
                "id": node["id"],
                "label": node["label"],
                "kind": "概念" if node["node_kind"] == "Concept" else "实体",
                "rawKind": node["node_kind"],
                "category": node["category"],
                "axis": node["research_axis"],
                "semantic": node["semantic_types"],
                "definition": node["definition"],
                "aliases": node["aliases"],
                "url": node["nci_url"],
                "depth": int(node["depth_from_root"] or -1),
                "color": CATEGORY_COLORS.get(node["category"], "#475569"),
                "degree": degree[node["id"]],
            }
            for node in nodes.values()
        ],
        "edges": [
            {
                "source": edge["source"],
                "target": edge["target"],
                "type": edge["relation_type"],
                "label": edge["relation_label_cn"],
                "tier": edge["research_tier"],
            }
            for edge in edges
        ],
    }
    categories = sorted({node["category"] for node in nodes.values()})
    category_counts = Counter(node["category"] for node in nodes.values())
    mode_relation_sets = {
        "overview": [
            "is_parent_of",
            "Disease_Mapped_To_Gene",
            "Disease_May_Have_Molecular_Abnormality",
            "Disease_Has_Primary_Anatomic_Site",
            "Regimen_Has_Accepted_Use_For_Disease",
        ],
        "molecular": [
            "Disease_Mapped_To_Gene",
            "Gene_Associated_With_Disease",
            "Gene_Involved_In_Pathogenesis_Of_Disease",
            "Gene_Product_Malfunction_Associated_With_Disease",
            "Gene_Is_Biomarker_Of",
            "Disease_May_Have_Molecular_Abnormality",
            "Disease_Has_Molecular_Abnormality",
        ],
        "anatomy": [
            "Disease_Has_Primary_Anatomic_Site",
            "Disease_Has_Associated_Anatomic_Site",
            "Disease_Has_Metastatic_Anatomic_Site",
            "Disease_Has_Normal_Tissue_Origin",
            "Disease_Has_Normal_Cell_Origin",
            "Disease_Has_Abnormal_Cell",
        ],
        "clinical": [
            "is_parent_of",
            "Disease_Is_Stage",
            "Disease_Is_Grade",
            "Disease_Has_Finding",
            "Disease_May_Have_Finding",
            "Disease_Has_Associated_Disease",
            "Disease_May_Have_Associated_Disease",
        ],
        "therapy": [
            "Regimen_Has_Accepted_Use_For_Disease",
        ],
    }

    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>结直肠癌概念-实体知识图谱</title>
<style>
  :root {
    --ink: #172033;
    --muted: #667085;
    --line: #d9e2ec;
    --panel: rgba(255,255,255,.92);
    --bg: #eef3f7;
    --blue: #2563eb;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: Arial, "Microsoft YaHei", sans-serif;
    color: var(--ink);
    background:
      radial-gradient(circle at 15% 10%, rgba(37,99,235,.10), transparent 30%),
      radial-gradient(circle at 85% 18%, rgba(22,163,74,.10), transparent 28%),
      linear-gradient(180deg, #f8fbff 0%, var(--bg) 100%);
  }
  header {
    min-height: 82px;
    display: grid;
    grid-template-columns: minmax(340px, 1fr) auto;
    gap: 18px;
    align-items: center;
    padding: 14px 22px;
    background: rgba(255,255,255,.88);
    border-bottom: 1px solid var(--line);
    backdrop-filter: blur(10px);
  }
  h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
  .subtitle { margin-top: 5px; color: var(--muted); font-size: 13px; line-height: 1.45; }
  .topStats { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
  .stat {
    min-width: 92px;
    padding: 8px 11px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
  }
  .stat b { display: block; font-size: 18px; }
  .stat span { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
  main {
    display: grid;
    grid-template-columns: 310px minmax(420px, 1fr) 360px;
    height: calc(100vh - 82px);
    min-height: 620px;
  }
  aside {
    overflow: auto;
    padding: 16px;
    background: var(--panel);
    border-right: 1px solid var(--line);
  }
  #details { border-right: 0; border-left: 1px solid var(--line); }
  .stage { position: relative; min-width: 0; }
  canvas { width: 100%; height: 100%; display: block; }
  .hint {
    position: absolute;
    left: 18px;
    bottom: 18px;
    max-width: 520px;
    padding: 10px 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255,255,255,.88);
    color: var(--muted);
    font-size: 12px;
    line-height: 1.5;
    pointer-events: none;
  }
  .section { margin-bottom: 18px; }
  .section h2 { margin: 0 0 9px; font-size: 14px; }
  .search {
    width: 100%;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 11px;
    font-size: 14px;
    background: #fff;
  }
  .modeGrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  button {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 9px 10px;
    background: #fff;
    color: #253046;
    cursor: pointer;
    font-size: 13px;
    text-align: left;
  }
  button.active {
    border-color: #2563eb;
    background: #eff6ff;
    color: #1d4ed8;
    font-weight: 700;
  }
  .smallButton { width: 100%; text-align: center; }
  .check { display: flex; align-items: center; gap: 8px; margin: 7px 0; font-size: 12px; line-height: 1.35; }
  .check input { width: 15px; height: 15px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
  .muted { color: var(--muted); font-size: 12px; line-height: 1.55; }
  .card {
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
    padding: 12px;
  }
  .kv { margin: 9px 0; font-size: 13px; line-height: 1.6; }
  .kv b { color: #344054; }
  .pill {
    display: inline-block;
    margin: 3px 4px 3px 0;
    padding: 3px 7px;
    border-radius: 999px;
    background: #eef2f7;
    font-size: 11px;
    color: #344054;
  }
  .legendTitle { display: flex; justify-content: space-between; gap: 8px; }
  .catBlock {
    border: 1px solid transparent;
    border-radius: 8px;
    margin: 6px 0;
  }
  .catHeader {
    width: 100%;
    display: grid;
    grid-template-columns: 18px 18px 18px 1fr auto;
    align-items: center;
    gap: 8px;
    border: 0;
    border-radius: 8px;
    padding: 7px 8px;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }
  .catHeader:hover { background: #f8fbff; }
  .catHeader input { width: 15px; height: 15px; margin: 0; }
  .catName { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .catCount { color: var(--muted); font-size: 12px; }
  .chev { color: #64748b; font-size: 13px; text-align: center; }
  .nodeList {
    display: none;
    margin: 2px 0 8px 31px;
    padding: 6px 0 4px 9px;
    border-left: 1px solid #d9e2ec;
    max-height: 230px;
    overflow: auto;
  }
  .catBlock.open .nodeList { display: block; }
  .nodeOption {
    display: grid;
    grid-template-columns: 16px 1fr;
    gap: 6px;
    align-items: start;
    padding: 4px 6px;
    border-radius: 6px;
    font-size: 12px;
    line-height: 1.35;
  }
  .nodeOption:hover { background: #f8fafc; }
  .nodeOption input { width: 14px; height: 14px; margin-top: 1px; }
  .nodeOption span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nodeOption small { display: block; color: #94a3b8; font-size: 10px; margin-top: 1px; }
  .filterTools { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
  .filterTools button { text-align: center; padding: 7px 8px; font-size: 12px; }
  a { color: var(--blue); text-decoration: none; }
  @media (max-width: 1100px) {
    header { grid-template-columns: 1fr; }
    .topStats { justify-content: flex-start; }
    main { grid-template-columns: 260px 1fr; }
    #details { display: none; }
  }
</style>
</head>
<body>
<header>
  <div>
    <h1>结直肠癌概念-实体知识图谱</h1>
    <div class="subtitle">把 NCIt 中的疾病概念、基因、分子异常、解剖部位、病理细胞、finding 和治疗方案组织成可探索网络。打开后默认是“导览视图”，适合先理解全局。</div>
  </div>
  <div class="topStats">
    <div class="stat"><b id="nodeCount">0</b><span>概念/实体</span></div>
    <div class="stat"><b id="edgeCount">0</b><span>当前关系</span></div>
    <div class="stat"><b>NCIt</b><span>C2955 根节点</span></div>
  </div>
</header>
<main>
  <aside>
    <div class="section">
      <h2>搜索</h2>
      <input id="search" class="search" placeholder="输入 CRC、KRAS、Stage、C2955 等"/>
      <div class="muted" style="margin-top:7px">搜索会显示匹配节点和它的一跳邻居。</div>
    </div>
    <div class="section">
      <h2>一键视角</h2>
      <div class="modeGrid">
        <button data-mode="overview" class="active">导览</button>
        <button data-mode="molecular">分子</button>
        <button data-mode="anatomy">解剖/病理</button>
        <button data-mode="clinical">分期/临床</button>
        <button data-mode="therapy">治疗</button>
        <button data-mode="all">全量核心</button>
      </div>
    </div>
    <div class="section">
      <div class="legendTitle"><h2>节点颜色</h2><span class="muted">可勾选</span></div>
      <div class="muted" style="margin-bottom:6px">点击类别名称展开节点清单；勾选类别控制整类，勾选节点控制单个概念/实体。</div>
      <div id="categoryFilters"></div>
    </div>
    <div class="section card">
      <h2>怎么看</h2>
      <div class="muted">圆点是概念或实体，线是 NCIt 关系。中心红点是结直肠癌。越靠近中心越像上位概念；外围按研究主题分区。滚轮缩放，拖拽空白移动画布，点击节点看解释。</div>
    </div>
    <button id="resetBtn" class="smallButton">回到中心</button>
  </aside>
  <section class="stage">
    <canvas id="graph"></canvas>
    <div class="hint" id="hint">当前为导览视图：只显示最能解释领域结构的关系。搜索或切换视角可展开局部网络。</div>
  </section>
  <aside id="details">
    <div class="section">
      <h2>当前节点</h2>
      <div id="nodeDetails" class="card muted">点击图中的圆点，这里会显示它是什么、有哪些别名、和结直肠癌有什么关系。</div>
    </div>
  </aside>
</main>
<script>
const graph = %%GRAPH%%;
const categories = %%CATEGORIES%%;
const categoryCounts = %%CATEGORY_COUNTS%%;
const modeRelations = %%MODE_RELATIONS%%;
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const search = document.getElementById('search');
const filters = document.getElementById('categoryFilters');
const details = document.getElementById('nodeDetails');
const hint = document.getElementById('hint');
let width = 0, height = 0, scale = 1, offsetX = 0, offsetY = 0;
let activeMode = 'overview';
let selected = null, draggingNode = null, panning = false, last = null;
let activeCategories = new Set(categories);
let activeNodeIds = new Set(graph.nodes.map(n => n.id));
const nodeById = new Map(graph.nodes.map(n => [n.id, n]));
const adjacency = new Map(graph.nodes.map(n => [n.id, []]));
graph.edges.forEach(e => {
  adjacency.get(e.source)?.push(e);
  adjacency.get(e.target)?.push(e);
});

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * dpr);
  canvas.height = Math.max(1, rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  width = rect.width; height = rect.height;
  layout();
  draw();
}

function layout() {
  const centerX = width / 2;
  const centerY = height / 2;
  const groups = new Map();
  graph.nodes.forEach(n => {
    if (!groups.has(n.category)) groups.set(n.category, []);
    groups.get(n.category).push(n);
  });
  const ordered = categories.filter(c => c !== 'Root Concept');
  const ringBase = Math.min(width, height) * 0.18;
  const ringStep = Math.max(74, Math.min(width, height) * 0.085);
  ordered.forEach((cat, gi) => {
    const arr = groups.get(cat) || [];
    const sector = (Math.PI * 2) / Math.max(1, ordered.length);
    const mid = -Math.PI / 2 + gi * sector;
    arr.sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label));
    arr.forEach((n, i) => {
      if (n._moved) return;
      const row = Math.floor(i / 18);
      const col = i % 18;
      const spread = Math.min(sector * 0.72, 1.1);
      const denom = Math.max(1, Math.min(17, arr.length - row * 18 - 1));
      const angle = mid - spread / 2 + spread * (col / denom);
      const radius = ringBase + ringStep * (1 + row);
      n.x = centerX + Math.cos(angle) * radius;
      n.y = centerY + Math.sin(angle) * radius;
    });
  });
  const root = nodeById.get('C2955');
  if (root && !root._moved) { root.x = centerX; root.y = centerY; }
}

function setupFilters() {
  const tools = document.createElement('div');
  tools.className = 'filterTools';
  const allBtn = document.createElement('button');
  allBtn.textContent = '全选';
  allBtn.onclick = () => setAllNodes(true);
  const noneBtn = document.createElement('button');
  noneBtn.textContent = '全不选';
  noneBtn.onclick = () => setAllNodes(false);
  tools.append(allBtn, noneBtn);
  filters.appendChild(tools);

  const groups = new Map();
  graph.nodes.forEach(n => {
    if (!groups.has(n.category)) groups.set(n.category, []);
    groups.get(n.category).push(n);
  });
  categories.forEach(cat => {
    const block = document.createElement('div');
    block.className = 'catBlock';
    block.dataset.category = cat;
    const header = document.createElement('div');
    header.className = 'catHeader';
    header.title = '点击展开/收起；勾选框控制这一类全部节点';
    const chev = document.createElement('span');
    chev.className = 'chev';
    chev.textContent = '›';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = true;
    cb.dataset.categoryToggle = cat;
    cb.onclick = evt => evt.stopPropagation();
    cb.onchange = () => setCategoryNodes(cat, cb.checked);
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = colorFor(cat);
    const name = document.createElement('span');
    name.className = 'catName';
    name.textContent = friendlyCategory(cat);
    const count = document.createElement('span');
    count.className = 'catCount';
    count.dataset.categoryCount = cat;
    count.textContent = `${categoryCounts[cat] || 0}/${categoryCounts[cat] || 0}`;
    header.append(chev, cb, dot, name, count);
    header.onclick = () => {
      block.classList.toggle('open');
      chev.textContent = block.classList.contains('open') ? '⌄' : '›';
    };

    const list = document.createElement('div');
    list.className = 'nodeList';
    const arr = (groups.get(cat) || []).slice().sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label));
    arr.forEach(n => {
      const item = document.createElement('label');
      item.className = 'nodeOption';
      const nodeCb = document.createElement('input');
      nodeCb.type = 'checkbox';
      nodeCb.checked = true;
      nodeCb.dataset.nodeToggle = n.id;
      nodeCb.onchange = () => {
        nodeCb.checked ? activeNodeIds.add(n.id) : activeNodeIds.delete(n.id);
        updateCategoryState(cat);
        draw();
      };
      const text = document.createElement('span');
      text.innerHTML = `${escapeHtml(n.label)}<small>${escapeHtml(n.id)}</small>`;
      item.append(nodeCb, text);
      list.appendChild(item);
    });
    block.append(header, list);
    filters.appendChild(block);
  });
  categories.forEach(updateCategoryState);
}

function setAllNodes(checked) {
  activeNodeIds = checked ? new Set(graph.nodes.map(n => n.id)) : new Set();
  activeCategories = checked ? new Set(categories) : new Set();
  filters.querySelectorAll('input[data-node-toggle], input[data-category-toggle]').forEach(input => {
    input.checked = checked;
    input.indeterminate = false;
  });
  updateAllCategoryCounts();
  draw();
}

function setCategoryNodes(cat, checked) {
  graph.nodes.filter(n => n.category === cat).forEach(n => {
    checked ? activeNodeIds.add(n.id) : activeNodeIds.delete(n.id);
    const nodeCb = filters.querySelector(`input[data-node-toggle="${cssEscape(n.id)}"]`);
    if (nodeCb) nodeCb.checked = checked;
  });
  checked ? activeCategories.add(cat) : activeCategories.delete(cat);
  updateCategoryState(cat);
  draw();
}

function updateAllCategoryCounts() {
  categories.forEach(updateCategoryState);
}

function updateCategoryState(cat) {
  const nodes = graph.nodes.filter(n => n.category === cat);
  const selectedCount = nodes.filter(n => activeNodeIds.has(n.id)).length;
  const cb = filters.querySelector(`input[data-category-toggle="${cssEscape(cat)}"]`);
  if (cb) {
    cb.checked = selectedCount > 0;
    cb.indeterminate = selectedCount > 0 && selectedCount < nodes.length;
  }
  selectedCount > 0 ? activeCategories.add(cat) : activeCategories.delete(cat);
  const count = filters.querySelector(`[data-category-count="${cssEscape(cat)}"]`);
  if (count) count.textContent = `${selectedCount}/${nodes.length}`;
}

function colorFor(cat) {
  const node = graph.nodes.find(n => n.category === cat);
  return node ? node.color : '#64748b';
}

function friendlyCategory(cat) {
  return ({
    'Root Concept': '中心概念',
    'Disease Concept': '疾病概念',
    'Histology': '病理亚型',
    'Anatomic Disease Subtype': '部位亚型',
    'Stage/Grade': '分期/分级',
    'Clinical Course': '病程状态',
    'Molecular Disease Subtype': '分子亚型',
    'Gene/Genome': '基因',
    'Molecular Abnormality': '分子异常',
    'Protein/Gene Product': '蛋白',
    'Anatomic Site': '解剖部位',
    'Cell': '细胞',
    'Tissue': '组织',
    'Finding/Clinical Attribute': '临床发现',
    'Treatment Regimen': '治疗方案',
    'Associated Disease/Neoplasm': '相关疾病/肿瘤',
    'Terminology/Data Model': '术语/数据模型',
    'Other Entity': '其他实体'
  })[cat] || cat;
}

function nodePassesCategory(n) {
  return activeCategories.has(n.category) && activeNodeIds.has(n.id);
}

function matchesSearch(n, q) {
  if (!q) return false;
  return (n.id + ' ' + n.label + ' ' + (n.aliases || '') + ' ' + n.category).toLowerCase().includes(q);
}

function isSpotlight(n) {
  if (n.id === 'C2955') return true;
  if (n.rawKind === 'Concept' && n.depth >= 0 && n.depth <= 1) return true;
  if (['Gene/Genome','Molecular Abnormality','Anatomic Site','Treatment Regimen'].includes(n.category) && n.degree >= 8) return true;
  return n.degree >= 65;
}

function edgePassesMode(e) {
  if (activeMode === 'all') return true;
  const allowed = modeRelations[activeMode] || [];
  if (!allowed.includes(e.type)) return false;
  const s = nodeById.get(e.source), t = nodeById.get(e.target);
  if (activeMode === 'overview') {
    if (e.type === 'is_parent_of') return (s.depth <= 1 && s.depth >= 0) || (t.depth <= 1 && t.depth >= 0);
    return isSpotlight(s) || isSpotlight(t);
  }
  if (activeMode === 'clinical') return s.rawKind === 'Concept' || t.rawKind === 'Concept';
  return true;
}

function visibleGraph() {
  const q = search.value.trim().toLowerCase();
  let edges = graph.edges.filter(e => {
    const s = nodeById.get(e.source), t = nodeById.get(e.target);
    if (!nodePassesCategory(s) || !nodePassesCategory(t)) return false;
    return edgePassesMode(e);
  });
  let nodeIds = new Set();
  if (q) {
    const matches = graph.nodes.filter(n => nodePassesCategory(n) && matchesSearch(n, q));
    matches.forEach(n => {
      nodeIds.add(n.id);
      (adjacency.get(n.id) || []).forEach(e => { nodeIds.add(e.source); nodeIds.add(e.target); });
    });
    edges = graph.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
  } else {
    edges.forEach(e => { nodeIds.add(e.source); nodeIds.add(e.target); });
    nodeIds.add('C2955');
  }
  const nodes = graph.nodes.filter(n => nodeIds.has(n.id) && nodePassesCategory(n));
  return { nodes, edges };
}

function draw() {
  const vg = visibleGraph();
  document.getElementById('nodeCount').textContent = vg.nodes.length;
  document.getElementById('edgeCount').textContent = vg.edges.length;
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.translate(offsetX, offsetY);
  ctx.scale(scale, scale);
  drawGrid();
  vg.edges.forEach(e => drawEdge(e));
  vg.nodes.sort((a, b) => a.degree - b.degree).forEach(n => drawNode(n));
  ctx.restore();
}

function drawGrid() {
  ctx.strokeStyle = 'rgba(148,163,184,.16)';
  ctx.lineWidth = 1 / scale;
  const step = 80;
  for (let x = -offsetX / scale % step; x < width / scale; x += step) {
    ctx.beginPath(); ctx.moveTo(x, -offsetY / scale); ctx.lineTo(x, (height - offsetY) / scale); ctx.stroke();
  }
  for (let y = -offsetY / scale % step; y < height / scale; y += step) {
    ctx.beginPath(); ctx.moveTo(-offsetX / scale, y); ctx.lineTo((width - offsetX) / scale, y); ctx.stroke();
  }
}

function drawEdge(e) {
  const s = nodeById.get(e.source), t = nodeById.get(e.target);
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
  const bend = e.type === 'is_parent_of' ? 0 : 18;
  ctx.quadraticCurveTo(mx, my - bend, t.x, t.y);
  ctx.strokeStyle = e.type === 'is_parent_of' ? 'rgba(71,85,105,.34)' : 'rgba(71,85,105,.17)';
  ctx.lineWidth = e.type === 'is_parent_of' ? 1.4 / scale : 1 / scale;
  ctx.stroke();
}

function drawNode(n) {
  const r = n.id === 'C2955' ? 16 : Math.max(5.5, Math.min(13, 5 + Math.sqrt(n.degree || 1) * 0.7));
  ctx.beginPath();
  ctx.fillStyle = n.color;
  ctx.strokeStyle = selected && selected.id === n.id ? '#111827' : '#ffffff';
  ctx.lineWidth = selected && selected.id === n.id ? 3 / scale : 1.7 / scale;
  ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
  ctx.fill(); ctx.stroke();
  const shouldLabel = n.id === 'C2955' || selected?.id === n.id || scale > 0.72 || n.degree >= 70;
  if (shouldLabel) {
    ctx.font = `${Math.max(10, 12 / scale)}px Arial`;
    ctx.fillStyle = '#172033';
    ctx.fillText(n.label.slice(0, 44), n.x + r + 5, n.y + 4);
  }
}

function toWorld(evt) {
  const rect = canvas.getBoundingClientRect();
  return { x: (evt.clientX - rect.left - offsetX) / scale, y: (evt.clientY - rect.top - offsetY) / scale };
}

function hitTest(p) {
  const vg = visibleGraph();
  let best = null, bestD = 18 / scale;
  vg.nodes.forEach(n => {
    const d = Math.hypot(n.x - p.x, n.y - p.y);
    if (d < bestD) { best = n; bestD = d; }
  });
  return best;
}

canvas.addEventListener('mousedown', evt => {
  const p = toWorld(evt);
  const n = hitTest(p);
  last = { x: evt.clientX, y: evt.clientY };
  if (n) { draggingNode = n; selected = n; showNode(n); }
  else { panning = true; }
  draw();
});
canvas.addEventListener('mousemove', evt => {
  if (draggingNode) {
    const p = toWorld(evt);
    draggingNode.x = p.x; draggingNode.y = p.y; draggingNode._moved = true;
    draw();
  } else if (panning && last) {
    offsetX += evt.clientX - last.x;
    offsetY += evt.clientY - last.y;
    last = { x: evt.clientX, y: evt.clientY };
    draw();
  }
});
window.addEventListener('mouseup', () => { draggingNode = null; panning = false; });
canvas.addEventListener('wheel', evt => {
  evt.preventDefault();
  const old = scale;
  scale *= evt.deltaY < 0 ? 1.12 : 0.89;
  scale = Math.max(0.22, Math.min(4, scale));
  const rect = canvas.getBoundingClientRect();
  const mx = evt.clientX - rect.left, my = evt.clientY - rect.top;
  offsetX = mx - (mx - offsetX) * (scale / old);
  offsetY = my - (my - offsetY) * (scale / old);
  draw();
});

function showNode(n) {
  const edges = (adjacency.get(n.id) || []).slice(0, 22);
  const rels = edges.map(e => `<span class="pill">${escapeHtml(e.label)}</span>`).join('');
  const aliases = n.aliases ? n.aliases.split('|').slice(0, 20).map(a => `<span class="pill">${escapeHtml(a)}</span>`).join('') : '<span class="muted">无</span>';
  details.innerHTML = `
    <div class="kv"><b>${escapeHtml(n.label)}</b><br/><span class="muted">${n.id} · ${escapeHtml(n.kind)} · ${escapeHtml(friendlyCategory(n.category))}</span></div>
    <div class="kv"><b>它属于：</b>${escapeHtml(friendlyAxis(n.axis))}</div>
    <div class="kv"><b>简单理解：</b>${escapeHtml(n.definition || 'NCIt 未提供定义。')}</div>
    <div class="kv"><b>同义词/缩写：</b><br/>${aliases}</div>
    <div class="kv"><b>相邻关系：</b><br/>${rels || '<span class="muted">当前视图中没有相邻关系</span>'}</div>
    <div class="kv"><a href="${n.url}" target="_blank">打开 NCIt 原始页面</a></div>`;
}

function friendlyAxis(axis) {
  return ({
    'Clinical stage/course': '临床分期与病程',
    'Pathology/cytology': '病理和细胞学',
    'Molecular genetics': '分子遗传学',
    'Associated conditions': '相关疾病或综合征',
    'Phenotype/finding': '临床发现和表型',
    'Therapy': '治疗方案',
    'Terminology/data model': '术语或数据模型',
    'Anatomy': '解剖结构',
    'Disease taxonomy': '疾病分类'
  })[axis] || axis || '其他';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(String(s));
  return String(s).replace(/["\\]/g, '\\$&');
}

function resetView() {
  scale = 0.78;
  offsetX = width * 0.11;
  offsetY = height * 0.04;
  draw();
}

document.querySelectorAll('button[data-mode]').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('button[data-mode]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeMode = btn.dataset.mode;
    hint.textContent = ({
      overview: '导览视图：保留最能解释领域结构的核心关系，适合外行先看全局。',
      molecular: '分子视图：聚焦基因、分子异常、biomarker 和致病机制。',
      anatomy: '解剖/病理视图：聚焦部位、组织来源、细胞来源和异常细胞。',
      clinical: '分期/临床视图：聚焦 AJCC 分期、分级、临床 finding 和相关疾病。',
      therapy: '治疗视图：聚焦治疗方案与适应疾病。',
      all: '全量核心视图：显示所有研究核心边，节点和线会明显增多。'
    })[activeMode];
    draw();
  };
});
search.oninput = draw;
document.getElementById('resetBtn').onclick = resetView;
window.addEventListener('resize', resize);
setupFilters();
resize();
resetView();
showNode(nodeById.get('C2955'));
</script>
</body>
</html>"""
    replacements = {
        "%%GRAPH%%": json.dumps(graph, ensure_ascii=False),
        "%%CATEGORIES%%": json.dumps(categories, ensure_ascii=False),
        "%%CATEGORY_COUNTS%%": json.dumps(dict(category_counts), ensure_ascii=False),
        "%%MODE_RELATIONS%%": json.dumps(mode_relation_sets, ensure_ascii=False),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    path.write_text(template, encoding="utf-8")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    nodes = build_nodes()
    edges = build_edges(nodes)
    core_edges = [
        edge for edge in edges
        if edge["research_tier"] in {"tree", "biomedical", "supporting"}
        and edge["relation_type"] not in NOISE_RELATIONS
        and not edge["relation_type"].startswith(VISUAL_EXCLUDED_PREFIXES)
    ]

    node_fields = [
        "id",
        "label",
        "node_kind",
        "in_colorectal_tree",
        "category",
        "research_axis",
        "semantic_types",
        "depth_from_root",
        "active",
        "concept_status",
        "umls_cui",
        "icd_o_3_code",
        "definition",
        "aliases",
        "alias_count",
        "nci_url",
    ]
    edge_fields = [
        "source",
        "source_label",
        "relation_code",
        "relation_type",
        "relation_label_cn",
        "target",
        "target_label",
        "relation_group",
        "direction",
        "research_tier",
    ]

    write_csv(OUT_DIR / "kg_nodes.csv", sorted(nodes.values(), key=lambda n: (n["node_kind"], n["category"], n["label"])), node_fields)
    write_csv(OUT_DIR / "kg_edges.csv", sorted(edges, key=lambda e: (e["source_label"], e["relation_type"], e["target_label"])), edge_fields)
    write_csv(OUT_DIR / "kg_edges_research_core.csv", sorted(core_edges, key=lambda e: (e["source_label"], e["relation_type"], e["target_label"])), edge_fields)
    write_graphml(nodes, core_edges, OUT_DIR / "kg_graph.graphml")
    write_cytoscape(nodes, core_edges, OUT_DIR / "kg_cytoscape.json")
    write_friendly_html(nodes, core_edges, OUT_DIR / "kg_browser.html")
    write_readme(nodes, edges, core_edges)

    summary = {
        "source_dir": str(SRC_DIR),
        "node_count": len(nodes),
        "concept_node_count": sum(1 for n in nodes.values() if n["node_kind"] == "Concept"),
        "entity_node_count": sum(1 for n in nodes.values() if n["node_kind"] == "Entity"),
        "edge_count_full": len(edges),
        "edge_count_research_core": len(core_edges),
        "category_counts": dict(Counter(n["category"] for n in nodes.values()).most_common()),
        "research_axis_counts": dict(Counter(n["research_axis"] for n in nodes.values()).most_common()),
        "relation_counts_full_top30": dict(Counter(e["relation_type"] for e in edges).most_common(30)),
        "relation_counts_core": dict(Counter(e["relation_type"] for e in core_edges).most_common()),
    }
    (OUT_DIR / "kg_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
