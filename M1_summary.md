# M1 Summary（学习效果评估与巩固智能体）

## 1）M1 目标与边界

**目标**
- 实现“资料导入 → 自动出题 → 自动判卷 → 错题本沉淀”的闭环
- 用云原生方式跑通异步链路（API 只负责投递任务，Worker 处理慢任务）

**范围**
- 不做知识体系图、掌握度回流（留给 M2）
- 不做 Tutor/Coach 引导式小灶（留给 M3）
- 不做 RAG/向量检索（M1 先基于全文/摘要出题）

**验收点**
- 可在本地或 Docker 一键启动
- 前端可演示完整闭环

---

## 2）系统结构与角色

- **Backend（FastAPI）**：接收请求、校验参数、写库、投递任务
- **Worker（RQ）**：执行耗时任务（解析资料、出题、判卷）
- **Redis**：任务队列
- **MongoDB**：持久化数据
- **Frontend（Vite + React）**：可视化演示上传/出题/判卷/错题
- **Storage**：`storage/uploads` 保存上传文件，容器内共享

---

## 3）数据模型（Mongo collections）

**materials**
- `notebook_id, title, source_type, material_type, is_primary`
- `status, file_url, text_chunk_count, summary_chunk_count, error_message`

**material_texts**
- `material_id, kind(full/summary), chunk_index, text`

**quizzes**
- `notebook_id, material_ids, status`
- `num_questions, type_mix, difficulty_mix, question_ids`

**questions**
- `quiz_id, type, stem, options, answer_key, rubric, difficulty`
- `knowledge_points, analysis, material_ids`

**attempts**
- `quiz_id, student_id, answers, status`
- `score, grading(每题判卷明细), error_message`

**mistakes**
- `student_id, notebook_id, question_id`
- `wrong_count, error_tags, knowledge_points, last_error_analysis`

---

## 4）核心流程（M1 主链路）

### 4.1 资料上传与入库
1. 前端通过 `POST /materials/upload` 上传文件（PDF/DOCX/MP3/TXT）
2. 后端落盘到 `storage/uploads`
3. 生成一条 materials 记录，状态置为 `queued`
4. 投递 `ingest_material` 任务

### 4.2 资料解析（Worker）
- PDF/DOCX：调用 Kimi `file-extract` 抽文本  
- MP3：调用 Groq ASR 转写  
- 结果文本切片存入 `material_texts(kind=full)`  
- 超长文本（> SUMMARY_MAX_CHARS）生成摘要存 `kind=summary`
- 更新 materials：`status=ready`, `text_chunk_count`, `summary_chunk_count`

### 4.3 出题（Worker）
1. `POST /quizzes/generate` 接收参数：题量(1-5)、难度(简单/正常/难)、题型(选择/填空/问答)
2. 生成 `type_mix` / `difficulty_mix`
3. 读取材料文本：优先 summary，最多 CONTEXT_MAX_CHARS
4. 调用 Kimi 生成 JSON 题目
5. 校验题目结构后写入 `questions`，更新 quiz 状态为 `ready`

### 4.4 判卷（Worker）
1. `POST /attempts/{quiz_id}/submit` 提交答案
2. 判卷规则：
   - 选择题：规则匹配
   - 填空题：先规则，失败则 LLM 判卷
   - 简答题：LLM 判卷
3. 每题记录：
   - `score`、`is_correct`、`mistake_added`
   - `error_tags`、`error_analysis`、`knowledge_points`
4. `is_correct = false` 时写入错题本

### 4.5 错题本查询
`GET /mistakes?student_id=...&notebook_id=...`
- 按 student + question 聚合
- 错题次数累加、错因标签/知识点沉淀

---

## 5）前端能力（M1 演示页）

- 上传资料（自动解析）
- 选择材料出题
- 设置题量/难度/题型
- 作答并查看判卷结果
- 展示错题本与薄弱点
- 每题显示：**得分 / 判定 / 是否加入错题本**

---

## 6）配置与运行

**核心环境变量**
- `MOONSHOT_API_KEY` / `GROQ_API_KEY`
- `MONGO_URI` / `MONGO_DB_NAME`
- `REDIS_URL`
- `KIMI_MODEL`
- `CONTEXT_MAX_CHARS` / `SUMMARY_MAX_CHARS` / `SUMMARY_CHUNK_CHARS`
- `UPLOAD_DIR`
- `CORS_ORIGINS`
- `VITE_API_BASE_URL`

**一键容器启动**
```
docker compose up -d --build
```

前端：`http://localhost:5173`  
后端：`http://localhost:8000`

---

## 7）演示流程（建议录屏步骤）

1. 打开前端 → 填 notebook_id / student_id  
2. 上传 PDF/DOCX/MP3  
3. 材料变为 `ready`  
4. 设置题量/难度/题型 → 生成测验  
5. 作答并提交 → 查看判卷  
6. 错题本自动更新

---

## 8）当前不足与风险

- 未实现知识体系树与掌握度回流（M2）
- 未实现 Tutor/Coach（M3）
- OSS 外部存储未接入（当前仅本地落盘）
- 错题判定为 `is_correct`，暂未引入分数阈值策略
- PDF 解析质量依赖 Kimi，复杂公式可能出现缺失

---

## 9）后续方向（M2 / M3）

**M2：知识体系 + 掌握度回流**
- ingest 生成章节/知识点树
- 题目绑定知识点
- 判卷后回写 mastery，并前端颜色可视化

**M3：小灶建议 + Tutor 引导**
- 错题聚合生成针对性建议
- 多轮引导式对话，避免直接给答案
