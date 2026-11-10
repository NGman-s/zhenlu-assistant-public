import { useState, type ChangeEvent, type DragEvent } from "react";
import type { BusyAction, SessionDetail } from "../types";
import { formatFileSize } from "../utils";

interface AudioPanelProps {
  workspace: SessionDetail;
  busy: BusyAction;
  onUpload: (file: File) => void;
}

function AudioGlyph() {
  return (
    <svg className="audio-glyph" viewBox="0 0 44 44" aria-hidden="true">
      <rect x="3" y="3" width="38" height="38" rx="12" />
      <path d="M14 27V17M20 30V14M26 26V18M32 24V20" />
    </svg>
  );
}

export function AudioPanel({
  workspace,
  busy,
  onUpload,
}: AudioPanelProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const audio = workspace.audio;
  const uploadBusy = busy === "upload";

  function chooseFile(file: File | null | undefined) {
    if (!file) return;
    if (file.size === 0) {
      setSelectedFile(null);
      setLocalError("该文件为空，请选择有效的音频文件。");
      return;
    }
    setLocalError(null);
    setSelectedFile(file);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    chooseFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragActive(false);
    if (uploadBusy) return;
    chooseFile(event.dataTransfer.files?.[0]);
  }

  if (audio) {
    return (
      <section className="card audio-card audio-card-ready">
        <div className="audio-summary">
          <AudioGlyph />
          <div className="audio-file-block">
            <div className="audio-file-topline">
              <h2>问诊音频</h2>
            </div>
            <p className="audio-filename" title={audio.filename}>
              {audio.filename}
            </p>
          </div>
        </div>
        <div className="audio-player-wrap">
          <audio
            id="consultation-audio"
            controls
            preload="metadata"
            src={audio.url}
            className="audio-player"
          >
            您的浏览器不支持音频播放。
          </audio>
        </div>
      </section>
    );
  }

  return (
    <section className="card audio-card">
      <header className="card-header">
        <div>
          <h2>上传音频</h2>
        </div>
      </header>

      <div className="audio-upload-body">
        <div className="upload-column">
          <label
            className={`dropzone${dragActive ? " dragging" : ""}${
              uploadBusy ? " disabled" : ""
            }`}
            onDragOver={(event) => {
              event.preventDefault();
              if (!uploadBusy) setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
          >
            <input
              type="file"
              accept=".wav,.mp3,.m4a,.ogg,.webm,.flac,audio/*"
              onChange={handleInputChange}
              disabled={uploadBusy}
              className="sr-only"
            />
            <span className="dropzone-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M12 16V5m0 0-4 4m4-4 4 4M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3" />
              </svg>
            </span>
            <span className="dropzone-title">拖拽音频到此处，或点击选择文件</span>
            <span className="dropzone-hint">
              支持 WAV、MP3、M4A、OGG、WEBM、FLAC；单段音频
            </span>
          </label>

          {selectedFile ? (
            <div className="selected-file">
              <div className="selected-file-main">
                <span className="selected-file-name" title={selectedFile.name}>
                  {selectedFile.name}
                </span>
                <span className="selected-file-meta">
                  {formatFileSize(selectedFile.size)} · 待上传
                </span>
              </div>
              <div className="selected-file-actions">
                <button
                  type="button"
                  className="text-btn"
                  onClick={() => setSelectedFile(null)}
                  disabled={uploadBusy}
                >
                  移除
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-small"
                  onClick={() => onUpload(selectedFile)}
                  disabled={uploadBusy}
                >
                  {busy === "upload" ? "正在上传…" : "上传音频"}
                </button>
              </div>
            </div>
          ) : null}

          {localError ? (
            <p className="field-error" role="alert">
              {localError}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
