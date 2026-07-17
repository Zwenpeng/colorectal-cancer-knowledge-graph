# 结直肠癌知识图谱增量系统

## 1. 目标

这个系统建立在现有 `colorectal_knowledge_graph` 之上，用来处理后续新来的资料：

1. 从新资料中识别主图谱已有的概念和实体。
2. 抽取新候选概念/实体。
3. 生成一个小知识图谱。
4. 可选择把小图谱合并进主图谱。
5. 基于图谱做智能问答；无 API 时返回图谱检索上下文，有 API 时调用第三方大模型生成答案。

核心原则延续前面图谱：**概念和实体是节点；同义词、证据、定义、来源资料是属性。**

## 2. 文件

| 文件 | 作用 |
|---|---|
| `kg_incremental.py` | 主脚本：抽取、合并、问答 |
| `config.example.json` | 第三方大模型 API 配置模板 |
| `sample_materials/sample_crc_note.txt` | 测试用新资料 |

先在 PowerShell 进入项目根目录：

```powershell
cd <项目根目录>
```

## 3. 支持的新资料格式

当前直接支持：

- `.txt`
- `.md`
- `.csv`
- `.json`
- `.html`
- `.htm`

PDF、Word、扫描件建议先转成 `.txt` 或 `.md`。如果后续你经常给 PDF/Word，可以再加专门解析模块。

## 4. 生成小知识图谱

不调用大模型，仅用主图谱词典 + 规则抽取：

```powershell
python .\kg_update_system\kg_incremental.py extract `
  --input .\kg_update_system\sample_materials `
  --kg-dir .\colorectal_knowledge_graph `
  --output .\kg_update_system\runs\sample_mini
```

输出：

| 文件 | 作用 |
|---|---|
| `mini_nodes.csv` | 小图谱节点 |
| `mini_edges.csv` | 小图谱边 |
| `mini_browser.html` | 小图谱浏览器 |
| `mini_graph.graphml` | Gephi / yEd / NetworkX |
| `mini_cytoscape.json` | Cytoscape |
| `mini_report.json` | 抽取统计 |

节点状态：

| `kg_status` | 含义 |
|---|---|
| `existing` | 主图谱已有概念/实体 |
| `new_candidate_rule` | 规则抽取的新候选实体 |
| `new_candidate_llm` | 大模型抽取的新候选实体 |
| `new_candidate_rule_llm` | 规则和大模型都命中的新候选实体 |

## 5. 合并更新主图谱

只合并已有节点的证据，不接受新增候选实体：

```powershell
python .\kg_update_system\kg_incremental.py merge `
  --base-kg .\colorectal_knowledge_graph `
  --mini .\kg_update_system\runs\sample_mini `
  --output .\kg_update_system\runs\updated_kg
```

接受新增候选实体并写入更新图谱：

```powershell
python .\kg_update_system\kg_incremental.py merge `
  --base-kg .\colorectal_knowledge_graph `
  --mini .\kg_update_system\runs\sample_mini `
  --output .\kg_update_system\runs\updated_kg `
  --accept-candidates
```

合并不会覆盖原始 `colorectal_knowledge_graph`，而是生成一个新目录。输出目录中会有：

- `kg_nodes.csv`
- `kg_edges.csv`
- `kg_edges_research_core.csv`
- `kg_browser.html`
- `kg_graph.graphml`
- `kg_cytoscape.json`
- `merge_report.json`
- `_backup_source_时间戳`

## 6. 智能问答

### 6.1 无 API 模式

无 API 时，系统只做图谱检索，返回相关节点和边：

```powershell
python .\kg_update_system\kg_incremental.py ask `
  --kg-dir .\colorectal_knowledge_graph `
  --question "KRAS 和结直肠癌有什么关系？"
```

### 6.2 第三方大模型 API 模式

复制配置文件：

```powershell
Copy-Item .\kg_update_system\config.example.json .\kg_update_system\config.json
```

编辑 `config.json`：

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai_compatible",
    "base_url": "https://你的服务商地址/v1",
    "model": "你的模型名",
    "api_key_env": "KG_LLM_API_KEY",
    "temperature": 0
  }
}
```

设置 API Key：

```powershell
$env:KG_LLM_API_KEY="你的API密钥"
```

调用问答：

```powershell
python .\kg_update_system\kg_incremental.py ask `
  --kg-dir .\colorectal_knowledge_graph `
  --config .\kg_update_system\config.json `
  --question "MSI-H 结直肠癌和免疫治疗有什么关系？"
```

## 7. 用大模型增强新资料抽取

启用 `--use-llm`：

```powershell
python .\kg_update_system\kg_incremental.py extract `
  --input .\你的新资料目录 `
  --kg-dir .\colorectal_knowledge_graph `
  --output .\kg_update_system\runs\my_new_mini `
  --config .\kg_update_system\config.json `
  --use-llm
```

大模型会补充：

- 规则未覆盖的新实体。
- 文中明确表达的新关系。
- 简短定义、别名和证据句。

## 8. 推荐的大模型能力

这个任务不一定必须用最贵模型，但模型要满足三个约束：

1. 支持长上下文，至少 32k token 更稳。
2. 中文和英文医学文本都能处理。
3. 支持稳定 JSON 输出，或至少能严格按 JSON 格式回答。

可用类型：

- OpenAI-compatible Chat Completions API
- 国内兼容 OpenAI 格式的模型服务
- 私有部署的大模型网关，只要接口兼容 `/chat/completions`

我需要你提供：

| 参数 | 例子 |
|---|---|
| `base_url` | `https://api.xxx.com/v1` |
| `model` | `gpt-4.1` / `qwen-xxx` / `deepseek-xxx` 等 |
| `api_key` 或环境变量名 | 推荐用环境变量 |
| 是否允许把资料内容发给第三方 API | 是/否 |

### 8.1 DeepSeek 配置

已提供 DeepSeek OpenAI-compatible 配置：

```text
kg_update_system/config.deepseek.json
```

该文件不保存 API key，只读取环境变量 `KG_LLM_API_KEY`。

在当前 PowerShell 窗口临时设置：

```powershell
$env:KG_LLM_API_KEY="你的API密钥"
```

测试问答：

```powershell
python .\kg_update_system\kg_incremental.py ask `
  --kg-dir .\colorectal_knowledge_graph `
  --config .\kg_update_system\config.deepseek.json `
  --question "KRAS mutation 和结直肠癌有什么关系？"
```

用 DeepSeek 增强新资料抽取：

```powershell
python .\kg_update_system\kg_incremental.py extract `
  --input .\你的新资料目录 `
  --kg-dir .\colorectal_knowledge_graph `
  --output .\kg_update_system\runs\deepseek_mini `
  --config .\kg_update_system\config.deepseek.json `
  --use-llm
```

当前配置：`base_url = https://api.deepseek.com`，`model = deepseek-v4-pro`。

## 9. 修改规则

### 9.1 改新增实体识别规则

编辑 `kg_incremental.py`：

- `extract_rule_candidates()`：控制正则抽取哪些候选实体。
- `classify_candidate()`：控制候选实体被归为基因、分子异常、治疗方案等类别。

### 9.2 改问答检索数量

使用 `--top-k`：

```powershell
python .\kg_update_system\kg_incremental.py ask `
  --question "BRAF V600E 在结直肠癌中意味着什么？" `
  --top-k 40
```

### 9.3 人工审核新增实体

合并前先打开：

```powershell
.\kg_update_system\runs\sample_mini\mini_nodes.csv
```

重点检查 `kg_status` 不是 `existing` 的行。确认后再用 `--accept-candidates` 合并。

## 10. 证据链

新增节点和边都保留：

- `source_docs`：来自哪些资料。
- `evidence`：原文片段或模型抽取证据。
- `kg_status`：已有节点还是候选节点。

这三个字段是后续人工审核、论文证据追踪、图谱版本管理的核心。
