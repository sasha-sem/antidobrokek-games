import { expect, test } from "@playwright/test";
import path from "node:path";

const configuredPack = process.env.E2E_EXISTING_PACK_PATH;
const hostSecret = process.env.E2E_HOST_SECRET;

test("одно видео запускается синхронно в двух браузерах", async ({ browser }) => {
  test.skip(!configuredPack || !hostSecret, "Нужны E2E_EXISTING_PACK_PATH и E2E_HOST_SECRET");
  const packPath = path.resolve(configuredPack!);
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  const first = await firstContext.newPage();
  const second = await secondContext.newPage();

  try {
    await first.goto("/");
    await first.getByRole("button", { name: "У меня есть пак" }).click();
    await first.getByLabel("Секрет создания игры").fill(hostSecret!);
    await first.locator('input[type="file"]').setInputFiles(packPath);
    await first.getByRole("button", { name: "Загрузить пак и войти" }).click();
    await expect(first).toHaveURL(/\/room\/[A-Z2-9]{6}$/);
    const inviteUrl = first.url();

    await first.getByLabel("Твоё имя").fill("Первый");
    await first.getByRole("button", { name: /Войти в лобби/ }).click();
    await second.goto(inviteUrl);
    await second.getByLabel("Твоё имя").fill("Второй");
    await second.getByRole("button", { name: /Войти в лобби/ }).click();

    for (const page of [first, second]) {
      await page.getByRole("button", { name: /Включить звук/ }).click();
    }
    await first.getByRole("button", { name: "Готов", exact: true }).click();
    await second.getByRole("button", { name: "Готов", exact: true }).click();

    await Promise.all([first, second].map((page) => expect(page.locator("video")).toBeVisible()));
    const started = await Promise.all(
      [first, second].map((page) => page.locator("video").evaluate(
        (element) => new Promise<number | null>((resolve) => {
          const video = element as HTMLVideoElement;
          if (!video.paused && video.currentTime > 0) {
            resolve(video.currentTime);
            return;
          }
          video.addEventListener("playing", () => resolve(video.currentTime), { once: true });
          window.setTimeout(() => resolve(null), 4_000);
        }),
      )),
    );
    expect(started[0]).not.toBeNull();
    expect(started[1]).not.toBeNull();
    expect(Math.abs(started[0]! - started[1]!)).toBeLessThan(1);
  } finally {
    if (!first.isClosed()) {
      await first.evaluate(async (secret) => {
        const body = new FormData();
        body.append("host_secret", secret);
        await fetch("/api/host/rooms/current/close", { method: "POST", body });
      }, hostSecret!).catch(() => undefined);
    }
    await firstContext.close();
    await secondContext.close();
  }
});
