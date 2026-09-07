import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it } from "vitest";

import { BarraLateral, BarraPestanas } from "@/components/Navegacion";

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true, value() { this.setAttribute("open", ""); },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true, value() { this.removeAttribute("open"); },
  });
});
afterEach(cleanup);

it("mantiene cinco destinos visibles y lleva el exceso autorizado a Más", async () => {
  render(<MemoryRouter initialEntries={["/regimen"]}><BarraPestanas admin trading regimen /></MemoryRouter>);
  const barra = screen.getByRole("navigation", { name: "Secciones" });
  expect(within(barra).getAllByRole("link")).toHaveLength(4);
  expect(within(barra).getByRole("link", { name: "Vigilancias" })).toHaveAttribute("href", "/vigilancias");
  expect(within(barra).getByRole("link", { name: "Trading" })).toHaveAttribute("href", "/trading");
  const mas = within(barra).getByRole("button", { name: "Más" });
  expect(mas).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(mas);
  const hoja = screen.getByRole("dialog", { name: "Más secciones" });
  expect(within(hoja).getByRole("link", { name: "Régimen de mercado" })).toHaveAttribute("aria-current", "page");
  expect(within(hoja).getByRole("link", { name: "Administración" })).toHaveAttribute("href", "/admin");
  expect(within(hoja).getByRole("link", { name: "Ajustes" })).toHaveAttribute("href", "/ajustes");
  await userEvent.click(within(hoja).getByRole("link", { name: "Actividad" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mas).toHaveAttribute("aria-expanded", "false");
});

it("conserva las cinco secciones originales sin conceder módulos nuevos", () => {
  render(<MemoryRouter><BarraPestanas admin={false} trading={false} regimen={false} /></MemoryRouter>);
  expect(screen.getAllByRole("link")).toHaveLength(5);
  expect(screen.queryByRole("button", { name: "Más" })).not.toBeInTheDocument();
  expect(screen.queryByText("Trading")).not.toBeInTheDocument();
  expect(screen.queryByText("Régimen de mercado")).not.toBeInTheDocument();
});

it("el acceso a régimen no requiere trading ni concede administración", async () => {
  render(<MemoryRouter><BarraPestanas admin={false} trading={false} regimen /></MemoryRouter>);
  expect(screen.queryByRole("link", { name: "Trading" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Régimen de mercado" })).toHaveAttribute("href", "/regimen");
  await userEvent.click(screen.getByRole("button", { name: "Más" }));
  expect(screen.queryByText("Administración")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Actividad" })).toBeInTheDocument();
});

it("la barra lateral preserva todos los módulos autorizados", () => {
  render(<MemoryRouter><BarraLateral admin trading regimen email="fixture@example.test" pie={null} /></MemoryRouter>);
  expect(screen.getAllByRole("link")).toHaveLength(8);
  expect(screen.getByRole("link", { name: "Trading" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Régimen de mercado" })).toBeInTheDocument();
});

it("agrupa los destinos por tarea y marca las rutas de segundo nivel", () => {
  render(<MemoryRouter initialEntries={["/admin/usuarios/demo"]}>
    <BarraLateral admin trading regimen email="fixture@example.test" pie={null} />
  </MemoryRouter>);
  const panel = screen.getByRole("list", { name: "Panel" });
  const finanzas = screen.getByRole("list", { name: "Finanzas" });
  const cuenta = screen.getByRole("list", { name: "Cuenta" });
  expect(within(panel).getAllByRole("link").map((link) => link.textContent))
    .toEqual(["Inicio", "Vigilancias", "Actividad"]);
  expect(within(finanzas).getAllByRole("link").map((link) => link.textContent))
    .toEqual(["Portafolio", "Trading", "Régimen de mercado"]);
  expect(within(cuenta).getByRole("link", { name: "Administración" }))
    .toHaveAttribute("aria-current", "page");
  expect(within(cuenta).getByRole("link", { name: "Ajustes" })).not.toHaveAttribute("aria-current");
});

it("no muestra destinos restringidos en los grupos de escritorio", () => {
  render(<MemoryRouter><BarraLateral admin={false} trading={false} regimen={false}
    email="fixture@example.test" pie={null} /></MemoryRouter>);
  expect(within(screen.getByRole("list", { name: "Finanzas" })).getAllByRole("link")).toHaveLength(1);
  expect(within(screen.getByRole("list", { name: "Cuenta" })).getAllByRole("link")).toHaveLength(1);
  expect(screen.queryByRole("link", { name: "Trading" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Régimen de mercado" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Administración" })).not.toBeInTheDocument();
});

it("no marca como activa una ruta que solo comparte un prefijo", () => {
  render(<MemoryRouter initialEntries={["/admin-inexistente"]}>
    <BarraLateral admin trading regimen email="fixture@example.test" pie={null} />
  </MemoryRouter>);
  expect(screen.getByRole("link", { name: "Administración" })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("link", { name: "Administración" })).not.toHaveClass("bg-accent-soft");
});
