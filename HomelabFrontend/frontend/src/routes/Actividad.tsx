/**
 * Actividad.
 *
 * El historial de ejecuciones y, al tocar una, su log. Mientras algo corre el
 * log se refresca solo y el foco se queda abajo, que es donde aparece lo nuevo.
 */

import { useEffect, useRef, useState } from "react";

import { Boton } from "@/components/Boton";
import { EstadoError, Esqueleto, EsqueletoLista, Vacio } from "@/components/Estados";
import { Hoja } from "@/components/Hoja";
import { Insignia } from "@/components/Insignia";
import { Pantalla } from "@/components/Pantalla";
import { IconoActividad } from "@/components/iconos";
import { useApps, useEjecuciones, useLog } from "@/lib/consultas";
import { cx } from "@/lib/cx";
import { mensajeDeError } from "@/lib/errores";
import { DISPARADOR, ESTADO_EJECUCION, TONO_EJECUCION } from "@/lib/etiquetas";
import { duracion, fechaHora, iso, relativo } from "@/lib/formato";
import type { Ejecucion, EstadoEjecucion } from "@/lib/tipos";

const ESTADOS: Array<{ valor: string; texto: string }> = [
  { valor: "", texto: "Todas" },
  { valor: "running", texto: "En curso" },
  { valor: "success", texto: "Correctas" },
  { valor: "error", texto: "Con error" },
  { valor: "skipped", texto: "Omitidas" },
];

/* ------------------------------------------------------------ visor log -- */

function VisorLog({ ejecucion, onCerrar }: { ejecucion: Ejecucion | null; onCerrar: () => void }) {
  const corriendo = ejecucion?.status === "running";
  const log = useLog(ejecucion?.id ?? null, corriendo);
  const fin = useRef<HTMLDivElement>(null);

  // Con el log creciendo, mantener la vista al final es lo que uno espera de
  // una consola. Sin animación: el salto instantáneo se lee mejor.
  useEffect(() => {
    if (corriendo) fin.current?.scrollIntoView({ block: "end" });
  }, [log.data?.content, corriendo]);

  return (
    <Hoja
      abierta={ejecucion !== null}
      onCerrar={onCerrar}
      tamano="lg"
      titulo={ejecucion ? ejecucion.command_label : "Registro"}
      descripcion={
        ejecucion?.started_at
          ? `${fechaHora(ejecucion.started_at)} · ${DISPARADOR[ejecucion.trigger] ?? ejecucion.trigger}`
          : undefined
      }
    >
      {log.isPending && (
        <div className="space-y-2">
          <Esqueleto className="h-4 w-full" />
          <Esqueleto className="h-4 w-5/6" />
          <Esqueleto className="h-4 w-4/6" />
        </div>
      )}

      {log.isError && (
        <EstadoError
          mensaje={mensajeDeError(log.error, "No pudimos leer el registro.")}
          onReintentar={() => void log.refetch()}
        />
      )}

      {log.isSuccess && (
        <>
          {corriendo && (
            <p className="mb-3 flex items-center gap-2 text-footnote text-muted" aria-live="polite">
              <span className="relative flex size-2" aria-hidden="true">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-70" />
                <span className="relative inline-flex size-2 rounded-full bg-accent" />
              </span>
              Actualizando en vivo…
            </p>
          )}

          <pre
            className={cx(
              "max-h-[60dvh] overflow-auto rounded-md bg-sunken p-3",
              "font-mono text-caption leading-relaxed whitespace-pre-wrap text-fg/85",
            )}
            tabIndex={0}
            role="log"
            aria-label="Salida de la ejecución"
          >
            {log.data.content || "Todavía no hay salida."}
            <div ref={fin} />
          </pre>
        </>
      )}
    </Hoja>
  );
}

/* -------------------------------------------------------------- pantalla -- */

export function Actividad() {
  const apps = useApps();
  const [app, setApp] = useState("");
  const [estado, setEstado] = useState("");
  const [abierta, setAbierta] = useState<Ejecucion | null>(null);

  const ejecuciones = useEjecuciones({
    app_name: app || undefined,
    status: estado || undefined,
    limit: 60,
  });

  const items = ejecuciones.data?.items ?? [];
  const opcionesApp = [
    { valor: "", texto: "Todas las apps" },
    ...(apps.data?.items ?? []).map((a) => ({ valor: a.app_name, texto: a.display_name })),
  ];

  return (
    <Pantalla
      titulo="Actividad"
      descripcion="Cada vez que una app corre queda registrada aquí, con su salida completa."
    >
      {/* Filtros como chips: en móvil se deslizan, en escritorio caben todos. */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {opcionesApp.map((opcion) => (
          <Chip
            key={opcion.valor}
            activo={app === opcion.valor}
            onClick={() => setApp(opcion.valor)}
          >
            {opcion.texto}
          </Chip>
        ))}
      </div>

      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {ESTADOS.map((opcion) => (
          <Chip
            key={opcion.valor}
            activo={estado === opcion.valor}
            onClick={() => setEstado(opcion.valor)}
          >
            {opcion.texto}
          </Chip>
        ))}
      </div>

      {ejecuciones.isPending && <EsqueletoLista filas={5} />}

      {ejecuciones.isError && (
        <EstadoError
          mensaje={mensajeDeError(ejecuciones.error, "No pudimos cargar el historial.")}
          onReintentar={() => void ejecuciones.refetch()}
          reintentando={ejecuciones.isFetching}
        />
      )}

      {ejecuciones.isSuccess && items.length === 0 && (
        <Vacio
          icono={<IconoActividad className="size-8" />}
          titulo={app || estado ? "Nada con estos filtros" : "Todavía no hay ejecuciones"}
          descripcion={
            app || estado
              ? "Prueba a quitar algún filtro para ver más resultados."
              : "Cuando lances una app a mano o el horario la dispare, aparecerá aquí con su registro."
          }
          accion={
            (app || estado) && (
              <Boton
                tono="secundario"
                onClick={() => {
                  setApp("");
                  setEstado("");
                }}
              >
                Quitar filtros
              </Boton>
            )
          }
        />
      )}

      {items.length > 0 && (
        <ul className="overflow-hidden rounded-lg border border-line bg-surface shadow-e1">
          {items.map((ejecucion) => (
            <li key={ejecucion.id}>
              <button
                type="button"
                onClick={() => setAbierta(ejecucion)}
                className={cx(
                  "relative flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left transition-colors",
                  "after:absolute after:inset-x-0 after:bottom-0 after:ml-4 after:h-px after:bg-line",
                  "hover:bg-sunken active:bg-neutral-soft",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body font-medium">
                    {ejecucion.command_label}
                  </span>
                  <span className="mt-0.5 block text-footnote text-muted">
                    {ejecucion.started_at ? (
                      <time dateTime={iso(ejecucion.started_at)} title={fechaHora(ejecucion.started_at)}>
                        {relativo(ejecucion.started_at)}
                      </time>
                    ) : (
                      "Sin iniciar"
                    )}
                    {ejecucion.duration_seconds !== null &&
                      ejecucion.duration_seconds !== undefined &&
                      ` · ${duracion(ejecucion.duration_seconds)}`}
                    {" · "}
                    {DISPARADOR[ejecucion.trigger] ?? ejecucion.trigger}
                  </span>
                  {ejecucion.skip_reason && (
                    <span className="mt-0.5 block text-footnote text-warn">
                      {ejecucion.skip_reason}
                    </span>
                  )}
                </span>

                <Insignia
                  tono={TONO_EJECUCION[ejecucion.status as EstadoEjecucion] ?? "neutro"}
                  latiendo={ejecucion.status === "running"}
                >
                  {ESTADO_EJECUCION[ejecucion.status as EstadoEjecucion] ?? ejecucion.status}
                </Insignia>
              </button>
            </li>
          ))}
        </ul>
      )}

      <VisorLog ejecucion={abierta} onCerrar={() => setAbierta(null)} />
    </Pantalla>
  );
}

/* ------------------------------------------------------------------ chip -- */

function Chip({
  activo,
  onClick,
  children,
}: {
  activo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activo}
      className={cx(
        "min-h-9 shrink-0 rounded-full border px-3.5 text-subhead font-medium whitespace-nowrap",
        "transition-colors duration-150",
        activo
          ? "border-transparent bg-accent text-on-accent"
          : "border-line bg-surface text-muted hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
