/**
 * Esquemas de validación del cliente.
 *
 * Reproducen exactamente las reglas del backend para dar respuesta inmediata
 * mientras se escribe. El backend sigue siendo la autoridad: esto es
 * comodidad, no seguridad, y por eso los mensajes son idénticos a los suyos.
 */

import { z } from "zod";

export const LARGO_MINIMO_PASSWORD = 10;
export const LARGO_MAXIMO_PASSWORD = 1024;

export const correo = z
  .string()
  .trim()
  .min(1, "Escribe tu correo.")
  .email("Ese correo no parece válido.");

export const password = z
  .string()
  .min(LARGO_MINIMO_PASSWORD, `La contraseña debe tener al menos ${LARGO_MINIMO_PASSWORD} caracteres.`)
  .max(LARGO_MAXIMO_PASSWORD, `La contraseña no puede superar los ${LARGO_MAXIMO_PASSWORD} caracteres.`)
  .refine((v) => v.trim() === v, "La contraseña no puede empezar ni terminar con espacios.")
  .refine((v) => /[A-Za-z]/.test(v), "La contraseña debe incluir al menos una letra.")
  .refine((v) => /[0-9]/.test(v), "La contraseña debe incluir al menos un número.");

export const esquemaLogin = z.object({
  email: correo,
  password: z.string().min(1, "Escribe tu contraseña."),
});
export type DatosLogin = z.infer<typeof esquemaLogin>;

export const esquemaRegistro = z.object({
  email: correo,
  password,
  timezone: z.string().min(1),
});
export type DatosRegistro = z.infer<typeof esquemaRegistro>;

export const esquemaCambioPassword = z
  .object({
    password_actual: z.string(),
    password_nueva: password,
    repetir: z.string().min(1, "Repite la contraseña nueva."),
  })
  .refine((datos) => datos.password_nueva === datos.repetir, {
    path: ["repetir"],
    message: "Las dos contraseñas no coinciden.",
  });
export type DatosCambioPassword = z.infer<typeof esquemaCambioPassword>;

/**
 * WhatsApp exige E.164: un `+`, el indicativo de país y hasta quince dígitos.
 * Sin el `+` el mensaje sencillamente no sale, así que se rechaza aquí.
 */
export const telefonoE164 = z
  .string()
  .trim()
  .regex(/^\+[1-9]\d{7,14}$/, "Usa el formato internacional, por ejemplo +573001234567.");

export const esquemaNotificaciones = z.object({
  whatsapp: z.union([telefonoE164, z.literal("")]).nullable().optional(),
  email: z.union([correo, z.literal("")]).nullable().optional(),
});
export type DatosNotificaciones = z.infer<typeof esquemaNotificaciones>;

/** Convierte "azul, negro" o varias líneas en una lista limpia y sin repetidos. */
export function aLista(texto: string): string[] {
  const partes = texto
    .split(/[\n,]/)
    .map((parte) => parte.trim())
    .filter(Boolean);
  return [...new Set(partes)];
}

export function deLista(valores: readonly string[] | null | undefined): string {
  return (valores ?? []).join(", ");
}

export const esquemaWatch = z.object({
  name: z.string().trim().min(1, "Ponle un nombre a la vigilancia.").max(120, "Máximo 120 caracteres."),
  enabled: z.boolean(),
  match_terms: z.string().trim().min(1, "Escribe al menos un término de búsqueda."),
  exclude_terms: z.string(),
  variants: z.string(),
  colors: z.string(),
  countries: z.string(),
  gender: z.enum(["mens", "womens", "unisex"]),
  max_price: z
    .string()
    .trim()
    .refine((v) => v === "" || (!Number.isNaN(Number(v.replace(",", "."))) && Number(v.replace(",", ".")) > 0), {
      message: "Escribe un precio mayor que cero, o déjalo vacío.",
    }),
  currency: z.string().trim().length(3, "Usa el código de tres letras, por ejemplo EUR."),
  notify_channels: z.array(z.enum(["whatsapp", "email"])),
});
export type DatosWatch = z.infer<typeof esquemaWatch>;

const numeroPositivo = (mensaje: string) =>
  z
    .string()
    .trim()
    .min(1, mensaje)
    .refine((v) => {
      const n = Number(v.replace(",", "."));
      return !Number.isNaN(n) && n > 0;
    }, mensaje);

export const esquemaHolding = z.object({
  ticker: z
    .string()
    .trim()
    .min(1, "Escribe el símbolo, por ejemplo AAPL.")
    .max(20, "Máximo 20 caracteres."),
  quantity: numeroPositivo("Escribe una cantidad mayor que cero."),
  avg_cost: numeroPositivo("Escribe el costo promedio por acción."),
  sector_hint: z.string().trim().max(80, "Máximo 80 caracteres."),
});
export type DatosHolding = z.infer<typeof esquemaHolding>;

export const esquemaPosicionCerrada = z.object({
  ticker: z.string().trim().min(1, "Escribe el símbolo.").max(20, "Máximo 20 caracteres."),
  note: z.string().trim().max(280, "Máximo 280 caracteres."),
});
export type DatosPosicionCerrada = z.infer<typeof esquemaPosicionCerrada>;

export const esquemaPerfilRiesgo = z.object({
  horizon: z.enum(["short_term", "medium_term", "long_term"]),
  tolerance: z.enum(["conservative", "moderate", "aggressive"]),
  notes: z.string().trim().max(1000, "Máximo 1000 caracteres."),
  analysis_interval_days: z
    .string()
    .trim()
    .refine((v) => {
      const n = Number(v);
      return Number.isInteger(n) && n >= 1 && n <= 365;
    }, "Escribe un número de días entre 1 y 365."),
});
export type DatosPerfilRiesgo = z.infer<typeof esquemaPerfilRiesgo>;

/**
 * Configuración de un bot de trading.
 *
 * Es una fábrica y no una constante porque los límites dependen del motor:
 * Freqtrade y TradingLab admiten distinta cantidad de instrumentos y distintos
 * marcos temporales, y la API los declara en `MotorInfoOut` justamente para que
 * la interfaz no tenga que saberlos de memoria.
 *
 * La *forma* de cada instrumento (`BTC/USDT` frente a `AAPL`) se deja al
 * backend a propósito: duplicar aquí esa expresión regular sería tener dos
 * definiciones de lo mismo que con el tiempo dejarían de coincidir. Lo que sí
 * se comprueba en el cliente es todo lo que se puede expresar sin copiarla.
 */
export function esquemaConfigTrading(limites: {
  maxInstrumentos: number;
  timeframes: string[];
  estrategias?: string[];
}) {
  // Con catálogo la lista manda; sin él solo se comprueba la forma, porque las
  // estrategias son archivos que viven en la VM y nadie puede enumerarlas.
  const catalogo = limites.estrategias ?? [];
  const validaEstrategia =
    catalogo.length > 0
      ? (v: string) => catalogo.includes(v)
      : (v: string) => /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(v);
  const errorEstrategia =
    catalogo.length > 0
      ? "Elige una de las estrategias disponibles."
      : "Solo letras, números y guion bajo, empezando por una letra.";

  const rango = (min: number, max: number, mensaje: string) =>
    z
      .string()
      .trim()
      .min(1, mensaje)
      .refine((v) => {
        const n = Number(v.replace(",", "."));
        return /^\d+(?:[.,]\d+)?$/.test(v) && Number.isFinite(n) && n >= min && n <= max;
      }, mensaje);

  return z
    .object({
      instrumentos: z
        .string()
        .trim()
        .refine(
          (v) => separarInstrumentos(v).length <= limites.maxInstrumentos,
          `Máximo ${limites.maxInstrumentos}: el bot corre en una VM compartida y cada uno cuesta memoria y llamadas.`,
        ),
      estrategia: z
        .string()
        .trim()
        .refine((v) => v === "" || validaEstrategia(v), errorEstrategia),
      timeframe: z.string().refine((v) => limites.timeframes.includes(v), "Elige un marco temporal."),
      capital_simulado: rango(100, 10_000_000, "El capital simulado debe estar entre 100 y 10.000.000."),
      max_posiciones_abiertas: z
        .string()
        .trim()
        .refine((v) => {
          const n = Number(v);
          return /^\d+$/.test(v) && Number.isInteger(n) && n >= 1 && n <= limites.maxInstrumentos;
        }, `Debe estar entre 1 y ${limites.maxInstrumentos}.`),
      stop_loss_pct: rango(0.1, 90, "El stop loss debe estar entre 0,1 y 90."),
      take_profit_pct: rango(0.1, 500, "El take profit debe estar entre 0,1 y 500."),
      max_perdida_diaria_pct: rango(0.1, 100, "La pérdida diaria máxima debe estar entre 0,1 y 100."),
    })
    .refine(
      (datos) =>
        Number(datos.stop_loss_pct.replace(",", ".")) <=
        Number(datos.max_perdida_diaria_pct.replace(",", ".")),
      {
        path: ["max_perdida_diaria_pct"],
        message:
          "La pérdida diaria máxima no puede ser menor que el stop loss: el freno nunca llegaría a activarse.",
      },
    );
}

export type DatosConfigTrading = z.infer<ReturnType<typeof esquemaConfigTrading>>;

/**
 * Convierte el campo de texto libre en la lista que espera la API.
 *
 * Se acepta separar por comas, espacios o saltos de línea porque quien pega
 * una lista desde otro lado no debería tener que reformatearla. El duplicado
 * se elimina aquí para que el contador que ve el usuario cuadre con lo que se
 * va a guardar.
 */
export function separarInstrumentos(texto: string): string[] {
  const partes = texto
    .split(/[\s,;]+/)
    .map((parte) => parte.trim().toUpperCase())
    .filter(Boolean);
  return [...new Set(partes)];
}
