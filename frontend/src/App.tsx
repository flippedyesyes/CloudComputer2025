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
        `${apiBase}/materials?notebook_id=${encodeURIComponent(notebookId)}`,
      );
      setMaterials(data);
      setMessage("材料列表已更新");
    } catch (err) {
      setMessage(`读取材料失败：${(err as Error).message}`);
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
    if (selectedMaterialIds.length === 0) {
      setMessage("请至少选择一个材料");
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
        material_ids: selectedMaterialIds,
        num_questions: numQuestions,
        difficulty,
        question_types: questionTypes,
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
    for (let i = 0; i < 10; i += 1) {
      try {
        const data = await fetchJson<{ quiz: Quiz; questions: Question[] }>(`${apiBase}/quizzes/${id}`);
        setQuestions(data.questions || []);
        setQuizStatus(data.quiz.status || "ready");
        setAnswers({});
        if (data.quiz.status === "ready") {
          return;
        }
      } catch (err) {
        setMessage(`查询测验失败：${(err as Error).message}`);
        return;
      }
      await sleep(1500);
    }
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

  const toggleType = (value: string) => {
    setQuestionTypes((prev) =>
      prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value],
    );
  };

  return (
    <div className="page">
      <header className="hero">
        <div className="hero__content">
          <p className="eyebrow">云原生 · 评测闭环 · M1 Demo</p>
          <h1>学习效果评估与巩固智能体</h1>
          <p className="hero__subtitle">
            从资料导入到出题判卷，再到错题沉淀与薄弱点诊断，一条链路清晰可见。
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
          <p className="muted">选择需要参与出题的材料。</p>
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
          <h2>3. 出题设置</h2>
          <p className="muted">最多 5 题，支持多题型混合。</p>
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

        <section className="card" style={cardStyle(3)}>
          <h2>4. 作答与判卷</h2>
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
            </div>
          )}
        </section>

        <section className="card" style={cardStyle(4)}>
          <h2>5. 错题与薄弱点</h2>
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
