/**
 * Hoja modal.
 *
 * Se apoya en `<dialog>` nativo para heredar gratis lo difícil: la capa
 * superior del navegador (escapa de cualquier contenedor con `overflow`), el
 * atrapado de foco, el cierre con Escape y el `inert` del resto de la página.
 *
 * En móvil sube desde abajo y se descarta invirtiendo esa entrada, como una
 * hoja de iOS. En escritorio aparece centrada.
 */

import { useCallback, useEffect, useId, useRef } from "react";

import { cx } from "@/lib/cx";

type Props = {
  abierta: boolean;
  onCerrar: () => void;
  titulo: string;
  descripcion?: string;
  children: React.ReactNode;
  /** Barra fija inferior para las acciones principales. */
  pie?: React.ReactNode;
  tamano?: "md" | "lg";
};

export function Hoja({
  abierta,
  onCerrar,
  titulo,
  descripcion,
  children,
  pie,
  tamano = "md",
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const cerrando = useRef(false);
  const idTitulo = useId();
  const idDescripcion = useId();

  useEffect(() => {
    const dialogo = ref.current;
    if (!dialogo) return;

    if (abierta && !dialogo.open) {
      dialogo.showModal();
    } else if (!abierta && dialogo.open) {
      dialogo.close();
    }
  }, [abierta]);

  // El navegador cierra el diálogo con Escape sin pasar por nuestro estado;
  // esto lo devuelve al padre para que ambos queden sincronizados.
  const alCerrarNativo = useCallback(() => {
    if (!cerrando.current) onCerrar();
    cerrando.current = false;
  }, [onCerrar]);

  const alPulsarFondo = (evento: React.MouseEvent<HTMLDialogElement>) => {
    if (evento.target === ref.current) onCerrar();
  };

  return (
    <dialog
      ref={ref}
      onClose={alCerrarNativo}
      onCancel={(evento) => {
        evento.preventDefault();
        onCerrar();
      }}
      onClick={alPulsarFondo}
      aria-labelledby={idTitulo}
      aria-describedby={descripcion ? idDescripcion : undefined}
      className={cx(
        "m-0 w-full max-w-none bg-transparent p-0 text-fg",
        "max-h-none h-full max-w-full",
        "backdrop:bg-scrim backdrop:backdrop-blur-[2px]",
        "open:animate-[hl-fade-in_200ms_ease-out]",
        // Centrado real en todos los tamaños; el hijo decide su forma.
        "grid place-items-end sm:place-items-center",
      )}
    >
      {abierta && (
        <div
          className={cx(
            "flex max-h-[92dvh] w-full flex-col overflow-hidden bg-bg shadow-e3",
            "rounded-t-xl sm:rounded-xl",
            "animate-[hl-sheet-up_280ms_cubic-bezier(0.32,0.72,0,1)] sm:animate-[hl-pop-in_200ms_ease-out]",
            tamano === "lg" ? "sm:max-w-2xl" : "sm:max-w-lg",
            "sm:mb-0",
          )}
        >
          {/* Asidero: en móvil comunica que la hoja se puede descartar. */}
          <div className="flex justify-center pt-2 sm:hidden" aria-hidden="true">
            <span className="h-1 w-9 rounded-full bg-line-strong opacity-60" />
          </div>

          <header className="flex items-start gap-3 px-5 pt-3 pb-3 sm:pt-5">
            <div className="min-w-0 flex-1">
              <h2 id={idTitulo} className="text-title3 font-semibold">
                {titulo}
              </h2>
              {descripcion && (
                <p id={idDescripcion} className="mt-1 text-subhead text-muted">
                  {descripcion}
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={onCerrar}
              aria-label="Cerrar"
              className={cx(
                "-mr-2 -mt-1 flex size-11 shrink-0 items-center justify-center rounded-full",
                "text-muted transition-colors hover:bg-neutral-soft hover:text-fg active:bg-line",
              )}
            >
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                className="size-4"
                aria-hidden="true"
              >
                <path d="m4 4 8 8M12 4l-8 8" />
              </svg>
            </button>
          </header>

          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5">
            {children}
          </div>

          {pie && (
            <footer className="area-bottom border-t border-line bg-surface px-5 py-3">
              {pie}
            </footer>
          )}
        </div>
      )}
    </dialog>
  );
}

/**
 * Pie de hoja: las acciones alineadas a la derecha en escritorio y apiladas a
 * ancho completo en móvil, donde el pulgar necesita superficie.
 */
export function PieDeHoja({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end [&>*]:w-full sm:[&>*]:w-auto">
      {children}
    </div>
  );
}
