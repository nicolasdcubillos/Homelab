import { useState } from "react";

import { Boton } from "@/components/Boton";
import { Vacio } from "@/components/Estados";
import { fechaRegimen, useInformeRegimen, useInformesRegimen } from "@/lib/regimen";

import { BloqueRegimen, ConsultaRegimen, MatrizEvidencia } from "./DatosRegimen";
import { Paginacion } from "./Historia";

function Informe({ id }: { id: string }) {
  const consulta = useInformeRegimen(id);
  return <ConsultaRegimen consulta={consulta}>{(informe) => <article className="min-w-0 space-y-6">
    <header className="space-y-2 border-b border-line pb-4">
      <h3 className="text-title2 font-semibold">{informe.data.title}</h3>
      <p className="text-footnote text-muted">Publicado: {fechaRegimen(informe.created_at)} · Semana {informe.week_key}</p>
      <p className="text-footnote text-muted">
        Narrativa: {informe.data.narrative_status === "COMPLETO" ? "Completa"
          : informe.data.narrative_status === "ERROR" ? "No disponible; informe determinista"
            : "Generación opcional desactivada"}
      </p>
    </header>
    <div className="space-y-2">
      <h4 className="text-body font-semibold">Resumen breve</h4>
      <p className="max-w-prose whitespace-pre-wrap break-words text-body leading-relaxed">{informe.data.brief}</p>
    </div>
    <div className="divide-y divide-line">
      {informe.data.sections.map((seccion) => <details key={seccion.number} className="py-1">
        <summary className="min-h-11 cursor-pointer py-3 text-body font-semibold">
          {seccion.number}. {seccion.title}
        </summary>
        <p className="max-w-prose whitespace-pre-wrap break-words pb-4 text-subhead leading-relaxed">{seccion.text}</p>
      </details>)}
    </div>
    <div className="space-y-3">
      <h4 className="text-body font-semibold">Matriz de evidencia</h4>
      <MatrizEvidencia items={informe.data.matrix} />
    </div>
    <details>
      <summary className="min-h-11 cursor-pointer py-3 text-subhead">Trazabilidad del informe</summary>
      <dl className="space-y-2 break-all text-footnote text-muted">
        <div><dt>ID</dt><dd>{informe.id}</dd></div>
        <div><dt>Snapshot</dt><dd>{informe.snapshot_id}</dd></div>
        <div><dt>SHA-256</dt><dd>{informe.sha256}</dd></div>
      </dl>
    </details>
  </article>}</ConsultaRegimen>;
}

export function Informes() {
  const [offset, setOffset] = useState(0);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const consulta = useInformesRegimen(offset);
  return <BloqueRegimen titulo="Informes semanales">
    <p className="text-subhead text-muted">
      Lecturas conservadas con su evidencia y snapshot originales. Crear un informe no envía mensajes por sí mismo.
    </p>
    <ConsultaRegimen consulta={consulta}>{(datos) => <div className="space-y-6">
      {!datos.items.length
        ? <Vacio titulo={datos.total ? "Sin informes disponibles en esta página" : "Aún no hay informes"}
          descripcion={datos.total ? "Puede haber informes en otras páginas; solo se muestran aquellos cuya evidencia conserva permiso de difusión."
            : "El primer informe aparecerá después de una ejecución válida. Puede publicarse con cobertura parcial claramente indicada."} />
        : <>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Seleccionar informe">
          {datos.items.map((informe) => <Boton key={informe.id}
            tono={(seleccion ?? datos.items[0]?.id) === informe.id ? "primario" : "secundario"}
            aria-pressed={(seleccion ?? datos.items[0]?.id) === informe.id}
            onClick={() => setSeleccion(informe.id)}>Semana {informe.week_key}</Boton>)}
        </div>
        <Informe id={seleccion ?? datos.items[0]!.id} />
        </>}
      <Paginacion offset={datos.offset} limit={datos.limit} total={datos.total}
        cambiar={(valor) => { setOffset(valor); setSeleccion(null); }} />
    </div>}</ConsultaRegimen>
  </BloqueRegimen>;
}
