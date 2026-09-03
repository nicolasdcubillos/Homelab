/**
 * Preferencia de apariencia.
 *
 * Tres opciones reales: seguir al sistema, claro y oscuro. La escena de uso es
 * un teléfono, muchas veces de noche, así que "sistema" es el valor por
 * defecto y el oscuro es un tema compuesto, no una inversión.
 */

import { createContext, use, useCallback, useEffect, useMemo, useState } from "react";

export type Apariencia = "sistema" | "claro" | "oscuro";

const CLAVE = "hld:tema";

type ContextoTema = {
  apariencia: Apariencia;
  resuelto: "claro" | "oscuro";
  cambiar: (valor: Apariencia) => void;
};

const Contexto = createContext<ContextoTema | null>(null);

function leerPreferencia(): Apariencia {
  try {
    const valor = localStorage.getItem(CLAVE);
    if (valor === "claro" || valor === "oscuro" || valor === "sistema") return valor;
  } catch {
    /* Safari en navegación privada puede lanzar al tocar localStorage. */
  }
  return "sistema";
}

function sistemaPrefiereOscuro(): boolean {
  return typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

export function ProveedorTema({ children }: { children: React.ReactNode }) {
  const [apariencia, setApariencia] = useState<Apariencia>(leerPreferencia);
  const [sistemaOscuro, setSistemaOscuro] = useState(sistemaPrefiereOscuro);

  useEffect(() => {
    if (!window.matchMedia) return;
    const consulta = window.matchMedia("(prefers-color-scheme: dark)");
    const alCambiar = (evento: MediaQueryListEvent) => setSistemaOscuro(evento.matches);
    consulta.addEventListener("change", alCambiar);
    return () => consulta.removeEventListener("change", alCambiar);
  }, []);

  const resuelto: "claro" | "oscuro" =
    apariencia === "sistema" ? (sistemaOscuro ? "oscuro" : "claro") : apariencia;

  useEffect(() => {
    document.documentElement.dataset.theme = resuelto === "oscuro" ? "dark" : "light";
  }, [resuelto]);

  const cambiar = useCallback((valor: Apariencia) => {
    setApariencia(valor);
    try {
      localStorage.setItem(CLAVE, valor);
    } catch {
      /* Sin almacenamiento el tema simplemente no persiste entre visitas. */
    }
  }, []);

  const valor = useMemo(
    () => ({ apariencia, resuelto, cambiar }),
    [apariencia, resuelto, cambiar],
  );

  return <Contexto value={valor}>{children}</Contexto>;
}

export function useTema(): ContextoTema {
  const contexto = use(Contexto);
  if (!contexto) throw new Error("useTema necesita estar dentro de <ProveedorTema>");
  return contexto;
}
