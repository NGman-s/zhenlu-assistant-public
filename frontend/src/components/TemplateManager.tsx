import { useState } from "react";
import {
  fieldNames,
  validateTemplate,
  type RecordTemplate,
  type TemplateSettings,
} from "../templates";
import { errorMessage } from "../utils";
export function TemplateManager({
  value,
  onSave,
  onDirtyChange,
}: {
  value: TemplateSettings;
  onSave: (v: TemplateSettings) => boolean;
  onDirtyChange: (v: boolean) => void;
}) {
  const [draft, setDraft] = useState<RecordTemplate>(() =>
    structuredClone(value.items.find((t) => t.id === value.selected)!),
  );
  const [error, setError] = useState("");
  const saved = value.items.find((t) => t.id === draft.id);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  function edit(next: RecordTemplate) {
    setDraft(next);
    onDirtyChange(
      JSON.stringify(next) !==
        JSON.stringify(value.items.find((t) => t.id === next.id)),
    );
  }
  function save(asNew: boolean) {
    try {
      validateTemplate(draft);
      const next = {
        ...draft,
        name: draft.name.trim(),
        id: asNew ? crypto.randomUUID() : draft.id,
      };
      if (
        onSave({
          selected: next.id,
          items: asNew
            ? [...value.items, next]
            : value.items.map((t) => (t.id === next.id ? next : t)),
        })
      ) {
        setDraft(structuredClone(next));
        onDirtyChange(false);
        setError("");
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <div className="template-layout">
      <section className="surface">
        <h2>机构模板</h2>
        {value.items.map((t) => (
          <button
            key={t.id}
            className={`template-choice ${t.id === draft.id ? "active" : ""}`}
            onClick={() => {
              if (dirty && !confirm("当前模板有未保存修改，确定切换？")) return;
              setDraft(structuredClone(t));
              onDirtyChange(false);
              setError("");
            }}
          >
            {t.name}
            <small>{t.rows.filter((r) => r.enabled).length} 个输出字段</small>
          </button>
        ))}
        <p className="small-note">模板保存在当前浏览器，不改变已确认病历。</p>
      </section>
      <section className="surface">
        <label className="form-label">
          模板名称
          <input
            value={draft.name}
            maxLength={80}
            onChange={(e) => edit({ ...draft, name: e.target.value })}
          />
        </label>
        <div className="template-rows">
          {draft.rows.map((row, index) => (
            <div className="template-config-row" key={index}>
              <div className="row-between">
                <label>
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={(e) =>
                      edit({
                        ...draft,
                        rows: draft.rows.map((r, i) =>
                          i === index ? { ...r, enabled: e.target.checked } : r,
                        ),
                      })
                    }
                  />
                  输出字段 {index + 1}
                </label>
                <div>
                  {[-1, 1].map((direction) => (
                    <button
                      className="btn btn-tiny"
                      key={direction}
                      disabled={
                        index + direction < 0 ||
                        index + direction >= draft.rows.length
                      }
                      aria-label={`${direction < 0 ? "上移" : "下移"}字段 ${index + 1}`}
                      onClick={() => {
                        const rows = [...draft.rows];
                        [rows[index], rows[index + direction]] = [
                          rows[index + direction],
                          rows[index],
                        ];
                        edit({ ...draft, rows });
                      }}
                    >
                      {direction < 0 ? "↑" : "↓"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="template-inputs">
                <label>
                  病历字段
                  <select
                    value={row.key}
                    onChange={(e) =>
                      edit({
                        ...draft,
                        rows: draft.rows.map((r, i) =>
                          i === index ? { ...r, key: e.target.value } : r,
                        ),
                      })
                    }
                  >
                    {Object.entries(fieldNames).map(([key, title]) => (
                      <option key={key} value={key}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  输出标题
                  <input
                    value={row.title}
                    maxLength={80}
                    onChange={(e) =>
                      edit({
                        ...draft,
                        rows: draft.rows.map((r, i) =>
                          i === index ? { ...r, title: e.target.value } : r,
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  空值规则
                  <select
                    value={row.empty}
                    onChange={(e) =>
                      edit({
                        ...draft,
                        rows: draft.rows.map((r, i) =>
                          i === index
                            ? {
                                ...r,
                                empty: e.target.value as typeof row.empty,
                              }
                            : r,
                        ),
                      })
                    }
                  >
                    <option>未提及</option>
                    <option>未记录</option>
                    <option value="omit">省略空字段</option>
                  </select>
                </label>
              </div>
            </div>
          ))}
        </div>
        <div className="form-grid">
          <label className="form-label">
            字段间隔
            <select
              value={draft.spacing}
              onChange={(e) =>
                edit({
                  ...draft,
                  spacing: e.target.value as RecordTemplate["spacing"],
                })
              }
            >
              <option value="double">空一行</option>
              <option value="single">仅换行</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.identity}
              onChange={(e) => edit({ ...draft, identity: e.target.checked })}
            />
            包含患者与确认标识
          </label>
        </div>
        <pre className="template-preview">
          {draft.rows
            .filter((r) => r.enabled)
            .map((r) => `${r.title}：[${fieldNames[r.key]}]`)
            .join(draft.spacing === "double" ? "\n\n" : "\n")}
        </pre>
        <p className="field-error" role="alert">
          {error}
        </p>
        <div className="page-actions">
          <button className="btn btn-secondary" onClick={() => save(true)}>
            另存为新模板
          </button>
          <button className="btn btn-primary" onClick={() => save(false)}>
            保存并使用模板
          </button>
        </div>
      </section>
    </div>
  );
}
