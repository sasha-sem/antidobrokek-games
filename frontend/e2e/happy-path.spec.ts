import { expect, test } from "@playwright/test";
import path from "node:path";

const packPath = path.resolve("../backend/tests/fixtures/e2e-pack.zip");

test("создатель и второй игрок проходят автоматическую игру", async ({ browser }) => {
  const creatorContext = await browser.newContext();
  const secondContext = await browser.newContext();
  await creatorContext.grantPermissions(["clipboard-read", "clipboard-write"]);
  const creator = await creatorContext.newPage();
  const second = await secondContext.newPage();

  await creator.goto("/");
  await creator.getByRole("button", { name: "У меня есть пак" }).click();
  await creator.getByLabel("Секрет создания игры").fill("host-secret-for-e2e");
  await creator.locator('input[type="file"]').setInputFiles(packPath);
  await creator.getByRole("button", { name: "Загрузить пак и войти" }).click();

  await expect(creator).toHaveURL(/\/room\/[A-Z2-9]{6}$/);
  const code = creator.url().split("/").pop()!;
  await expect(creator.getByRole("heading", { name: code })).toBeVisible();
  await creator.getByLabel("Твоё имя").fill("Алиса");
  await creator.getByRole("button", { name: /Войти в лобби/ }).click();

  await creator.getByRole("button", { name: "Скопировать приглашение" }).click();
  await expect(creator.getByRole("button", { name: "Ссылка скопирована ✓" })).toBeVisible();
  const inviteUrl = await creator.evaluate(() => navigator.clipboard.readText());
  expect(inviteUrl).toBe(`http://127.0.0.1:5173/room/${code}`);

  // An invitation is a complete entry point: it asks for a name rather than
  // requiring a reconnect token created on the home page.
  await second.goto(inviteUrl);
  await expect(second.getByText("Приглашение в комнату")).toBeVisible();
  await second.getByLabel("Твоё имя").fill("Боб");
  await second.getByRole("button", { name: /Войти в лобби/ }).click();

  await expect(creator.getByText("Боб")).toBeVisible();
  for (const page of [creator, second]) {
    await page.getByRole("button", { name: /Включить звук/ }).click();
  }
  await creator.getByRole("button", { name: "Готов", exact: true }).click();
  await expect(creator.getByText(/когда все подключённые игроки будут готовы/i)).toBeVisible();
  await second.getByRole("button", { name: "Готов", exact: true }).click();

  await Promise.all([creator, second].map((page) => expect(page.locator("video")).toBeVisible()));
  const videoStarted = await Promise.all(
    [creator, second].map((page) => page.locator("video").evaluate(
      (element) => new Promise<boolean>((resolve) => {
        const video = element as HTMLVideoElement;
        if (!video.paused && video.currentTime > 0) {
          resolve(true);
          return;
        }
        video.addEventListener("playing", () => resolve(true), { once: true });
        window.setTimeout(() => resolve(false), 3_000);
      }),
    )),
  );
  expect(videoStarted).toEqual([true, true]);
  await expect(creator.getByRole("button", { name: "Саша" })).toBeVisible();
  await expect(second.getByRole("button", { name: "Миша" })).toBeVisible();
  await creator.getByRole("button", { name: "Саша" }).click();
  await second.getByRole("button", { name: "Миша" }).click();
  await expect(creator.getByText("Верно! +1")).toBeVisible();
  await expect(second.getByText("Неверно")).toBeVisible();
  await creator.getByRole("button", { name: /Лайк/ }).click();
  await second.getByRole("button", { name: /Дизлайк/ }).click();

  await expect(creator.getByRole("heading", { name: "Победитель" })).toBeVisible();
  await expect(creator.getByText("Алиса", { exact: true }).first()).toBeVisible();
  await expect(creator.getByText("1/1", { exact: true })).toBeVisible();

  await creatorContext.close();
  await secondContext.close();
});
