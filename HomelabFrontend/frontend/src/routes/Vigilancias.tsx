/**
 * Vigilancias de StockWatcher.
 *
 * Una vigilancia es una frase: «avísame de X, en tallas Y, por debajo de Z».
 * La tarjeta la muestra así, en lenguaje natural, en vez de repetir los
 * nombres de los campos del formulario.
 */

import { useState } from "react";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Confirmar } from "@/components/Confirmar";
import { EditorWatch } from "@/components/EditorWatch";
import { EstadoError, EsqueletoLista, Vacio } from "@/components/Estados";
import { Insignia } from "@/components/Insignia";
import { Interruptor } from "@/components/Campos";
import { Pantalla } from "@/components/Pantalla";
import { PanelAutomatizacion } from "@/components/PanelAutomatizacion";
import { IconoEditar, IconoMas, IconoPapelera, IconoVigilancia } from "@/components/iconos";
import { useActualizarWatch, useBorrarWatch, useNotificaciones, useWatches } from "@/lib/consultas";
import { mensajeDeError } from "@/lib/errores";
import { CANAL, GENERO } from "@/lib/etiquetas";
import { enumerar } from "@/lib/formato";
import type { Canal, Genero, Watch } from "@/lib/tipos";

/** Resume la vigilancia en una frase legible. */
function resumen(watch: Watch): string {
  const partes: string[] = [];

  if (watch.variants.length > 0) {
    partes.push(`tallas ${enumerar(watch.variants)}`);
  }
  if (watch.colors.length > 0) {
    partes.push(`en ${enumerar(watch.colors)}`);
  }
  if (watch.max_price) {
    partes.push(`hasta ${watch.max_price} ${watch.currency}`);
  }
  if (watch.gender !== "unisex") {
    partes.push(GENERO[watch.gender as Genero].toLowerCase());
  }
  if (watch.countries.length > 0) {
    partes.push(`en ${watch.countries.join(", ")}`);
  }

  return partes.length > 0 ? partes.join(" · ") : "Cualquier talla, color y precio.";
}

function TarjetaWatch({
  watch,
  onEditar,
  onBorrar,
}: {
  watch: Watch;
  onEditar: () => void;
  onBorrar: () => void;
}) {
  const actualizar = useActualizarWatch();
  const avisos = useAvisos();

  const alternar = async (activa: boolean) => {
    try {
      await actualizar.mutateAsync({
        id: watch.id,
        datos: {
          name: watch.name,
          enabled: activa,
          match_terms: watch.match_terms,
          exclude_terms: watch.exclude_terms,
          variants: watch.variants,
          colors: watch.colors,
          countries: watch.countries,
          gender: watch.gender,
          max_price: watch.max_price,
          currency: watch.currency,
          notify_channels: watch.notify_channels,
        },
      });
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos cambiar el estado de la vigilancia."));
    }
  };

  return (
    <article className="rounded-lg border border-line bg-surface p-4 shadow-e1">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-body font-semibold">{watch.name}</h3>
          <p className="mt-0.5 text-subhead text-muted">{enumerar(watch.match_terms)}</p>
        </div>
        {!watch.enabled && <Insignia tono="neutro">En pausa</Insignia>}
      </div>

      <p className="mt-2 text-footnote text-muted">{resumen(watch)}</p>

      {watch.exclude_terms.length > 0 && (
        <p className="mt-1 text-footnote text-muted">
          Descarta: <span className="text-fg/80">{enumerar(watch.exclude_terms)}</span>
        </p>
      )}

      {watch.notify_channels.length > 0 && (
        <p className="mt-1 text-footnote text-muted">
          Avisa por {enumerar(watch.notify_channels.map((canal) => CANAL[canal as Canal] ?? canal))}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-3">
        <Interruptor
          checked={watch.enabled}
          onChange={(valor) => void alternar(valor)}
          etiqueta="Activa"
          disabled={actualizar.isPending}
        />

        <div className="flex gap-1">
          <Boton
            tono="sutil"
            tamano="sm"
            onClick={onEditar}
            icono={<IconoEditar className="size-4" />}
            aria-label={`Editar ${watch.name}`}
          >
            Editar
          </Boton>
          <Boton
            tono="sutil"
            tamano="sm"
            onClick={onBorrar}
            icono={<IconoPapelera className="size-4" />}
            aria-label={`Eliminar ${watch.name}`}
          />
        </div>
      </div>
    </article>
  );
}

export function Vigilancias() {
  const watches = useWatches();
  const notificaciones = useNotificaciones();
  const borrar = useBorrarWatch();
  const avisos = useAvisos();

  const [editando, setEditando] = useState<Watch | null>(null);
  const [hojaAbierta, setHojaAbierta] = useState(false);
  const [porBorrar, setPorBorrar] = useState<Watch | null>(null);

  const canalesDisponibles = (notificaciones.data?.supported?.stockwatcher ?? []) as Canal[];
  const items = watches.data?.items ?? [];
  const limite = watches.data?.limit ?? 0;
  const alLimite = limite > 0 && items.length >= limite;

  const abrirNueva = () => {
    setEditando(null);
    setHojaAbierta(true);
  };

  const confirmarBorrado = async () => {
    if (!porBorrar) return;
    try {
      await borrar.mutateAsync(porBorrar.id);
      avisos.exito(`Eliminamos «${porBorrar.name}».`);
      setPorBorrar(null);
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos eliminar la vigilancia."));
    }
  };

  return (
    <Pantalla
      titulo="Vigilancias"
      descripcion="Los productos que StockWatcher busca por ti en las tiendas configuradas."
      acciones={
        items.length > 0 ? (
          <Boton
            tono="primario"
            tamano="sm"
            onClick={abrirNueva}
            disabled={alLimite}
            icono={<IconoMas className="size-4" />}
          >
            Nueva
          </Boton>
        ) : undefined
      }
    >
      {watches.isPending && <EsqueletoLista filas={3} />}

      {watches.isError && (
        <EstadoError
          mensaje={mensajeDeError(watches.error, "No pudimos cargar tus vigilancias.")}
          onReintentar={() => void watches.refetch()}
          reintentando={watches.isFetching}
        />
      )}

      {watches.isSuccess && items.length === 0 && (
        <Vacio
          icono={<IconoVigilancia className="size-8" />}
          titulo="Aún no vigilas nada"
          descripcion="Crea tu primera vigilancia con el producto que buscas, las tallas que te sirven y el precio máximo que pagarías."
          accion={
            <Boton tono="primario" onClick={abrirNueva} icono={<IconoMas className="size-4" />}>
              Crear vigilancia
            </Boton>
          }
        />
      )}

      {items.length > 0 && (
        <div className="space-y-3">
          {items.map((watch) => (
            <TarjetaWatch
              key={watch.id}
              watch={watch}
              onEditar={() => {
                setEditando(watch);
                setHojaAbierta(true);
              }}
              onBorrar={() => setPorBorrar(watch)}
            />
          ))}
        </div>
      )}

      {alLimite && (
        <p className="text-footnote text-muted">
          Llegaste al máximo de {limite} vigilancias. Elimina alguna para crear otra.
        </p>
      )}

      {items.length > 0 && <PanelAutomatizacion app="stockwatcher" />}

      <EditorWatch
        abierta={hojaAbierta}
        watch={editando}
        canalesDisponibles={canalesDisponibles}
        onCerrar={() => setHojaAbierta(false)}
        onGuardado={(mensaje) => avisos.exito(mensaje)}
      />

      <Confirmar
        abierta={porBorrar !== null}
        titulo="¿Eliminar esta vigilancia?"
        descripcion={
          porBorrar
            ? `«${porBorrar.name}» dejará de buscarse. Esta acción no se puede deshacer.`
            : ""
        }
        textoConfirmar="Eliminar"
        cargando={borrar.isPending}
        onConfirmar={() => void confirmarBorrado()}
        onCerrar={() => setPorBorrar(null)}
      />
    </Pantalla>
  );
}
