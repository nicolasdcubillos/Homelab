/**
 * Marco de las pantallas de acceso.
 *
 * Sin navegación ni distracciones: una sola tarea por pantalla. En móvil ocupa
 * el ancho completo con aire suficiente; en escritorio se centra en una
 * columna estrecha, porque un formulario de cuatro campos no gana nada por
 * extenderse.
 */

import { cx } from "@/lib/cx";

type Props = {
  titulo: string;
  descripcion?: string;
  children: React.ReactNode;
  pie?: React.ReactNode;
};

export function MarcoAcceso({ titulo, descripcion, children, pie }: Props) {
  return (
    <div
      className={cx(
        "flex min-h-dvh flex-col bg-bg",
        "px-5 pt-[max(env(safe-area-inset-top),2rem)] pb-[max(env(safe-area-inset-bottom),1.5rem)]",
        "sm:items-center sm:justify-center",
      )}
    >
      <div className="mx-auto flex w-full max-w-sm flex-1 flex-col sm:flex-none">
        <div className="flex flex-1 flex-col justify-center sm:flex-none">
          <span
            aria-hidden="true"
            className="mb-6 flex size-11 items-center justify-center rounded-lg bg-accent text-on-accent shadow-e1"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" className="size-6">
              <path d="M8 1.5 2.5 4.4v4.2c0 3.1 2.2 5.9 5.5 6.9 3.3-1 5.5-3.8 5.5-6.9V4.4L8 1.5Z" />
            </svg>
          </span>

          <h1 className="text-title1 font-bold tracking-tight text-balance">{titulo}</h1>
          {descripcion && <p className="mt-2 text-body text-muted">{descripcion}</p>}

          <div className="mt-7">{children}</div>
        </div>

        {pie && <div className="mt-8 text-center text-subhead text-muted">{pie}</div>}
      </div>
    </div>
  );
}
