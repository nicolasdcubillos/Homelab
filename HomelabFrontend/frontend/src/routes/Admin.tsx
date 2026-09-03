/**
 * Panel de administración — lista de usuarios y métricas.
 *
 * Las métricas van como una tira de cifras enfatizadas que enlazan a la lista
 * ya filtrada, no como tarjetas "hero-metric" sueltas: el número siempre lleva
 * a donde se explica.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Campo, Selector } from "@/components/Campos";
import { EstadoError, EsqueletoLista, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { Pantalla } from "@/components/Pantalla";
import { IconoAdmin, IconoBuscar } from "@/components/iconos";
import { useMetricasAdmin, useUsuariosAdmin, type FiltrosUsuarios } from "@/lib/consultas";
import { cx } from "@/lib/cx";
import { ESTADO_USUARIO, ROL } from "@/lib/etiquetas";
import { mensajeDeError } from "@/lib/errores";
import { relativo } from "@/lib/formato";
import type { EstadoUsuario } from "@/lib/tipos";
import { useDebounce } from "@/lib/useDebounce";

const ORDENES: Array<{ valor: string; texto: string }> = [
  { valor: "created_at:desc", texto: "Más recientes primero" },
  { valor: "created_at:asc", texto: "Más antiguos primero" },
  { valor: "email:asc", texto: "Correo A-Z" },
  { valor: "last_login_at:desc", texto: "Último acceso" },
];

const TONO_ESTADO: Record<EstadoUsuario, "ok" | "aviso" | "neutro"> = {
  active: "ok",
  pending: "aviso",
  suspended: "neutro",
};

/** Tira de métricas: cifras enfatizadas, cada una enlaza a la vista filtrada. */
function TiraMetricas({ estado, onEstado }: { estado: string; onEstado: (v: string) => void }) {
  const metricas = useMetricasAdmin();
  if (metricas.isPending || !metricas.data) return null;

  const m = metricas.data;

  const items: Array<{ id: string; valor: number; etiqueta: string; onClick?: () => void }> = [
    { id: "total", valor: m.users_total, etiqueta: "usuarios", onClick: () => onEstado("") },
    {
      id: "activos",
      valor: m.users_by_status.active ?? 0,
      etiqueta: "activos",
      onClick: () => onEstado("active"),
    },
    {
      id: "pendientes",
      valor: m.users_by_status.pending ?? 0,
      etiqueta: "pendientes",
      onClick: () => onEstado("pending"),
    },
    { id: "jobs", valor: m.jobs_running, etiqueta: "corriendo" },
    { id: "fallos", valor: m.recent_failures, etiqueta: `fallos ${m.window_hours}h` },
  ];

  return (
    <div
      className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0"
      role="group"
      aria-label="Métricas globales"
    >
      {items.map((item) => {
        const Elemento = item.onClick ? "button" : "div";
        return (
          <Elemento
            key={item.id}
            type={item.onClick ? "button" : undefined}
            onClick={item.onClick}
            aria-pressed={item.onClick ? estado === (item.id === "activos" ? "active" : item.id === "pendientes" ? "pending" : "") : undefined}
            className={cx(
              "flex min-h-16 shrink-0 flex-col items-start justify-center gap-0.5 rounded-lg border border-line bg-surface px-4 py-2 text-left",
              item.onClick && "transition-colors hover:bg-sunken active:bg-neutral-soft",
            )}
          >
            <span className="tabular text-title2 font-semibold leading-none">{item.valor}</span>
            <span className="text-caption text-muted whitespace-nowrap">{item.etiqueta}</span>
          </Elemento>
        );
      })}
    </div>
  );
}

export function Admin() {
  const [q, setQ] = useState("");
  const [estado, setEstado] = useState("");
  const [orden, setOrden] = useState("created_at:desc");
  const debounced = useDebounce(q, 300);

  const [sort, order] = orden.split(":");
  const filtros: FiltrosUsuarios = {
    q: debounced || undefined,
    status: estado || undefined,
    sort,
    order,
    limit: 50,
  };

  const usuarios = useUsuariosAdmin(filtros);
  const items = usuarios.data?.items ?? [];

  return (
    <Pantalla titulo="Administración" descripcion="Usuarios, su configuración y el estado del panel.">
      <div className="space-y-5">
        <TiraMetricas estado={estado} onEstado={setEstado} />

        <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
          <Campo
            etiqueta="Buscar"
            etiquetaOculta
            placeholder="Buscar por correo…"
            value={q}
            onChange={(evento) => setQ(evento.target.value)}
            prefijo={<IconoBuscar className="size-4" />}
          />
          <Selector
            etiqueta="Estado"
            etiquetaOculta
            value={estado}
            onChange={(evento) => setEstado(evento.target.value)}
            opciones={[
              { valor: "", texto: "Cualquier estado" },
              { valor: "active", texto: "Activos" },
              { valor: "pending", texto: "Pendientes" },
              { valor: "suspended", texto: "Suspendidos" },
            ]}
          />
          <Selector
            etiqueta="Orden"
            etiquetaOculta
            value={orden}
            onChange={(evento) => setOrden(evento.target.value)}
            opciones={ORDENES}
          />
        </div>

        {usuarios.isPending && <EsqueletoLista filas={5} />}

        {usuarios.isError && (
          <EstadoError
            mensaje={mensajeDeError(usuarios.error, "No pudimos cargar los usuarios.")}
            onReintentar={() => void usuarios.refetch()}
            reintentando={usuarios.isFetching}
          />
        )}

        {usuarios.isSuccess && items.length === 0 && (
          <Vacio
            icono={<IconoAdmin className="size-8" />}
            titulo="Sin resultados"
            descripcion="Nadie coincide con esta búsqueda o estos filtros."
          />
        )}

        {items.length > 0 && (
          <ul className="overflow-hidden rounded-lg border border-line bg-surface shadow-e1">
            {items.map((usuario) => (
              <li key={usuario.id}>
                <Link
                  to={`/admin/usuarios/${usuario.id}`}
                  className={cx(
                    "relative flex min-h-14 items-center gap-3 px-4 py-3",
                    "after:absolute after:inset-x-0 after:bottom-0 after:ml-4 after:h-px after:bg-line last:after:hidden",
                    "hover:bg-sunken active:bg-neutral-soft transition-colors",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-medium">{usuario.email}</span>
                    <span className="mt-0.5 block text-footnote text-muted">
                      {usuario.last_login_at
                        ? `Activo ${relativo(usuario.last_login_at)}`
                        : "Nunca ha entrado"}
                      {usuario.role === "admin" && ` · ${ROL.admin}`}
                    </span>
                  </span>
                  <Insignia tono={TONO_ESTADO[usuario.status as EstadoUsuario]}>{ESTADO_USUARIO[usuario.status as EstadoUsuario]}</Insignia>
                </Link>
              </li>
            ))}
          </ul>
        )}

        {usuarios.data && usuarios.data.total > items.length && (
          <p className="text-center text-footnote text-muted">
            Mostrando {items.length} de {usuarios.data.total}. Afina la búsqueda para ver menos.
          </p>
        )}
      </div>
    </Pantalla>
  );
}
