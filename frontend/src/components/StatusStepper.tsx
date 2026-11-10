import type { BusyAction, SessionStatus } from "../types";

interface StatusStepperProps {
  status: SessionStatus;
  hasAudio: boolean;
  hasTranscript: boolean;
  hasDraft: boolean;
  busy: BusyAction;
}

type StepState = "done" | "active" | "pending";

interface Step {
  label: string;
  state: StepState;
  busy?: boolean;
}

export function StatusStepper({
  status,
  hasAudio,
  hasTranscript,
  hasDraft,
  busy,
}: StatusStepperProps) {
  const confirmed = status === "confirmed";
  if (!hasAudio) {
    const steps: Step[] = [
      { label: "创建会话", state: "done" },
      { label: hasTranscript ? "录入文字" : "录入文字或音频", state: hasTranscript ? "done" : "active", busy: busy === "transcribe" || busy === "upload" },
      { label: "草稿生成", state: hasDraft ? "done" : hasTranscript ? "active" : "pending", busy: busy === "generate" },
      { label: confirmed ? "已确认" : "审核确认", state: confirmed ? "done" : hasDraft ? "active" : "pending", busy: busy === "confirm" },
    ];
    return (
      <ol className="stepper" aria-label="问诊处理进度">
        {steps.map((step, index) => (
          <li key={step.label} className={`step ${step.state}${step.busy ? " busy" : ""}`} aria-current={step.state === "active" ? "step" : undefined}>
            <span className="step-dot" aria-hidden="true">{step.state === "done" ? "✓" : index + 1}</span>
            <span className="step-label">{step.label}</span>
          </li>
        ))}
      </ol>
    );
  }
  const steps: Step[] = [
    { label: "创建会话", state: "done" },
    {
      label: "上传音频",
      state: hasAudio ? "done" : "active",
      busy: busy === "upload",
    },
    {
      label: "语音转写",
      state: hasTranscript ? "done" : hasAudio ? "active" : "pending",
      busy: busy === "transcribe",
    },
    {
      label: "草稿生成",
      state: hasDraft ? "done" : hasTranscript ? "active" : "pending",
      busy: busy === "generate",
    },
    {
      label: confirmed ? "已确认" : "审核确认",
      state: confirmed ? "done" : hasDraft ? "active" : "pending",
      busy: busy === "confirm",
    },
  ];

  return (
    <ol className="stepper" aria-label="问诊处理进度">
      {steps.map((step, index) => (
        <li
          key={step.label}
          className={`step ${step.state}${step.busy ? " busy" : ""}`}
          aria-current={step.state === "active" ? "step" : undefined}
        >
          <span className="step-dot" aria-hidden="true">
            {step.state === "done" ? "✓" : index + 1}
          </span>
          <span className="step-label">{step.label}</span>
        </li>
      ))}
    </ol>
  );
}
