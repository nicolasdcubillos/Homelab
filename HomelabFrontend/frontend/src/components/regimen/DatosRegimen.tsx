import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { EstadoError, EsqueletoLista, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { CATEGORIAS_REGIMEN, CLASIFICACION_REGIMEN, ESTADO_DATOS_REGIMEN, HORIZONTES_REGIMEN } from "@/lib/etiquetas";
import { mensajeDeError } from "@/lib/errores";
import { estadoHorizonte, fechaRegimen, numeroRegimen, tonoHorizonte, urlFuente } from "@/lib/regimen";
import type { DatosSnapshotRegimen, EvidenciaRegimen, HorizonteRegimen } from "@/lib/tipos";

export function ConsultaRegimen<T>({
  consulta, children,
}: { consulta: UseQueryResult<T, Error>; children: (datos: T) => ReactNode }) {
  if (consulta.isPending) return <EsqueletoLista />;
  if (consulta.isError || !consulta.data) return (
    <EstadoError className="[&_button]:min-h-11" mensaje={mensajeDeError(consulta.error, "No pudimos leer los datos de régimen.")}
      onReintentar={() => void consulta.refetch()} reintentando={consulta.isFetching} />
  );
  return <>{children(consulta.data)}</>;
}

export function EnlaceFuente({ url, children = "Fuente oficial" }: {
  url?: string | null; children?: ReactNode;
}) {
  const destino = urlFuente(url);
  if (!destino) return <span className="text-footnote text-muted">Enlace no disponible</span>;
  return <a href={destino} target="_blank" rel="noopener noreferrer"
    className="inline-flex min-h-11 items-center break-all text-subhead text-accent underline underline-offset-4">
    {children}<span className="sr-only"> (abre en otra pestaña)</span>
  </a>;
}

export function BloqueRegimen({ titulo, children }: { titulo: string; children: ReactNode }) {
  return <section className="min-w-0 space-y-3">
    <h2 className="text-title3 font-semibold">{titulo}</h2>
    {children}
  </section>;
}

const HORIZONTES: HorizonteRegimen[] = ["SHORT", "MEDIUM", "LONG"];
const CONFIA = { BAJA: "Baja", MEDIA: "Media", ALTA: "Alta", NO_EVALUABLE: "No evaluable" };
const TRANSICION = { ESTABLE: "Estable", EN_TRANSICION: "En transición", NO_EVALUABLE: "No evaluable" };

export function TarjetasHorizontes({ datos }: { datos?: DatosSnapshotRegimen | null }) {
  return <div className="grid gap-3 md:grid-cols-3">
    {HORIZONTES.map((horizonte) => {
      const resultado = datos?.horizons.find((item) => item.horizon === horizonte);
      const completo = resultado?.data_status === "COMPLETO";
      return <article key={horizonte} aria-label={HORIZONTES_REGIMEN[horizonte]}
        className="min-w-0 rounded-lg border border-line bg-surface p-4">
        <h3 className="mb-3 text-body font-semibold">{HORIZONTES_REGIMEN[horizonte]}</h3>
        <Insignia tono={tonoHorizonte(resultado)}>{estadoHorizonte(resultado)}</Insignia>
        <p className="mt-4 text-title1 font-semibold tabular-nums">
          {completo && resultado.score != null
            ? <>{numeroRegimen(resultado.score)}<span className="text-body font-normal text-muted"> / 100</span></>
            : <span className="text-title3">Score no disponible</span>}
        </p>
        <p className="mt-1 text-footnote text-muted">
          {resultado ? `Calidad: ${ESTADO_DATOS_REGIMEN[resultado.data_status]}` : "Aún no hay un snapshot."}
        </p>
        <p className="mt-2 text-footnote text-muted">
          Confianza: {resultado ? CONFIA[resultado.confidence ?? "NO_EVALUABLE"] : "No evaluable"}
        </p>
        {resultado && <p className="mt-1 text-footnote text-muted">
          Transición: {TRANSICION[resultado.transition_status ?? "NO_EVALUABLE"]}
        </p>}
        {resultado?.previous_regime && <p className="mt-1 text-footnote text-muted">
          Lectura anterior: {CLASIFICACION_REGIMEN[resultado.previous_regime]}
        </p>}
        {!completo && <p className="mt-3 text-subhead text-muted">
          {resultado?.data_status === "INCOMPLETO"
            ? "Hay evidencia parcial; no es una clasificación completa de régimen."
            : "Sin evidencia suficiente. La ausencia de datos no significa neutralidad."}
        </p>}
      </article>;
    })}
  </div>;
}

function ListaLecturas({ titulo, items, vacio }: { titulo: string; items: string[]; vacio: string }) {
  return <div>
    <h4 className="text-subhead font-semibold">{titulo}</h4>
    {items.length ? <ul className="mt-1 list-disc space-y-1 pl-5 text-subhead text-muted">
      {items.map((texto, index) => <li key={index} className="break-words">{texto}</li>)}
    </ul> : <p className="mt-1 text-footnote text-muted">{vacio}</p>}
  </div>;
}

export function DetalleHorizontes({ datos }: { datos: DatosSnapshotRegimen }) {
  return <div className="space-y-3">
    {datos.horizons.map((resultado) => <details key={resultado.horizon}
      className="rounded-lg border border-line bg-surface">
      <summary className="min-h-11 cursor-pointer px-4 py-3 text-body font-semibold">
        {HORIZONTES_REGIMEN[resultado.horizon]} · {estadoHorizonte(resultado)}
      </summary>
      <div className="space-y-5 border-t border-line p-4">
        <p className="text-footnote text-muted">Modelo heurístico no validado. Confianza no equivale a probabilidad de ganancias.</p>
        <ListaLecturas titulo="Factores determinantes" items={resultado.drivers ?? []} vacio="No hay factores evaluables." />
        <ListaLecturas titulo="Contradicciones" items={resultado.contradictions ?? []} vacio="No hay contradicciones registradas; no implica ausencia de riesgo." />
        <ListaLecturas titulo="Qué cambió" items={resultado.changes ?? []} vacio="Sin cambios documentados." />
        <ListaLecturas titulo="Qué cambiaría la lectura" items={resultado.would_change ?? []} vacio="Sin condiciones documentadas." />
        <ListaLecturas titulo="Datos faltantes" items={resultado.missing ?? []} vacio="Sin faltantes declarados." />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-subhead">
            <caption className="pb-2 text-left font-semibold">Contribuciones por categoría</caption>
            <thead className="text-muted"><tr>
              <th scope="col" className="p-2">Categoría</th><th scope="col" className="p-2">Peso</th>
              <th scope="col" className="p-2">Valor</th><th scope="col" className="p-2">Aporte</th>
            </tr></thead>
            <tbody>{(resultado.categories ?? []).map((categoria) => <tr key={categoria.category} className="border-t border-line">
              <th scope="row" className="p-2 font-medium">{CATEGORIAS_REGIMEN[categoria.category] ?? categoria.category}</th>
              <td className="p-2 tabular-nums">{numeroRegimen(categoria.weight, "%")}</td>
              <td className="p-2 tabular-nums">{numeroRegimen(categoria.value)}</td>
              <td className="p-2 tabular-nums">{numeroRegimen(categoria.contribution, "puntos")}</td>
            </tr>)}</tbody>
          </table>
        </div>
        {(resultado.categories ?? []).map((categoria) => <div key={categoria.category} className="space-y-2">
          <h4 className="text-subhead font-semibold">{CATEGORIAS_REGIMEN[categoria.category] ?? categoria.category}</h4>
          <p className="break-words text-subhead text-muted">{categoria.reason}</p>
          {!!categoria.evidence?.length && <MatrizEvidencia items={categoria.evidence} />}
        </div>)}
      </div>
    </details>)}
  </div>;
}

const DIRECCION = { FAVORABLE: "Favorable", ADVERSA: "Adversa", MIXTA: "Mixta", NO_EVALUABLE: "No evaluable" };
export function MatrizEvidencia({ items }: { items: EvidenciaRegimen[] }) {
  if (!items.length) return <Vacio titulo="Sin evidencia registrada"
    descripcion="La matriz aparecerá cuando haya observaciones autorizadas y evaluables." />;
  return <div className="overflow-x-auto rounded-lg border border-line bg-surface">
    <table className="w-full text-left text-subhead">
      <caption className="sr-only">Matriz de evidencia con valores, unidades y procedencia</caption>
      <thead className="bg-sunken text-muted"><tr>
        <th scope="col" className="p-3">Serie / lectura</th>
        <th scope="col" className="p-3">Valor</th>
        <th scope="col" className="p-3">Procedencia</th>
      </tr></thead>
      <tbody>{items.map((evidencia, index) => <tr key={`${evidencia.series_id}-${index}`} className="border-t border-line align-top">
        <th scope="row" className="min-w-40 p-3 font-normal">
          <span className="block font-semibold">{evidencia.series_id}</span>
          <span className="mt-1 block break-words">{evidencia.reading}</span>
          <span className="mt-2 block text-footnote text-muted">{DIRECCION[evidencia.direction]}</span>
        </th>
        <td className="p-3 tabular-nums">{numeroRegimen(evidencia.value, evidencia.unit)}</td>
        <td className="min-w-44 p-3 text-footnote text-muted">
          <p>Observación: {fechaRegimen(evidencia.observed_at)}</p>
          <p className="mt-1">Disponible desde: {fechaRegimen(evidencia.available_at)}</p>
          <EnlaceFuente url={evidencia.source_url}>Consultar fuente</EnlaceFuente>
        </td>
      </tr>)}</tbody>
    </table>
  </div>;
}
