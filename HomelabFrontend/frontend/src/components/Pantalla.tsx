/**
 * Cabecera de pantalla con título grande que colapsa.
 *
 * Al abrir, el título se lee en grande y establece dónde estás. Al bajar, se
 * encoge a una barra compacta que deja el sitio al contenido, con el mismo
 * texto para no perder la referencia. Es el comportamiento nativo de iOS y
 * aquí se consigue con un observador de intersección, sin escuchar el scroll.
 */

import { useEffect, useRef, useState } from "react";

import { cx } from "@/lib/cx";

type Props = {
  titulo: string;
  descripcion?: string;
  /** Acciones de la pantalla: van en la barra compacta al hacer scroll. */
  acciones?: React.ReactNode;
  children: React.ReactNode;
  /** Botón de volver, para las pantallas que son un segundo nivel. */
  atras?: React.ReactNode;
};

export function Pantalla({ titulo, descripcion, acciones, children, atras }: Props) {
  const centinela = useRef<HTMLDivElement>(null);
  const [compacta, setCompacta] = useState(false);

  useEffect(() => {
    const nodo = centinela.current;
    if (!nodo || typeof IntersectionObserver === "undefined") return;

    const observador = new IntersectionObserver(
      ([entrada]) => setCompacta(!entrada?.isIntersecting),
      { rootMargin: "-52px 0px 0px 0px", threshold: 0 },
    );
    observador.observe(nodo);
    return () => observador.disconnect();
  }, []);

  useEffect(() => {
    document.title = `${titulo} · Homelab`;
  }, [titulo]);

  return (
    <>
      <header
        className={cx(
          "material-bar area-top sticky top-0 z-30 transition-[border-color] duration-200",
          compacta ? "border-b border-line" : "border-b border-transparent",
        )}
      >
        <div className="mx-auto flex h-13 max-w-4xl items-center gap-2 px-4 sm:px-6">
          {atras}

          <span
            aria-hidden="true"
            className={cx(
              "min-w-0 flex-1 truncate text-body font-semibold transition-opacity duration-200",
              compacta ? "opacity-100" : "opacity-0",
            )}
          >
            {titulo}
          </span>

          {acciones && <div className="flex shrink-0 items-center gap-2">{acciones}</div>}
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] sm:px-6 lg:pb-12">
        <div ref={centinela} className="h-px" />

        <div className="pt-1 pb-5">
          <h1 className="text-title1 font-bold tracking-tight sm:text-display">{titulo}</h1>
          {descripcion && (
            <p className="mt-1.5 max-w-[60ch] text-subhead text-muted">{descripcion}</p>
          )}
        </div>

        {children}
      </div>
    </>
  );
}
