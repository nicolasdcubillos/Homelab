import { useState } from "react";

import { Boton } from "@/components/Boton";
import { Cargando } from "@/components/Cargando";
import { Aviso, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { Pantalla } from "@/components/Pantalla";
import { BloqueRegimen, ConsultaRegimen, DetalleHorizontes, TarjetasHorizontes } from "@/components/regimen/DatosRegimen";
import { Cobertura, Evidencia } from "@/components/regimen/Evidencia";
import { Historia } from "@/components/regimen/Historia";
import { Informes } from "@/components/regimen/Informes";
import { Operacion } from "@/components/regimen/Operacion";
import { Preferencias } from "@/components/regimen/Preferencias";
import { fechaRegimen, usePermisoRegimen, useResumenRegimen } from "@/lib/regimen";

function Resumen() {
  const consulta = useResumenRegimen();
  return <ConsultaRegimen consulta={consulta}>{(datos) => <div className="space-y-7">
    <div className="flex flex-wrap gap-2">
      <Insignia tono={datos.enabled && datos.engine_enabled ? "activo" : "neutro"}>
        Motor {datos.enabled && datos.engine_enabled ? "habilitado" : "detenido"}
      </Insignia>
      <Insignia>Entregas {datos.deliveries_enabled ? "habilitadas" : "desactivadas"}</Insignia>
    </div>
    <TarjetasHorizontes datos={datos.snapshot} />
    <div className="grid gap-4 border-y border-line py-4 text-subhead sm:grid-cols-2">
      <div><p className="font-semibold">Último corte</p><p className="mt-1 text-muted">{fechaRegimen(datos.snapshot?.as_of)}</p></div>
      <div><p className="font-semibold">Próximo informe semanal</p><p className="mt-1 text-muted">{fechaRegimen(datos.next_report_at)}</p></div>
      <div><p className="font-semibold">Historia disponible desde</p><p className="mt-1 text-muted">{fechaRegimen(datos.first_snapshot_at)}</p></div>
      <div><p className="font-semibold">Estado del calendario</p><p className="mt-1 break-words text-muted">{datos.calendar_status}</p></div>
    </div>
    {datos.snapshot
      ? <BloqueRegimen titulo="Lectura contextual">
        <p className="max-w-prose whitespace-pre-wrap break-words text-body leading-relaxed">{datos.snapshot.context}</p>
        <p className="text-footnote text-muted">
          Modelo {datos.snapshot.model_version} · {datos.snapshot.mode === "RECONSTRUCCION" ? "Reconstrucción histórica" : "Registro operacional"}
        </p>
        <DetalleHorizontes datos={datos.snapshot} />
      </BloqueRegimen>
      : <Vacio titulo="La historia aún no comenzó" descripcion="No hay un snapshot registrado. Un operador puede iniciar la ingesta y crear el primer corte; los faltantes seguirán visibles." />}
    <BloqueRegimen titulo="Cobertura actual"><Cobertura items={datos.coverage} /></BloqueRegimen>
    {datos.warning && <p className="text-footnote text-muted">{datos.warning}</p>}
  </div>}</ConsultaRegimen>;
}

const SECCIONES = [
  { id: "resumen", texto: "Resumen" }, { id: "evidencia", texto: "Evidencia" },
  { id: "historia", texto: "Historia" }, { id: "informes", texto: "Informes" },
  { id: "preferencias", texto: "Mi suscripción" }, { id: "operacion", texto: "Modelo y operación" },
] as const;
type Seccion = (typeof SECCIONES)[number]["id"];

export function Regimen() {
  const permiso = usePermisoRegimen();
  const [seccion, setSeccion] = useState<Seccion>("resumen");
  if (permiso.cargando) return <Cargando />;
  if (!permiso.permitido) return <Pantalla titulo="Régimen de mercado">
    <Aviso titulo="Acceso no disponible">Necesitas una cuenta activa y un permiso de régimen independiente. Solicítalo a un administrador.</Aviso>
  </Pantalla>;
  return <Pantalla titulo="Régimen de mercado" descripcion="Evidencia, calidad de datos y lecturas independientes por horizonte.">
    <div className="space-y-6">
      <Aviso titulo="Modelo heurístico no validado">
        El score no es probabilidad de ganancias ni una recomendación de inversión. Sin cobertura suficiente, no se publica una clasificación.
      </Aviso>
      <nav aria-label="Vistas de régimen" className="flex flex-wrap gap-2">
        {SECCIONES.map(({ id, texto }) => <Boton key={id}
          tono={seccion === id ? "primario" : "secundario"} aria-pressed={seccion === id}
          onClick={() => setSeccion(id)}>{texto}</Boton>)}
      </nav>
      {seccion === "resumen" && <Resumen />}
      {seccion === "evidencia" && <Evidencia />}
      {seccion === "historia" && <Historia />}
      {seccion === "informes" && <Informes />}
      {seccion === "preferencias" && <Preferencias />}
      {seccion === "operacion" && <Operacion />}
    </div>
  </Pantalla>;
}
