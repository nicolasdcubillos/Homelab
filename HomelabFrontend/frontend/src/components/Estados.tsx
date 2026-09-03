/**
 * Estados de una superficie: cargando, vacío y con error.
 *
 * Están juntos a propósito: son las tres formas en que una pantalla existe
 * antes de tener datos, y resolverlas en un solo sitio evita que una se quede
 * sin diseñar.
 */

import { cx } from "@/lib/cx";

import { Boton } from "./Boton";

/* ------------------------------------------------------------- esqueleto -- */

/**
 * Silueta de lo que va a llegar. Un esqueleto le dice al usuario qué forma
 * tendrá el contenido; un girador solo dice "espera".
 */
export function Esqueleto({ className }: { className?: string }) {
  return (
    <div
      className={cx(
        "animate-pulse rounded-md bg-neutral-soft",
        className,
      )}
      aria-hidden="true"
    />
  );
}

export function EsqueletoLista({ filas = 3 }: { filas?: number }) {
  return (
    <div
      className="overflow-hidden rounded-lg border border-line bg-surface"
      role="status"
      aria-label="Cargando"
    >
      {Array.from({ length: filas }, (_, indice) => (
        <div
          key={indice}
          className="relative flex items-center gap-3 px-4 py-3.5 after:absolute after:inset-x-0 after:bottom-0 after:ml-4 after:h-px after:bg-line last:after:hidden"
        >
          <div className="flex-1 space-y-2">
            <Esqueleto className="h-4 w-1/3" />
            <Esqueleto className="h-3 w-2/3" />
          </div>
          <Esqueleto className="size-5 rounded-full" />
        </div>
      ))}
      <span className="sr-only">Cargando…</span>
    </div>
  );
}

/* ----------------------------------------------------------------- vacío -- */

type VacioProps = {
  titulo: string;
  descripcion: string;
  accion?: React.ReactNode;
  icono?: React.ReactNode;
  className?: string;
};

/**
 * Un estado vacío bien hecho enseña para qué sirve la pantalla: explica lo que
 * aparecerá aquí y ofrece el siguiente paso concreto.
 */
export function Vacio({ titulo, descripcion, accion, icono, className }: VacioProps) {
  return (
    <div
      className={cx(
        "flex flex-col items-center rounded-lg border border-dashed border-line-strong/60",
        "bg-surface/50 px-6 py-10 text-center",
        className,
      )}
    >
      {icono && <div className="mb-3 text-faint">{icono}</div>}
      <h3 className="text-body font-semibold text-fg">{titulo}</h3>
      <p className="mt-1.5 max-w-[38ch] text-subhead text-muted">{descripcion}</p>
      {accion && <div className="mt-5">{accion}</div>}
    </div>
  );
}

/* ----------------------------------------------------------------- error -- */

type ErrorProps = {
  titulo?: string;
  mensaje: string;
  onReintentar?: () => void;
  reintentando?: boolean;
  className?: string;
};

export function EstadoError({
  titulo = "No pudimos cargar esto",
  mensaje,
  onReintentar,
  reintentando,
  className,
}: ErrorProps) {
  return (
    <div
      role="alert"
      className={cx(
        "flex flex-col items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4",
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="mt-0.5 size-5 shrink-0 text-danger"
          aria-hidden="true"
        >
          <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 3.75a.9.9 0 0 1 .9.9v4.6a.9.9 0 1 1-1.8 0v-4.6a.9.9 0 0 1 .9-.9ZM10 15a1.15 1.15 0 1 1 0-2.3A1.15 1.15 0 0 1 10 15Z" />
        </svg>
        <div className="min-w-0">
          <p className="text-body font-semibold text-fg">{titulo}</p>
          <p className="mt-0.5 text-subhead text-muted">{mensaje}</p>
        </div>
      </div>

      {onReintentar && (
        <Boton tono="secundario" tamano="sm" onClick={onReintentar} cargando={reintentando}>
          Reintentar
        </Boton>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- aviso -- */

type AvisoProps = {
  tono?: "info" | "aviso" | "alerta" | "ok";
  titulo?: string;
  children: React.ReactNode;
  accion?: React.ReactNode;
  className?: string;
};

const TONOS_AVISO = {
  info: "border-accent/25 bg-accent-soft",
  aviso: "border-warn/30 bg-warn-soft",
  alerta: "border-danger/30 bg-danger-soft",
  ok: "border-ok/30 bg-ok-soft",
};

const ICONOS_AVISO = {
  info: "text-accent-quiet",
  aviso: "text-warn",
  alerta: "text-danger",
  ok: "text-ok",
};

export function Aviso({ tono = "info", titulo, children, accion, className }: AvisoProps) {
  return (
    <div
      className={cx("rounded-lg border p-3.5", TONOS_AVISO[tono], className)}
      role={tono === "alerta" ? "alert" : undefined}
    >
      <div className="flex items-start gap-2.5">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className={cx("mt-0.5 size-4.5 shrink-0", ICONOS_AVISO[tono])}
          aria-hidden="true"
        >
          {tono === "ok" ? (
            <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm3.7 6.1-4.4 4.4a.9.9 0 0 1-1.27 0L6.3 10.77a.9.9 0 1 1 1.27-1.27l1.1 1.09 3.76-3.76a.9.9 0 0 1 1.27 1.27Z" />
          ) : (
            <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 3.6a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2Zm.9 8.6a.9.9 0 1 1-1.8 0V9.6a.9.9 0 1 1 1.8 0v4.6Z" />
          )}
        </svg>

        <div className="min-w-0 flex-1">
          {titulo && <p className="text-subhead font-semibold text-fg">{titulo}</p>}
          <div className={cx("text-subhead text-fg/85", titulo && "mt-0.5")}>{children}</div>
          {accion && <div className="mt-2.5">{accion}</div>}
        </div>
      </div>
    </div>
  );
}
