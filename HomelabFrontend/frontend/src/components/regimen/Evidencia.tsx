import { Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { ESTADO_FUENTE_REGIMEN } from "@/lib/etiquetas";
import { fechaRegimen, useCoberturaRegimen, useFuentesRegimen } from "@/lib/regimen";
import type { CoberturaRegimen } from "@/lib/tipos";

import { BloqueRegimen, ConsultaRegimen, EnlaceFuente } from "./DatosRegimen";

export function Cobertura({ items }: CoberturaRegimen) {
  if (!items.length) return <Vacio titulo="Cobertura aún no disponible"
    descripcion="El catálogo y los motivos de ausencia aparecerán cuando el servidor los publique." />;
  const requeridos = items.filter((item) => item.required);
  return <div className="space-y-3">
    <p className="text-subhead text-muted">
      {requeridos.filter((item) => item.available).length} de {requeridos.length} requisitos centrales disponibles.
      {" "}Los datos gubernamentales por sí solos no completan la clasificación.
    </p>
    <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
      {items.map((item) => <li key={item.series_id} className="space-y-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="min-w-0 break-words text-subhead font-semibold">{item.name}</h3>
          <Insignia tono={item.available ? "ok" : "aviso"}>{item.available ? "Disponible" : "Faltante"}</Insignia>
        </div>
        <p className="text-footnote text-muted">{item.series_id} · {item.source_id} · {item.required ? "Obligatorio" : "Complementario"}</p>
        {item.reason && <p className="break-words text-subhead">{item.reason}</p>}
        <dl className="grid gap-2 text-footnote text-muted sm:grid-cols-3">
          <div><dt>Observado</dt><dd>{fechaRegimen(item.observed_at)}</dd></div>
          <div><dt>Publicado</dt><dd>{fechaRegimen(item.published_at)}</dd></div>
          <div><dt>Ingestado</dt><dd>{fechaRegimen(item.ingested_at)}</dd></div>
        </dl>
        <EnlaceFuente url={item.source_url}>Ver procedencia</EnlaceFuente>
      </li>)}
    </ul>
  </div>;
}

export function Evidencia() {
  const cobertura = useCoberturaRegimen();
  const fuentes = useFuentesRegimen();
  return <div className="space-y-8">
    <BloqueRegimen titulo="Cobertura y faltantes">
      <ConsultaRegimen consulta={cobertura}>{(datos) => <Cobertura items={datos.items} />}</ConsultaRegimen>
    </BloqueRegimen>
    <BloqueRegimen titulo="Fuentes y permisos de uso">
      <p className="text-subhead text-muted">
        Una página pública no garantiza derechos de descarga o redistribución. No se sustituyen índices ni datos licenciados por proxies.
      </p>
      <ConsultaRegimen consulta={fuentes}>{(datos) => datos.items.length
        ? <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {datos.items.map((fuente) => <li key={fuente.id} className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-body font-semibold">{fuente.name}</h3>
              <Insignia tono={fuente.status === "DISPONIBLE" ? "ok" : fuente.status === "ERROR" ? "alerta" : "aviso"}>
                {ESTADO_FUENTE_REGIMEN[fuente.status ?? "PENDIENTE"]}
              </Insignia>
            </div>
            <p className="break-words text-subhead text-muted">{fuente.detail}</p>
            <p className="text-footnote text-muted">Última lectura correcta: {fechaRegimen(fuente.last_success_at)}</p>
            {!!fuente.series?.length && <p className="break-words text-footnote text-muted">Series: {fuente.series.join(", ")}</p>}
            <div className="flex flex-wrap gap-x-6">
              <EnlaceFuente url={fuente.url}>Abrir fuente</EnlaceFuente>
              <EnlaceFuente url={fuente.terms_url}>Condiciones de uso</EnlaceFuente>
            </div>
          </li>)}
        </ul> : <Vacio titulo="Sin fuentes registradas" descripcion="No hay un catálogo disponible. No se están mostrando datos de ejemplo." />
      }</ConsultaRegimen>
    </BloqueRegimen>
  </div>;
}
