/**
 * Estructura de navegación.
 *
 * En móvil: barra de pestañas fija abajo, con las cinco secciones de primer
 * nivel y respeto por el área segura del teléfono. En escritorio: barra
 * lateral. Las pestañas son secciones, nunca acciones; lo accionable vive
 * dentro de cada pantalla.
 */

import { NavLink, useLocation } from "react-router-dom";

import { cx } from "@/lib/cx";

import {
  IconoActividad,
  IconoAdmin,
  IconoAjustes,
  IconoInicio,
  IconoPortafolio,
  IconoVigilancia,
} from "./iconos";

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

export const SECCION_ADMIN: Seccion = {
  ruta: "/admin",
  texto: "Administración",
  Icono: IconoAdmin,
};

/* ------------------------------------------------------------------ móvil -- */

export function BarraPestanas({ admin }: { admin: boolean }) {
  const { pathname } = useLocation();

  return (
    <nav
      aria-label="Secciones"
      className={cx(
        "material-bar area-bottom fixed inset-x-0 bottom-0 z-40 border-t border-line",
        "lg:hidden",
      )}
    >
      <ul className="flex items-stretch">
        {SECCIONES.map(({ ruta, texto, Icono }) => {
          const activa = ruta === "/" ? pathname === "/" : pathname.startsWith(ruta);
          return (
            <li key={ruta} className="flex-1">
              <NavLink
                to={ruta}
                aria-current={activa ? "page" : undefined}
                className={cx(
                  "flex min-h-[3.25rem] flex-col items-center justify-center gap-0.5 px-1 pt-1.5 pb-1",
                  "transition-colors duration-150",
                  activa ? "text-accent" : "text-muted hover:text-fg",
                )}
              >
                <Icono className="size-6" />
                <span className="text-caption2 leading-none font-medium">{texto}</span>
              </NavLink>
            </li>
          );
        })}

        {admin && (
          <li className="flex-1">
            <NavLink
              to={SECCION_ADMIN.ruta}
              aria-current={pathname.startsWith("/admin") ? "page" : undefined}
              className={cx(
                "flex min-h-[3.25rem] flex-col items-center justify-center gap-0.5 px-1 pt-1.5 pb-1",
                "transition-colors duration-150",
                pathname.startsWith("/admin") ? "text-accent" : "text-muted hover:text-fg",
              )}
            >
              <SECCION_ADMIN.Icono className="size-6" />
              <span className="text-caption2 leading-none font-medium">Admin</span>
            </NavLink>
          </li>
        )}
      </ul>
    </nav>
  );
}

/* ------------------------------------------------------------- escritorio -- */

export function BarraLateral({
  admin,
  email,
  pie,
}: {
  admin: boolean;
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
          {SECCIONES.map((seccion) =>
            enlace(
              seccion,
              seccion.ruta === "/" ? pathname === "/" : pathname.startsWith(seccion.ruta),
            ),
          )}
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
