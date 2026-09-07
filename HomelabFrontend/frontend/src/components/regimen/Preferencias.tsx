import { useState } from "react";
import { Link } from "react-router-dom";

import { Boton } from "@/components/Boton";
import { Casilla, Interruptor } from "@/components/Campos";
import { Aviso, EstadoError, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { HORIZONTES_REGIMEN } from "@/lib/etiquetas";
import { mensajeDeError } from "@/lib/errores";
import { fechaRegimen, useEntregasRegimen, useGuardarSuscripcionRegimen, usePermisoRegimen, useSuscripcionRegimen } from "@/lib/regimen";
import type { HorizonteRegimen, SuscripcionRegimen } from "@/lib/tipos";

import { BloqueRegimen, ConsultaRegimen } from "./DatosRegimen";

function FormularioSuscripcion({ datos }: { datos: SuscripcionRegimen }) {
  const guardar = useGuardarSuscripcionRegimen();
  const [enabled, setEnabled] = useState(datos.enabled);
  const [email, setEmail] = useState(datos.email);
  const [whatsapp, setWhatsapp] = useState(datos.whatsapp);
  const [horizontes, setHorizontes] = useState<HorizonteRegimen[]>(datos.horizons);
  const [consentimiento, setConsentimiento] = useState(false);
  const [guardado, setGuardado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const incompleto = enabled && (!consentimiento || (!email && !whatsapp) || !horizontes.length);
  const enviar = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null); setGuardado(false);
    try {
      await guardar.mutateAsync({ enabled, email, whatsapp, horizons: horizontes, accept_consent: consentimiento });
      setGuardado(true);
    } catch (causa) {
      setError(mensajeDeError(causa, "No pudimos guardar tu suscripción."));
    }
  };
  return <form onSubmit={(event) => void enviar(event)} className="space-y-5 rounded-lg border border-line bg-surface p-4">
    <Interruptor etiqueta="Recibir informes semanales" checked={enabled} onChange={(valor) => { setEnabled(valor); setGuardado(false); }}
      disabled={guardar.isPending} descripcion="Esta suscripción es independiente del motor y de tus vigilancias." />
    <fieldset disabled={guardar.isPending} className="space-y-2">
      <legend className="mb-2 text-subhead font-semibold">Mis canales</legend>
      <Casilla checked={email} onChange={setEmail} etiqueta="Correo electrónico" />
      <p className="text-footnote text-muted">Correo: {datos.email_ready ? "Destino listo" : "Destino no configurado o no disponible"}</p>
      <Casilla checked={whatsapp} onChange={setWhatsapp} etiqueta="WhatsApp" />
      <p className="text-footnote text-muted">WhatsApp: {datos.whatsapp_ready ? "Destino listo" : "Destino no configurado o no disponible"}</p>
      <Link to="/ajustes" className="inline-flex min-h-11 items-center text-subhead text-accent underline">Gestionar mis destinos en Ajustes</Link>
    </fieldset>
    <fieldset disabled={guardar.isPending} className="space-y-1">
      <legend className="mb-2 text-subhead font-semibold">Horizontes incluidos</legend>
      {(["SHORT", "MEDIUM", "LONG"] as const).map((h) => <Casilla key={h}
        checked={horizontes.includes(h)} etiqueta={HORIZONTES_REGIMEN[h]}
        onChange={(marcado) => setHorizontes(marcado ? [...horizontes, h] : horizontes.filter((actual) => actual !== h))} />)}
    </fieldset>
    <Casilla checked={consentimiento} onChange={setConsentimiento} disabled={guardar.isPending}
      etiqueta={`Acepto recibir estos informes en mis canales seleccionados (${datos.consent_version ?? "market-regime-v1"}). Puedo darme de baja en cualquier momento.`} />
    {enabled && <p className="text-footnote text-muted">Para activar o actualizar una suscripción activa, selecciona al menos un canal, un horizonte y acepta el consentimiento.</p>}
    {datos.detail && <Aviso>{datos.detail}</Aviso>}
    {error && <EstadoError mensaje={error} />}
    {guardado && <p role="status" className="text-subhead text-ok">Preferencias guardadas.</p>}
    <Boton type="submit" cargando={guardar.isPending} disabled={incompleto}>
      {enabled ? "Guardar suscripción" : "Guardar sin suscripción"}
    </Boton>
    <p className="text-footnote text-muted">Desactivar no requiere aceptar consentimiento. Tus destinos no se muestran a otros usuarios.</p>
  </form>;
}

export function Preferencias() {
  const permiso = usePermisoRegimen();
  const consulta = useSuscripcionRegimen();
  const entregas = useEntregasRegimen();
  return <div className="space-y-8">
    <BloqueRegimen titulo="Mi suscripción">
      <ConsultaRegimen consulta={consulta}>{(datos) =>
        <FormularioSuscripcion key={permiso.id} datos={datos} />}
      </ConsultaRegimen>
    </BloqueRegimen>
    <BloqueRegimen titulo="Mis entregas">
      <ConsultaRegimen consulta={entregas}>{(datos) => datos.items.length
        ? <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {datos.items.map((item) => <li key={item.id} className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-subhead font-semibold">{item.channel === "email" ? "Correo electrónico" : item.channel === "whatsapp" ? "WhatsApp" : item.channel}</span>
              <Insignia>{item.status}</Insignia>
            </div>
            <p className="text-footnote text-muted">{fechaRegimen(item.created_at)} · Intentos: {item.attempts}</p>
            <p className="break-words text-subhead text-muted">{item.detail}</p>
          </li>)}
        </ul> : <Vacio titulo="Sin entregas" descripcion="Aquí aparecerá únicamente el estado de tus envíos. Guardar preferencias no envía un mensaje de prueba." />
      }</ConsultaRegimen>
    </BloqueRegimen>
  </div>;
}
