/**
 * Portafolio de PortfolioWatcher.
 *
 * Tres bloques en el orden en que importan: lo que tienes, lo que cerraste y
 * cómo quieres que se interprete tu riesgo. El costo base se calcula en el
 * servidor y se muestra sin adornos: es un dato, no un titular.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Area, Campo, Selector } from "@/components/Campos";
import { Confirmar } from "@/components/Confirmar";
import { EstadoError, EsqueletoLista, Vacio } from "@/components/Estados";
import { Hoja, PieDeHoja } from "@/components/Hoja";
import { Lista, Fila } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";
import { PanelAutomatizacion } from "@/components/PanelAutomatizacion";
import { IconoMas, IconoPapelera, IconoPortafolio } from "@/components/iconos";
import {
  useActualizarHolding,
  useBorrarHolding,
  useBorrarPosicionCerrada,
  useCrearHolding,
  useCrearPosicionCerrada,
  useGuardarPerfilRiesgo,
  usePortafolio,
} from "@/lib/consultas";
import { aplicarErroresDeApi, mensajeDeError } from "@/lib/errores";
import { HORIZONTE, TOLERANCIA } from "@/lib/etiquetas";
import { dinero, numero } from "@/lib/formato";
import type { Holding, Horizonte, PerfilRiesgo, PosicionCerrada, Tolerancia } from "@/lib/tipos";
import {
  esquemaHolding,
  esquemaPerfilRiesgo,
  esquemaPosicionCerrada,
  type DatosHolding,
  type DatosPerfilRiesgo,
  type DatosPosicionCerrada,
} from "@/lib/validacion";

const HORIZONTES = [
  { valor: "short_term", texto: HORIZONTE.short_term },
  { valor: "medium_term", texto: HORIZONTE.medium_term },
  { valor: "long_term", texto: HORIZONTE.long_term },
] as const;

const TOLERANCIAS = [
  { valor: "conservative", texto: TOLERANCIA.conservative },
  { valor: "moderate", texto: TOLERANCIA.moderate },
  { valor: "aggressive", texto: TOLERANCIA.aggressive },
] as const;

/* --------------------------------------------------------------- holding -- */

function EditorHolding({
  abierta,
  holding,
  onCerrar,
}: {
  abierta: boolean;
  holding: Holding | null;
  onCerrar: () => void;
}) {
  const crear = useCrearHolding();
  const actualizar = useActualizarHolding();
  const avisos = useAvisos();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosHolding>({
    resolver: zodResolver(esquemaHolding),
    defaultValues: { ticker: "", quantity: "", avg_cost: "", sector_hint: "" },
  });

  useEffect(() => {
    if (!abierta) return;
    // La hoja se reutiliza entre posiciones: hay que recargar el formulario
    // al abrirla, y un efecto es el único enganche a esa transición.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setErrorGeneral(null);
    reset(
      holding
        ? {
            ticker: holding.ticker,
            quantity: String(holding.quantity),
            avg_cost: String(holding.avg_cost),
            sector_hint: holding.sector_hint === "unknown" ? "" : holding.sector_hint,
          }
        : { ticker: "", quantity: "", avg_cost: "", sector_hint: "" },
    );
  }, [abierta, holding, reset]);

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    const cuerpo = {
      ticker: datos.ticker.toUpperCase(),
      quantity: Number(datos.quantity.replace(",", ".")),
      avg_cost: Number(datos.avg_cost.replace(",", ".")),
      sector_hint: datos.sector_hint.trim() || "unknown",
    };

    try {
      if (holding) {
        await actualizar.mutateAsync({ id: holding.id, datos: cuerpo });
        avisos.exito(`Actualizamos ${cuerpo.ticker}.`);
      } else {
        await crear.mutateAsync(cuerpo);
        avisos.exito(`Añadimos ${cuerpo.ticker} a tu portafolio.`);
      }
      onCerrar();
    } catch (error) {
      setErrorGeneral(
        aplicarErroresDeApi(error, setError, ["ticker", "quantity", "avg_cost", "sector_hint"]),
      );
    }
  });

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo={holding ? `Editar ${holding.ticker}` : "Añadir activo"}
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton tono="primario" onClick={() => void enviar()} cargando={isSubmitting}>
            Guardar
          </Boton>
        </PieDeHoja>
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-5">
        {errorGeneral && (
          <p role="alert" className="text-subhead text-danger">
            {errorGeneral}
          </p>
        )}

        <Campo
          {...register("ticker")}
          etiqueta="Símbolo"
          placeholder="AAPL"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          error={errors.ticker?.message}
          requerido
          autoFocus={!holding}
        />

        <div className="grid gap-5 sm:grid-cols-2">
          <Campo
            {...register("quantity")}
            etiqueta="Cantidad"
            inputMode="decimal"
            placeholder="12"
            error={errors.quantity?.message}
            requerido
          />
          <Campo
            {...register("avg_cost")}
            etiqueta="Costo promedio"
            inputMode="decimal"
            placeholder="187.40"
            descripcion="Por acción, en la moneda de la posición."
            error={errors.avg_cost?.message}
            requerido
          />
        </div>

        <Campo
          {...register("sector_hint")}
          etiqueta="Sector"
          placeholder="Tecnología"
          descripcion="Opcional. Ayuda al análisis a agrupar tu exposición."
          error={errors.sector_hint?.message}
        />

        <button type="submit" className="sr-only" tabIndex={-1} aria-hidden="true" />
      </form>
    </Hoja>
  );
}

/* ------------------------------------------------------ posición cerrada -- */

function EditorCerrada({ abierta, onCerrar }: { abierta: boolean; onCerrar: () => void }) {
  const crear = useCrearPosicionCerrada();
  const avisos = useAvisos();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosPosicionCerrada>({
    resolver: zodResolver(esquemaPosicionCerrada),
    defaultValues: { ticker: "", note: "" },
  });

  useEffect(() => {
    if (abierta) {
      reset({ ticker: "", note: "" });
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setErrorGeneral(null);
    }
  }, [abierta, reset]);

  const enviar = handleSubmit(async (datos) => {
    try {
      await crear.mutateAsync({ ticker: datos.ticker.toUpperCase(), note: datos.note });
      avisos.exito("Posición cerrada registrada.");
      onCerrar();
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, ["ticker", "note"]));
    }
  });

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo="Registrar posición cerrada"
      descripcion="El análisis la tendrá en cuenta como historial, no como exposición actual."
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton tono="primario" onClick={() => void enviar()} cargando={isSubmitting}>
            Guardar
          </Boton>
        </PieDeHoja>
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-5">
        {errorGeneral && (
          <p role="alert" className="text-subhead text-danger">
            {errorGeneral}
          </p>
        )}
        <Campo
          {...register("ticker")}
          etiqueta="Símbolo"
          placeholder="TSLA"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          error={errors.ticker?.message}
          requerido
          autoFocus
        />
        <Area
          {...register("note")}
          etiqueta="Nota"
          rows={3}
          placeholder="Vendida en marzo tras el rebote."
          descripcion="Opcional. Contexto para ti y para el análisis."
          error={errors.note?.message}
        />
        <button type="submit" className="sr-only" tabIndex={-1} aria-hidden="true" />
      </form>
    </Hoja>
  );
}

/* ---------------------------------------------------------------- perfil -- */

function EditorPerfil({
  abierta,
  perfil,
  onCerrar,
}: {
  abierta: boolean;
  perfil: PerfilRiesgo | undefined;
  onCerrar: () => void;
}) {
  const guardar = useGuardarPerfilRiesgo();
  const avisos = useAvisos();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosPerfilRiesgo>({
    resolver: zodResolver(esquemaPerfilRiesgo),
    defaultValues: {
      horizon: "long_term",
      tolerance: "moderate",
      notes: "",
      analysis_interval_days: "7",
    },
  });

  useEffect(() => {
    if (!abierta || !perfil) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setErrorGeneral(null);
    reset({
      horizon: perfil.horizon as DatosPerfilRiesgo["horizon"],
      tolerance: perfil.tolerance as DatosPerfilRiesgo["tolerance"],
      notes: perfil.notes,
      analysis_interval_days: String(perfil.analysis_interval_days),
    });
  }, [abierta, perfil, reset]);

  const enviar = handleSubmit(async (datos) => {
    try {
      await guardar.mutateAsync({
        horizon: datos.horizon,
        tolerance: datos.tolerance,
        notes: datos.notes,
        analysis_interval_days: Number(datos.analysis_interval_days),
      });
      avisos.exito("Perfil de riesgo actualizado.");
      onCerrar();
    } catch (error) {
      setErrorGeneral(
        aplicarErroresDeApi(error, setError, [
          "horizon",
          "tolerance",
          "notes",
          "analysis_interval_days",
        ]),
      );
    }
  });

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo="Perfil de riesgo"
      descripcion="Orienta el tono del análisis: qué tanto te preocupa la volatilidad y a cuánto plazo inviertes."
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton tono="primario" onClick={() => void enviar()} cargando={isSubmitting}>
            Guardar
          </Boton>
        </PieDeHoja>
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-5">
        {errorGeneral && (
          <p role="alert" className="text-subhead text-danger">
            {errorGeneral}
          </p>
        )}

        <Selector
          {...register("horizon")}
          etiqueta="Horizonte"
          opciones={HORIZONTES}
          error={errors.horizon?.message}
        />
        <Selector
          {...register("tolerance")}
          etiqueta="Tolerancia al riesgo"
          opciones={TOLERANCIAS}
          error={errors.tolerance?.message}
        />
        <Campo
          {...register("analysis_interval_days")}
          etiqueta="Días entre análisis"
          inputMode="numeric"
          descripcion="Cuántos días de historial considera cada informe."
          error={errors.analysis_interval_days?.message}
        />
        <Area
          {...register("notes")}
          etiqueta="Notas"
          rows={4}
          placeholder="Prefiero dividendos y evito cripto."
          descripcion="Opcional. Cualquier preferencia que el análisis deba respetar."
          error={errors.notes?.message}
        />
        <button type="submit" className="sr-only" tabIndex={-1} aria-hidden="true" />
      </form>
    </Hoja>
  );
}

/* -------------------------------------------------------------- pantalla -- */

export function Portafolio() {
  const portafolio = usePortafolio();
  const borrarHolding = useBorrarHolding();
  const borrarCerrada = useBorrarPosicionCerrada();
  const avisos = useAvisos();

  const [holdingEditando, setHoldingEditando] = useState<Holding | null>(null);
  const [hojaHolding, setHojaHolding] = useState(false);
  const [hojaCerrada, setHojaCerrada] = useState(false);
  const [hojaPerfil, setHojaPerfil] = useState(false);
  const [porBorrar, setPorBorrar] = useState<Holding | null>(null);

  const holdings = portafolio.data?.holdings ?? [];
  const cerradas = portafolio.data?.closed_positions ?? [];
  const perfil = portafolio.data?.profile;

  const abrirNuevo = () => {
    setHoldingEditando(null);
    setHojaHolding(true);
  };

  const confirmarBorrado = async () => {
    if (!porBorrar) return;
    try {
      await borrarHolding.mutateAsync(porBorrar.id);
      avisos.exito(`Eliminamos ${porBorrar.ticker}.`);
      setPorBorrar(null);
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos eliminar la posición."));
    }
  };

  const quitarCerrada = async (posicion: PosicionCerrada) => {
    try {
      await borrarCerrada.mutateAsync(posicion.id);
      avisos.exito(`Quitamos ${posicion.ticker} del historial.`);
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos quitar la posición."));
    }
  };

  return (
    <Pantalla
      titulo="Portafolio"
      descripcion="Tus posiciones y tu perfil de riesgo alimentan el análisis de PortfolioWatcher."
      acciones={
        holdings.length > 0 ? (
          <Boton
            tono="primario"
            tamano="sm"
            onClick={abrirNuevo}
            icono={<IconoMas className="size-4" />}
          >
            Añadir
          </Boton>
        ) : undefined
      }
    >
      {portafolio.isPending && <EsqueletoLista filas={4} />}

      {portafolio.isError && (
        <EstadoError
          mensaje={mensajeDeError(portafolio.error, "No pudimos cargar tu portafolio.")}
          onReintentar={() => void portafolio.refetch()}
          reintentando={portafolio.isFetching}
        />
      )}

      {portafolio.isSuccess && holdings.length === 0 && (
        <Vacio
          icono={<IconoPortafolio className="size-8" />}
          titulo="Tu portafolio está vacío"
          descripcion="Añade tus posiciones para recibir el análisis periódico con el contexto de lo que realmente tienes."
          accion={
            <Boton tono="primario" onClick={abrirNuevo} icono={<IconoMas className="size-4" />}>
              Añadir activo
            </Boton>
          }
        />
      )}

      {holdings.length > 0 && (
        <Lista
          titulo="Posiciones"
          nota={
            <>
              Costo base total:{" "}
              <span className="tabular text-fg">{dinero(portafolio.data?.cost_basis_total ?? 0)}</span>
            </>
          }
        >
          {holdings.map((holding) => (
            <Fila key={holding.id} className="flex items-center gap-3 py-2.5">
              <button
                type="button"
                onClick={() => {
                  setHoldingEditando(holding);
                  setHojaHolding(true);
                }}
                className="flex min-h-11 min-w-0 flex-1 items-center gap-3 text-left"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-semibold">{holding.ticker}</span>
                  <span className="block text-footnote text-muted">
                    {numero(holding.quantity)} × {dinero(holding.avg_cost)}
                    {holding.sector_hint !== "unknown" && ` · ${holding.sector_hint}`}
                  </span>
                </span>
                <span className="tabular shrink-0 text-body text-muted">
                  {dinero(holding.cost_basis)}
                </span>
              </button>

              <Boton
                tono="sutil"
                tamano="sm"
                onClick={() => setPorBorrar(holding)}
                aria-label={`Eliminar ${holding.ticker}`}
                icono={<IconoPapelera className="size-4" />}
              />
            </Fila>
          ))}
        </Lista>
      )}

      {portafolio.isSuccess && (
        <Lista
          titulo="Posiciones cerradas"
          nota="Se conservan como historial: el análisis sabe que ya no las tienes."
          accion={
            <button
              type="button"
              onClick={() => setHojaCerrada(true)}
              className="text-subhead font-medium text-accent hover:underline"
            >
              Registrar
            </button>
          }
        >
          {cerradas.length === 0 ? (
            <Fila className="text-subhead text-muted">Todavía no registraste ninguna.</Fila>
          ) : (
            cerradas.map((posicion) => (
              <Fila key={posicion.id} className="flex items-center gap-3">
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-medium">{posicion.ticker}</span>
                  {posicion.note && (
                    <span className="block text-footnote text-muted">{posicion.note}</span>
                  )}
                </span>
                <Boton
                  tono="sutil"
                  tamano="sm"
                  onClick={() => void quitarCerrada(posicion)}
                  aria-label={`Quitar ${posicion.ticker} del historial`}
                  icono={<IconoPapelera className="size-4" />}
                />
              </Fila>
            ))
          )}
        </Lista>
      )}

      {perfil && (
        <Lista
          titulo="Perfil de riesgo"
          accion={
            <button
              type="button"
              onClick={() => setHojaPerfil(true)}
              className="text-subhead font-medium text-accent hover:underline"
            >
              Editar
            </button>
          }
        >
          <Fila className="flex items-center justify-between gap-3">
            <span className="text-body">Horizonte</span>
            <span className="text-body text-muted">{HORIZONTE[perfil.horizon as Horizonte]}</span>
          </Fila>
          <Fila className="flex items-center justify-between gap-3">
            <span className="text-body">Tolerancia</span>
            <span className="text-body text-muted">{TOLERANCIA[perfil.tolerance as Tolerancia]}</span>
          </Fila>
          <Fila className="flex items-center justify-between gap-3">
            <span className="text-body">Días entre análisis</span>
            <span className="tabular text-body text-muted">{perfil.analysis_interval_days}</span>
          </Fila>
          {perfil.notes && (
            <Fila>
              <p className="text-subhead text-muted">{perfil.notes}</p>
            </Fila>
          )}
        </Lista>
      )}

      {holdings.length > 0 && <PanelAutomatizacion app="portfoliowatcher" />}

      <EditorHolding
        abierta={hojaHolding}
        holding={holdingEditando}
        onCerrar={() => setHojaHolding(false)}
      />
      <EditorCerrada abierta={hojaCerrada} onCerrar={() => setHojaCerrada(false)} />
      <EditorPerfil abierta={hojaPerfil} perfil={perfil} onCerrar={() => setHojaPerfil(false)} />

      <Confirmar
        abierta={porBorrar !== null}
        titulo="¿Eliminar esta posición?"
        descripcion={
          porBorrar
            ? `${porBorrar.ticker} dejará de contar en tu portafolio. Esta acción no se puede deshacer.`
            : ""
        }
        textoConfirmar="Eliminar"
        cargando={borrarHolding.isPending}
        onConfirmar={() => void confirmarBorrado()}
        onCerrar={() => setPorBorrar(null)}
      />
    </Pantalla>
  );
}
