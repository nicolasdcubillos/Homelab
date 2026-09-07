/**
 * Bloque de estado y control de una app.
 *
 * Es el objeto central del panel: reúne en un solo sitio lo que el usuario
 * quiere saber (¿corrió?, ¿fue bien?, ¿cuándo vuelve a correr?) y lo que
 * quiere hacer (lanzarla, probarla sin enviar nada, detenerla).
 *
 * Cuando la app no está lista, en vez de un botón muerto se explica qué falta
 * y se enlaza el sitio donde se arregla.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Insignia, type Tono } from "@/components/Insignia";
import { ResultadoEjecucion } from "@/components/ResultadoEjecucion";
import { IconoDetener, IconoJugar, IconoReloj } from "@/components/iconos";
import { useCancelar, useLanzar } from "@/lib/consultas";
import { cx } from "@/lib/cx";
import { ESTADO_EJECUCION, TONO_EJECUCION } from "@/lib/etiquetas";
import { mensajeDeError } from "@/lib/errores";
import { fechaHora, iso, relativo } from "@/lib/formato";
import type { App, EstadoEjecucion } from "@/lib/tipos";

/** Dónde se arregla cada motivo por el que una app no puede correr. */
const DESTINO_MOTIVO: Record<string, { texto: string; ruta: string }> = {
  sin_watches: { texto: "Añadir una vigilancia", ruta: "/vigilancias" },
  sin_holdings: { texto: "Añadir un activo", ruta: "/portafolio" },
  sin_destino: { texto: "Configurar notificaciones", ruta: "/ajustes" },
};

function estadoVisual(app: App): { tono: Tono; texto: string; latiendo: boolean } {
  if (app.running) return { tono: "activo", texto: "En curso", latiendo: true };
  if (!app.installed) return { tono: "neutro", texto: "No instalada", latiendo: false };
  if (!app.readiness.ready) return { tono: "aviso", texto: "Falta configurar", latiendo: false };

  const ultima = app.last_run?.status as EstadoEjecucion | undefined;
  if (!ultima) return { tono: "neutro", texto: "Sin ejecutar", latiendo: false };

  return { tono: TONO_EJECUCION[ultima], texto: ESTADO_EJECUCION[ultima], latiendo: false };
}

type Props = {
  app: App;
  /** Comando que lanza el botón principal. Por defecto, el primero declarado. */
  comandoPrincipal?: string;
};

export function BloqueApp({ app, comandoPrincipal }: Props) {
  const lanzar = useLanzar();
  const cancelar = useCancelar();
  const avisos = useAvisos();
  const [enVuelo, setEnVuelo] = useState<"real" | "prueba" | "cancelar" | null>(null);

  const comando = comandoPrincipal ?? app.commands[0]?.key;
  const estado = estadoVisual(app);
  const puedeLanzar = app.installed && app.readiness.ready && !app.running && Boolean(comando);

  const ejecutar = async (dry: boolean) => {
    if (!comando) return;
    setEnVuelo(dry ? "prueba" : "real");
    try {
      await lanzar.mutateAsync({ app: app.app_name, command_key: comando, dry_run: dry });
      avisos.exito(
        dry
          ? `Prueba de ${app.display_name} lanzada. No se enviará ninguna notificación.`
          : `${app.display_name} está corriendo.`,
      );
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos lanzar la ejecución."));
    } finally {
      setEnVuelo(null);
    }
  };

  const detener = async () => {
    setEnVuelo("cancelar");
    try {
      await cancelar.mutateAsync(app.app_name);
      avisos.info(`Pedimos a ${app.display_name} que se detenga.`);
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos detener la ejecución."));
    } finally {
      setEnVuelo(null);
    }
  };

  return (
    <article className="overflow-hidden rounded-lg border border-line bg-surface shadow-e1">
      {/* Franja de estado: da el color sin gastar un borde grueso de color. */}
      <div
        aria-hidden="true"
        className={cx(
          "h-0.5 w-full",
          estado.tono === "ok" && "bg-ok",
          estado.tono === "alerta" && "bg-danger",
          estado.tono === "aviso" && "bg-warn",
          estado.tono === "activo" && "bg-accent",
          estado.tono === "neutro" && "bg-line",
        )}
      />

      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-title3 font-semibold tracking-tight">{app.display_name}</h2>

            <p className="mt-1 text-subhead text-muted">
              {app.last_run?.started_at ? (
                <>
                  Última:{" "}
                  <time dateTime={iso(app.last_run.started_at)} title={fechaHora(app.last_run.started_at)}>
                    {relativo(app.last_run.started_at)}
                  </time>
                </>
              ) : (
                "Todavía no se ha ejecutado."
              )}
            </p>
          </div>

          <Insignia tono={estado.tono} latiendo={estado.latiendo}>
            {estado.texto}
          </Insignia>
        </div>

        {app.next_run_at && !app.running && (
          <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-subhead text-muted">
            <IconoReloj className="size-4 shrink-0" />
            Próxima{" "}
            <time dateTime={iso(app.next_run_at)} className="text-fg">
              {relativo(app.next_run_at)}
            </time>
            <span className="text-faint">· {fechaHora(app.next_run_at)}</span>
          </p>
        )}

        {!app.installed && (
          <p className="mt-3 rounded-md bg-neutral-soft px-3 py-2 text-footnote text-muted">
            Esta app no está instalada en el servidor. Avisa a un administrador.
          </p>
        )}

        {app.installed && !app.readiness.ready && app.readiness.reasons.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {app.readiness.reasons.map((motivo) => {
              const destino = DESTINO_MOTIVO[motivo.code];
              return (
                <li
                  key={motivo.code}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-subhead text-muted"
                >
                  <span className="text-warn" aria-hidden="true">
                    •
                  </span>
                  {motivo.message}
                  {destino?.ruta && (
                    <Link to={destino.ruta} className="font-medium text-accent hover:underline">
                      {destino.texto}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {app.running ? (
            <Boton
              tono="secundario"
              onClick={detener}
              cargando={enVuelo === "cancelar"}
              icono={<IconoDetener className="size-4" />}
            >
              Detener
            </Boton>
          ) : (
            <>
              <Boton
                tono="primario"
                onClick={() => ejecutar(false)}
                disabled={!puedeLanzar}
                cargando={enVuelo === "real"}
                icono={<IconoJugar className="size-4" />}
              >
                Ejecutar ahora
              </Boton>
              <Boton
                tono="secundario"
                onClick={() => ejecutar(true)}
                disabled={!puedeLanzar}
                cargando={enVuelo === "prueba"}
              >
                Probar sin enviar
              </Boton>
            </>
          )}
        </div>

        {!app.running && app.last_run?.result && (
          <div className="mt-4 border-t border-line pt-4">
            <p className="mb-2 text-caption font-medium text-muted uppercase tracking-wide">
              Resultado de la última corrida
            </p>
            <ResultadoEjecucion resultado={app.last_run.result} />
          </div>
        )}
      </div>
    </article>
  );
}
