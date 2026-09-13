import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VideoPreview } from "./VideoPreview";

afterEach(() => vi.restoreAllMocks());

describe("VideoPreview", () => {
  it("keeps the player and external ref stable when a signed URL refreshes", () => {
    const ref = createRef<HTMLVideoElement>();
    const { rerender } = render(
      <VideoPreview
        src="/video?signature=old"
        ref={ref}
        aria-label="可刷新成片"
      />,
    );
    const player = ref.current;
    rerender(
      <VideoPreview
        src="/video?signature=new"
        ref={ref}
        aria-label="可刷新成片"
      />,
    );
    expect(ref.current).toBe(player);
    expect(player).toHaveAttribute("src", "/video?signature=new");
  });

  it("cancels background frame callbacks on pause and unmount", () => {
    const ref = createRef<HTMLVideoElement>();
    const { unmount } = render(<VideoPreview src="/wide.mp4" ref={ref} />);
    const video = ref.current as HTMLVideoElement;
    const request = vi.fn().mockReturnValue(7);
    const cancel = vi.fn();
    Object.defineProperties(video, {
      paused: { value: false },
      requestVideoFrameCallback: { value: request },
      cancelVideoFrameCallback: { value: cancel },
    });
    fireEvent.playing(video);
    expect(request).toHaveBeenCalledOnce();
    fireEvent.pause(video);
    expect(cancel).toHaveBeenCalledWith(7);
    fireEvent.playing(video);
    unmount();
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it("does not render an invisible blurred copy for exact portrait media", () => {
    const draw = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(
      <VideoPreview src="/portrait.mp4" ref={ref} />,
    );
    Object.defineProperties(ref.current, {
      videoWidth: { value: 1080 },
      videoHeight: { value: 1920 },
      readyState: { value: 2 },
    });
    fireEvent.loadedData(ref.current as HTMLVideoElement);
    expect(draw).not.toHaveBeenCalled();
    expect(container.querySelector("canvas")).toHaveAttribute("hidden");
  });
  it("uses one controllable video and decorates it without another audio stream", () => {
    const onPlay = vi.fn();
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(
      <VideoPreview
        src="/landscape.mp4"
        poster="/poster.jpg"
        aria-label="成片"
        controls
        ref={ref}
        onPlay={onPlay}
      />,
    );
    const video = screen.getByLabelText("成片");
    expect(container.querySelectorAll("video")).toHaveLength(1);
    expect(ref.current).toBe(video);
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("playsinline");
    expect(video).not.toHaveAttribute("autoplay");
    fireEvent.play(video);
    expect(onPlay).toHaveBeenCalledOnce();
    expect(container.querySelector("canvas")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("shows one accessible poster, reports a broken source once, and recovers when replaced", () => {
    const onError = vi.fn();
    const { rerender } = render(
      <VideoPreview
        poster="/wide.jpg"
        alt="横屏海报"
        onPosterError={onError}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(1);
    fireEvent.error(screen.getByRole("img", { name: "横屏海报" }));
    expect(onError).toHaveBeenCalledOnce();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    rerender(
      <VideoPreview
        poster="/tall.jpg"
        alt="竖屏海报"
        onPosterError={onError}
      />,
    );
    expect(screen.getByRole("img", { name: "竖屏海报" })).toHaveAttribute(
      "src",
      "/tall.jpg",
    );
  });

  it("draws the current landscape frame for the blurred background and stops after unmount", () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
      clearRect: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    const ref = createRef<HTMLVideoElement>();
    const onError = vi.fn();
    const { container, unmount } = render(
      <VideoPreview
        src="/wide.mp4"
        aria-label="横屏播放"
        ref={ref}
        onError={onError}
      />,
    );
    const video = ref.current as HTMLVideoElement;
    Object.defineProperties(video, {
      videoWidth: { value: 1920 },
      videoHeight: { value: 1080 },
      readyState: { value: 2 },
    });
    fireEvent.loadedData(video);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 160, 90);
    expect(container.querySelector("canvas")).not.toHaveAttribute("hidden");
    fireEvent.seeked(video);
    expect(drawImage).toHaveBeenCalledTimes(2);
    fireEvent.error(video);
    expect(onError).toHaveBeenCalledOnce();
    unmount();
    fireEvent.seeked(video);
    expect(drawImage).toHaveBeenCalledTimes(2);
  });
});
