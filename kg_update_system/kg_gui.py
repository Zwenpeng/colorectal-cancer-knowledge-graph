#!/usr/bin/env python
import argparse
import base64
import html
import json
import os
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from kg_incremental import (
    DEFAULT_OUT_DIR,
    answer_question,
    build_mini_kg,
    call_chat_api,
    load_config,
    merge_kg,
)


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = Path(__file__).resolve().parent
DEFAULT_KG_DIR = ROOT / "colorectal_knowledge_graph"
DEFAULT_CONFIG = SYSTEM_DIR / "config.deepseek.json"
GUI_RUN_DIR = SYSTEM_DIR / "runs" / "gui"
UPLOAD_DIR = GUI_RUN_DIR / "uploads"


def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def html_response(handler, html):
    data = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def file_response(handler, path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        json_response(handler, {"error": "文件不存在", "path": str(path)}, status=404)
        return
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        content_type = "text/html; charset=utf-8"
    elif suffix in {".md", ".txt"}:
        content_type = "text/plain; charset=utf-8"
    elif suffix == ".json":
        content_type = "application/json; charset=utf-8"
    else:
        content_type = "application/octet-stream"
    if suffix in {".md", ".txt", ".json"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gb18030", errors="ignore")
        if suffix == ".md":
            html_page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{html.escape(path.name)}</title><style>body{{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f4f8fc;color:#162033}}main{{max-width:980px;margin:0 auto;padding:24px}}pre{{white-space:pre-wrap;background:#fff;border:1px solid #d9e2ec;border-radius:8px;padding:16px;line-height:1.6}}</style></head><body><main><h1>{html.escape(path.name)}</h1><pre>{html.escape(text)}</pre></main></body></html>"""
            html_response(handler, html_page)
            return
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def safe_path(text):
    return Path(str(text or "").strip().strip('"')).expanduser()


def resolve_path(text, default=None):
    if not text:
        return default
    path = safe_path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path


def write_gui_input(text):
    ts = time.strftime("%Y%m%d_%H%M%S")
    input_dir = GUI_RUN_DIR / "inputs" / ts
    input_dir.mkdir(parents=True, exist_ok=True)
    file = input_dir / "pasted_material.txt"
    file.write_text(text, encoding="utf-8")
    return input_dir


def write_text_and_files(text, files):
    ts = time.strftime("%Y%m%d_%H%M%S")
    batch_dir = GUI_RUN_DIR / "mixed_inputs" / ts
    batch_dir.mkdir(parents=True, exist_ok=True)
    if text.strip():
        (batch_dir / "pasted_material.txt").write_text(text, encoding="utf-8")
    for item in files or []:
        name = Path(item.get("name") or "upload.bin").name
        data = item.get("data") or ""
        if "," in data and data.startswith("data:"):
            data = data.split(",", 1)[1]
        raw = base64.b64decode(data.encode("utf-8")) if data else b""
        (batch_dir / name).write_bytes(raw)
    return batch_dir


def save_uploaded_files(files):
    ts = time.strftime("%Y%m%d_%H%M%S")
    batch_dir = UPLOAD_DIR / ts
    batch_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in files:
        name = Path(item.get("name") or "upload.bin").name
        data = item.get("data") or ""
        if "," in data and data.startswith("data:"):
            data = data.split(",", 1)[1]
        raw = base64.b64decode(data.encode("utf-8")) if data else b""
        target = batch_dir / name
        target.write_bytes(raw)
        saved.append(str(target))
    return batch_dir, saved


def save_single_upload(file_item):
    batch_dir, saved = save_uploaded_files([file_item])
    return batch_dir, saved[0] if saved else ""


def load_llm_config(config_path):
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if path.exists():
        return load_config(path)
    return {"llm": {"enabled": False}}


def config_has_api_key(config_path=DEFAULT_CONFIG):
    if os.getenv("KG_LLM_API_KEY"):
        return True
    if not Path(config_path).exists():
        return False
    try:
        llm = load_config(config_path).get("llm", {})
    except Exception:
        return False
    if llm.get("api_key"):
        return True
    api_key_env = llm.get("api_key_env", "")
    if api_key_env.startswith("sk-"):
        return True
    return bool(api_key_env and os.getenv(api_key_env))


def config_summary(config_path=DEFAULT_CONFIG):
    path = Path(config_path)
    summary = {
        "path": str(path),
        "exists": path.exists(),
        "enabled": False,
        "base_url": "",
        "model": "",
        "api_key_present": False,
        "api_key_source": "none",
    }
    if not path.exists():
        return summary
    try:
        llm = load_config(path).get("llm", {})
    except Exception:
        return summary
    summary["enabled"] = bool(llm.get("enabled", False))
    summary["base_url"] = llm.get("base_url", "")
    summary["model"] = llm.get("model", "")
    if llm.get("api_key"):
        summary["api_key_present"] = True
        summary["api_key_source"] = "config.api_key"
    elif str(llm.get("api_key_env", "")).startswith("sk-"):
        summary["api_key_present"] = True
        summary["api_key_source"] = "config.api_key_env_direct"
    elif llm.get("api_key_env") and os.getenv(llm.get("api_key_env")):
        summary["api_key_present"] = True
        summary["api_key_source"] = f"env:{llm.get('api_key_env')}"
    return summary


def page_html():
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>结直肠癌知识图谱工作台</title>
<style>
:root{--ink:#162033;--muted:#667085;--line:#d9e2ec;--bg:#f4f8fc;--blue:#2563eb;--green:#0f766e;--orange:#f97316;--pink:#db2777;--slate:#475569}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;color:var(--ink);background:linear-gradient(180deg,#fbfdff 0%,var(--bg) 100%)}
header{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 20px;background:rgba(255,255,255,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(8px)}
h1{margin:0;font-size:20px}.sub{font-size:12px;color:var(--muted);margin-top:4px}
.status{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.badge{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 10px;font-size:12px}
main{display:grid;grid-template-columns:320px 1fr;min-height:calc(100vh - 70px)}
aside{background:#fff;border-right:1px solid var(--line);padding:16px;overflow:auto}
.content{padding:16px;overflow:auto}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:12px}
.layer{border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:8px;background:#fff}.layer b{display:block;margin-bottom:5px}.arrow{text-align:center;color:#94a3b8;margin:-2px 0 6px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.tab{border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:9px 12px;cursor:pointer}.tab.active{border-color:var(--blue);background:#eff6ff;color:#1d4ed8;font-weight:700}
label{display:block;font-size:13px;margin:10px 0 6px;color:#344054}input,textarea,select{width:100%;border:1px solid #cbd5e1;border-radius:8px;padding:10px;font-size:14px;background:#fff}textarea{min-height:142px;resize:vertical;line-height:1.5}
button{border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:10px 13px;cursor:pointer;font-size:14px}button.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:700}button.good{background:var(--green);border-color:var(--green);color:#fff;font-weight:700}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}.muted{color:var(--muted);font-size:12px;line-height:1.55}
.result{white-space:pre-wrap;background:#0f172a;color:#e5eefb;border-radius:8px;padding:12px;max-height:360px;overflow:auto;font-size:12px;line-height:1.5}.friendly{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;line-height:1.65}
.pill{display:inline-block;margin:3px 4px 3px 0;padding:3px 8px;background:#eef2f7;border-radius:999px;font-size:12px}.node{border-left:4px solid var(--blue);padding:8px 10px;background:#f8fafc;margin:7px 0;border-radius:6px}.edge{border-left:4px solid var(--green);padding:8px 10px;background:#f8fafc;margin:7px 0;border-radius:6px}
.answer-shell{background:transparent;border:0;padding:0}.answer-hero{background:#fff;border:1px solid #bfdbfe;border-left:6px solid var(--blue);border-radius:8px;padding:18px;margin-bottom:12px;box-shadow:0 10px 26px rgba(37,99,235,.09)}.answer-hero.comprehensive{border-color:#c7d2fe;border-left-color:#7c3aed;background:linear-gradient(180deg,#fff 0%,#f8f7ff 100%)}.answer-hero h3{margin:0 0 8px;font-size:19px}.answer-text{font-size:15px;line-height:1.8;white-space:pre-wrap}.answer-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.answer-section{background:#fff;border:1px solid var(--line);border-radius:8px;padding:13px;min-height:110px}.answer-section h3{margin:0 0 8px;font-size:15px}.answer-section p{margin:0;white-space:pre-wrap}.answer-section.graph{border-left:5px solid var(--blue)}.answer-section.pubmed{border-left:5px solid var(--green)}.answer-section.ai{border-left:5px solid #7c3aed}.answer-section.limit{border-left:5px solid var(--orange)}.evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}.evidence-grid .answer-section{max-height:420px;overflow:auto}.source-tag{font-size:12px;color:#475467;margin-bottom:8px}.loading{background:#fff;border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:8px;padding:14px}
.chatbar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:10px}.chatbar b{font-size:14px}.chat-actions{display:flex;gap:8px;flex-wrap:wrap}.chat-thread{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px;max-height:520px;overflow:auto}.chat-empty{color:var(--muted);font-size:13px}.msg{display:grid;gap:5px;margin:10px 0}.msg .bubble{max-width:86%;border-radius:8px;padding:10px 12px;white-space:pre-wrap;line-height:1.65}.msg.user{justify-items:end}.msg.user .bubble{background:#eff6ff;border:1px solid #bfdbfe}.msg.assistant{justify-items:start}.msg.assistant .bubble{background:#f8fafc;border:1px solid var(--line)}.msg-meta{font-size:11px;color:var(--muted)}.memory-note{border:1px solid #c7d2fe;background:#f8f7ff;color:#4338ca;border-radius:8px;padding:9px 10px;font-size:12px;line-height:1.55}
.viewer{width:100%;height:68vh;min-height:520px;border:1px solid var(--line);border-radius:8px;background:#fff}
.quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.quick button{text-align:left;min-height:82px}.quick b{display:block;margin-bottom:5px}
.pathgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.pathcard{border:1px solid var(--line);border-radius:8px;background:#fff;padding:11px;cursor:pointer}.pathcard:hover{border-color:var(--blue);background:#f8fbff}.pathcard b{display:block;margin-bottom:5px}.pathcard code{font-size:11px;color:#475467;word-break:break-all}
.guide{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.step{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px}.step b{display:block;margin-bottom:4px}
.dropzone{border:1.5px dashed #94a3b8;border-radius:10px;background:#f8fafc;padding:14px;min-height:150px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:8px}
.dropzone.drag{border-color:var(--blue);background:#eff6ff}
.split{display:grid;grid-template-columns:1.1fr .9fr;gap:12px}
.mini{font-size:12px;color:var(--muted)}
.hidden{display:none}.small{font-size:12px}.ok{color:var(--green)}.warn{color:var(--orange)}
@media(max-width:1060px){main{grid-template-columns:1fr}aside{display:none}.row,.pathgrid,.guide,.split,.answer-grid,.evidence-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div><h1>结直肠癌知识图谱工作台</h1><div class="sub">主图谱 · 更新图谱 · 树状结构 · 新资料抽取 · Obsidian 联动</div></div>
  <div class="status"><span class="badge" id="apiBadge">API 未检测</span><span class="badge">本地 GUI</span></div>
</header>
<main>
<aside>
  <div class="layer"><b>数据输入层</b><span class="muted">NCIt术语 / PubMed文献 / 指南 / 病历 / 新资料</span></div>
  <div class="arrow">↓</div>
  <div class="layer"><b>知识抽取层</b><span class="muted">NER实体识别 → 关系抽取 → 事件抽取 → 属性补全</span></div>
  <div class="arrow">↓</div>
  <div class="layer"><b>知识存储层</b><span class="muted">图数据库 Neo4j + 向量库 Chroma + 元数据 SQLite<br/>当前实现：CSV/GraphML/JSON + 可扩展接口</span></div>
  <div class="arrow">↓</div>
  <div class="layer"><b>应用层</b><span class="muted">知识图谱可视化 / 智能问答 GraphRAG / 知识更新 / Obsidian 笔记</span></div>
  <div class="card">
    <b>当前目录</b>
    <div class="muted" id="cwd"></div>
  </div>
  <div class="card">
    <b>默认路径</b>
    <div class="muted">主图谱<br/><code>colorectal_knowledge_graph</code></div>
    <div class="muted" style="margin-top:8px">DeepSeek配置<br/><code>kg_update_system/config.deepseek.json</code></div>
  </div>
</aside>
<section class="content">
  <div class="card">
    <div class="guide">
      <div class="step"><b>1. 提问</b><span class="muted">直接问概念、关系、机制、治疗。</span></div>
      <div class="step"><b>2. 加资料</b><span class="muted">拖拽 Word / PDF / 图片 / 文本。</span></div>
      <div class="step"><b>3. 审核</b><span class="muted">看小图谱、树状结构、Markdown。</span></div>
      <div class="step"><b>4. 更新</b><span class="muted">合并主图谱并同步到 Obsidian。</span></div>
    </div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="ask">智能问答</button>
    <button class="tab" data-tab="extract">新资料抽取</button>
    <button class="tab" data-tab="merge">合并更新</button>
    <button class="tab" data-tab="view">图谱浏览</button>
    <button class="tab" data-tab="tree">树状结构</button>
    <button class="tab" data-tab="settings">设置</button>
  </div>

  <div id="ask" class="panel">
    <div class="card">
      <h2>智能问答 GraphRAG</h2>
      <div class="muted">先从知识图谱检索相关节点和边，再调用模型生成回答。若未设置 API Key，则只返回检索上下文。</div>
      <label>问题</label>
      <textarea id="question" placeholder="例如：KRAS mutation 和结直肠癌有什么关系？"></textarea>
      <div class="row">
        <div><label>知识图谱目录</label><input id="askKgDir" value="colorectal_knowledge_graph"/></div>
        <div><label>配置文件</label><input id="askConfig" value="kg_update_system/config.deepseek.json"/></div>
      </div>
      <div class="row">
        <div><label>图谱参考数量</label><input id="topK" value="20"/><div class="muted">意思是：从图谱里最多找多少个相关概念/实体给 AI 参考。数字越大，依据越多，但回答会慢一点。</div></div>
        <div><label>是否调用模型</label><select id="useModel"><option value="true">调用 DeepSeek</option><option value="false">只做图谱检索</option></select></div>
      </div>
      <div class="row">
        <div><label>回答方式</label><select id="answerMode"><option value="graph">图谱优先：适合查概念和关系</option><option value="literature">PubMed文献综述：总结检索到的文献</option><option value="comprehensive">综合AI回答：图谱 + PubMed + AI医学知识</option></select></div>
        <div><label>结果要求</label><div class="muted" style="padding:10px;border:1px solid #d9e2ec;border-radius:8px;background:#fff">综合模式会标明：哪些来自图谱、哪些来自 PubMed、哪些是 AI 综合医学知识。</div></div>
      </div>
      <div class="row">
        <div><label>第三方资料</label><select id="useExternal"><option value="false">不联网，只用图谱</option><option value="true">检索 PubMed，并标注第三方来源</option></select></div>
        <div><label>第三方资料数量</label><input id="externalK" value="5"/><div class="muted">从 PubMed 取多少篇相关文献摘要作为补充依据。</div></div>
      </div>
      <div class="row">
        <div><label>问答记忆</label><select id="memoryEnabled"><option value="true">启用多轮记忆</option><option value="false">本轮不使用历史</option></select><div class="muted">启用后，系统会把最近几轮问答发给模型，并用历史问题辅助图谱检索。</div></div>
        <div><label>记忆轮数</label><input id="memoryTurns" value="6"/><div class="muted">保留最近多少轮用户问题和 AI 回答。轮数越多，上下文越完整，但模型调用会更慢。</div></div>
      </div>
      <div class="actions"><button class="primary" onclick="ask()">开始回答</button><button onclick="fillDemoQuestion()">填入示例问题</button><button onclick="testAI()">测试 AI 连接</button><button onclick="clearChatMemory()">清空记忆</button><button onclick="exportChatMemory()">导出问答</button></div>
    </div>
    <div class="chatbar"><b>多轮问答记录</b><span class="muted">记录保存在本机浏览器 localStorage；清空后不会再作为记忆使用。</span></div>
    <div id="chatBox" class="chat-thread"></div>
    <div id="answerBox" class="friendly hidden"></div>
    <div id="askRaw" class="result hidden"></div>
  </div>

  <div id="extract" class="panel hidden">
    <div class="card">
      <h2>新资料抽取小图谱</h2>
      <div class="split">
        <div>
          <div id="dropzone" class="dropzone" ondragover="event.preventDefault();this.classList.add('drag')" ondragleave="this.classList.remove('drag')" ondrop="handleDrop(event)">
            <b>拖拽文件到这里</b>
            <div class="muted">支持 Word / PDF / 图片 / 文本 / JSON / HTML</div>
            <div class="mini">也可以下面直接粘贴一段材料。</div>
          </div>
          <label>粘贴新资料文本</label>
          <textarea id="materialText" placeholder="粘贴 PubMed 摘要、指南段落、病历摘要或研究笔记"></textarea>
        </div>
        <div>
          <label>上传文件队列</label>
          <div id="uploadList" class="friendly" style="min-height:150px"></div>
          <label>Obsidian Vault 路径</label><input id="obsidianVault" placeholder="例如 D:\ObsidianVault"/>
          <label>Obsidian 子目录</label><input id="obsidianFolder" value="结直肠癌知识图谱"/>
          <label><input type="checkbox" id="obsidianOpen" style="width:auto"/> 抽取后打开笔记</label>
        </div>
      </div>
      <div class="row">
        <div><label>输出目录</label><input id="extractOutput" value="kg_update_system/runs/gui_mini"/></div>
        <div><label>资料路径</label><input id="materialPath" placeholder="例如 kg_update_system/sample_materials"/></div>
      </div>
      <div class="row">
        <div><label>知识图谱目录</label><input id="extractKgDir" value="colorectal_knowledge_graph"/></div>
        <div><label>大模型增强</label><select id="extractUseModel"><option value="false">不用模型，先规则抽取</option><option value="true">调用 DeepSeek 快速增强（抽取更细）</option></select><div class="muted">已改为相关片段优先抽取，速度比全文逐段读取更快。</div></div>
      </div>
      <label><input type="checkbox" id="extractSummarize" style="width:auto"/> 对新资料生成简要总结，并写入 Markdown 笔记</label>
      <div class="muted">总结不要求打开“大模型增强”，但会单独调用 DeepSeek；不勾选则只生成图谱，速度最快。</div>
      <label>配置文件</label><input id="extractConfig" value="kg_update_system/config.deepseek.json"/>
      <div class="actions"><button class="primary" onclick="extractMini()">生成小图谱</button><button onclick="fillDemoMaterial()">填入示例资料</button><button onclick="quickLLMExtractTest()">测试 DeepSeek 抽取</button></div>
    </div>
    <div id="extractBox" class="friendly hidden"></div>
    <div id="extractRaw" class="result hidden"></div>
  </div>

  <div id="merge" class="panel hidden">
    <div class="card">
      <h2>合并更新主图谱</h2>
      <div class="muted">建议先人工检查 `mini_nodes.csv` 中 `new_candidate*` 节点，再决定是否接受新增候选实体。</div>
      <div class="row">
        <div><label>基础图谱目录</label><input id="mergeBase" value="colorectal_knowledge_graph"/></div>
        <div><label>小图谱目录</label><input id="mergeMini" value="kg_update_system/runs/gui_mini"/></div>
      </div>
      <label>更新后输出目录</label><input id="mergeOutput" value="kg_update_system/runs/gui_updated_kg"/>
      <label><input type="checkbox" id="acceptCandidates" style="width:auto"/> 接受新增候选实体并写入更新图谱</label>
      <div class="actions"><button class="good" onclick="mergeKg()">合并更新</button></div>
    </div>
    <div id="mergeBox" class="friendly hidden"></div>
    <div id="mergeRaw" class="result hidden"></div>
  </div>

  <div id="view" class="panel hidden">
    <div class="card">
      <h2>图谱浏览</h2>
      <div class="quick">
        <button onclick="openGraph('colorectal_knowledge_graph/kg_browser.html')"><b>主知识图谱</b><span class="muted">NCIt 结直肠癌核心网络</span></button>
        <button onclick="openGraph('kg_update_system/runs/gui_mini/mini_browser.html')"><b>最近小图谱</b><span class="muted">新资料抽取结果</span></button>
        <button onclick="openGraph('kg_update_system/runs/gui_updated_kg/kg_browser.html')"><b>最近更新图谱</b><span class="muted">合并后的版本</span></button>
        <button onclick="openGraph('kg_update_system/runs/gui_updated_kg/kg_tree.html')"><b>更新树状结构</b><span class="muted">概念与实体层级树</span></button>
      </div>
      <label>自定义 HTML 路径</label>
      <div class="row">
        <input id="customGraphPath" value="colorectal_knowledge_graph/kg_browser.html"/>
        <button onclick="openGraph($('customGraphPath').value)">打开网页</button>
      </div>
    </div>
    <div id="viewBox" class="friendly hidden"></div>
    <iframe id="graphFrame" class="viewer hidden" title="知识图谱浏览器"></iframe>
  </div>

  <div id="tree" class="panel hidden">
    <div class="card">
      <h2>树状结构浏览</h2>
      <div class="muted">这里展示概念和实体的层级关系，和主图谱同样采用本地网页打开。</div>
      <div class="quick" style="margin-top:12px">
        <button onclick="openGraph('colorectal_knowledge_graph/kg_tree.html')"><b>主知识树</b><span class="muted">完整概念-实体层级</span></button>
        <button onclick="openGraph('kg_update_system/runs/gui_mini/mini_tree.html')"><b>最近小图谱树</b><span class="muted">新资料的层级结构</span></button>
        <button onclick="openGraph('kg_update_system/runs/gui_updated_kg/kg_tree.html')"><b>最近更新树</b><span class="muted">合并后树状视图</span></button>
      </div>
    </div>
  </div>

  <div id="settings" class="panel hidden">
    <div class="card">
      <h2>设置</h2>
      <div class="muted">这里显示系统实际使用的目录和配置。点击路径卡片可以自动填入对应输入框。</div>
      <div class="pathgrid" style="margin-top:12px">
        <div class="pathcard" onclick="fillPath('colorectal_knowledge_graph')"><b>主知识图谱</b><code>colorectal_knowledge_graph</code></div>
        <div class="pathcard" onclick="fillConfig('kg_update_system/config.deepseek.json')"><b>DeepSeek 配置</b><code>kg_update_system/config.deepseek.json</code></div>
        <div class="pathcard" onclick="fillMini('kg_update_system/runs/gui_mini')"><b>默认小图谱输出</b><code>kg_update_system/runs/gui_mini</code></div>
        <div class="pathcard" onclick="fillUpdated('kg_update_system/runs/gui_updated_kg')"><b>默认更新图谱输出</b><code>kg_update_system/runs/gui_updated_kg</code></div>
        <div class="pathcard" onclick="fillVault('')"><b>Obsidian Vault</b><code>填写你的 Obsidian 库路径</code></div>
      </div>
      <div class="actions"><button onclick="status()">重新检测状态</button><button onclick="testAI()">测试 AI 连接</button></div>
    </div>
    <div id="statusBox" class="friendly hidden"></div>
  </div>
</section>
</main>
<script>
function $(id){return document.getElementById(id)}
document.querySelectorAll('.tab').forEach(btn=>btn.onclick=()=>{document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.panel').forEach(p=>p.classList.add('hidden'));$(btn.dataset.tab).classList.remove('hidden')})
async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw j;return j}
function showRaw(id,data){$(id).classList.remove('hidden');$(id).textContent=JSON.stringify(data,null,2)}
function nodeHtml(n){return `<div class="node"><b>${esc(n.label||'')}</b> <span class="muted">${esc(n.id||'')}</span><br><span class="pill">${esc(n.category||'')}</span><span class="pill">${esc(n.kind||'')}</span><div class="muted">${esc((n.definition||'').slice(0,260))}</div></div>`}
function edgeHtml(e){return `<div class="edge">${esc(e.source||'')} <b>→ ${esc(e.relation||'')} →</b> ${esc(e.target||'')}</div>`}
function sourceHtml(s){if(s.error)return `<div class="edge"><b>PubMed 检索失败</b><br>${esc(s.error)}</div>`;return `<div class="edge"><b>${esc(s.title||'')}</b><br><span class="muted">PubMed · PMID ${esc(s.pmid||'')} · ${esc(s.journal||'')} · ${esc(s.year||'')}</span><br><span class="muted">${esc((s.abstract||'').slice(0,420))}</span><br>${s.url?`<a href="${esc(s.url)}" target="_blank">打开 PubMed</a>`:''}</div>`}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
const CHAT_KEY='crc_kg_chat_history_v1';
function loadChatMemory(){try{return JSON.parse(localStorage.getItem(CHAT_KEY)||'[]')}catch{return []}}
function saveChatMemory(items){localStorage.setItem(CHAT_KEY,JSON.stringify(items.slice(-80)))}
window.__chatHistory=loadChatMemory();
function renderChatMemory(){const box=$('chatBox');const items=window.__chatHistory||[];if(!items.length){box.innerHTML='<div class="chat-empty">暂无多轮问答。连续提问后，系统会在这里保留上下文记忆。</div>';return}box.innerHTML=items.map((m,i)=>`<div class="msg ${m.role==='user'?'user':'assistant'}"><div class="msg-meta">${m.role==='user'?'用户':'AI'} · ${esc(m.time||'')}</div><div class="bubble">${esc(m.content||'')}</div></div>`).join('');box.scrollTop=box.scrollHeight}
function appendChat(role,content){const items=window.__chatHistory||[];items.push({role,content:String(content||'').trim(),time:new Date().toLocaleString()});window.__chatHistory=items.filter(x=>x.content).slice(-80);saveChatMemory(window.__chatHistory);renderChatMemory()}
function clearChatMemory(){window.__chatHistory=[];saveChatMemory([]);renderChatMemory();$('answerBox').classList.add('hidden');$('askRaw').classList.add('hidden')}
function exportChatMemory(){const items=window.__chatHistory||[];const body=['# 结直肠癌知识图谱问答记录','',`导出时间：${new Date().toLocaleString()}`,'',...items.map(m=>`## ${m.role==='user'?'用户':'AI'}｜${m.time||''}\n\n${m.content||''}\n`) ].join('\n');const blob=new Blob([body],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='crc_kg_chat_history.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function fillDemoQuestion(){$('question').value='KRAS mutation 和 metastatic colorectal cancer 有什么关系？'}
function fillDemoMaterial(){$('materialText').value='In metastatic colorectal cancer, KRAS mutation and BRAF V600E are clinically relevant molecular alterations. MSI-H or dMMR colorectal carcinoma may respond to immune checkpoint inhibitor therapy.'}
function fillPath(p){['askKgDir','extractKgDir','mergeBase'].forEach(id=>$(id).value=p)}
function fillConfig(p){['askConfig','extractConfig'].forEach(id=>$(id).value=p)}
function fillMini(p){$('extractOutput').value=p;$('mergeMini').value=p}
function fillUpdated(p){$('mergeOutput').value=p}
function fillVault(p){$('obsidianVault').value=p}
async function status(){try{const j=await post('/api/status',{});$('cwd').textContent=j.root;$('apiBadge').textContent=j.api_key_present?'AI 可用':'AI 未配置';$('apiBadge').className='badge '+(j.api_key_present?'ok':'warn');$('statusBox').classList.remove('hidden');$('statusBox').innerHTML=`<h3>系统状态</h3><div class="node"><b>工作目录</b><br><code>${esc(j.root)}</code></div><div class="node"><b>主图谱</b><br><code>${esc(j.paths?.base_kg||'')}</code></div><div class="node"><b>DeepSeek</b><br>模型：<code>${esc(j.llm?.model||'')}</code><br>接口：<code>${esc(j.llm?.base_url||'')}</code><br>Key：${j.api_key_present?'已检测到':'未检测到'}</div>`}catch(e){alert(JSON.stringify(e))}}
async function testAI(){const box=$('statusBox');box.classList.remove('hidden');box.innerHTML='正在测试 DeepSeek 连接...';try{const j=await post('/api/test-llm',{config:$('askConfig')?.value||'kg_update_system/config.deepseek.json'});box.innerHTML=`<h3>AI 连接测试</h3><div class="node"><b class="${j.ok?'ok':'warn'}">${j.ok?'连接成功':'连接失败'}</b><br>${esc(j.answer||j.error||'')}</div>`;status()}catch(e){box.innerHTML=`<h3>AI 连接测试</h3><div class="node"><b class="warn">连接失败</b><br>${esc(e.error||JSON.stringify(e))}</div>`}}
function valueText(value){if(!value)return '';return Array.isArray(value)?value.join('\\n'):String(value)}
function joinParts(...parts){return parts.map(valueText).filter(x=>x.trim()).join('\n')}
function answerSection(title,value,kind,empty='暂无'){const text=valueText(value);return `<section class="answer-section ${kind||''}"><h3>${esc(title)}</h3><p>${text?esc(text):`<span class="muted">${esc(empty)}</span>`}</p></section>`}
function sourceListHtml(items,empty){return items.length?items:`<div class="muted">${esc(empty)}</div>`}
async function ask(){
const box=$('answerBox');box.classList.remove('hidden');box.className='answer-shell';box.innerHTML='<div class="loading">正在检索图谱；文献/综合模式会同时检索 PubMed，并整理来源...</div>';
try{
const q=$('question').value.trim();if(!q){throw {error:'请先输入问题。'}}
const useModel=$('useModel').value==='true';const answerMode=$('answerMode').value;const useExternal=$('useExternal').value==='true'||answerMode==='literature'||answerMode==='comprehensive';
const memoryEnabled=$('memoryEnabled').value==='true';const memoryTurns=Number($('memoryTurns').value||6);const historyForRequest=memoryEnabled?(window.__chatHistory||[]).slice(-memoryTurns*2):[];
const j=await post('/api/ask',{question:q,kg_dir:$('askKgDir').value,config:$('askConfig').value,top_k:Number($('topK').value||20),use_model:useModel,use_external:useExternal,external_k:Number($('externalK').value||5),answer_mode:answerMode,chat_history:historyForRequest,memory_enabled:memoryEnabled,memory_turns:memoryTurns});
const ans=j.answer||j.response||'(模型未返回 answer 字段)';const nodes=(j.context?.nodes||[]).map(nodeHtml).join('');const edges=(j.context?.edges||[]).slice(0,18).map(edgeHtml).join('');const sources=(j.external_context||[]).map(sourceHtml).join('');
const mode=j.mode==='llm_answer'?'AI 已回答':'仅图谱检索';const modeName={graph:'图谱优先',literature:'PubMed文献综述',comprehensive:'综合AI回答'}[j.answer_mode||answerMode]||answerMode;
const heroTitle=answerMode==='comprehensive'?'综合 AI 回答':'总体回答';const heroClass=answerMode==='comprehensive'?'answer-hero comprehensive':'answer-hero';
box.innerHTML=`<div class="${heroClass}"><div class="source-tag"><span class="pill">${mode}</span><span class="pill">${modeName}</span><span class="pill">${useExternal?'含 PubMed 第三方资料':'仅图谱'}</span><span class="pill">${memoryEnabled?'已使用记忆 '+(j.chat_history_used||0)+' 条':'未使用记忆'}</span></div><h3>${heroTitle}</h3><div class="answer-text">${esc(ans)}</div></div>
<div class="answer-grid">${answerSection('图谱依据',j.graph_basis,'graph','模型未单独输出图谱依据；下方仍列出检索命中的节点和关系。')}${answerSection('PubMed 第三方资料',j.pubmed_summary||j.third_party_basis,'pubmed','未启用 PubMed 或未检索到文献。')}${answerSection('AI 综合医学知识',j.ai_general_knowledge,'ai','当前模式没有单独使用 AI 综合医学知识。')}${answerSection('争议、不确定性与边界',joinParts(j.conflicts_or_uncertainty,j.limitations),'limit','未输出特别限制。')}</div>
<div class="memory-note">本轮问题已写入本机问答记忆。后续追问可直接说“它”“上面这个突变”“继续解释”等，系统会结合最近对话理解。</div>
<div class="evidence-grid"><section class="answer-section graph"><h3>相关概念/实体</h3>${sourceListHtml(nodes,'无命中节点')}</section><section class="answer-section graph"><h3>图谱关系</h3>${sourceListHtml(edges,'无命中关系')}</section><section class="answer-section pubmed"><h3>第三方资料来源</h3>${sourceListHtml(sources,'未启用第三方资料，或未检索到 PubMed 结果。')}</section></div>`;
appendChat('user',q);appendChat('assistant',ans);
showRaw('askRaw',j)
}catch(e){box.className='friendly';box.innerHTML='<span class="warn">出错：</span>'+esc(e.error||JSON.stringify(e));showRaw('askRaw',e)}
}
async function extractMini(){
const box=$('extractBox');box.classList.remove('hidden');const useLLM=$('extractUseModel').value==='true';const useSummary=$('extractSummarize').checked;const files=window.__uploadedFiles||[];
box.innerHTML=useLLM?'正在调用 DeepSeek 快速增强抽取；系统会优先发送相关片段...':(useSummary?'正在规则抽取图谱，并单独调用 DeepSeek 总结资料...':'正在用规则抽取实体、关系并生成小图谱...');
try{
const j=await post('/api/extract',{text:$('materialText').value,input_path:$('materialPath').value,kg_dir:$('extractKgDir').value,output:$('extractOutput').value,config:$('extractConfig').value,use_model:useLLM,summary:useSummary,files:files,obsidian_vault:$('obsidianVault').value,obsidian_folder:$('obsidianFolder').value,obsidian_open:$('obsidianOpen').checked});
window.__uploadedFiles=[];renderUploads();
const llmWarn=j.llm_error_count?`<div class="edge"><b class="warn">DeepSeek 部分片段抽取失败</b><br>已自动保留规则抽取结果。失败片段数：${j.llm_error_count}</div>`:'';
const parseWarn=j.parse_error_count?`<div class="edge"><b class="warn">部分文件未读出文字</b><br>已处理能读取的文件；未读取文件数：${j.parse_error_count}<br>${(j.parse_errors||[]).slice(0,5).map(x=>`<span class="muted">· ${esc((x.path||'').split(/[\\\\/]/).pop())}：${esc(x.error||'')}</span>`).join('<br>')}</div>`:'';
const parseOk=j.document_count?`<div class="node"><b>已读取文档</b><br><span class="muted">${j.document_count} 个文件/文本进入抽取流程。</span></div>`:'';
const summary=j.summary_brief?`<div class="answer-hero"><h3>资料简要总结</h3><div class="answer-text">${esc(j.summary_brief)}</div><div class="muted">更完整的分析与整合建议已写入 mini_note.md。</div></div>`:(j.summary_error?`<div class="edge"><b class="warn">资料总结失败</b><br>${esc(j.summary_error)}</div>`:'');
const obs=j.obsidian_uri?`<div class="edge"><b>Obsidian 笔记</b><br><a href="${esc(j.obsidian_uri)}" target="_blank">打开笔记</a><br><span class="muted">${esc(j.obsidian_note_path||'')}</span></div>`:'';
box.innerHTML=`<h3>小图谱已生成</h3><p>输出目录：<code>${esc(j.output_dir)}</code></p><span class="pill">已读取 ${j.document_count||0}</span><span class="pill">已知节点 ${j.known_node_count}</span><span class="pill">新增候选 ${j.new_candidate_count}</span><span class="pill">边 ${j.edge_count}</span><span class="pill">LLM实体 ${j.llm_entity_count||0}</span><span class="pill">LLM关系 ${j.llm_relation_count||0}</span>${summary}${parseOk}${parseWarn}${llmWarn}${obs}<div class="actions"><button onclick="openGraph('${esc(j.output_dir).replace(/\\/g,'/')}/mini_browser.html')">打开小图谱</button><button onclick="openGraph('${esc(j.output_dir).replace(/\\/g,'/')}/mini_tree.html')">打开树状结构</button><button onclick="openGraph('${esc(j.output_dir).replace(/\\/g,'/')}/mini_note.md')">打开 Markdown</button></div>`;
showRaw('extractRaw',j)
}catch(e){box.innerHTML='<span class="warn">出错：</span><pre style="white-space:pre-wrap">'+esc(e.error||JSON.stringify(e))+'</pre>';showRaw('extractRaw',e)}
}
async function quickLLMExtractTest(){fillDemoMaterial();$('extractUseModel').value='true';$('extractOutput').value='kg_update_system/runs/gui_llm_test_mini';await extractMini()}
async function mergeKg(){const box=$('mergeBox');box.classList.remove('hidden');box.innerHTML='正在合并，原图谱会备份到输出目录...';try{const j=await post('/api/merge',{base_kg:$('mergeBase').value,mini:$('mergeMini').value,output:$('mergeOutput').value,accept_candidates:$('acceptCandidates').checked,obsidian_vault:$('obsidianVault').value,obsidian_folder:$('obsidianFolder').value,obsidian_open:$('obsidianOpen').checked});const obs=j.obsidian_uri?`<div class="edge"><b>Obsidian 笔记</b><br><a href="${esc(j.obsidian_uri)}" target="_blank">打开笔记</a><br><span class="muted">${esc(j.obsidian_note_path||'')}</span></div>`:'';box.innerHTML=`<h3>更新图谱已生成</h3><p>输出目录：<code>${esc(j.output_dir||$('mergeOutput').value)}</code></p><span class="pill">节点 ${j.node_count}</span><span class="pill">边 ${j.edge_count}</span><span class="pill">新增节点 ${j.added_nodes}</span>${obs}<div class="actions"><button onclick="openGraph('${esc($('mergeOutput').value).replace(/\\/g,'/')}/kg_browser.html')">打开更新图谱</button><button onclick="openGraph('${esc($('mergeOutput').value).replace(/\\/g,'/')}/kg_tree.html')">打开更新树</button></div>`;showRaw('mergeRaw',j)}catch(e){box.innerHTML='<span class="warn">出错：</span>'+esc(e.error||JSON.stringify(e));showRaw('mergeRaw',e)}}
async function openGraph(path){try{const j=await post('/api/view-url',{path});$('viewBox').classList.remove('hidden');$('viewBox').innerHTML=`正在显示：<code>${esc(j.path)}</code>`;const frame=$('graphFrame');frame.classList.remove('hidden');frame.src=j.url;window.open(j.url,'_blank')}catch(e){$('viewBox').classList.remove('hidden');$('viewBox').innerHTML=`<span class="warn">无法显示：</span>${esc(e.error||JSON.stringify(e))}`}}
function renderUploads(){const box=$('uploadList');const files=window.__uploadedFiles||[];if(!files.length){box.innerHTML='<span class="muted">尚未上传文件。</span>';return}box.innerHTML=files.map((f,i)=>`<div class="node"><b>${esc(f.name)}</b><br><span class="muted">${esc(f.size||'')} bytes</span> <button onclick="removeUpload(${i})">移除</button></div>`).join('')}
function removeUpload(i){const files=window.__uploadedFiles||[];files.splice(i,1);window.__uploadedFiles=files;renderUploads()}
async function handleDrop(evt){evt.preventDefault();evt.currentTarget.classList.remove('drag');const arr=[...(evt.dataTransfer.files||[])];if(!arr.length)return;window.__uploadedFiles=window.__uploadedFiles||[];for(const f of arr){const data=await fileToDataUrl(f);window.__uploadedFiles.push({name:f.name,data,size:f.size})}renderUploads()}
function fileToDataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file)})}
renderUploads();
renderChatMemory();
status();fillDemoQuestion();
</script>
</body>
</html>"""


class GuiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html_response(self, page_html())
            return
        if parsed.path == "/view-file":
            params = parse_qs(parsed.query)
            target = resolve_path(params.get("path", [""])[0])
            if not target:
                json_response(self, {"error": "缺少 path 参数"}, status=400)
                return
            file_response(self, target)
            return
        json_response(self, {"error": "Not found"}, status=404)

    def do_POST(self):
        try:
            if self.path == "/api/status":
                config_path = DEFAULT_CONFIG
                llm_summary = config_summary(config_path)
                payload = {
                    "root": str(ROOT),
                    "config_exists": config_path.exists(),
                    "api_key_present": config_has_api_key(config_path),
                    "llm": llm_summary,
                    "paths": {
                        "base_kg": str(DEFAULT_KG_DIR),
                        "config": str(DEFAULT_CONFIG),
                        "gui_runs": str(GUI_RUN_DIR),
                        "main_browser": str(DEFAULT_KG_DIR / "kg_browser.html"),
                    },
                }
                json_response(self, payload)
                return

            if self.path == "/api/test-llm":
                body = read_body(self)
                config_path = resolve_path(body.get("config"), DEFAULT_CONFIG)
                config = load_llm_config(config_path)
                content = call_chat_api(
                    config,
                    [
                        {"role": "system", "content": "你是连接测试助手。只输出 JSON。"},
                        {"role": "user", "content": "请输出 {\"answer\":\"DeepSeek连接正常\"}"},
                    ],
                    temperature=0,
                )
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = {"answer": content}
                json_response(self, {"ok": True, "answer": parsed.get("answer", content), "config": str(config_path)})
                return

            body = read_body(self)
            if self.path == "/api/ask":
                config = load_llm_config(resolve_path(body.get("config"), DEFAULT_CONFIG))
                if not body.get("use_model", True):
                    config.setdefault("llm", {})["enabled"] = False
                kg_dir = resolve_path(body.get("kg_dir"), DEFAULT_KG_DIR)
                result = answer_question(
                    body.get("question", ""),
                    kg_dir,
                    config=config,
                    top_k=int(body.get("top_k") or 20),
                    use_external=bool(body.get("use_external")),
                    external_k=int(body.get("external_k") or 5),
                    answer_mode=body.get("answer_mode", "graph"),
                    chat_history=body.get("chat_history") or [],
                    memory_enabled=bool(body.get("memory_enabled", True)),
                    memory_turns=int(body.get("memory_turns") or 6),
                )
                json_response(self, result)
                return

            if self.path == "/api/extract":
                input_path = None
                files = body.get("files") or []
                if body.get("text", "").strip() or files:
                    input_path = write_text_and_files(body.get("text", ""), files)
                else:
                    input_path = resolve_path(body.get("input_path"))
                if not input_path:
                    raise RuntimeError("请粘贴资料文本，或填写资料文件/目录路径。")
                output = resolve_path(body.get("output"), GUI_RUN_DIR / "mini")
                kg_dir = resolve_path(body.get("kg_dir"), DEFAULT_KG_DIR)
                config = load_llm_config(resolve_path(body.get("config"), DEFAULT_CONFIG))
                report = build_mini_kg(
                    input_path,
                    kg_dir,
                    output,
                    config=config,
                    use_llm=bool(body.get("use_model")),
                    summarize=bool(body.get("summary")),
                    obsidian_vault=resolve_path(body.get("obsidian_vault")),
                    obsidian_folder=body.get("obsidian_folder") or "结直肠癌知识图谱",
                    obsidian_open=bool(body.get("obsidian_open")),
                )
                json_response(self, {"output_dir": str(output.resolve()), **report})
                return

            if self.path == "/api/merge":
                base_kg = resolve_path(body.get("base_kg"), DEFAULT_KG_DIR)
                mini = resolve_path(body.get("mini"))
                output = resolve_path(body.get("output"), GUI_RUN_DIR / "updated_kg")
                if not mini:
                    raise RuntimeError("请填写小图谱目录。")
                report = merge_kg(
                    base_kg,
                    mini,
                    output,
                    accept_candidates=bool(body.get("accept_candidates")),
                    obsidian_vault=resolve_path(body.get("obsidian_vault")),
                    obsidian_folder=body.get("obsidian_folder") or "结直肠癌知识图谱",
                    obsidian_open=bool(body.get("obsidian_open")),
                )
                json_response(self, {"output_dir": str(output.resolve()), **report})
                return

            if self.path == "/api/view-url":
                target = resolve_path(body.get("path"))
                if not target or not target.exists():
                    json_response(self, {"ok": False, "error": "文件不存在", "path": str(target)}, status=400)
                    return
                rel_or_abs = str(target.resolve())
                json_response(self, {"ok": True, "path": rel_or_abs, "url": f"/view-file?path={quote(rel_or_abs)}"})
                return

            json_response(self, {"error": "Not found"}, status=404)
        except Exception as exc:
            json_response(
                self,
                {"error": str(exc), "traceback": traceback.format_exc(limit=6)},
                status=500,
            )


def main():
    parser = argparse.ArgumentParser(description="结直肠癌知识图谱本地 GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), GuiHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"GUI running: {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
