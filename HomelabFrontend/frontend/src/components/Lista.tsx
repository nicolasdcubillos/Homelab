/**
 * Lista agrupada con recuadro.
 *
 * Un encabezado discreto, un
 * bloque redondeado con filas separadas por líneas que no llegan al borde, y
 * una nota al pie que explica la consecuencia de lo que hay arriba. Encaja con
 * casi todo lo que este panel tiene que mostrar: pares clave/valor, ajustes e
 * interruptores.
 */

import { Link } from "react-router-dom";

import { cx } from "@/lib/cx";

type ListaProps = {
  titulo?: string;
  nota?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Acción a la derecha del encabezado, del tipo "Añadir" o "Editar". */
  accion?: React.ReactNode;
};

export function Lista({ titulo, nota, children, className, accion }: ListaProps) {
  return (
    <section className={cx("flex flex-col", className)}>
      {(titulo || accion) && (
        <div className="flex min-h-9 items-center justify-between gap-3 px-1 pb-2">
          {titulo && (
            <h2 className="text-subhead font-semibold text-fg">
              {titulo}
            </h2>
          )}
          {accion}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-e1">
        {children}
      </div>

      {nota && <p className="px-4 pt-2 text-footnote text-muted sm:px-1">{nota}</p>}
    </section>
  );
}

/* -------------------------------------------------------------------------- */

type FilaProps = {
  children: React.ReactNode;
  className?: string;
};

/** Contenedor de una fila: pone la línea separadora salvo en la última. */
export function Fila({ children, className }: FilaProps) {
  return (
    <div
      className={cx(
        "relative px-4 py-3",
        "after:absolute after:inset-x-0 after:bottom-0 after:ml-4 after:h-px after:bg-line",
        "last:after:hidden",
        className,
      )}
    >
      {children}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

type FilaValorProps = {
  etiqueta: React.ReactNode;
  valor?: React.ReactNode;
  descripcion?: React.ReactNode;
  /** Convierte la fila en un control navegable con su galón a la derecha. */
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  icono?: React.ReactNode;
  tono?: "normal" | "peligro" | "accion";
};

const TONOS_FILA = {
  normal: "text-fg",
  peligro: "text-danger",
  accion: "text-accent",
};

export function FilaValor({
  etiqueta,
  valor,
  descripcion,
  onClick,
  href,
  disabled,
  icono,
  tono = "normal",
}: FilaValorProps) {
  const navegable = Boolean(onClick || href);

  const contenido = (
    <>
      {icono && <span className="shrink-0 text-muted">{icono}</span>}

      <span className="flex min-w-0 flex-1 flex-col text-left">
        <span className={cx("break-words text-body font-medium", TONOS_FILA[tono])}>{etiqueta}</span>
        {descripcion && (
          <span className="mt-0.5 text-footnote text-muted">{descripcion}</span>
        )}
      </span>

      {valor !== undefined && valor !== null && (
        <span className="max-w-[45%] min-w-0 break-words text-right text-subhead text-muted">{valor}</span>
      )}

      {navegable && (
        <svg
          className="size-4 shrink-0 text-faint"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 3.5 4.5 4.5L6 12.5" />
        </svg>
      )}
    </>
  );

  const clases = cx(
    "relative flex w-full min-h-11 items-center gap-3 px-4 py-2.5 text-left",
    "after:absolute after:inset-x-0 after:bottom-0 after:ml-4 after:h-px after:bg-line",
    "last:after:hidden",
    navegable && !disabled && "hover:bg-sunken active:bg-neutral-soft transition-colors duration-100",
    disabled && "opacity-50",
  );

  if (href && !disabled) {
    return (
      <Link to={href} className={clases}>
        {contenido}
      </Link>
    );
  }

  if (onClick) {
    return (
      <button type="button" onClick={onClick} disabled={disabled} className={clases}>
        {contenido}
      </button>
    );
  }

  return <div className={clases}>{contenido}</div>;
}
