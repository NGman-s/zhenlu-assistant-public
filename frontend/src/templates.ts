import type { ConfirmedRecord } from "./types";
export const fieldNames: Record<string, string> = {
  chief_complaint: "主诉",
  present_illness: "现病史",
  past_history: "既往史",
  medication_history: "用药史",
  allergy_history: "过敏史",
};
export interface TemplateRow {
  key: string;
  title: string;
  enabled: boolean;
  empty: "未提及" | "未记录" | "omit";
}
export interface RecordTemplate {
  id: string;
  name: string;
  identity: boolean;
  spacing: "single" | "double";
  rows: TemplateRow[];
}
export interface TemplateSettings {
  selected: string;
  items: RecordTemplate[];
}
export const defaultTemplates = (): TemplateSettings => ({
  selected: "general",
  items: [
    {
      id: "general",
      name: "全科门诊 · 标准病历",
      identity: false,
      spacing: "double",
      rows: Object.entries(fieldNames).map(([key, title]) => ({
        key,
        title,
        enabled: true,
        empty: "未提及",
      })),
    },
  ],
});
export function validateTemplate(t: RecordTemplate) {
  if (!t.id || typeof t.name !== "string" || !t.name.trim())
    throw new Error("请填写模板名称。");
  if (
    !["single", "double"].includes(t.spacing) ||
    !Array.isArray(t.rows) ||
    !t.rows.some((r) => r.enabled)
  )
    throw new Error("请至少启用一个有效字段。");
  if (new Set(t.rows.map((r) => r.key)).size !== t.rows.length)
    throw new Error("字段映射不能重复。");
  if (
    t.rows.some(
      (r) =>
        !fieldNames[r.key] ||
        typeof r.title !== "string" ||
        !r.title.trim() ||
        !["未提及", "未记录", "omit"].includes(r.empty),
    )
  )
    throw new Error("请检查字段映射、标题和空值规则。");
}
export function loadTemplates(owner: string): TemplateSettings {
  const raw = localStorage.getItem(`zhenlu.templates.${owner}`);
  if (!raw) return defaultTemplates();
  const data = JSON.parse(raw) as TemplateSettings;
  if (
    !Array.isArray(data.items) ||
    !data.items.length ||
    !data.items.some((t) => t.id === data.selected)
  )
    throw new Error("模板配置无法读取，请重新配置。");
  data.items.forEach(validateTemplate);
  return data;
}
export function saveTemplates(owner: string, data: TemplateSettings) {
  data.items.forEach(validateTemplate);
  localStorage.setItem(`zhenlu.templates.${owner}`, JSON.stringify(data));
}
export function formatRecord(
  record: ConfirmedRecord,
  template: RecordTemplate,
  patient: string,
  reference: string | null,
) {
  const items = template.rows
    .filter((r) => r.enabled)
    .flatMap((row) => {
      const field = record.fields.find((f) => f.key === row.key);
      if (!field) return [];
      const unknown = ["", "未提及", "未记录", "不详"].includes(
        field.value.trim(),
      );
      if (unknown && row.empty === "omit") return [];
      return [
        {
          key: row.key,
          title: row.title,
          value: unknown ? row.empty : field.value,
        },
      ];
    });
  const prefix = template.identity
    ? `${patient}${reference ? `｜${reference}` : ""}\n确认版本 ${record.version}｜${record.confirmed_at}\n\n`
    : "";
  return {
    items,
    text:
      prefix +
      items
        .map((r) => `${r.title}：${r.value}`)
        .join(template.spacing === "double" ? "\n\n" : "\n"),
  };
}
