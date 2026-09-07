/**
 * Estructura de navegación.
 *
 * En móvil: barra de pestañas fija abajo, con las cinco secciones de primer
 * nivel y respeto por el área segura del teléfono. En escritorio: barra
 * lateral. Las pestañas son secciones, nunca acciones; lo accionable vive
 * dentro de cada pantalla.
 */

import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { cx } from "@/lib/cx";

import {
  IconoActividad,
  IconoAdmin,
  IconoAjustes,
  IconoInicio,
  IconoMenuMas,
  IconoPortafolio,
  IconoRegimen,
  IconoTrading,
  IconoVigilancia,
} from "./iconos";
import { Hoja } from "./Hoja";

export type Seccion = {
  ruta: string;
  texto: string;
  Icono: (props: { className?: string }) => React.JSX.Element;
};

export const SECCIONES: Seccion[] = [
  { ruta: "/", texto: "Inicio", Icono: IconoInicio },
  { ruta: "/vigilancias", texto: "Vigilancias", Icono: IconoVigilancia },
  { ruta: "/portafolio", texto: "Portafolio", Icono: IconoPortafolio },
  { ruta: "/actividad", texto: "Actividad", Icono: IconoActividad },
  { ruta: "/ajustes", texto: "Ajustes", Icono: IconoAjustes },
];

/**
 * Trading no está en `SECCIONES` porque no es de primer nivel para todos: solo
 * aparece si el backend concedió acceso. Se inserta junto a Portafolio, que es
 * la otra sección de dinero, en vez de al final.
 */
export const SECCION_TRADING: Seccion = {
  ruta: "/trading",
  texto: "Trading",
  Icono: IconoTrading,
};

export const SECCION_ADMIN: Seccion = {
  ruta: "/admin",
  texto: "Administración",
  Icono: IconoAdmin,
};

const SECCION_REGIMEN: Seccion = {
  ruta: "/regimen",
  texto: "Régimen de mercado",
  Icono: IconoRegimen,
};

function secciones(trading: boolean, regimen = false): Seccion[] {
  const posicion = SECCIONES.findIndex((s) => s.ruta === "/portafolio") + 1;
  return [...SECCIONES.slice(0, posicion), ...(trading ? [SECCION_TRADING] : []),
    ...(regimen ? [SECCION_REGIMEN] : []), ...SECCIONES.slice(posicion)];
}

function esActiva(ruta: string, pathname: string): boolean {
  return ruta === "/" ? pathname === "/" : pathname.startsWith(ruta);
}

/* ------------------------------------------------------------------ móvil -- */

export function BarraPestanas({ admin, trading, regimen = false }: { admin: boolean; trading: boolean; regimen?: boolean }) {
  const { pathname } = useLocation();
  const [mas, setMas] = useState(false);
  const lista = [...secciones(trading, regimen), ...(admin ? [SECCION_ADMIN] : [])];
  const visibles = lista.length > 5 ? lista.slice(0, 4) : lista;
  const adicionales = lista.length > 5 ? lista.slice(4) : [];

  const clases = (activa: boolean) =>
    cx(
      "flex min-h-[3.25rem] flex-col items-center justify-center gap-0.5 px-0.5 pt-1.5 pb-1",
      "transition-colors duration-150",
      activa ? "text-accent" : "text-muted hover:text-fg",
    );

  return (
    <>
    <nav
      aria-label="Secciones"
      className={cx(
        "material-bar area-bottom fixed inset-x-0 bottom-0 z-40 border-t border-line",
        "lg:hidden",
      )}
    >
      <ul className="flex items-stretch">
        {visibles.map(({ ruta, texto, Icono }) => {
          const activa = esActiva(ruta, pathname);
          return (
            <li key={ruta} className="min-w-0 flex-1">
              <NavLink to={ruta} aria-label={texto} aria-current={activa ? "page" : undefined} className={clases(activa)}>
                <Icono className="size-6 shrink-0" />
                <span className="w-full truncate text-center text-caption2 leading-none font-medium">
                  {ruta === "/regimen" ? "Régimen" : texto}
                </span>
              </NavLink>
            </li>
          );
        })}

        {adicionales.length > 0 && (
          <li className="min-w-0 flex-1">
            <button
              type="button"
              aria-haspopup="dialog"
              aria-expanded={mas}
              onClick={() => setMas(true)}
              className={cx(clases(adicionales.some((item) => esActiva(item.ruta, pathname))), "w-full")}
            >
              <IconoMenuMas className="size-6 shrink-0" />
              <span className="w-full truncate text-center text-caption2 leading-none font-medium">
                Más
              </span>
            </button>
          </li>
        )}
      </ul>
    </nav>
    <Hoja abierta={mas} onCerrar={() => setMas(false)} titulo="Más secciones">
      <nav aria-label="Más secciones">
        <ul className="space-y-1">
          {adicionales.map(({ ruta, texto, Icono }) => <li key={ruta}>
            <NavLink to={ruta} onClick={() => setMas(false)}
              aria-current={esActiva(ruta, pathname) ? "page" : undefined}
              className={cx("flex min-h-11 items-center gap-3 rounded-md px-3 py-3 text-body",
                esActiva(ruta, pathname) ? "bg-accent-soft text-accent-quiet" : "text-fg hover:bg-neutral-soft")}>
              <Icono className="size-5 shrink-0" />{texto}
            </NavLink>
          </li>)}
        </ul>
      </nav>
    </Hoja>
    </>
  );
}

/* ------------------------------------------------------------- escritorio -- */

export function BarraLateral({
  admin,
  trading,
  regimen = false,
  email,
  pie,
}: {
  admin: boolean;
  trading: boolean;
  regimen?: boolean;
  email: string;
  pie: React.ReactNode;
}) {
  const { pathname } = useLocation();

  const enlace = (seccion: Seccion, activa: boolean) => (
    <li key={seccion.ruta}>
      <NavLink
        to={seccion.ruta}
        aria-current={activa ? "page" : undefined}
        className={cx(
          "flex min-h-11 items-center gap-3 rounded-md px-3 text-subhead font-medium",
          "transition-colors duration-150",
          activa
            ? "bg-accent-soft text-accent-quiet"
            : "text-muted hover:bg-neutral-soft hover:text-fg",
        )}
      >
        <seccion.Icono className="size-5 shrink-0" />
        {seccion.texto}
      </NavLink>
    </li>
  );

  return (
    <aside
      className={cx(
        "fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-line bg-sunken",
        "lg:flex",
      )}
    >
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-5">
        <span
          aria-hidden="true"
          className="flex size-7 items-center justify-center rounded-md bg-accent text-on-accent"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" className="size-4">
            <path d="M8 1.5 2.5 4.4v4.2c0 3.1 2.2 5.9 5.5 6.9 3.3-1 5.5-3.8 5.5-6.9V4.4L8 1.5Z" />
          </svg>
        </span>
        <span className="text-body font-semibold tracking-tight">Homelab</span>
      </div>

      <nav aria-label="Secciones" className="min-h-0 flex-1 overflow-y-auto px-3">
        <ul className="space-y-0.5">
          {secciones(trading, regimen).map((seccion) => enlace(seccion, esActiva(seccion.ruta, pathname)))}
        </ul>

        {admin && (
          <>
            <p className="mt-6 mb-1.5 px-3 text-caption font-semibold tracking-wide text-faint uppercase">
              Sistema
            </p>
            <ul className="space-y-0.5">
              {enlace(SECCION_ADMIN, pathname.startsWith("/admin"))}
            </ul>
          </>
        )}
      </nav>

      <div className="shrink-0 border-t border-line p-3">
        <p className="truncate px-3 pb-2 text-footnote text-muted" title={email}>
          {email}
        </p>
        {pie}
      </div>
    </aside>
  );
}
