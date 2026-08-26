import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("показывает русскую форму входа", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /доброкек/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Войти/ })).toBeInTheDocument();
});
