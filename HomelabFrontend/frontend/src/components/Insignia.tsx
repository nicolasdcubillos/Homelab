/**
 * Insignia de estado.
 *
 * El color nunca va solo: siempre lleva su texto y un punto de forma propia,
 * porque un usuario con daltonismo no puede distinguir "correcta" de "con
 * error" solo por el tono.
 */

import { cx } from "@/lib/cx";

export type Tono = "ok" | "alerta" | "aviso" | "activo" | "neutro";

const TONOS: Record<Tono, string> = {
  ok: "bg-ok-soft text-ok",
  alerta: "bg-danger-soft text-danger",
  aviso: "bg-warn-soft text-warn",
  activo: "bg-accent-soft text-accent-quiet",
  neutro: "bg-neutral-soft text-muted",
};

const PUNTOS: Record<Tono, string> = {
  ok: "bg-ok",
  alerta: "bg-danger",
  aviso: "bg-warn",
  activo: "bg-accent",
  neutro: "bg-faint",
};

type Props = {
  tono?: Tono;
  children: React.ReactNode;
  /** Late cuando el estado es "algo está pasando ahora mismo". */
  latiendo?: boolean;
  punto?: boolean;
  className?: string;
};

export function Insignia({
  tono = "neutro",
  children,
  latiendo = false,
  punto = true,
  className,
}: Props) {
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5",
        "text-caption font-medium whitespace-nowrap",
        TONOS[tono],
        className,
      )}
    >
      {punto && (
        <span className="relative flex size-1.5" aria-hidden="true">
          {latiendo && (
            <span
              className={cx(
                "absolute inline-flex size-full animate-ping rounded-full opacity-70",
                PUNTOS[tono],
              )}
            />
          )}
          <span className={cx("relative inline-flex size-1.5 rounded-full", PUNTOS[tono])} />
        </span>
      )}
      {children}
    </span>
  );
}
