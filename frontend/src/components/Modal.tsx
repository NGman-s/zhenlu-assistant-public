import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface ModalProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  closeDisabled?: boolean;
}

export function Modal({
  title,
  subtitle,
  children,
  footer,
  onClose,
  closeDisabled = false,
}: ModalProps) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !closeDisabled) {
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [closeDisabled, onClose]);

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !closeDisabled) {
          onClose();
        }
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="modal-title">{title}</h2>
            {subtitle ? <p className="modal-subtitle">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            disabled={closeDisabled}
            aria-label="关闭对话框"
          >
            ×
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-footer">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}
