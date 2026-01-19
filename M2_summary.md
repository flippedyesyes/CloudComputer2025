下面是基于你们**命题二**要求（PDF 第2个）以及两份“整体设计思路”+ M1 实现文档，并对照你提供的**当前代码 zip**后，整理出来的 **M2《实现情况说明》**（可直接放进报告/README 作为 M2 章节）。

---

## M2 目标与范围

### 对齐命题二要求

命题二要求系统具备“动态出题、智能判卷、弱点记忆”的闭环，并强调持久化学习状态与工程化实现。
M1 已完成闭环主链路（出题/判卷/错题本），M2 在此基础上补齐“知识体系与掌握度”能力，即：**从教材自动抽取知识目录结构 → 支持按章节范围出题 → 判卷结果回流到知识树掌握度**。

### M2 的新增能力（相对 M1）

1. **知识体系树（章节/小节）生成与展示**：资料导入后自动生成章/节两层树，并入库持久化。
2. **按知识范围（node_id）出题**：出题参数支持选择某一章节/节点作为范围入口。
3. **掌握度（mastery）回流**：判卷后把每题的正确/错误回写到知识点掌握度，并在知识树中可视化（百分比/颜色）。

---

## M2 数据模型与持久化（MongoDB）

在 M1 已有 collections（materials/material_texts/quizzes/questions/attempts/mistakes）基础上，M2 新增/强化两类数据：

### 1) knowledge_nodes（知识体系树节点）

用于存储教材的章/节结构与层级关系（两层：章 level=1，节 level=2）。并为“按范围出题”准备了范围证据：`source_chunk_indexes`。

* 关键字段：`material_id`, `notebook_id`, `title`, `level`, `order`, `parent_id`, `source_chunk_indexes`

> 设计上与“首页知识体系图（章节/知识点树）”一致，实现上采用两层目录以降低不稳定性（目录提取更稳、演示更清晰）。

### 2) mastery（掌握度表）

用于持久化用户对各知识节点的学习状态：`seen/correct/wrong/mastery_score`。掌握度是后续“弱点诊断/再练”基础，也符合题目建议“持久化学习状态”。

---

## M2 核心流程实现

### A. 导入资料 → 生成知识体系树（Worker：ingest）

在 M1 的 ingest 基础上增加“知识树抽取与入库”步骤：

1. **资料解析**：仍沿用 M1（PDF/DOCX 用 Kimi file-extract，音频用 Groq ASR）并写入 `material_texts(kind=full)`；超长文本生成摘要写入 `material_texts(kind=summary)`。
2. **知识树生成（M2 新增）**：从 `summary`（优先）或原文前段截断内容中提取“章/节目录结构”，输出 JSON 数组并入库 `knowledge_nodes`。
3. **范围映射（M2 新增）**：为每个章/节节点生成 `source_chunk_indexes`（当前实现为“按全文 chunk 均分的稳定粗绑定”），使后续出题能真的只用该章节 chunks，而不是仅靠 prompt 限制。

> 这一步对应你们设计里“导入资料→生成知识体系树→首页可视化”的主链路。

---

### B. 选择章节范围出题（Backend → Worker：generate_quiz）

M2 在 `POST /quizzes/generate` 上支持传入 `node_id` 作为范围入口（全局/章节二选一入口与设计一致）。

Worker 出题时：

1. 若传入 `node_id`：优先读取该节点的 `source_chunk_indexes` 并只加载这些 chunks 作为上下文；否则回退到 M1 的“summary/full 拼接”。
2. 为了支持“子节点独立统计、父节点整体聚合”，出题阶段会尽量把每道题绑定到**子树叶子节点**（如果存在），写入 `question.node_ids`（见下一节掌握度回流）。
3. 题型/难度混合仍沿用 M1 的参数体系（题量/题型/难度），并保持异步队列模式（API 投任务、Worker 执行）。

---

### C. 提交答案 → 判卷 → 回写掌握度（Worker：grade_attempt）

判卷能力沿用 M1：选择题规则判、填空规则+LLM兜底、简答用 LLM 判卷，产出结构化 grading。

M2 新增在判卷循环内做两类回流：

1. **错题本（mistakes）**：保持 M1 逻辑（错题 upsert，累加 wrong_count，沉淀 error_tags/knowledge_points）。
2. **掌握度（mastery）**：对每题的 `node_ids` 执行 upsert + seen/correct/wrong 自增，并重算 `mastery_score = correct/seen`。

> 注意：为满足“子节点独立统计、父节点整体统计”的目标，M2 的回流策略是：**只更新题目绑定的 node_ids（通常是叶子/子节点）**；父节点不直接写同样的分数，而是在知识树接口里做聚合（见下一节）。这样不会出现“子节点复制父节点分数”的问题。

---

## 知识树掌握度展示（Backend：GET /knowledge/tree）

知识树展示接口将 `knowledge_nodes` 与 `mastery` 做关联，并按以下规则计算展示值：

* **叶子节点**：直接展示自身 mastery（来自 mastery 表：correct/seen）。
* **父节点**：不使用“父节点自身 mastery”，而是对所有后代节点聚合：
  [
  mastery(parent) = \frac{\sum correct(children)}{\sum seen(children)}
  ]
  这与“父节点统计所有子节点整体”的需求一致，也与设计中“知识树节点颜色=掌握度”的展示目标一致。

---

## 前端（M2）功能呈现

在原 M1 演示页基础上，M2 新增“知识体系与掌握度”区域，实现：

1. 选择 material → 拉取并展示知识树（章/节列表或树形 UI）
2. 点击某节点 → 设置为出题范围入口（node_id）
3. 完成作答并判卷后 → 重新拉取知识树 → 看到掌握度百分比/颜色变化（父节点为聚合值、子节点为独立值）

这与设计文档中“首页知识体系图可全局/局部出题、节点颜色=掌握度”的交互目标一致。 

---

## 工程化与云原生体现（M2 延续 + 强化）

* **服务拆分**：Backend（FastAPI）只负责请求/入库/投递；Worker 负责耗时 LLM 任务（ingest/generate/grade）；Redis 作为队列；MongoDB 作为持久化。
* **异步链路稳定性**：M2 针对出题链路做了鲁棒性处理（LLM 输出题数多/少允许降级处理，避免前端一直停留在 processing）。
* **容错/降级**：知识树生成失败不会拖垮 ingest 主流程，而是“跳过知识树但材料仍 ready”，保证核心闭环可用（符合“注重容错”的建议）。

---

## 当前 M2 已实现点与不足（为 M3/优化留口）

### 已实现

* 知识树自动生成与入库（章/节两层）
* 支持 node_id 范围出题（按节点 chunk 范围取上下文）
* 每题绑定 node_ids，判卷后回写 mastery
* 知识树接口对父节点做“子节点聚合掌握度”展示

### 已知不足/可优化方向

* `source_chunk_indexes` 当前为“均分粗绑定”，对目录结构不明显的教材可能不够精准（可用标题关键词匹配或向量检索提升）
* 暂未做系统化 Check layer（QuizCheck/GraphCheck/GradeCheck）为独立模块，只做了轻量字段校验与失败降级；后续可按设计补齐。
* Tutor/Coach 引导式对话、小灶建议属于 M3（在 M1 文档里也明确留到后续）。

---

如果你希望我把这份“**M2 实现情况**”直接按你们现有 M1_summary 的写法排版成同风格的 `M2_summary.md`（包含接口清单、字段表、演示脚本），我也可以继续基于这份内容帮你整理成可提交的最终文档结构。
