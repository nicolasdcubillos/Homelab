import { useState } from "react";

import { Boton } from "@/components/Boton";
import { Aviso, Vacio } from "@/components/Estados";
import { Hoja } from "@/components/Hoja";
import { Insignia } from "@/components/Insignia";
import { HORIZONTES_REGIMEN } from "@/lib/etiquetas";
import { estadoHorizonte, fechaRegimen, numeroRegimen, RANGOS_REGIMEN, tonoHorizonte, useHistoriaRegimen, useSnapshotRegimen, type RangoRegimen } from "@/lib/regimen";

import { BloqueRegimen, ConsultaRegimen, DetalleHorizontes, TarjetasHorizontes } from "./DatosRegimen";
import { Cobertura } from "./Evidencia";

function DetalleSnapshot({ id }: { id: string }) {
  const consulta = useSnapshotRegimen(id);
  return <ConsultaRegimen consulta={consulta}>{(snapshot) => <div className="space-y-6">
    <p className="text-subhead text-muted">Corte: {fechaRegimen(snapshot.data.as_of)}</p>
    <p className="text-footnote text-muted">
      Modelo {snapshot.data.model_version} · {snapshot.data.mode === "RECONSTRUCCION" ? "Reconstrucción histórica" : "Registro operacional"}
    </p>
    <TarjetasHorizontes datos={snapshot.data} />
    <p className="break-words text-subhead">{snapshot.data.context}</p>
    <DetalleHorizontes datos={snapshot.data} />
    <Cobertura items={snapshot.data.coverage} />
    <details>
      <summary className="min-h-11 cursor-pointer py-3 text-subhead">Identidad y trazabilidad</summary>
      <dl className="space-y-2 break-all text-footnote text-muted">
        <div><dt>ID</dt><dd>{snapshot.id}</dd></div>
        <div><dt>Creado</dt><dd>{fechaRegimen(snapshot.created_at)}</dd></div>
        <div><dt>SHA-256</dt><dd>{snapshot.sha256}</dd></div>
      </dl>
    </details>
  </div>}</ConsultaRegimen>;
}

export function Paginacion({ offset, limit, total, cambiar }: {
  offset: number; limit: number; total: number; cambiar: (offset: number) => void;
}) {
  if (total <= limit) return null;
  return <div className="flex flex-wrap items-center justify-between gap-3">
    <p className="text-footnote text-muted">{offset + 1}–{Math.min(offset + limit, total)} de {total}</p>
    <div className="flex gap-2">
      <Boton tono="secundario" disabled={offset === 0} onClick={() => cambiar(Math.max(0, offset - limit))}>Anterior</Boton>
      <Boton tono="secundario" disabled={offset + limit >= total} onClick={() => cambiar(offset + limit)}>Siguiente</Boton>
    </div>
  </div>;
}

export function Historia() {
  const [rango, setRango] = useState<RangoRegimen>("1m");
  const [offset, setOffset] = useState(0);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const historia = useHistoriaRegimen(rango, offset);
  return <BloqueRegimen titulo="Historia registrada">
    <p className="text-subhead text-muted">
      Solo snapshots existentes. No se rellenan huecos ni se atribuye a la aplicación información que todavía no había recibido.
    </p>
    <div role="group" aria-label="Rango de historia" className="flex flex-wrap gap-2">
      {RANGOS_REGIMEN.map((opcion) => <Boton key={opcion.valor}
        tono={opcion.valor === rango ? "primario" : "secundario"} aria-pressed={opcion.valor === rango}
        onClick={() => { setRango(opcion.valor); setOffset(0); }}>{opcion.texto}</Boton>)}
    </div>
    <ConsultaRegimen consulta={historia}>{(datos) => <div className="space-y-4">
      {datos.unavailable_before_first && datos.first_available_at && (
        <Aviso titulo={`No disponible antes de ${fechaRegimen(datos.first_available_at)}`}>
          El rango solicitado es más amplio que la historia real. Las fechas anteriores no tienen un score registrado.
        </Aviso>
      )}
      {!datos.items.length
        ? <Vacio titulo="No hay snapshots en este rango"
          descripcion={datos.first_available_at
            ? `La historia comenzó el ${fechaRegimen(datos.first_available_at)}. Prueba otro rango.`
            : "La historia comenzará con el primer snapshot. Por ahora no hay valores que comparar."} />
        : <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full text-left text-subhead">
            <caption className="sr-only">Scores registrados por fecha y horizonte</caption>
            <thead className="bg-sunken text-muted"><tr>
              <th scope="col" className="p-3">Corte</th>
              {(["SHORT", "MEDIUM", "LONG"] as const).map((h) => <th scope="col" key={h} className="p-3">{HORIZONTES_REGIMEN[h]}</th>)}
              <th scope="col" className="p-3">Detalle</th>
            </tr></thead>
            <tbody>{datos.items.map((item) => <tr key={item.id} className="border-t border-line align-top">
              <th scope="row" className="min-w-36 p-3 font-normal">
                {fechaRegimen(item.data.as_of)}
                <span className="mt-1 block text-footnote text-muted">
                  {item.data.mode === "RECONSTRUCCION" ? "Reconstrucción" : "Operacional"} · {item.data.model_version}
                </span>
              </th>
              {(["SHORT", "MEDIUM", "LONG"] as const).map((h) => {
                const resultado = item.data.horizons.find((r) => r.horizon === h);
                return <td key={h} className="p-3">
                  <Insignia tono={tonoHorizonte(resultado)}>{estadoHorizonte(resultado)}</Insignia>
                  <span className="mt-2 block tabular-nums">
                    {resultado?.data_status === "COMPLETO" ? numeroRegimen(resultado.score) : "No disponible"}
                  </span>
                </td>;
              })}
              <td className="p-3"><Boton tono="sutil" onClick={() => setSnapshot(item.id)}
                aria-label={`Ver snapshot del ${fechaRegimen(item.data.as_of)}`}>Ver</Boton></td>
            </tr>)}</tbody>
          </table>
        </div>}
      <Paginacion offset={datos.offset} limit={datos.limit} total={datos.total} cambiar={setOffset} />
    </div>}</ConsultaRegimen>
    <Hoja abierta={Boolean(snapshot)} onCerrar={() => setSnapshot(null)} titulo="Snapshot registrado" tamano="lg">
      {snapshot && <DetalleSnapshot id={snapshot} />}
    </Hoja>
  </BloqueRegimen>;
}
