/**
 * Cliente HTTP de la API.
 *
 * La sesión viaja en una cookie httpOnly, así que el frontend nunca ve el
 * token: solo tiene que acompañar cada método mutante con el token CSRF de
 * doble envío que el backend deja en una cookie legible.
 */

import type { paths } from "./api-schema";

export const BASE = "/api/v1";

const COOKIE_CSRF = "hld_csrf";
const CABECERA_CSRF = "X-CSRF-Token";

/** Error de la API ya normalizado a la forma `{error: {code, message}}`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string>;

  constructor(status: number, code: string, message: string, fields?: Record<string, string>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields ?? {};
  }

  /** La sesión no sirve: hay que volver al login. */
  get esNoAutenticado(): boolean {
    return this.status === 401;
  }

  /** El backend exige cambiar la contraseña antes de dejar hacer nada más. */
  get exigeCambioDePassword(): boolean {
    return this.code === "password_change_required";
  }
}

/** Fallo de red o servidor caído: ni siquiera hubo respuesta HTTP. */
export class ErrorDeRed extends Error {
  constructor() {
    super("No pudimos contactar el servidor. Revisa tu conexión e inténtalo de nuevo.");
    this.name = "ErrorDeRed";
  }
}

function leerCookie(nombre: string): string | null {
  const escapado = nombre.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|;\\s*)${escapado}=([^;]*)`).exec(document.cookie);
  return match ? decodeURIComponent(match[1]!) : null;
}

/**
 * Pide un token CSRF al backend si todavía no hay cookie.
 *
 * Pasa en la primera visita y tras un logout. Es una sola petición y se
 * memoriza en vuelo para que diez mutaciones simultáneas no disparen diez.
 */
let csrfEnVuelo: Promise<string | null> | null = null;

async function asegurarCsrf(): Promise<string | null> {
  const actual = leerCookie(COOKIE_CSRF);
  if (actual) return actual;

  csrfEnVuelo ??= fetch(`${BASE}/auth/csrf`, { credentials: "same-origin" })
    .then(() => leerCookie(COOKIE_CSRF))
    .catch(() => null)
    .finally(() => {
      csrfEnVuelo = null;
    });

  return csrfEnVuelo;
}

const MUTANTES = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type OpcionesPeticion = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
};

function construirUrl(ruta: string, query?: OpcionesPeticion["query"]): string {
  const url = ruta.startsWith("/api") ? ruta : `${BASE}${ruta}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [clave, valor] of Object.entries(query)) {
    if (valor === undefined || valor === null || valor === "") continue;
    params.set(clave, String(valor));
  }
  const cadena = params.toString();
  return cadena ? `${url}?${cadena}` : url;
}

async function normalizarError(respuesta: Response): Promise<ApiError> {
  let cuerpo: unknown = null;
  try {
    cuerpo = await respuesta.json();
  } catch {
    /* Una respuesta sin JSON (un 502 de Caddy, por ejemplo) cae al genérico. */
  }

  const error =
    cuerpo && typeof cuerpo === "object" && "error" in cuerpo
      ? (cuerpo as { error: { code?: string; message?: string; fields?: Record<string, string> } })
          .error
      : null;

  if (error?.message) {
    return new ApiError(respuesta.status, error.code ?? "error", error.message, error.fields);
  }

  const genericos: Record<number, string> = {
    401: "Tu sesión expiró. Vuelve a iniciar sesión.",
    403: "No tienes permiso para hacer eso.",
    404: "No encontramos lo que buscabas.",
    429: "Demasiados intentos. Espera un momento.",
    500: "El servidor tuvo un problema. Inténtalo de nuevo en unos segundos.",
    502: "El servidor no está respondiendo.",
    503: "El servicio no está disponible ahora mismo.",
  };

  return new ApiError(
    respuesta.status,
    "error",
    genericos[respuesta.status] ?? `Error inesperado (${respuesta.status}).`,
  );
}

/** Ejecuta una petición contra la API y devuelve el JSON ya tipado. */
export async function peticion<T>(ruta: string, opciones: OpcionesPeticion = {}): Promise<T> {
  const method = (opciones.method ?? "GET").toUpperCase();
  const cabeceras: Record<string, string> = { Accept: "application/json" };

  if (opciones.body !== undefined) {
    cabeceras["Content-Type"] = "application/json";
  }

  if (MUTANTES.has(method)) {
    const token = await asegurarCsrf();
    if (token) cabeceras[CABECERA_CSRF] = token;
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(construirUrl(ruta, opciones.query), {
      method,
      credentials: "same-origin",
      headers: cabeceras,
      body: opciones.body === undefined ? undefined : JSON.stringify(opciones.body),
      signal: opciones.signal ?? null,
    });
  } catch (causa) {
    if (causa instanceof DOMException && causa.name === "AbortError") throw causa;
    throw new ErrorDeRed();
  }

  if (!respuesta.ok) throw await normalizarError(respuesta);
  if (respuesta.status === 204) return undefined as T;

  const tipo = respuesta.headers.get("content-type") ?? "";
  if (!tipo.includes("json")) return undefined as T;

  return (await respuesta.json()) as T;
}

export const api = {
  get: <T>(ruta: string, opciones: Omit<OpcionesPeticion, "method" | "body"> = {}) =>
    peticion<T>(ruta, { ...opciones, method: "GET" }),
  post: <T>(ruta: string, body?: unknown, opciones: OpcionesPeticion = {}) =>
    peticion<T>(ruta, { ...opciones, method: "POST", body }),
  put: <T>(ruta: string, body?: unknown, opciones: OpcionesPeticion = {}) =>
    peticion<T>(ruta, { ...opciones, method: "PUT", body }),
  patch: <T>(ruta: string, body?: unknown, opciones: OpcionesPeticion = {}) =>
    peticion<T>(ruta, { ...opciones, method: "PATCH", body }),
  delete: <T>(ruta: string, opciones: OpcionesPeticion = {}) =>
    peticion<T>(ruta, { ...opciones, method: "DELETE" }),
};

/* -------------------------------------------------------------------------- */
/* Atajos de tipo sobre el esquema generado.                                   */
/* -------------------------------------------------------------------------- */

type Json200<T> = T extends { responses: { 200: { content: { "application/json": infer R } } } }
  ? R
  : never;

/** Cuerpo de respuesta 200 de una ruta y método concretos. */
export type Respuesta<
  R extends keyof paths,
  M extends keyof paths[R],
> = Json200<paths[R][M]>;

type JsonBody<T> = T extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : T extends { requestBody?: { content: { "application/json": infer B } } }
    ? B
    : never;

/** Cuerpo de petición de una ruta y método concretos. */
export type Cuerpo<R extends keyof paths, M extends keyof paths[R]> = JsonBody<paths[R][M]>;
