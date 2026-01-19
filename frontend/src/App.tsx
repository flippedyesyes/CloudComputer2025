import { useMemo, useState } from "react";
import type { CSSProperties } from "react";

const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type Material = {
  id: string;
  title: string;
  source_type: string;
  material_type: string;
  is_primary: boolean;
  status: string;
  text_chunk_count: number;
  summary_chunk_count: number;
  error_message?: string;
};

type Quiz = {
  id: string;
  status: string;
  error_message?: string;
};

type Question = {
  id: string;
  type: "mcq" | "blank" | "short";
  stem: string;
  options?: string[];
};

type Attempt = {
  id: string;
  status: string;
  score?: number;
  grading?: Array<{
    question_id: string;
    result?: {
      score?: number;
      is_correct?: boolean;
      missing_points?: string[];
      error_tags?: string[];
      error_analysis?: string;
      feedback?: string;
    };
    score?: number;
    is_correct?: boolean;
    mistake_added?: boolean;
    analysis?: string;
    knowledge_points?: string[];
  }>;
};

type Mistake = {
  id: string;
  question_id: string;
  error_tags: string[];
  knowledge_points: string[];
  last_error_analysis?: string;
  wrong_count: number;
};

// ---------------- M3: Coach ----------------
type CoachPlanDoc = {
  id: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  plan?: {
    diagnosis?: {
      summary?: string;
      key_weak_node_ids?: string[];
      top_error_tags?: string[];
      top_missing_points?: string[];
    };
    corrective_actions?: Array<{
      issue?: string;
      how_to_fix?: string;
      evidence?: {
        missing_points?: string[];
        error_tags?: string[];
        weak_node_ids?: string[];
      };
    }>;
    practice_plan?: Array<{
      level?: "L1" | "L2";
      focus_node_ids?: string[];
      num_questions?: number;
      notes?: string;
    }>;
    one_click_practice?: {
      node_id?: string | null;
      num_questions?: number;
      difficulty_mix?: Record<string, number>;
      type_mix?: Record<string, number>;
      material_ids?: string[];
    };
  };
};

// ---------------- M3: Tutor ----------------
type TutorMessage = {
  role: "user" | "assistant";
  content: string;
};

// ---------------- M2: Knowledge tree ----------------
type KnowledgeNode = {
  id: string;
  title: string;
  level: number;
  order: number;
  parent_id?: string | null;
  mastery_score?: number;
  // backend variants (some implementations use different field names)
  mastery?: number;
  mastery_percent?: number;
  children?: KnowledgeNode[];
};

type KnowledgeTreeResponse = {
  material_id: string;
  tree: KnowledgeNode[];
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const cardStyle = (index: number) =>
  ({ "--delay": `${index * 0.08}s` } as CSSProperties);

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [notebookId, setNotebookId] = useState("demo-notebook");
  const [studentId, setStudentId] = useState("demo_user");

  const [materials, setMaterials] = useState<Material[]>([]);
  const [selectedMaterials, setSelectedMaterials] = useState<Record<string, boolean>>({});

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadSourceType, setUploadSourceType] = useState("auto");
  const [materialType, setMaterialType] = useState("textbook");
  const [isPrimary, setIsPrimary] = useState(true);
  const [uploadStatus, setUploadStatus] = useState("");

  const [numQuestions, setNumQuestions] = useState(3);
  const [difficulty, setDifficulty] = useState("正常");
  const [questionTypes, setQuestionTypes] = useState<string[]>(["选择", "填空", "问答"]);
  const [quizId, setQuizId] = useState("");
  const [quizStatus, setQuizStatus] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [attemptId, setAttemptId] = useState("");
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [mistakes, setMistakes] = useState<Mistake[]>([]);

  // ---- M3: Coach state ----
  const [coachStatus, setCoachStatus] = useState("");
  const [coachPlanDoc, setCoachPlanDoc] = useState<CoachPlanDoc | null>(null);

  // ---- M3: Tutor state ----
  const [tutorOpen, setTutorOpen] = useState(false);
  const [tutorQuestionId, setTutorQuestionId] = useState<string>("");
  const [tutorSessionId, setTutorSessionId] = useState<string>("");
  const [tutorLevel, setTutorLevel] = useState<string>("L0");
  const [tutorTurn, setTutorTurn] = useState<number>(0);
  const [tutorMessages, setTutorMessages] = useState<TutorMessage[]>([]);
  const [tutorInput, setTutorInput] = useState<string>("");
  const [tutorGiveUp, setTutorGiveUp] = useState<boolean>(false);

  // ---- M2 state ----
  const [knowledgeTree, setKnowledgeTree] = useState<KnowledgeNode[]>([]);
  const [treeMaterialId, setTreeMaterialId] = useState<string>("");
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const [selectedNodeTitle, setSelectedNodeTitle] = useState<string>("");

  const [message, setMessage] = useState("");

  const selectedMaterialIds = useMemo(
    () => Object.keys(selectedMaterials).filter((id) => selectedMaterials[id]),
    [selectedMaterials],
  );

  const gradingMap = useMemo(() => {
    if (!attempt?.grading) {
      return new Map<string, NonNullable<Attempt["grading"]>[number]>();
    }
    return new Map(attempt.grading.map((item) => [item.question_id, item]));
  }, [attempt]);

  const loadMaterials = async () => {
    if (!notebookId.trim()) {
      setMessage("请先填写 notebook_id");
      return;
    }
    try {
      const data = await fetchJson<Material[]>(
        `${apiBase}/materials/?notebook_id=${encodeURIComponent(notebookId)}`,
      );
      setMaterials(data);
      // 默认用于知识树的 material：优先主教材，否则第一个
      if (!treeMaterialId) {
        const primary = data.find((m) => m.is_primary);
        setTreeMaterialId(primary?.id || data[0]?.id || "");
      }
      setMessage("材料列表已更新");
    } catch (err) {
      setMessage(`读取材料失败：${(err as Error).message}`);
    }
  };

  const normalizeMastery = (raw?: number) => {
    if (typeof raw !== "number" || Number.isNaN(raw)) return 0;
    // Accept either [0,1] or [0,100]
    if (raw > 1) return Math.max(0, Math.min(1, raw / 100));
    return Math.max(0, Math.min(1, raw));
  };

  const masteryLabel = (node: KnowledgeNode) => {
    const s = normalizeMastery(
      node.mastery_score ?? node.mastery ?? (typeof node.mastery_percent === "number" ? node.mastery_percent : undefined),
    );
    if (s >= 0.7) return { text: `${(s * 100).toFixed(0)}%`, cls: "mastery mastery--good" };
    if (s >= 0.4) return { text: `${(s * 100).toFixed(0)}%`, cls: "mastery mastery--mid" };
    return { text: `${(s * 100).toFixed(0)}%`, cls: "mastery mastery--low" };
  };

  const loadKnowledgeTree = async (materialId?: string) => {
    const mid = (materialId ?? treeMaterialId).trim();
    if (!mid) {
      setKnowledgeTree([]);
      return;
    }
    try {
      const url = new URL(`${apiBase}/knowledge/tree`);
      url.searchParams.set("material_id", mid);
      if (studentId.trim()) url.searchParams.set("student_id", studentId.trim());
      if (notebookId.trim()) url.searchParams.set("notebook_id", notebookId.trim());
      const data = await fetchJson<KnowledgeTreeResponse>(url.toString());
      setKnowledgeTree(data.tree || []);
    } catch (err) {
      setMessage(`读取知识树失败：${(err as Error).message}`);
    }
  };

  const uploadMaterial = async () => {
    if (!uploadFile) {
      setMessage("请选择文件");
      return;
    }
    setUploadStatus("上传中...");
    try {
      const form = new FormData();
      form.append("notebook_id", notebookId);
      form.append("material_type", materialType);
      form.append("is_primary", String(isPrimary));
      if (uploadTitle.trim()) {
        form.append("title", uploadTitle.trim());
      }
      if (uploadSourceType !== "auto") {
        form.append("source_type", uploadSourceType);
      }
      form.append("file", uploadFile);

      const data = await fetchJson<{ id: string; status: string; job_id?: string }>(
        `${apiBase}/materials/upload`,
        { method: "POST", body: form },
      );
      setUploadStatus(`已创建：${data.id} (${data.status})`);
      await loadMaterials();
    } catch (err) {
      setUploadStatus("");
      setMessage(`上传失败：${(err as Error).message}`);
    }
  };

  const generateQuiz = async () => {
    const scopedByNode = !!selectedNodeId;
    const materialIdsForQuiz = scopedByNode
      ? (treeMaterialId ? [treeMaterialId] : [])
      : selectedMaterialIds;

    if (materialIdsForQuiz.length === 0) {
      setMessage(scopedByNode ? "请先在 M2 选择用于知识树的 material" : "请至少选择一个材料");
      return;
    }
    if (numQuestions < 1 || numQuestions > 5) {
      setMessage("题量必须在 1 到 5 之间");
      return;
    }
    if (questionTypes.length === 0) {
      setMessage("请至少选择一种题型");
      return;
    }
    try {
      setQuizStatus("出题中...");
      const payload = {
        notebook_id: notebookId,
        // 规则：
        // - 若在 M2 选择了章节/知识点，则以该知识树所属 material 作为出题语料，并传递 node_id 做范围约束。
        // - 若未选择章节，则使用【材料列表】中勾选的 materials 进行全局出题。
        material_ids: materialIdsForQuiz,
        num_questions: numQuestions,
        difficulty,
        question_types: questionTypes,
        // ---- M2: 按章节/知识点出题（可选）----
        node_id: selectedNodeId || undefined,
      };
      const data = await fetchJson<{ id: string; status: string }>(
        `${apiBase}/quizzes/generate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      setQuizId(data.id);
      setQuizStatus("排队中...");
      await pollQuiz(data.id);
    } catch (err) {
      setQuizStatus("");
      setMessage(`出题失败：${(err as Error).message}`);
    }
  };

  const pollQuiz = async (id: string) => {
    // Quiz generation can take longer (LLM call). Poll a bit longer and surface
    // failures to the user.
    for (let i = 0; i < 40; i += 1) {
      try {
        const data = await fetchJson<{ quiz: Quiz; questions: Question[] }>(`${apiBase}/quizzes/${id}`);
        setQuestions(data.questions || []);
        setQuizStatus(data.quiz.status || "ready");
        setAnswers({});
        if (data.quiz.status === "failed") {
          setMessage(`出题失败：${data.quiz.error_message || "unknown error"}`);
          return;
        }
        if (data.quiz.status === "ready") {
          return;
        }
      } catch (err) {
        setMessage(`查询测验失败：${(err as Error).message}`);
        return;
      }
      await sleep(1500);
    }
    setMessage("出题仍在进行中，请稍后再刷新（或检查 worker 日志/LLM KEY 配置）");
  };

  const submitAttempt = async () => {
    if (!quizId) {
      setMessage("请先生成测验");
      return;
    }
    setMessage("");
    try {
      const payload = {
        student_id: studentId,
        notebook_id: notebookId,
        // 让后端能明确把作答回流到对应的知识树范围（若后端支持这些字段则会使用；不支持也不会破坏）
        material_id: treeMaterialId || undefined,
        node_id: selectedNodeId || undefined,
        answers,
      };
      const data = await fetchJson<{ id: string; status: string }>(
        `${apiBase}/attempts/${quizId}/submit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      setAttemptId(data.id);
      await pollAttempt(data.id);
    } catch (err) {
      setMessage(`提交作答失败：${(err as Error).message}`);
    }
  };

  const pollAttempt = async (id: string) => {
    for (let i = 0; i < 10; i += 1) {
      try {
        const data = await fetchJson<Attempt>(`${apiBase}/attempts/${id}`);
        setAttempt(data);
        if (data.status === "done") {
          await loadMistakes();
          // ---- M2: 判卷完成后刷新知识树（mastery 回流可见）----
          await loadKnowledgeTree();
          return;
        }
      } catch (err) {
        setMessage(`查询判卷失败：${(err as Error).message}`);
        return;
      }
      await sleep(1500);
    }
  };

  const loadMistakes = async () => {
    try {
      const data = await fetchJson<{ mistakes: Mistake[] }>(
        `${apiBase}/mistakes?student_id=${encodeURIComponent(studentId)}&notebook_id=${encodeURIComponent(notebookId)}`,
      );
      setMistakes(data.mistakes || []);
    } catch (err) {
      setMessage(`读取错题失败：${(err as Error).message}`);
    }
  };

  // ---------------- M3: Coach ----------------
  const fetchCoachLatest = async () => {
    const url = new URL(`${apiBase}/coach/latest`);
    url.searchParams.set("student_id", studentId.trim());
    if (notebookId.trim()) url.searchParams.set("notebook_id", notebookId.trim());
    if (treeMaterialId.trim()) url.searchParams.set("material_id", treeMaterialId.trim());
    return fetchJson<{ plan: CoachPlanDoc | null }>(url.toString());
  };

  const generateCoach = async () => {
    if (!studentId.trim()) {
      setMessage("请先填写 student_id");
      return;
    }
    setCoachStatus("生成小灶建议中...");
    setCoachPlanDoc(null);
    try {
      await fetchJson<{ status: string; job_id: string }>(`${apiBase}/coach/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: studentId.trim(),
          notebook_id: notebookId.trim() || null,
          material_id: treeMaterialId.trim() || null,
          days: 14,
          top_k: 5,
        }),
      });

      // Poll latest plan
      for (let i = 0; i < 20; i += 1) {
        const data = await fetchCoachLatest();
        if (data.plan) {
          setCoachPlanDoc(data.plan);
          setCoachStatus(data.plan.status === "failed" ? "小灶建议生成失败" : "小灶建议已生成");
          return;
        }
        await sleep(1500);
      }
      setCoachStatus("小灶建议仍在生成中，请稍后再点‘刷新’或查看 worker 日志");
    } catch (err) {
      setCoachStatus("");
      setMessage(`生成小灶建议失败：${(err as Error).message}`);
    }
  };

  const refreshCoach = async () => {
    try {
      const data = await fetchCoachLatest();
      setCoachPlanDoc(data.plan);
      setCoachStatus(data.plan ? (data.plan.status === "failed" ? "小灶建议生成失败" : "小灶建议已生成") : "暂无小灶建议");
    } catch (err) {
      setMessage(`刷新小灶建议失败：${(err as Error).message}`);
    }
  };

  const oneClickPractice = async () => {
    const oc = coachPlanDoc?.plan?.one_click_practice;
    if (!oc) {
      setMessage("暂无可用的一键再练计划");
      return;
    }
    const materialIds = (oc.material_ids && oc.material_ids.length > 0)
      ? oc.material_ids
      : (treeMaterialId ? [treeMaterialId] : selectedMaterialIds);
    if (materialIds.length === 0) {
      setMessage("缺少 material_ids：请先上传材料并在‘材料列表’勾选或选择知识树 material");
      return;
    }

    try {
      setQuizStatus("一键再练出题中...");
      const payload = {
        notebook_id: notebookId,
        material_ids: materialIds,
        num_questions: Math.max(1, Math.min(5, oc.num_questions || 5)),
        node_id: oc.node_id || undefined,
        type_mix: oc.type_mix || undefined,
        difficulty_mix: oc.difficulty_mix || undefined,
      };
      const data = await fetchJson<{ id: string; status: string }>(`${apiBase}/quizzes/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setQuizId(data.id);
      setQuestions([]);
      setAnswers({});
      await pollQuiz(data.id);
      setMessage("已按小灶建议生成‘再练’测验");
    } catch (err) {
      setMessage(`一键再练失败：${(err as Error).message}`);
    }
  };

  // ---------------- M3: Tutor ----------------
  const startTutorForQuestion = async (q: Question) => {
    const grading = gradingMap.get(q.id);
    const missing = grading?.result?.missing_points || [];
    const tags = grading?.result?.error_tags || [];

    setTutorOpen(true);
    setTutorQuestionId(q.id);
    setTutorMessages([
      { role: "assistant", content: "我们来一步步把这题做对。先从你的思路开始。" },
    ]);
    setTutorInput("");
    setTutorGiveUp(false);

    try {
      const start = await fetchJson<{ session_id: string; hint_level: string; turn: number }>(`${apiBase}/tutor/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: studentId.trim(),
          question_id: q.id,
          stem: q.stem,
          student_answer: answers[q.id] || "",
          missing_points: missing,
          error_tags: tags,
          weak_node_ids: [],
          hint_level: "L0",
        }),
      });
      setTutorSessionId(start.session_id);
      setTutorLevel(start.hint_level);
      setTutorTurn(start.turn);

      // Auto fetch the first hint
      const first = await fetchJson<{ assistant: any; hint_level: string; turn: number }>(`${apiBase}/tutor/next`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: start.session_id, message: "", give_up: false }),
      });
      const hint = first.assistant?.hint || first.assistant?.question || JSON.stringify(first.assistant);
      const ask = first.assistant?.question ? `\n\n👉 ${first.assistant.question}` : "";
      setTutorMessages((prev) => [...prev, { role: "assistant", content: `${hint}${ask}` }]);
      setTutorLevel(first.hint_level || start.hint_level);
      setTutorTurn(first.turn || start.turn + 1);
    } catch (err) {
      setMessage(`Tutor 启动失败：${(err as Error).message}`);
    }
  };

  const sendTutor = async () => {
    if (!tutorSessionId) {
      setMessage("Tutor session 未创建");
      return;
    }
    const text = tutorInput.trim();
    if (!text && !tutorGiveUp) {
      setMessage("请输入你的想法，或勾选‘我放弃’获取最终解答");
      return;
    }
    if (text) {
      setTutorMessages((prev) => [...prev, { role: "user", content: text }]);
    }
    setTutorInput("");

    try {
      const data = await fetchJson<{ assistant: any; hint_level: string; turn: number }>(`${apiBase}/tutor/next`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: tutorSessionId, message: text, give_up: tutorGiveUp }),
      });
      const hint = data.assistant?.hint || data.assistant?.answer || "";
      const q = data.assistant?.question ? `\n\n👉 ${data.assistant.question}` : "";
      const final = data.assistant?.final_answer ? `\n\n✅ 最终：${data.assistant.final_answer}` : "";
      setTutorMessages((prev) => [...prev, { role: "assistant", content: `${hint}${q}${final}`.trim() || JSON.stringify(data.assistant) }]);
      setTutorLevel(data.hint_level || tutorLevel);
      setTutorTurn(data.turn || tutorTurn + 1);
    } catch (err) {
      setMessage(`Tutor 失败：${(err as Error).message}`);
    }
  };

  const renderTree = (nodes: KnowledgeNode[], depth = 0) => {
    if (!nodes || nodes.length === 0) return null;
    return (
      <ul className="tree">
        {nodes.map((n) => {
          const label = masteryLabel(n);
          const active = selectedNodeId === n.id;
          return (
            <li key={n.id} className="tree__item">
              <button
                type="button"
                className={active ? "tree__node tree__node--active" : "tree__node"}
                style={{ paddingLeft: 12 + depth * 16 }}
                onClick={() => {
                  setSelectedNodeId(n.id);
                  setSelectedNodeTitle(n.title);
                }}
                title="点击后生成测验将只围绕该章节"
              >
                <span className="tree__title">{n.title}</span>
                <span className={label.cls}>{label.text}</span>
              </button>
              {n.children && n.children.length > 0 && renderTree(n.children, depth + 1)}
            </li>
          );
        })}
      </ul>
    );
  };

  const toggleType = (value: string) => {
    setQuestionTypes((prev) =>
      prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value],
    );
  };

  return (
    <div className="page">
      <header className="hero">
        <div className="hero__content">
          <p className="eyebrow">云原生 · 评测闭环 · M2 Demo</p>
          <h1>学习效果评估与巩固智能体</h1>
          <p className="hero__subtitle">
            从资料导入到出题判卷，再到错题沉淀与掌握度回流（知识树），形成可视化学习闭环。
          </p>
        </div>
        <div className="hero__panel">
          <div className="panel-row">
            <label>API Base</label>
            <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          </div>
          <div className="panel-row">
            <label>Notebook</label>
            <input value={notebookId} onChange={(e) => setNotebookId(e.target.value)} />
          </div>
          <div className="panel-row">
            <label>Student</label>
            <input value={studentId} onChange={(e) => setStudentId(e.target.value)} />
          </div>
          <div className="panel-actions">
            <button className="ghost" onClick={loadMaterials}>
              拉取材料
            </button>
            <button className="ghost" onClick={() => loadKnowledgeTree()}>
              刷新知识树
            </button>
            <button className="ghost" onClick={loadMistakes}>
              刷新错题
            </button>
          </div>
        </div>
      </header>

      {message && <div className="toast">{message}</div>}

      <main className="grid">
        <section className="card" style={cardStyle(0)}>
          <h2>1. 上传资料</h2>
          <p className="muted">支持 PDF / DOCX / MP3，后端会自动转写为文本。</p>
          <div className="form">
            <label className="file">
              <input
                type="file"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
              <span>{uploadFile ? uploadFile.name : "选择文件"}</span>
            </label>
            <div className="row">
              <input
                placeholder="标题（可选）"
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
              />
              <select value={materialType} onChange={(e) => setMaterialType(e.target.value)}>
                <option value="textbook">教材</option>
                <option value="note">笔记</option>
                <option value="handout">讲义</option>
                <option value="other">其他</option>
              </select>
            </div>
            <div className="row">
              <select value={uploadSourceType} onChange={(e) => setUploadSourceType(e.target.value)}>
                <option value="auto">自动识别类型</option>
                <option value="pdf">PDF</option>
                <option value="docx">DOCX</option>
                <option value="audio">音频</option>
                <option value="text">TXT</option>
              </select>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={isPrimary}
                  onChange={(e) => setIsPrimary(e.target.checked)}
                />
                设为主教材
              </label>
            </div>
            <button onClick={uploadMaterial}>上传并解析</button>
            {uploadStatus && <p className="status">{uploadStatus}</p>}
          </div>
        </section>

        <section className="card" style={cardStyle(1)}>
          <h2>2. 材料列表</h2>
          <p className="muted">
            用于<span className="chip chip--primary">全局出题</span>的材料范围。
            <br />
            若你在 <strong>3. M2</strong> 选择了章节/知识点，则出题会<strong>以知识树所属 material</strong>为准（并按章节约束），此处勾选将被忽略。
          </p>
          <div className="list">
            {materials.length === 0 && <p className="muted">暂无材料</p>}
            {materials.map((item) => (
              <label key={item.id} className="list-item">
                <input
                  type="checkbox"
                  checked={!!selectedMaterials[item.id]}
                  onChange={(e) =>
                    setSelectedMaterials((prev) => ({
                      ...prev,
                      [item.id]: e.target.checked,
                    }))
                  }
                />
                <div>
                  <strong>{item.title}</strong>
                  <span className={`chip chip--${item.status}`}>{item.status}</span>
                  {item.is_primary && <span className="chip chip--primary">主教材</span>}
                </div>
                <small>
                  {item.source_type} · chunks {item.text_chunk_count}
                  {item.summary_chunk_count ? ` / summary ${item.summary_chunk_count}` : ""}
                </small>
              </label>
            ))}
          </div>
        </section>

        <section className="card" style={cardStyle(2)}>
          <h2>3. 知识体系与掌握度（M2）</h2>
          <p className="muted">
            选择一个 material 查看章节树；点击章节后，生成测验将<strong>只围绕该章节（及其子节点）</strong>出题。
            （这是“范围选择”的唯一入口。）
          </p>
          <div className="form">
            <div className="row">
              <label>
                用于知识树的 material
                <select
                  value={treeMaterialId}
                  onChange={(e) => {
                    const v = e.target.value;
                    setTreeMaterialId(v);
                    // 切换 material 时清空章节选择，避免误用旧 node
                    setSelectedNodeId("");
                    setSelectedNodeTitle("");
                    void loadKnowledgeTree(v);
                  }}
                >
                  <option value="">-- 请选择 --</option>
                  {materials.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.title}{m.is_primary ? "（主）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="ghost" onClick={() => loadKnowledgeTree()}>
                加载/刷新
              </button>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setSelectedNodeId("");
                  setSelectedNodeTitle("");
                }}
                title="清除章节选择后，将进行全局出题"
              >
                清除章节选择
              </button>
            </div>
            <div className="muted">
              当前章节：<strong>{selectedNodeTitle || "（未选择，默认全局出题）"}</strong>
            </div>
            <div className="tree-wrap">
              {knowledgeTree.length === 0 ? (
                <p className="muted">暂无知识树，请先上传并解析材料，然后点击“加载/刷新”。</p>
              ) : (
                renderTree(knowledgeTree)
              )}
            </div>
          </div>
        </section>

        <section className="card" style={cardStyle(3)}>
          <h2>4. 出题设置</h2>
          <p className="muted">
            最多 5 题，支持多题型混合。
            {selectedNodeId ? (
              <>
                <br />当前已按 M2 章节范围出题：<strong>{selectedNodeTitle}</strong>
              </>
            ) : (
              <>
                <br />当前为全局出题：使用第 2 步勾选的材料。
              </>
            )}
          </p>
          <div className="form">
            <div className="row">
              <label>
                题量
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={numQuestions}
                  onChange={(e) => setNumQuestions(Number(e.target.value))}
                />
              </label>
              <label>
                难度
                <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
                  <option value="简单">简单</option>
                  <option value="正常">正常</option>
                  <option value="难">困难</option>
                </select>
              </label>
            </div>
            <div className="row tags">
              {"选择 填空 问答".split(" ").map((type) => (
                <button
                  type="button"
                  key={type}
                  className={questionTypes.includes(type) ? "tag active" : "tag"}
                  onClick={() => toggleType(type)}
                >
                  {type}
                </button>
              ))}
            </div>
            <button onClick={generateQuiz}>生成测验</button>
            {quizStatus && <p className="status">{quizStatus}</p>}
          </div>
        </section>

        <section className="card" style={cardStyle(4)}>
          <h2>5. 作答与判卷</h2>
          <p className="muted">测验编号：{quizId || "--"}</p>
          {questions.length === 0 ? (
            <p className="muted">请先生成测验。</p>
          ) : (
            <div className="questions">
              {questions.map((q, index) => {
                const grading = gradingMap.get(q.id);
                const isCorrect = grading?.is_correct ?? grading?.result?.is_correct;
                const score = grading?.score ?? grading?.result?.score;
                const mistakeAdded = grading?.mistake_added ?? (isCorrect === false);
                return (
                <div key={q.id} className="question">
                  <div className="question__header">
                    <span>
                      Q{index + 1} · {q.type}
                    </span>
                  </div>
                  <p>{q.stem}</p>
                  {q.type === "mcq" && q.options ? (
                    <div className="options">
                      {q.options.map((opt) => (
                        <label key={opt}>
                          <input
                            type="radio"
                            name={q.id}
                            value={opt}
                            checked={answers[q.id] === opt}
                            onChange={(e) =>
                              setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                            }
                          />
                          {opt}
                        </label>
                      ))}
                    </div>
                  ) : q.type === "short" ? (
                    <textarea
                      rows={3}
                      placeholder="输入简答..."
                      value={answers[q.id] || ""}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                      }
                    />
                  ) : (
                    <input
                      placeholder="输入答案..."
                      value={answers[q.id] || ""}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                      }
                    />
                  )}
                  {grading && (
                    <div className="grading">
                      <strong>解析：</strong> {grading?.analysis}
                      <div className="grading-meta">
                        <span>得分：{score ?? "--"}</span>
                        <span>判定：{isCorrect ? "正确" : "错误"}</span>
                        <span>错题本：{mistakeAdded ? "已加入" : "未加入"}</span>
                      </div>
                      {isCorrect === false && (
                        <div className="grading-actions">
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => startTutorForQuestion(q)}
                          >
                            Tutor 引导
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
              })}
              <button onClick={submitAttempt}>提交作答</button>
            </div>
          )}
          {attempt && (
            <div className="result">
              <p>
                判卷状态：<strong>{attempt.status}</strong> · 分数：
                <strong>{attempt.score ?? "--"}</strong>
              </p>
              {attemptId && <p className="muted">attempt_id: {attemptId}</p>}

              {/* ---------------- M3 entry buttons ---------------- */}
              <div className="result-actions">
                <button
                  type="button"
                  onClick={generateCoach}
                  disabled={attempt.status !== "done"}
                  title={attempt.status !== "done" ? "请先完成判卷" : "基于错题聚合生成小灶建议"}
                >
                  生成小灶建议
                </button>
                <button type="button" className="ghost" onClick={refreshCoach}>
                  刷新小灶建议
                </button>
                {coachStatus && <span className="muted">{coachStatus}</span>}
              </div>

              {coachPlanDoc?.plan && (
                <div className="coach">
                  <div className="coach__header">
                    <h3>小灶建议（Coach）</h3>
                    <button type="button" onClick={oneClickPractice}>
                      一键再练
                    </button>
                  </div>
                  <p className="muted">
                    {coachPlanDoc.plan.diagnosis?.summary || "（暂无摘要）"}
                  </p>
                  {coachPlanDoc.plan.corrective_actions && coachPlanDoc.plan.corrective_actions.length > 0 && (
                    <div className="coach__grid">
                      {coachPlanDoc.plan.corrective_actions.slice(0, 3).map((a, idx) => (
                        <div key={idx} className="coach__item">
                          <strong>{a.issue || `建议 ${idx + 1}`}</strong>
                          <p>{a.how_to_fix}</p>
                          <div className="coach__evidence">
                            {a.evidence?.missing_points?.length ? (
                              <span>缺失点：{a.evidence.missing_points.join("，")}</span>
                            ) : null}
                            {a.evidence?.error_tags?.length ? (
                              <span>错因标签：{a.evidence.error_tags.join("，")}</span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ---------------- M3: Tutor panel (minimal) ---------------- */}
        {tutorOpen && (
          <section className="card" style={cardStyle(4.5)}>
            <h2>5.1 Tutor 引导（Hint ladder）</h2>
            <p className="muted">
              当前题目：<strong>{tutorQuestionId || "--"}</strong> · level：<strong>{tutorLevel}</strong> · turn：<strong>{tutorTurn}</strong>
            </p>
            <div className="tutor">
              <div className="tutor__log">
                {tutorMessages.map((m, idx) => (
                  <div key={idx} className={m.role === "assistant" ? "tutor__msg tutor__msg--a" : "tutor__msg tutor__msg--u"}>
                    {m.content}
                  </div>
                ))}
              </div>
              <div className="tutor__controls">
                <textarea
                  rows={2}
                  placeholder="输入你的思路（或勾选‘我放弃’拿最终解答）"
                  value={tutorInput}
                  onChange={(e) => setTutorInput(e.target.value)}
                />
                <div className="tutor__row">
                  <label className="toggle">
                    <input type="checkbox" checked={tutorGiveUp} onChange={(e) => setTutorGiveUp(e.target.checked)} />
                    我放弃（允许 FINAL）
                  </label>
                  <div className="tutor__actions">
                    <button type="button" className="ghost" onClick={() => setTutorOpen(false)}>
                      关闭
                    </button>
                    <button type="button" onClick={sendTutor}>
                      发送
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        <section className="card" style={cardStyle(5)}>
          <h2>6. 错题与薄弱点</h2>
          <p className="muted">按 notebook 聚合的错题记录。</p>
          {mistakes.length === 0 ? (
            <p className="muted">暂无错题。</p>
          ) : (
            <div className="mistakes">
              {mistakes.map((item) => (
                <div key={item.id} className="mistake">
                  <h3>{item.knowledge_points?.join(" / ") || "未标注知识点"}</h3>
                  <p>{item.last_error_analysis}</p>
                  <div className="mistake__meta">
                    <span>错因标签：{item.error_tags.join(", ")}</span>
                    <span>累计次数：{item.wrong_count}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
