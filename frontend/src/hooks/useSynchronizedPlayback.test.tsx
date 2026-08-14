import { act, render } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { CurrentQuestion } from "../types/events";
import { useSynchronizedPlayback } from "./useSynchronizedPlayback";

const question: CurrentQuestion = {
  position: 1,
  question_count: 1,
  media_url: "/media/test.mp4",
  duration_ms: 5_000,
  starts_at: "2026-08-14T10:00:01.000Z",
  ends_at: "2026-08-14T10:00:06.000Z",
};

function Harness({ serverOffsetMs }: { serverOffsetMs: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [, setMuted] = useState(false);
  useSynchronizedPlayback({
    active: true,
    question,
    serverOffsetMs,
    setMuted,
    videoRef,
  });
  return <video ref={videoRef} />;
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("перепланирует старт при изменении clock offset до starts_at", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-14T10:00:00.000Z"));
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  const view = render(<Harness serverOffsetMs={0} />);

  await act(async () => vi.advanceTimersByTime(400));
  view.rerender(<Harness serverOffsetMs={100} />);
  await act(async () => vi.advanceTimersByTime(500));

  expect(play).toHaveBeenCalled();
});

test("при запрете autoplay запускает видео без звука", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-14T10:00:01.000Z"));
  const play = vi
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockRejectedValueOnce(new DOMException("Autoplay blocked", "NotAllowedError"))
    .mockResolvedValueOnce();
  const view = render(<Harness serverOffsetMs={0} />);

  await act(async () => vi.advanceTimersByTime(0));

  expect(play).toHaveBeenCalledTimes(2);
  expect(view.container.querySelector("video")?.muted).toBe(true);
});
