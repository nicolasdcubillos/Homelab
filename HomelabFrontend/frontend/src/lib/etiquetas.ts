/**
 * Etiquetas en español para los valores cerrados que devuelve la API.
 *
 * Vive aparte para que ningún componente invente su propia traducción de
 * `success` o `mens` y la interfaz acabe diciendo dos cosas distintas para el
 * mismo estado.
 */

import type {
  Canal,
  EstadoEjecucion,
  EstadoUsuario,
  Genero,
  Horizonte,
  Rol,
  Tolerancia,
} from "./tipos";

export const ESTADO_EJECUCION: Record<EstadoEjecucion, string> = {
  running: "En curso",
  success: "Correcta",
  error: "Con error",
  skipped: "Omitida",
  cancelled: "Cancelada",
};

/** Tono visual de cada estado. Nunca es el único indicador: siempre va texto. */
export const TONO_EJECUCION: Record<EstadoEjecucion, "activo" | "ok" | "alerta" | "aviso" | "neutro"> =
  {
    running: "activo",
    success: "ok",
    error: "alerta",
    skipped: "aviso",
    cancelled: "neutro",
  };

export const DISPARADOR: Record<string, string> = {
  manual: "Manual",
  schedule: "Automática",
};

export const ESTADO_USUARIO: Record<EstadoUsuario, string> = {
  pending: "Pendiente",
  active: "Activa",
  suspended: "Suspendida",
};

export const DESCRIPCION_ESTADO_USUARIO: Record<EstadoUsuario, string> = {
  pending: "Puede configurar su cuenta, pero todavía no ejecutar nada.",
  active: "Puede configurar y ejecutar con normalidad.",
  suspended: "No puede entrar. Sus ejecuciones automáticas están detenidas.",
};

export const ROL: Record<Rol, string> = {
  user: "Usuario",
  admin: "Administrador",
};

export const CANAL: Record<Canal, string> = {
  whatsapp: "WhatsApp",
  email: "Correo",
};

export const GENERO: Record<Genero, string> = {
  mens: "Hombre",
  womens: "Mujer",
  unisex: "Unisex",
};

export const TOLERANCIA: Record<Tolerancia, string> = {
  conservative: "Conservador",
  moderate: "Moderado",
  aggressive: "Agresivo",
};

export const HORIZONTE: Record<Horizonte, string> = {
  short_term: "Corto plazo",
  medium_term: "Mediano plazo",
  long_term: "Largo plazo",
};

export const DESCRIPCION_TOLERANCIA: Record<Tolerancia, string> = {
  conservative: "Prioriza no perder capital por encima de crecer.",
  moderate: "Acepta caídas pasajeras a cambio de crecer con el tiempo.",
  aggressive: "Asume caídas fuertes buscando el máximo crecimiento.",
};

/** Nombre corto de cada app para títulos y pestañas. */
export const APP_TITULO: Record<string, string> = {
  stockwatcher: "Vigilancias",
  portfoliowatcher: "Portafolio",
};

export function etiqueta<T extends string>(
  mapa: Record<string, string>,
  clave: T | null | undefined,
  respaldo = "—",
): string {
  if (!clave) return respaldo;
  return mapa[clave] ?? clave;
}
