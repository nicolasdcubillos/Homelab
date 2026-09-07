/**
 * Controles de formulario.
 *
 * Cada campo lleva su etiqueta asociada, su descripción y su error enlazados
 * por `aria-describedby`, para que un lector de pantalla anuncie el problema
 * al llegar al input y no haya que buscarlo por la pantalla.
 */

import { forwardRef, useId } from "react";

import { cx } from "@/lib/cx";

/* -------------------------------------------------------------------------- */

type BaseProps = {
  etiqueta: string;
  descripcion?: string;
  error?: string;
  requerido?: boolean;
  /** Oculta la etiqueta visualmente sin quitarla del árbol de accesibilidad. */
  etiquetaOculta?: boolean;
  className?: string;
};

function Envoltura({
  id,
  etiqueta,
  descripcion,
  error,
  requerido,
  etiquetaOculta,
  className,
  children,
  idDescripcion,
  idError,
}: BaseProps & {
  id: string;
  idDescripcion: string;
  idError: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <label
        htmlFor={id}
        className={cx(
          "text-subhead font-medium text-fg",
          etiquetaOculta && "sr-only",
        )}
      >
        {etiqueta}
        {requerido && (
          <span className="ml-1 text-danger" aria-hidden="true">
            *
          </span>
        )}
      </label>

      {children}

      {descripcion && !error && (
        <p id={idDescripcion} className="text-footnote text-muted">
          {descripcion}
        </p>
      )}

      {error && (
        <p id={idError} className="flex items-start gap-1.5 text-footnote text-danger">
          <svg
            className="mt-0.5 size-3.5 shrink-0"
            viewBox="0 0 16 16"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3.25a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0V5A.75.75 0 0 1 8 4.25ZM8 12a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" />
          </svg>
          {error}
        </p>
      )}
    </div>
  );
}

const CONTROL_BASE =
  "w-full rounded-md border bg-surface px-3 text-fg placeholder:text-faint " +
  "transition-[border-color,box-shadow] duration-150 " +
  "disabled:cursor-not-allowed disabled:bg-sunken disabled:text-muted";

const CONTROL_NORMAL = "border-line-strong hover:border-fg/60 focus-visible:border-accent";
const CONTROL_ERROR = "border-danger";

/* --------------------------------------------------------------- texto ---- */

type CampoProps = BaseProps &
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "className"> & {
    sufijo?: React.ReactNode;
    prefijo?: React.ReactNode;
  };

export const Campo = forwardRef<HTMLInputElement, CampoProps>(function Campo(
  {
    etiqueta,
    descripcion,
    error,
    requerido,
    etiquetaOculta,
    className,
    prefijo,
    sufijo,
    id: idExterno,
    ...resto
  },
  ref,
) {
  const generado = useId();
  const id = idExterno ?? generado;
  const idDescripcion = `${id}-desc`;
  const idError = `${id}-err`;

  return (
    <Envoltura
      id={id}
      etiqueta={etiqueta}
      descripcion={descripcion}
      error={error}
      requerido={requerido}
      etiquetaOculta={etiquetaOculta}
      className={className}
      idDescripcion={idDescripcion}
      idError={idError}
    >
      <div className="relative flex items-center">
        {prefijo && (
          <span className="pointer-events-none absolute left-3 text-subhead text-muted">
            {prefijo}
          </span>
        )}
        <input
          ref={ref}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? idError : descripcion ? idDescripcion : undefined}
          aria-required={requerido || undefined}
          className={cx(
            CONTROL_BASE,
            "min-h-11 py-2",
            error ? CONTROL_ERROR : CONTROL_NORMAL,
            Boolean(prefijo) && "pl-9",
            Boolean(sufijo) && "pr-12",
          )}
          {...resto}
        />
        {sufijo && (
          <span className="pointer-events-none absolute right-3 text-subhead text-muted">
            {sufijo}
          </span>
        )}
      </div>
    </Envoltura>
  );
});

/* ---------------------------------------------------------------- área ---- */

type AreaProps = BaseProps & Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "className">;

export const Area = forwardRef<HTMLTextAreaElement, AreaProps>(function Area(
  { etiqueta, descripcion, error, requerido, etiquetaOculta, className, id: idExterno, ...resto },
  ref,
) {
  const generado = useId();
  const id = idExterno ?? generado;
  const idDescripcion = `${id}-desc`;
  const idError = `${id}-err`;

  return (
    <Envoltura
      id={id}
      etiqueta={etiqueta}
      descripcion={descripcion}
      error={error}
      requerido={requerido}
      etiquetaOculta={etiquetaOculta}
      className={className}
      idDescripcion={idDescripcion}
      idError={idError}
    >
      <textarea
        ref={ref}
        id={id}
        rows={3}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? idError : descripcion ? idDescripcion : undefined}
        aria-required={requerido || undefined}
        className={cx(
          CONTROL_BASE,
          "resize-y py-2 leading-relaxed",
          error ? CONTROL_ERROR : CONTROL_NORMAL,
        )}
        {...resto}
      />
    </Envoltura>
  );
});

/* -------------------------------------------------------------- selector -- */

type SelectorProps = BaseProps &
  Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "className"> & {
    opciones: ReadonlyArray<{ valor: string; texto: string }>;
  };

export const Selector = forwardRef<HTMLSelectElement, SelectorProps>(function Selector(
  {
    etiqueta,
    descripcion,
    error,
    requerido,
    etiquetaOculta,
    className,
    opciones,
    id: idExterno,
    ...resto
  },
  ref,
) {
  const generado = useId();
  const id = idExterno ?? generado;
  const idDescripcion = `${id}-desc`;
  const idError = `${id}-err`;

  return (
    <Envoltura
      id={id}
      etiqueta={etiqueta}
      descripcion={descripcion}
      error={error}
      requerido={requerido}
      etiquetaOculta={etiquetaOculta}
      className={className}
      idDescripcion={idDescripcion}
      idError={idError}
    >
      <div className="relative">
        <select
          ref={ref}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? idError : descripcion ? idDescripcion : undefined}
          className={cx(
            CONTROL_BASE,
            "min-h-11 appearance-none py-2 pr-10",
            error ? CONTROL_ERROR : CONTROL_NORMAL,
          )}
          {...resto}
        >
          {opciones.map((opcion) => (
            <option key={opcion.valor} value={opcion.valor}>
              {opcion.texto}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m4 6.5 4 4 4-4" />
        </svg>
      </div>
    </Envoltura>
  );
});

/* ----------------------------------------------------------- interruptor -- */

type InterruptorProps = {
  checked: boolean;
  onChange: (valor: boolean) => void;
  etiqueta: string;
  descripcion?: string;
  disabled?: boolean;
  id?: string;
};

export function Interruptor({
  checked,
  onChange,
  etiqueta,
  descripcion,
  disabled,
  id: idExterno,
}: InterruptorProps) {
  const generado = useId();
  const id = idExterno ?? generado;
  const idDescripcion = `${id}-desc`;

  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex min-w-0 flex-col">
        <label htmlFor={id} className="text-body text-fg">
          {etiqueta}
        </label>
        {descripcion && (
          <span id={idDescripcion} className="text-footnote text-muted">
            {descripcion}
          </span>
        )}
      </span>

      {/* El área táctil llega a 44 px aunque la pista dibujada mida 31. */}
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={descripcion ? idDescripcion : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative inline-flex h-11 w-[3.25rem] shrink-0 items-center justify-center",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <span
          className={cx(
            "pointer-events-none flex h-[1.9375rem] w-[3.25rem] items-center rounded-full p-0.5",
            "transition-colors duration-200 ease-[var(--ease-standard)]",
            checked ? "bg-ok" : "bg-line-strong",
          )}
        >
          <span
            className={cx(
              "size-[1.6875rem] rounded-full bg-white shadow-e1",
              "transition-transform duration-200 ease-[var(--ease-standard)]",
              checked ? "translate-x-[1.3125rem]" : "translate-x-0",
            )}
          />
        </span>
      </button>
    </div>
  );
}

/* -------------------------------------------------------------- casilla --- */

type CasillaProps = {
  checked: boolean;
  onChange: (valor: boolean) => void;
  etiqueta: React.ReactNode;
  disabled?: boolean;
  id?: string;
};

export function Casilla({ checked, onChange, etiqueta, disabled, id: idExterno }: CasillaProps) {
  const generado = useId();
  const id = idExterno ?? generado;

  return (
    <label
      htmlFor={id}
      className={cx(
        "flex min-h-11 cursor-pointer items-center gap-3 text-body",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(evento) => onChange(evento.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className={cx(
          "flex size-[1.375rem] shrink-0 items-center justify-center rounded-[0.4375rem] border",
          "transition-colors duration-150",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent",
          checked ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-surface",
        )}
      >
        {checked && (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.25" className="size-3.5">
            <path d="m3.5 8.5 3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </span>
      <span className="min-w-0">{etiqueta}</span>
    </label>
  );
}
