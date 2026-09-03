/**
 * Inicio.
 *
 * Responde de un vistazo a las tres preguntas con las que uno abre este panel
 * desde el teléfono: ¿está corriendo algo?, ¿lo último salió bien?, ¿cuándo
 * vuelve a correr? Cuando aún no hay nada configurado, la pantalla se convierte
 * en el camino de puesta en marcha en vez de mostrar tarjetas vacías.
 */

import { BloqueApp } from "@/components/BloqueApp";
import { BotonEnlace } from "@/components/Boton";
import { EstadoError, Esqueleto, Vacio } from "@/components/Estados";
import { Lista, FilaValor } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";
import { IconoCampana, IconoPortafolio, IconoVigilancia } from "@/components/iconos";
import { useApps, useNotificaciones, usePortafolio, useSesion, useWatches } from "@/lib/consultas";
import { mensajeDeError } from "@/lib/errores";
import { plural } from "@/lib/formato";

function EsqueletoApp() {
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-5">
      <div className="flex items-center justify-between">
        <Esqueleto className="h-5 w-40" />
        <Esqueleto className="h-5 w-20 rounded-full" />
      </div>
      <Esqueleto className="h-4 w-52" />
      <div className="flex gap-2 pt-1">
        <Esqueleto className="h-11 w-36 rounded-lg" />
        <Esqueleto className="h-11 w-36 rounded-lg" />
      </div>
    </div>
  );
}

export function Inicio() {
  const apps = useApps();
  const watches = useWatches();
  const portafolio = usePortafolio();
  const notificaciones = useNotificaciones();
  const { data: sesion } = useSesion();

  const totalWatches = watches.data?.items.length ?? 0;
  const totalHoldings = portafolio.data?.holdings.length ?? 0;
  const tieneCanal = Boolean(notificaciones.data?.whatsapp || notificaciones.data?.email);

  const cargandoResumen = watches.isPending || portafolio.isPending || notificaciones.isPending;
  const sinConfigurar = !cargandoResumen && totalWatches === 0 && totalHoldings === 0;

  const corriendo = apps.data?.items.filter((app) => app.running) ?? [];
  const descripcion = corriendo.length
    ? `Ahora mismo ${corriendo.length === 1 ? "corre" : "corren"} ${corriendo
        .map((app) => app.display_name)
        .join(" y ")}.`
    : "Todo tranquilo. Aquí ves el estado de tus vigilantes y puedes lanzarlos a mano.";

  return (
    <Pantalla titulo="Inicio" descripcion={descripcion}>
      {sinConfigurar ? (
        <div className="space-y-6">
          <Vacio
            titulo="Pon en marcha tu panel"
            descripcion="Tres pasos y tus vigilantes empiezan a trabajar solos. Puedes hacerlos en cualquier orden."
          />

          <Lista titulo="Primeros pasos">
            <FilaValor
              icono={<IconoCampana className="size-5" />}
              etiqueta="Dinos dónde avisarte"
              descripcion="Un número de WhatsApp o un correo. Sin esto no se envía nada."
              valor={tieneCanal ? "Listo" : undefined}
              href="/ajustes"
            />
            <FilaValor
              icono={<IconoVigilancia className="size-5" />}
              etiqueta="Crea tu primera vigilancia"
              descripcion="Qué producto quieres seguir, en qué talla y hasta qué precio."
              href="/vigilancias"
            />
            <FilaValor
              icono={<IconoPortafolio className="size-5" />}
              etiqueta="Registra tu portafolio"
              descripcion="Tus posiciones y tu perfil de riesgo, para recibir el análisis."
              href="/portafolio"
            />
          </Lista>
        </div>
      ) : (
        <div className="space-y-4">
          {apps.isPending && (
            <>
              <EsqueletoApp />
              <EsqueletoApp />
            </>
          )}

          {apps.isError && (
            <EstadoError
              mensaje={mensajeDeError(apps.error, "No pudimos leer el estado de las apps.")}
              onReintentar={() => void apps.refetch()}
              reintentando={apps.isFetching}
            />
          )}

          {apps.data?.items.map((app) => <BloqueApp key={app.app_name} app={app} />)}

          {apps.data?.items.length === 0 && (
            <Vacio
              titulo="No hay apps registradas"
              descripcion="El servidor no tiene ninguna aplicación configurada en su registro. Habla con un administrador."
            />
          )}

          <Lista
            titulo="Tu configuración"
            nota={
              sesion?.user.timezone
                ? `Los horarios se calculan en ${sesion.user.timezone}.`
                : undefined
            }
          >
            <FilaValor
              etiqueta="Vigilancias"
              valor={plural(totalWatches, "producto", "productos")}
              href="/vigilancias"
            />
            <FilaValor
              etiqueta="Portafolio"
              valor={plural(totalHoldings, "activo", "activos")}
              href="/portafolio"
            />
            <FilaValor
              etiqueta="Notificaciones"
              valor={tieneCanal ? "Configuradas" : "Sin configurar"}
              href="/ajustes"
            />
          </Lista>

          <div className="pt-2">
            <BotonEnlace to="/actividad" tono="sutil" tamano="sm">
              Ver todo el historial
            </BotonEnlace>
          </div>
        </div>
      )}
    </Pantalla>
  );
}
