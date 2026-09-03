/**
 * Avisos efímeros.
 *
 * Confirman una acción que ya ocurrió sin robar el foco ni interrumpir. Se
 * anuncian por una región `aria-live` para que un lector de pantalla los lea,
 * y el error se queda más tiempo en pantalla que el éxito porque hay algo que
 * leer y decidir.
 */

import { createContext, use, useCallback, useMemo, useRef, useState } from "react";

import { cx } from "@/lib/cx";

type TonoAviso = "ok" | "error" | "info";

type AvisoEfimero = {
  id: number;
  tono: TonoAviso;
  mensaje: string;
};

type ContextoAvisos = {
  exito: (mensaje: string) => void;
  error: (mensaje: string) => void;
  info: (mensaje: string) => void;
};

const Contexto = createContext<ContextoAvisos | null>(null);

const DURACION: Record<TonoAviso, number> = {
  ok: 3200,
  info: 4000,
  error: 6500,
};

export function ProveedorAvisos({ children }: { children: React.ReactNode }) {
  const [avisos, setAvisos] = useState<AvisoEfimero[]>([]);
  const siguienteId = useRef(1);

  const quitar = useCallback((id: number) => {
    setAvisos((previos) => previos.filter((aviso) => aviso.id !== id));
  }, []);

  const empujar = useCallback(
    (tono: TonoAviso, mensaje: string) => {
      const id = siguienteId.current++;
      setAvisos((previos) => [...previos.slice(-2), { id, tono, mensaje }]);
      window.setTimeout(() => quitar(id), DURACION[tono]);
    },
    [quitar],
  );

  const valor = useMemo<ContextoAvisos>(
    () => ({
      exito: (mensaje) => empujar("ok", mensaje),
      error: (mensaje) => empujar("error", mensaje),
      info: (mensaje) => empujar("info", mensaje),
    }),
    [empujar],
  );

  return (
    <Contexto value={valor}>
      {children}

      <div
        // Sobre la barra de pestañas en móvil; esquina inferior en escritorio.
        className={cx(
          "pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2",
          "px-4 pb-[calc(env(safe-area-inset-bottom)+4.75rem)]",
          "sm:items-end sm:px-6 sm:pb-6",
        )}
      >
        <div role="status" aria-live="polite" className="contents">
          {avisos.map((aviso) => (
            <button
              key={aviso.id}
              type="button"
              onClick={() => quitar(aviso.id)}
              className={cx(
                "pointer-events-auto flex w-full max-w-md items-start gap-2.5 rounded-lg px-4 py-3 text-left",
                "border shadow-e2 backdrop-blur-xl",
                "animate-[hl-pop-in_200ms_ease-out]",
                aviso.tono === "ok" && "border-ok/30 bg-ok-soft text-fg",
                aviso.tono === "error" && "border-danger/30 bg-danger-soft text-fg",
                aviso.tono === "info" && "border-line bg-surface text-fg",
              )}
            >
              <span
                aria-hidden="true"
                className={cx(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  aviso.tono === "ok" && "bg-ok",
                  aviso.tono === "error" && "bg-danger",
                  aviso.tono === "info" && "bg-accent",
                )}
              />
              <span className="min-w-0 flex-1 text-subhead">{aviso.mensaje}</span>
            </button>
          ))}
        </div>
      </div>
    </Contexto>
  );
}

export function useAvisos(): ContextoAvisos {
  const contexto = use(Contexto);
  if (!contexto) throw new Error("useAvisos necesita estar dentro de <ProveedorAvisos>");
  return contexto;
}
