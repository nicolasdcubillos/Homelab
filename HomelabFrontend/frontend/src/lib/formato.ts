/**
 * Formato de fechas, duraciones y textos en español.
 *
 * El backend habla siempre en ISO 8601 con zona; aquí se traduce a lo que una
 * persona quiere leer en su teléfono. Los relativos ("hace 4 min") pesan más
 * que la marca exacta cuando lo que importa es "¿corrió hace poco?".
 */

const RTF = new Intl.RelativeTimeFormat("es", { numeric: "auto" });

const FECHA_CORTA = new Intl.DateTimeFormat("es", { day: "numeric", month: "short" });
const FECHA_LARGA = new Intl.DateTimeFormat("es", {
  day: "numeric",
  month: "long",
  year: "numeric",
});
const HORA = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit" });
const FECHA_HORA = new Intl.DateTimeFormat("es", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function aFecha(valor: string | Date | null | undefined): Date | null {
  if (!valor) return null;
  const fecha = valor instanceof Date ? valor : new Date(valor);
  return Number.isNaN(fecha.getTime()) ? null : fecha;
}

/** "hace 4 min", "en 2 h", "ahora mismo". */
export function relativo(valor: string | Date | null | undefined, ahora = new Date()): string {
  const fecha = aFecha(valor);
  if (!fecha) return "—";

  const segundos = Math.round((fecha.getTime() - ahora.getTime()) / 1000);
  const abs = Math.abs(segundos);

  if (abs < 45) return "ahora mismo";
  if (abs < 3600) return RTF.format(Math.round(segundos / 60), "minute");
  if (abs < 86400) return RTF.format(Math.round(segundos / 3600), "hour");
  if (abs < 2592000) return RTF.format(Math.round(segundos / 86400), "day");
  if (abs < 31536000) return RTF.format(Math.round(segundos / 2592000), "month");
  return RTF.format(Math.round(segundos / 31536000), "year");
}

/** Marca legible: hoy muestra la hora, otro día muestra día y hora. */
export function fechaHora(valor: string | Date | null | undefined): string {
  const fecha = aFecha(valor);
  if (!fecha) return "—";

  const hoy = new Date();
  const mismoDia =
    fecha.getFullYear() === hoy.getFullYear() &&
    fecha.getMonth() === hoy.getMonth() &&
    fecha.getDate() === hoy.getDate();

  return mismoDia ? HORA.format(fecha) : FECHA_HORA.format(fecha);
}

export function soloHora(valor: string | Date | null | undefined): string {
  const fecha = aFecha(valor);
  return fecha ? HORA.format(fecha) : "—";
}

export function fechaCorta(valor: string | Date | null | undefined): string {
  const fecha = aFecha(valor);
  return fecha ? FECHA_CORTA.format(fecha) : "—";
}

export function fechaLarga(valor: string | Date | null | undefined): string {
  const fecha = aFecha(valor);
  return fecha ? FECHA_LARGA.format(fecha) : "—";
}

/** Marca completa para el atributo `title` o `datetime`. */
export function iso(valor: string | Date | null | undefined): string | undefined {
  return aFecha(valor)?.toISOString();
}

/** "3,4 s", "1 min 12 s", "2 h 5 min". */
export function duracion(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "—";
  if (segundos < 1) return "menos de 1 s";
  if (segundos < 60) return `${segundos.toFixed(segundos < 10 ? 1 : 0).replace(".", ",")} s`;

  const minutos = Math.floor(segundos / 60);
  const resto = Math.round(segundos % 60);
  if (minutos < 60) return resto ? `${minutos} min ${resto} s` : `${minutos} min`;

  const horas = Math.floor(minutos / 60);
  const minutosResto = minutos % 60;
  return minutosResto ? `${horas} h ${minutosResto} min` : `${horas} h`;
}

/** "cada 30 minutos", "cada 2 horas", "cada día". */
export function cadaCuanto(minutos: number | null | undefined): string {
  if (!minutos) return "—";
  if (minutos < 60) return `cada ${minutos} minutos`;
  if (minutos === 60) return "cada hora";
  if (minutos % 1440 === 0) {
    const dias = minutos / 1440;
    return dias === 1 ? "cada día" : `cada ${dias} días`;
  }
  if (minutos % 60 === 0) return `cada ${minutos / 60} horas`;
  return `cada ${Math.floor(minutos / 60)} h ${minutos % 60} min`;
}

const MONEDA = new Map<string, Intl.NumberFormat>();

export function dinero(valor: number | string | null | undefined, moneda = "USD"): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  const numero = typeof valor === "string" ? Number.parseFloat(valor) : valor;
  if (Number.isNaN(numero)) return "—";

  let formato = MONEDA.get(moneda);
  if (!formato) {
    try {
      formato = new Intl.NumberFormat("es", {
        style: "currency",
        currency: moneda,
        maximumFractionDigits: 2,
      });
    } catch {
      // Una moneda que Intl no reconoce no debe romper la pantalla.
      formato = new Intl.NumberFormat("es", { maximumFractionDigits: 2 });
    }
    MONEDA.set(moneda, formato);
  }
  return formato.format(numero);
}

const NUMERO = new Intl.NumberFormat("es", { maximumFractionDigits: 4 });

export function numero(valor: number | string | null | undefined): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  const n = typeof valor === "string" ? Number.parseFloat(valor) : valor;
  return Number.isNaN(n) ? "—" : NUMERO.format(n);
}

/** "3 vigilancias" / "1 vigilancia". */
export function plural(cantidad: number, singular: string, plural_: string): string {
  return `${cantidad} ${cantidad === 1 ? singular : plural_}`;
}

/** Une una lista con comas y una "y" final, como se escribe en español. */
export function enumerar(partes: readonly string[]): string {
  const limpias = partes.filter(Boolean);
  if (limpias.length === 0) return "";
  if (limpias.length === 1) return limpias[0]!;
  return `${limpias.slice(0, -1).join(", ")} y ${limpias.at(-1)}`;
}
