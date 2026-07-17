# 数据来源与范围

## 上游来源

本图谱来自美国国家癌症研究所术语库（NCI Thesaurus，NCIt），通过 NCI EVSREST API 获取：

```text
https://api-evsrest.nci.nih.gov/api/v1
```

当前发布快照生成于 `2026-05-14`，使用 NCIt `26.04d` 版本，以 `C2955 / Colorectal Carcinoma` 为根概念。

## 抽取边界

1. 获取完整的 `C2955` 记录。
2. 获取 `C2955` 的全部下位概念。
3. 获取根概念及每个下位概念的完整 NCIt 记录。
4. 保留父子层级、role、association、inverse role 和 inverse association。
5. 找到与树内概念通过 NCIt role 或 association 直接相连的树外概念，并获取其完整记录。

结果包含 `285` 个树内疾病概念和 `463` 个直接关联的树外 NCIt 实体。

## 项目内术语约定

NCIt 在本体层面将全部记录称为 concept。本项目为了明确图谱边界，使用两种工作标签：

- `Concept`：位于 `C2955` 下位概念树内的 NCIt 概念。
- `Entity`：位于树外、但通过 NCIt role 或 association 与树内概念直接相连的 NCIt 概念。

这是一种图谱边界约定，不表示 NCIt 存在两种不兼容的本体对象类型。

## 关系解释

- `is_parent_of`：标准化后的父概念到子概念分类边。
- `role`：NCIt 语义关系，例如疾病与基因、分期或治疗方案的关系。
- `association`：术语或数据模型关联，不能自动视为生物医学证据。

系统保留 NCIt 原始方向。例如 `Regimen_Has_Accepted_Use_For_Disease` 存为“方案到疾病”。查询时可以双向遍历，但不能把 NCIt 原始断言方向改写为相反方向。

## 派生文件

`ncit_colorectal_cancer/` 保存 NCIt 快照及标准化 CSV/JSONL 表；`colorectal_knowledge_graph/` 是其派生表示，负责对完全相同的关系三元组去重、赋予研究型类别，并输出可视化与交换格式。

## 数据使用边界

本仓库不发布患者级资料。MIT 许可证仅适用于项目原创代码和文档；使用者仍需遵守 NCI/NCIt 的来源条款，以及将自有资料加入系统时适用的全部规范。
