/**
 * Utilidades para conectar los errores de la API con react-hook-form.
 *
 * El backend devuelve `{error: {code, message, fields}}`; `fields` trae el
 * error por campo con el mismo nombre que usa el formulario. Esto lo traslada
 * al sitio correcto para que el usuario vea el problema junto al input, y
 * reserva el mensaje general para lo que no pertenece a ningún campo.
 */

import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "./api";

export function aplicarErroresDeApi<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  camposConocidos?: ReadonlyArray<Path<T>>,
): string | null {
  if (!(error instanceof ApiError)) {
    return error instanceof Error
      ? error.message
      : "Algo salió mal. Inténtalo de nuevo.";
  }

  const entradas = Object.entries(error.fields);
  if (entradas.length === 0) return error.message;

  let sobrante: string | null = null;

  for (const [campo, mensaje] of entradas) {
    const conocido = !camposConocidos || camposConocidos.includes(campo as Path<T>);
    if (conocido) {
      setError(campo as Path<T>, { type: "server", message: mensaje });
    } else {
      // Un error sobre un campo que este formulario no pinta se perdería en
      // silencio; mejor mostrarlo arriba que no mostrarlo.
      sobrante = mensaje;
    }
  }

  return sobrante;
}

/** Mensaje legible para cualquier error, con respaldo en español. */
export function mensajeDeError(error: unknown, respaldo = "Algo salió mal."): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return respaldo;
}
