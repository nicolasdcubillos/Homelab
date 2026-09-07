import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { Boton, BotonEnlace } from "@/components/Boton";
import { Campo } from "@/components/Campos";
import { FilaValor, Lista } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";

afterEach(cleanup);

it("mantiene un único título y la acción en la misma cabecera", async () => {
  const guardar = vi.fn();
  render(<Pantalla titulo="Mi portafolio" descripcion="Posiciones y perfil de riesgo."
    acciones={<Boton onClick={guardar}>Guardar</Boton>}>
    <p>Contenido de la pantalla</p>
  </Pantalla>);
  const cabecera = screen.getByRole("banner");
  expect(within(cabecera).getByRole("heading", { level: 1 })).toHaveTextContent("Mi portafolio");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(document.title).toBe("Mi portafolio · Homelab");
  expect(within(cabecera).queryByText("Posiciones y perfil de riesgo.")).not.toBeInTheDocument();
  await userEvent.tab();
  expect(screen.getByRole("button", { name: "Guardar" })).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(guardar).toHaveBeenCalledOnce();
});

it("actualiza el título y admite pantallas sin acciones ni descripción", () => {
  const vista = render(<Pantalla titulo="Inicio"><p>Resumen</p></Pantalla>);
  vista.rerender(<Pantalla titulo="Actividad"><p>Historial</p></Pantalla>);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Actividad");
  expect(document.title).toBe("Actividad · Homelab");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("conserva los estados de carga y la semántica de los controles compactos", async () => {
  const ejecutar = vi.fn();
  render(<MemoryRouter>
    <Boton tamano="sm" cargando onClick={ejecutar}>Ejecutar</Boton>
    <BotonEnlace tamano="sm" to="/actividad">Ver actividad</BotonEnlace>
  </MemoryRouter>);
  const boton = screen.getByRole("button");
  expect(boton).toBeDisabled();
  expect(boton).toHaveAttribute("aria-busy", "true");
  await userEvent.click(boton);
  expect(ejecutar).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Ver actividad" })).toHaveAttribute("href", "/actividad");
});

it("conserva etiquetas, errores y navegación en formularios y listas", async () => {
  const editar = vi.fn();
  render(<MemoryRouter>
    <Campo etiqueta="Correo" error="Introduce un correo válido." requerido />
    <Lista titulo="Tu configuración">
      <FilaValor etiqueta="Notificaciones" valor="Sin configurar" href="/ajustes" />
      <FilaValor etiqueta="Perfil" onClick={editar} />
    </Lista>
  </MemoryRouter>);
  const campo = screen.getByRole("textbox", { name: "Correo" });
  expect(campo).toHaveAttribute("aria-required", "true");
  expect(campo).toHaveAttribute("aria-invalid", "true");
  expect(campo).toHaveAccessibleDescription("Introduce un correo válido.");
  expect(screen.getByRole("heading", { name: "Tu configuración" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Notificaciones\s*Sin configurar/ })).toHaveAttribute("href", "/ajustes");
  await userEvent.click(screen.getByRole("button", { name: "Perfil" }));
  expect(editar).toHaveBeenCalledOnce();
});
