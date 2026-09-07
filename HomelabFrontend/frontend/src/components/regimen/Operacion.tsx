import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Boton } from "@/components/Boton";
import { Area, Interruptor } from "@/components/Campos";
import { Aviso, EstadoError, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { ApiError } from "@/lib/api";
import { mensajeDeError } from "@/lib/errores";
import {
  clavesRegimen, ejecucionActiva, fechaRegimen, useConfigRegimen, useEjecucionRegimen,
  useGuardarConfigRegimen, useIniciarRegimen, useOperacionesRegimen, usePermisoRegimen,
  useResumenRegimen,
} from "@/lib/regimen";
import type { ConfigRegimen, EjecucionRegimen } from "@/lib/tipos";

import { BloqueRegimen, ConsultaRegimen } from "./DatosRegimen";

function EditorConfig({ datos, recargar }: { datos: ConfigRegimen; recargar: () => void }) {
  const permiso = usePermisoRegimen();
  const guardar = useGuardarConfigRegimen();
  const [texto, setTexto] = useState(JSON.stringify(datos.config, null, 2));
  const [enabled, setEnabled] = useState(datos.enabled);
  const [version, setVersion] = useState(datos.version);
  const [error, setError] = useState<string | null>(null);
  const [conflicto, setConflicto] = useState(false);
  const [guardado, setGuardado] = useState(false);
  const enviar = async (evento: React.FormEvent) => {
    evento.preventDefault(); setError(null); setConflicto(false); setGuardado(false);
    let config: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(texto);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
      config = parsed as Record<string, unknown>;
    } catch {
      setError("La configuración debe ser un objeto JSON válido. No se guardó ningún cambio.");
      return;
    }
    try {
      const actualizada = await guardar.mutateAsync({ version, enabled, config });
      setVersion(actualizada.version);
      setEnabled(actualizada.enabled);
      setTexto(JSON.stringify(actualizada.config, null, 2));
      setGuardado(true);
    } catch (causa) {
      const versionCambio = causa instanceof ApiError && causa.status === 409;
      setConflicto(versionCambio);
      setError(versionCambio
        ? "Otro operador cambió la configuración. Tu borrador se conserva. Copia lo que necesites y carga la versión vigente antes de guardar."
        : mensajeDeError(causa, "No pudimos guardar la configuración."));
    }
  };
  return <form onSubmit={(evento) => void enviar(evento)} className="space-y-4">
    <p className="text-footnote text-muted">Versión de edición {version} · Actualizada: {fechaRegimen(datos.updated_at)}</p>
    <Interruptor etiqueta="Motor habilitado en la configuración" checked={enabled}
      disabled={!permiso.operador || guardar.isPending} onChange={setEnabled}
      descripcion="El proceso también debe estar habilitado por el administrador del servidor." />
    <Area etiqueta="Modelo y reglas (JSON)" value={texto} rows={20}
      onChange={(evento) => setTexto(evento.target.value)} readOnly={!permiso.operador}
      disabled={guardar.isPending}
      descripcion="Pesos, ventanas y reglas compartidas. No introduzcas credenciales ni destinos privados. El servidor valida el modelo completo." />
    {error && <EstadoError mensaje={error} />}
    {datos.version !== version && !conflicto && <Aviso tono="aviso">
      Hay una versión más reciente en el servidor. El borrador conserva su versión original para evitar sobrescribir cambios ajenos.
    </Aviso>}
    {conflicto && <Boton tono="secundario" onClick={recargar}>Cargar versión vigente y descartar borrador</Boton>}
    {guardado && <p role="status" className="text-subhead text-ok">Configuración guardada.</p>}
    {permiso.operador ? <Boton type="submit" cargando={guardar.isPending} disabled={conflicto}>Guardar configuración compartida</Boton>
      : <Aviso titulo="Configuración de solo lectura">Un operador puede cambiar el modelo compartido. Tu suscripción sigue siendo privada.</Aviso>}
    <p className="text-footnote text-muted">Los cambios son prospectivos: no reescriben snapshots ni informes existentes.</p>
  </form>;
}

const TIPOS = { ingest: "Ingestar fuentes", snapshot: "Crear snapshot", report: "Crear informe" } as const;
const ESTADOS: Record<string, string> = {
  queued: "En cola", pending: "Pendiente", running: "En curso",
  success: "Completado", completed: "Completado", error: "Error", failed: "Falló",
  cancelled: "Cancelado", skipped: "Omitido",
  PENDIENTE: "Pendiente", EJECUTANDO: "En curso", ERROR: "Error",
  COMPLETO: "Completado", INCOMPLETO: "Completado con cobertura parcial", CANCELADO: "Cancelado",
};

function EstadoTrabajo({ trabajo }: { trabajo: EjecucionRegimen }) {
  const activo = ejecucionActiva(trabajo.status);
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-subhead font-semibold">{TIPOS[trabajo.kind as keyof typeof TIPOS] ?? trabajo.kind}</h3>
      <Insignia tono={activo ? "activo" : ["error", "failed", "ERROR"].includes(trabajo.status) ? "alerta"
        : trabajo.status === "INCOMPLETO" ? "aviso" : "neutro"}>
        {ESTADOS[trabajo.status] ?? trabajo.status}
      </Insignia>
    </div>
    <p className="text-footnote text-muted">Solicitado: {fechaRegimen(trabajo.requested_at)}</p>
    {trabajo.started_at && <p className="text-footnote text-muted">Inicio: {fechaRegimen(trabajo.started_at)}</p>}
    {trabajo.finished_at && <p className="text-footnote text-muted">Fin: {fechaRegimen(trabajo.finished_at)}</p>}
    <p className="break-words text-subhead">{trabajo.detail}</p>
    {activo && <p className="text-footnote text-muted">El trabajo continúa en el servidor. Puedes salir de esta sección.</p>}
  </div>;
}

function TrabajoActual({ id }: { id: string }) {
  const consulta = useEjecucionRegimen(id);
  const cliente = useQueryClient();
  const permiso = usePermisoRegimen();
  const estado = consulta.data?.status;
  useEffect(() => {
    if (estado && !ejecucionActiva(estado)) {
      void cliente.invalidateQueries({ queryKey: clavesRegimen.usuario(permiso.id) });
    }
  }, [cliente, estado, id, permiso.id]);
  return <div aria-live="polite" className="rounded-lg border border-line bg-surface p-4">
    <ConsultaRegimen consulta={consulta}>{(datos) => <EstadoTrabajo trabajo={datos} />}</ConsultaRegimen>
  </div>;
}

function Operaciones() {
  const [id, setId] = useState<string | null>(null);
  const iniciar = useIniciarRegimen();
  const operaciones = useOperacionesRegimen();
  const resumen = useResumenRegimen();
  const [error, setError] = useState<string | null>(null);
  const pendiente = operaciones.data?.items.some((run) => ejecucionActiva(run.status)) ?? false;
  const solicitar = async (kind: keyof typeof TIPOS) => {
    setError(null);
    try {
      const run = await iniciar.mutateAsync({ kind });
      setId(run.id);
    } catch (causa) {
      setError(mensajeDeError(causa, "No pudimos solicitar el trabajo."));
    }
  };
  return <BloqueRegimen titulo="Ejecuciones del motor">
    <p className="text-subhead text-muted">
      La ingesta consulta únicamente fuentes autorizadas. Snapshot e informe conservan la evidencia disponible; no completan faltantes ni disparan envíos de prueba.
    </p>
    <ConsultaRegimen consulta={resumen}>{(datos) => <div className="space-y-3">
      {(!datos.engine_enabled || !datos.enabled) && <Aviso tono="aviso" titulo="Motor detenido">
        {!datos.engine_enabled ? "El proceso está deshabilitado en el servidor. Solicita su activación al administrador."
          : "Activa el motor en la configuración compartida para solicitar ejecuciones."}
      </Aviso>}
      <div className="flex flex-wrap gap-2">
        {(Object.keys(TIPOS) as (keyof typeof TIPOS)[]).map((kind) => <Boton key={kind}
          tono="secundario" disabled={iniciar.isPending || pendiente || !datos.engine_enabled || !datos.enabled}
          onClick={() => void solicitar(kind)}>{TIPOS[kind]}</Boton>)}
      </div>
      {iniciar.isPending && <p role="status" className="text-subhead text-muted">Solicitando ejecución…</p>}
    </div>}</ConsultaRegimen>
    {error && <EstadoError mensaje={error} />}
    {id && <TrabajoActual id={id} />}
    <ConsultaRegimen consulta={operaciones}>{(datos) => datos.items.length
      ? <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
        {datos.items.filter((run) => run.id !== id).map((run) => <li key={run.id} className="p-4"><EstadoTrabajo trabajo={run} /></li>)}
      </ul> : <Vacio titulo="Sin ejecuciones registradas" descripcion="Los trabajos del motor y sus incidencias aparecerán aquí, sin mostrar destinos de otros usuarios." />
    }</ConsultaRegimen>
  </BloqueRegimen>;
}

export function Operacion() {
  const config = useConfigRegimen();
  const permiso = usePermisoRegimen();
  const [revision, setRevision] = useState(0);
  return <div className="space-y-8">
    <BloqueRegimen titulo="Modelo compartido">
      <ConsultaRegimen consulta={config}>{(datos) => <EditorConfig key={revision} datos={datos}
        recargar={() => { void config.refetch().then((respuesta) => { if (respuesta.isSuccess) setRevision((n) => n + 1); }); }} />}</ConsultaRegimen>
    </BloqueRegimen>
    {permiso.operador && <Operaciones />}
  </div>;
}
