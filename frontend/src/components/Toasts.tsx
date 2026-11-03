export type ToastTone = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastStackProps {
  items: ToastItem[];
  onDismiss: (id: number) => void;
}

export function ToastStack({ items, onDismiss }: ToastStackProps) {
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {items.map((item) => (
        <div className={`toast toast-${item.tone}`} key={item.id}>
          <span className="toast-dot" aria-hidden="true" />
          <span className="toast-message">{item.message}</span>
          <button
            type="button"
            className="toast-close"
            aria-label="关闭提示"
            onClick={() => onDismiss(item.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
