import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import type { BusyAction, SessionDetail, TranscriptSegment } from "../types";
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

export function AudioPanel({ workspace, busy, onUpload }: AudioPanelProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const player = useRef<HTMLAudioElement>(null);
  const [rangeLabel, setRangeLabel] = useState("整段音频");
  const range = useRef<{ start: number; end: number } | null>(null);
  const audio = workspace.audio;
  useEffect(() => {
    let frame = 0;
    const element = player.current;
    function stopAtEnd() {
      if (!element) return;
      if (range.current && element.currentTime >= range.current.end) {
        element.pause();
        element.currentTime = range.current.end;
      }
      if (!element.paused) frame = requestAnimationFrame(stopAtEnd);
    }
    const playing = () => {
      cancelAnimationFrame(frame);
      stopAtEnd();
    };
    const seek = () => {
      if (
        element &&
        range.current &&
        (element.currentTime < range.current.start ||
          element.currentTime > range.current.end + 0.1)
      ) {
        range.current = null;
        setRangeLabel("整段音频");
      }
    };
    const pauseForAuth = () => element?.pause();
    async function sourcePlay(event: Event) {
      const detail = (
        event as CustomEvent<{ sessionId: string; source: TranscriptSegment }>
      ).detail;
      if (
        detail.sessionId !== workspace.id ||
        !element ||
        !workspace.transcript?.has_reliable_timestamps
      )
        return;
      const { start_ms: start, end_ms: end } = detail.source;
      if (
        start == null ||
        end == null ||
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        start < 0 ||
        end <= start
      )
        return;
      if (element.readyState < 1) {
        setLocalError("音频正在加载，请稍后再试。");
        return;
      }
      if (end / 1000 > element.duration + 0.1) {
        setLocalError("来源区间超出录音长度，请核对原文。");
        return;
      }
      range.current = { start: start / 1000, end: end / 1000 };
      setRangeLabel(
        `${(start / 1000).toFixed(1)}–${(end / 1000).toFixed(1)} 秒 · 到点暂停`,
      );
      element.currentTime = start / 1000;
      try {
        await element.play();
        setLocalError(null);
      } catch {
        setLocalError("无法播放录音，请检查音频或点击播放器重试。");
      }
    }
    window.addEventListener("zhenlu:play-source", sourcePlay);
    window.addEventListener("zhenlu:unauthorized", pauseForAuth);
    element?.addEventListener("play", playing);
    element?.addEventListener("seeking", seek);
    return () => {
      cancelAnimationFrame(frame);
      element?.pause();
      range.current = null;
      window.removeEventListener("zhenlu:play-source", sourcePlay);
      window.removeEventListener("zhenlu:unauthorized", pauseForAuth);
      element?.removeEventListener("play", playing);
      element?.removeEventListener("seeking", seek);
    };
  }, [
    workspace.id,
    workspace.audio?.url,
    workspace.transcript?.has_reliable_timestamps,
  ]);
  const uploadBusy = busy === "upload";

  function chooseFile(file: File | null | undefined) {
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      setLocalError("音频不能超过 50 MB。");
      setSelectedFile(null);
      return;
    }
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
            ref={player}
            onError={() => setLocalError("音频无法加载，请检查连接后重试。")}
            controls
            preload="metadata"
            src={audio.url}
            className="audio-player"
          >
            您的浏览器不支持音频播放。
          </audio>
          <div className="audio-range-controls">
            <span>{rangeLabel}</span>
            <button
              type="button"
              className="text-btn"
              onClick={() => {
                range.current = null;
                setRangeLabel("整段音频");
                if (player.current) {
                  player.current.currentTime = 0;
                  void player.current
                    .play()
                    .catch(() => setLocalError("无法播放音频"));
                }
              }}
            >
              整段播放
            </button>
            <label>
              速度
              <select
                aria-label="播放速度"
                defaultValue="1"
                onChange={(e) => {
                  if (player.current)
                    player.current.playbackRate = Number(e.target.value);
                }}
              >
                {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
                  <option key={rate} value={rate}>
                    {rate}×
                  </option>
                ))}
              </select>
            </label>
          </div>
          {localError && (
            <p className="field-error" role="alert">
              {localError}
              <button
                className="text-btn"
                onClick={() => {
                  player.current?.load();
                  setLocalError(null);
                }}
              >
                重新加载
              </button>
            </p>
          )}
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
            <span className="dropzone-title">
              拖拽音频到此处，或点击选择文件
            </span>
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
