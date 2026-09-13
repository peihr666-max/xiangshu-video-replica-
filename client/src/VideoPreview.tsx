import {
  type ComponentProps,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import "./video-preview.css";

type Props = ComponentProps<"video"> & {
  alt?: string;
  videoClassName?: string;
  onPosterError?: () => void;
  fallback?: ReactNode;
  overlay?: ReactNode;
};

/** One decoder/audio stream; the decorative canvas only copies already decoded frames.
 * No pixel reads or export, so signed cross-origin media needs no extra CORS permission.
 */
export function VideoPreview({
  src,
  poster,
  alt = "",
  className = "",
  videoClassName = "",
  ref,
  onPosterError,
  fallback,
  overlay,
  children,
  ...videoProps
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failedPoster, setFailedPoster] = useState<string>();
  const posterFailed = Boolean(poster && failedPoster === poster);
  const attachVideo = useCallback(
    (video: HTMLVideoElement | null) => {
      videoRef.current = video;
      if (typeof ref === "function") return ref(video);
      if (ref) ref.current = video;
    },
    [ref],
  );

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!src || !video || !canvas) return;
    canvas.hidden = true;
    let frameId: number | undefined;
    let animationId: number | undefined;
    let active = true;
    let lastPaint = 0;
    const stop = () => {
      if (frameId !== undefined) video.cancelVideoFrameCallback?.(frameId);
      if (animationId !== undefined) cancelAnimationFrame(animationId);
      frameId = undefined;
      animationId = undefined;
    };
    const paint = () => {
      if (
        !active ||
        document.hidden ||
        video.readyState < 2 ||
        !video.videoWidth ||
        !video.videoHeight
      )
        return;
      // Exact portrait fills the foreground already; do not draw an invisible background.
      if (Math.abs(video.videoWidth / video.videoHeight - 9 / 16) < 0.01)
        return;
      try {
        const scale = Math.min(160 / video.videoWidth, 284 / video.videoHeight);
        const width = Math.max(1, Math.round(video.videoWidth * scale));
        const height = Math.max(1, Math.round(video.videoHeight * scale));
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
        }
        const context = canvas.getContext("2d");
        if (!context) return;
        context.drawImage(video, 0, 0, width, height);
        canvas.hidden = false;
      } catch {
        // A missing decoded frame must never interfere with playback or source retry.
        canvas.hidden = true;
      }
    };
    const tick = (now: number) => {
      if (!active || video.paused || video.ended) return;
      if (now - lastPaint >= 80) {
        paint();
        lastPaint = now;
      }
      schedule();
    };
    const schedule = () => {
      if (video.requestVideoFrameCallback)
        frameId = video.requestVideoFrameCallback(tick);
      else animationId = requestAnimationFrame(tick);
    };
    const start = () => {
      stop();
      paint();
      if (!video.paused && !video.ended) schedule();
    };
    const fail = () => {
      stop();
      canvas.hidden = true;
    };
    video.addEventListener("loadeddata", paint);
    video.addEventListener("seeked", paint);
    video.addEventListener("playing", start);
    video.addEventListener("pause", stop);
    video.addEventListener("ended", stop);
    video.addEventListener("error", fail);
    start();
    return () => {
      active = false;
      stop();
      video.removeEventListener("loadeddata", paint);
      video.removeEventListener("seeked", paint);
      video.removeEventListener("playing", start);
      video.removeEventListener("pause", stop);
      video.removeEventListener("ended", stop);
      video.removeEventListener("error", fail);
    };
  }, [src]);

  return (
    <div className={`video-preview ${className}`}>
      {poster && !posterFailed && (
        <img
          className="video-preview__backdrop"
          src={poster}
          alt=""
          aria-hidden="true"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      )}
      {src ? (
        <>
          <canvas
            className="video-preview__backdrop"
            ref={canvasRef}
            tabIndex={-1}
            aria-hidden="true"
            hidden
          />
          <video
            {...videoProps}
            ref={attachVideo}
            className={`video-preview__foreground ${videoClassName}`}
            src={src}
            poster={posterFailed ? undefined : poster}
            playsInline
            preload={videoProps.preload ?? "metadata"}
          >
            {children}
          </video>
        </>
      ) : poster && !posterFailed ? (
        <img
          className="video-preview__foreground"
          src={poster}
          alt={alt}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => {
            setFailedPoster(poster);
            onPosterError?.();
          }}
        />
      ) : (
        <div className="video-preview__empty">
          {fallback ??
            (posterFailed ? "预览图暂不可用" : alt || "暂无视频预览")}
        </div>
      )}
      {overlay}
    </div>
  );
}
