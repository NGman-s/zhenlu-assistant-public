import { useState } from "react";
import type { SessionDetail } from "../types";
import { formatRecord, type TemplateSettings } from "../templates";
import { copyToClipboard } from "../utils";
import { Modal } from "./Modal";
export function RecordExport({
  workspace,
  templates,
  onClose,
}: {
  workspace: SessionDetail;
  templates: TemplateSettings;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState(templates.selected);
  const [manual, setManual] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const record = workspace.latest_record;
  if (!record) return null;
  const output = formatRecord(
    record,
    templates.items.find((t) => t.id === selected) || templates.items[0],
    workspace.patient_name,
    workspace.patient_ref,
  );
  async function copy(text: string) {
    if (await copyToClipboard(text)) {
      setStatus("已复制");
      setManual(null);
    } else {
      setManual(text);
      setStatus("浏览器未允许自动复制，请选中文本后手动复制。");
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob(["\ufeff", output.text], { type: "text/plain;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `${workspace.id}-v${record!.version}-病历.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Modal
      title="复制与导出已确认记录"
      subtitle={`${workspace.patient_name} · 第 ${record.version} 版`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={download}>
            导出 TXT
          </button>
          <button
            className="btn btn-primary"
            onClick={() => void copy(output.text)}
          >
            复制整段
          </button>
        </>
      }
    >
      <label className="form-label">
        机构模板
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {templates.items.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <textarea
        className="export-preview"
        aria-label="确认病历输出预览"
        readOnly
        value={output.text}
      />
      <p className="small-note">
        当前模板输出 {output.items.length}{" "}
        个字段。仅使用已确认记录，不读取未确认草稿。
      </p>
      <div className="export-fields">
        {output.items.map((r) => (
          <div key={r.key}>
            <span>{r.title}</span>
            <button
              className="btn btn-small"
              onClick={() => void copy(r.value)}
            >
              复制字段
            </button>
          </div>
        ))}
      </div>
      <p role="status">{status}</p>
      {manual !== null && (
        <textarea
          aria-label="手动复制内容"
          className="export-preview"
          readOnly
          value={manual}
          onFocus={(e) => e.target.select()}
          ref={(el) => {
            if (el) {
              el.focus();
              el.select();
            }
          }}
        />
      )}
    </Modal>
  );
}
