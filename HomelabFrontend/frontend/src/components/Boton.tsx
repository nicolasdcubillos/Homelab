/**
 * Botón.
 *
 * Los siete estados que exige un control real —normal, hover, foco, activo,
 * deshabilitado, cargando y destructivo— están resueltos aquí y no en cada
 * pantalla. La altura mínima es de 44 px porque este panel se usa con el dedo.
 */

import { forwardRef } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { cx } from "@/lib/cx";

export type TonoBoton = "primario" | "secundario" | "sutil" | "peligro";
export type TamanoBoton = "md" | "sm" | "lg";

const TONOS: Record<TonoBoton, string> = {
  primario:
    "bg-accent text-on-accent shadow-e1 hover:bg-accent-hover active:bg-accent-active " +
    "disabled:bg-accent/45 disabled:shadow-none",
  secundario:
    "bg-surface text-fg border border-line shadow-e1 hover:bg-sunken active:bg-neutral-soft " +
    "disabled:text-faint disabled:shadow-none",
  sutil:
    "bg-transparent text-accent hover:bg-accent-soft active:bg-accent-soft/70 " +
    "disabled:text-faint",
  peligro:
    "bg-danger text-on-accent shadow-e1 hover:bg-danger-hover active:bg-danger-hover " +
    "disabled:bg-danger/45 disabled:shadow-none",
};

const TAMANOS: Record<TamanoBoton, string> = {
  sm: "min-h-9 px-3 text-subhead gap-1.5 rounded-md",
  md: "min-h-11 px-4 text-body gap-2 rounded-lg",
  lg: "min-h-12 px-5 text-body gap-2 rounded-lg",
};

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  tono?: TonoBoton;
  tamano?: TamanoBoton;
  cargando?: boolean;
  ancho?: boolean;
  icono?: React.ReactNode;
};

export const Boton = forwardRef<HTMLButtonElement, Props>(function Boton(  {
    tono = "secundario",
    tamano = "md",
    cargando = false,
    ancho = false,
    icono,
    className,
    children,
    disabled,
    type = "button",
    ...resto
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      // Mientras carga sigue enfocable y anunciado: si se deshabilitara, el
      // lector de pantalla perdería el foco justo al pulsar.
      disabled={disabled || cargando}
      aria-busy={cargando || undefined}
      className={cx(
        "relative inline-flex select-none items-center justify-center font-medium",
        "transition-[background-color,color,box-shadow,transform] duration-150 ease-[var(--ease-standard)]",
        "active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100",
        TAMANOS[tamano],
        TONOS[tono],
        ancho && "w-full",
        className,
      )}
      {...resto}
    >
      {cargando && (
        <span
          aria-hidden="true"
          className="absolute inline-block size-4 animate-[hl-spin_0.7s_linear_infinite] rounded-full border-2 border-current border-r-transparent opacity-90"
        />
      )}
      <span
        className={cx(
          "inline-flex items-center gap-2",
          cargando && "invisible",
        )}
      >
        {icono}
        {children}
      </span>
    </button>
  );
});

/**
 * Enlace con aspecto de botón.
 *
 * Existe para no anidar un `<Link>` dentro de un `<button>`: navegar es un
 * enlace y debe comportarse como tal (abrir en otra pestaña, copiar la
 * dirección), aunque se pinte como acción principal.
 */
export function BotonEnlace({
  tono = "secundario",
  tamano = "md",
  ancho = false,
  icono,
  className,
  children,
  ...resto
}: Omit<Props, "cargando" | "type" | "disabled"> & LinkProps) {
  return (
    <Link
      className={cx(
        "inline-flex select-none items-center justify-center font-medium",
        "transition-[background-color,color,box-shadow,transform] duration-150 ease-[var(--ease-standard)]",
        "active:scale-[0.98]",
        TAMANOS[tamano],
        TONOS[tono],
        ancho && "w-full",
        className,
      )}
      {...resto}
    >
      {icono}
      {children}
    </Link>
  );
}
