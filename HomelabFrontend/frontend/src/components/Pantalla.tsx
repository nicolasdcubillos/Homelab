/**
 * Cabecera persistente: el título y las acciones comparten contexto.
 * La descripción se desplaza con el contenido para liberar espacio al bajar.
 */

import { useEffect } from "react";

type Props = {
  titulo: string;
  descripcion?: string;
  /** Acciones de la pantalla, siempre junto al título. */
  acciones?: React.ReactNode;
  children: React.ReactNode;
  /** Botón de volver, para las pantallas que son un segundo nivel. */
  atras?: React.ReactNode;
};

export function Pantalla({ titulo, descripcion, acciones, children, atras }: Props) {
  useEffect(() => {
    document.title = `${titulo} · Homelab`;
  }, [titulo]);

  return (
    <>
      <header className="material-bar area-top sticky top-0 z-30 border-b border-line">
        <div className="mx-auto flex min-h-20 max-w-4xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-4 sm:px-6">
          {atras}
          <h1 className="min-w-0 flex-1 basis-48 break-words text-title1 font-semibold tracking-tight sm:text-display">
            {titulo}
          </h1>
          {acciones && <div className="flex max-w-full flex-wrap items-center gap-2">{acciones}</div>}
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 pt-5 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] sm:px-6 lg:pt-6 lg:pb-12">
        {descripcion && (
          <p className="mb-6 max-w-[65ch] text-subhead text-muted">{descripcion}</p>
        )}

        {children}
      </div>
    </>
  );
}
