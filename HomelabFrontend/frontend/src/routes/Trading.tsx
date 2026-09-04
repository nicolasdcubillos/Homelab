/**
 * Trading simulado.
 *
 * Esta pantalla se sale de la regla del resto de la app: aquí no hay datos por
 * usuario. Hay **un** bot por motor, compartido, y lo que uno enciende lo ven
 * todos. Eso obliga a dos cosas que las demás pantallas no necesitan.
 *
 * La primera es decir siempre quién tocó qué y cuándo: sin esa línea, una
 * configuración que cambió sola es indistinguible de un error. La segunda es
 * asumir que el estado puede cambiar mientras lo miras, así que el guardado
 * viaja con la versión que se leyó y el servidor rechaza lo que llegue tarde.
 *
 * El aviso de que todo es simulado es permanente y no se puede descartar. No
 * es decorativo: es la única pantalla de la app donde alguien podría creer que
 * está moviendo dinero de verdad.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Campo, Interruptor, Selector } from "@/components/Campos";
import { Aviso, EstadoError, EsqueletoLista, Vacio } from "@/components/Estados";
import { Hoja, PieDeHoja } from "@/components/Hoja";
import { Insignia, type Tono } from "@/components/Insignia";
import { Fila, FilaValor, Lista } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";
import { IconoTrading } from "@/components/iconos";
import {
  useBotsTrading,
  useGuardarConfigTrading,
  useInterruptorTrading,
  useOperacionesTrading,
  useRendimientoTrading,
} from "@/lib/consultas";
import { aplicarErroresDeApi, mensajeDeError } from "@/lib/errores";
import { LADO_OPERACION, etiqueta } from "@/lib/etiquetas";
import { dinero, fechaHora, numero, plural, relativo } from "@/lib/formato";
import type {
  BotTrading,
  ConfigTradingEntrada,
  NivelTrading,
  OperacionTrading,
  RendimientoTrading,
} from "@/lib/tipos";
import {
  esquemaConfigTrading,
  separarInstrumentos,
  type DatosConfigTrading,
} from "@/lib/validacion";

const CAMPOS_CONFIG = [
  "instrumentos",
  "estrategia",
  "timeframe",
  "capital_simulado",
  "max_posiciones_abiertas",
  "stop_loss_pct",
  "take_profit_pct",
  "max_perdida_diaria_pct",
] as const;

/** Los porcentajes se muestran con el signo delante: el `+` es información. */
function porcentaje(valor: number | null | undefined, conSigno = false): string {
  if (valor === null || valor === undefined) return "—";
  const signo = conSigno && valor > 0 ? "+" : "";
  return `${signo}${numero(valor)} %`;
}

function aNumero(texto: string): number {
  return Number(texto.replace(",", "."));
}

/**
 * Estado legible de un motor.
 *
 * «Encendido» y «operando» no son lo mismo y confundirlos es el peor fallo
 * posible en este panel: alguien podría creer que su bot está trabajando
 * cuando en realidad el proceso está caído. Por eso hay un estado intermedio
 * explícito para «lo pedimos, pero el motor no lo confirma».
 */
function estadoDeBot(bot: BotTrading): { tono: Tono; texto: string; latiendo: boolean } {
  if (!bot.estado.alcanzable) return { tono: "alerta", texto: "Sin respuesta", latiendo: false };
  if (bot.estado.corriendo) return { tono: "activo", texto: "Operando", latiendo: true };
  if (bot.enabled) return { tono: "aviso", texto: "Encendido, sin confirmar", latiendo: false };
  return { tono: "neutro", texto: "Apagado", latiendo: false };
}

/* --------------------------------------------------------- configuración -- */

function EditorConfig({
  abierta,
  bot,
  soloLectura,
  onCerrar,
}: {
  abierta: boolean;
  bot: BotTrading;
  soloLectura: boolean;
  onCerrar: () => void;
}) {
  const guardar = useGuardarConfigTrading();
  const avisos = useAvisos();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const { motor, config } = bot;

  const valores = (): DatosConfigTrading => ({
    instrumentos: config.instrumentos.join(", "),
    estrategia: config.estrategia,
    timeframe: config.timeframe,
    capital_simulado: String(config.capital_simulado),
    max_posiciones_abiertas: String(config.max_posiciones_abiertas),
    stop_loss_pct: String(config.stop_loss_pct),
    take_profit_pct: String(config.take_profit_pct),
    max_perdida_diaria_pct: String(config.max_perdida_diaria_pct),
  });

  const {
    register,
    handleSubmit,
    reset,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<DatosConfigTrading>({
    resolver: zodResolver(
      esquemaConfigTrading({
        maxInstrumentos: motor.max_instrumentos,
        timeframes: motor.timeframes,
        estrategias: motor.estrategias.map((e) => e.nombre),
      }),
    ),
    defaultValues: valores(),
  });

  useEffect(() => {
    if (!abierta) return;
    // Al abrir hay que releer: puede que otro operador haya guardado mientras
    // esta pestaña estaba en otra sección.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setErrorGeneral(null);
    reset(valores());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierta, bot.version, reset]);

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    const cuerpo: ConfigTradingEntrada = {
      instrumentos: separarInstrumentos(datos.instrumentos),
      estrategia: datos.estrategia.trim(),
      timeframe: datos.timeframe,
      capital_simulado: aNumero(datos.capital_simulado),
      max_posiciones_abiertas: Number(datos.max_posiciones_abiertas),
      stop_loss_pct: aNumero(datos.stop_loss_pct),
      take_profit_pct: aNumero(datos.take_profit_pct),
      max_perdida_diaria_pct: aNumero(datos.max_perdida_diaria_pct),
      version: bot.version,
    };

    try {
      await guardar.mutateAsync({ bot: motor.bot_name, datos: cuerpo });
      avisos.exito(`Guardamos la configuración de ${motor.display_name}.`);
      onCerrar();
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, [...CAMPOS_CONFIG]));
    }
  });

  const opcionesTimeframe = motor.timeframes.map((t) => ({ valor: t, texto: t }));

  // Un motor con catálogo cerrado se ofrece como lista; uno sin él (Freqtrade,
  // cuyas estrategias son archivos en la VM) sigue pidiendo el nombre a mano.
  // Escribir «cruce_medias» sin una errata desde el celular no es razonable.
  const catalogo = motor.estrategias;
  const opcionesEstrategia = [
    { valor: "", texto: "La que trae por defecto" },
    ...catalogo.map((e) => ({ valor: e.nombre, texto: e.etiqueta })),
  ];
  // `useWatch` y no `watch()`: este último devuelve una función que el React
  // Compiler no puede memoizar, y basta usarlo para que deje de optimizar el
  // componente entero.
  const estrategiaElegida = useWatch({ control, name: "estrategia" });
  const descripcionEstrategia =
    catalogo.find((e) => e.nombre === estrategiaElegida)?.descripcion ??
    "El motor decide con la estrategia que traiga configurada.";

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo={`Configurar ${motor.display_name}`}
      descripcion={
        soloLectura
          ? "Tienes acceso de solo lectura: puedes revisar la configuración, pero no cambiarla."
          : `Esta configuración es compartida: la verán y podrán editarla todos los operadores.`
      }
      pie={
        soloLectura ? (
          <PieDeHoja>
            <Boton tono="sutil" onClick={onCerrar}>
              Cerrar
            </Boton>
          </PieDeHoja>
        ) : (
          <PieDeHoja>
            <Boton tono="sutil" onClick={onCerrar}>
              Cancelar
            </Boton>
            <Boton tono="primario" onClick={enviar} cargando={isSubmitting}>
              Guardar
            </Boton>
          </PieDeHoja>
        )
      }
    >
      <div className="space-y-4">
        {errorGeneral && <Aviso tono="alerta">{errorGeneral}</Aviso>}

        <Campo
          {...register("instrumentos")}
          etiqueta={motor.termino_plural.charAt(0).toUpperCase() + motor.termino_plural.slice(1)}
          descripcion={`Separa con comas. Máximo ${motor.max_instrumentos}. Por ejemplo: ${motor.ejemplo_instrumento}`}
          error={errors.instrumentos?.message}
          disabled={soloLectura}
          autoCapitalize="characters"
          spellCheck={false}
        />

        {catalogo.length > 0 ? (
          <Selector
            {...register("estrategia")}
            etiqueta="Estrategia"
            descripcion={descripcionEstrategia}
            opciones={opcionesEstrategia}
            error={errors.estrategia?.message}
            disabled={soloLectura}
          />
        ) : (
          <Campo
            {...register("estrategia")}
            etiqueta="Estrategia"
            descripcion="Nombre de la estrategia en el motor. Déjalo vacío para usar la que trae por defecto."
            error={errors.estrategia?.message}
            disabled={soloLectura}
            spellCheck={false}
          />
        )}
        <Selector
          {...register("timeframe")}
          etiqueta="Marco temporal"
          descripcion="Cada cuánto evalúa el mercado. Más corto es más reactivo y más ruidoso."
          opciones={opcionesTimeframe}
          error={errors.timeframe?.message}
          disabled={soloLectura}
        />

        <Campo
          {...register("capital_simulado")}
          etiqueta="Capital simulado"
          descripcion="Dinero ficticio con el que arranca la simulación."
          error={errors.capital_simulado?.message}
          disabled={soloLectura}
          inputMode="decimal"
        />

        <Campo
          {...register("max_posiciones_abiertas")}
          etiqueta="Posiciones abiertas a la vez"
          descripcion={`Entre 1 y ${motor.max_instrumentos}.`}
          error={errors.max_posiciones_abiertas?.message}
          disabled={soloLectura}
          inputMode="numeric"
        />

        <Campo
          {...register("stop_loss_pct")}
          etiqueta="Stop loss"
          descripcion="Pérdida máxima por operación antes de cerrarla."
          error={errors.stop_loss_pct?.message}
          disabled={soloLectura}
          inputMode="decimal"
          sufijo="%"
        />

        <Campo
          {...register("take_profit_pct")}
          etiqueta="Take profit"
          descripcion="Ganancia a la que se cierra la operación."
          error={errors.take_profit_pct?.message}
          disabled={soloLectura}
          inputMode="decimal"
          sufijo="%"
        />

        <Campo
          {...register("max_perdida_diaria_pct")}
          etiqueta="Freno de pérdida diaria"
          descripcion="Si el día acumula esta pérdida, el bot deja de abrir posiciones. No puede ser menor que el stop loss."
          error={errors.max_perdida_diaria_pct?.message}
          disabled={soloLectura}
          inputMode="decimal"
          sufijo="%"
        />
      </div>
    </Hoja>
  );
}

/* ------------------------------------------------------------- resultados -- */

function ResumenRendimiento({ datos }: { datos: RendimientoTrading }) {
  if (!datos.disponible) {
    return (
      <Aviso tono="aviso">
        No pudimos consultar los resultados del motor. Lo que ves puede estar desactualizado.
      </Aviso>
    );
  }

  return (
    <Lista titulo="Resultados">
      <FilaValor
        etiqueta="Resultado"
        valor={`${datos.pnl_absoluto >= 0 ? "+" : ""}${dinero(datos.pnl_absoluto)}`}
        descripcion={`${porcentaje(datos.pnl_pct, true)} sobre ${dinero(datos.capital_inicial)}`}
      />
      <FilaValor etiqueta="Capital actual" valor={dinero(datos.capital_actual)} />
      <FilaValor
        etiqueta="Aciertos"
        valor={porcentaje(datos.win_rate)}
        descripcion={`${datos.ganadoras} ganadoras y ${datos.perdedoras} perdedoras de ${plural(
          datos.operaciones_cerradas,
          "operación cerrada",
          "operaciones cerradas",
        )}`}
      />
      <FilaValor
        etiqueta="Mejor y peor"
        valor={`${porcentaje(datos.mejor_pct, true)} / ${porcentaje(datos.peor_pct, true)}`}
      />
      <FilaValor
        etiqueta="Costos simulados"
        valor={dinero(datos.costos_simulados)}
        descripcion="Comisiones y deslizamiento estimados. Ya están descontados del resultado."
      />
    </Lista>
  );
}

function FilaOperacion({ operacion }: { operacion: OperacionTrading }) {
  const cerrada = !operacion.abierta;
  const ganancia = (operacion.pnl_absoluto ?? 0) >= 0;

  return (
    <Fila>
      <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-body font-medium">{operacion.instrumento}</p>
          <p className="text-footnote text-muted">
            {etiqueta(LADO_OPERACION, operacion.lado)} · {numero(operacion.cantidad)} ·{" "}
            {dinero(operacion.precio_entrada)}
            {cerrada && operacion.precio_salida !== null
              ? ` → ${dinero(operacion.precio_salida)}`
              : ""}
          </p>
          <p className="text-caption text-faint">
            {cerrada
              ? `Cerrada ${relativo(operacion.cerrada_en)}`
              : `Abierta ${relativo(operacion.abierta_en)}`}
          </p>
        </div>
        <div className="shrink-0 text-right">
          {cerrada ? (
            <>
              <p
                className={`text-body font-semibold tabular-nums ${
                  ganancia ? "text-ok" : "text-danger"
                }`}
              >
                {ganancia ? "+" : ""}
                {dinero(operacion.pnl_absoluto ?? 0)}
              </p>
              <p className="text-footnote text-muted tabular-nums">
                {porcentaje(operacion.pnl_pct, true)}
              </p>
            </>
          ) : (
            <Insignia tono="activo" latiendo>
              Abierta
            </Insignia>
          )}
        </div>
      </div>
    </Fila>
  );
}

function DetalleBot({
  abierta,
  bot,
  onCerrar,
}: {
  abierta: boolean;
  bot: BotTrading;
  onCerrar: () => void;
}) {
  const nombre = bot.motor.bot_name;
  const rendimiento = useRendimientoTrading(nombre, abierta);
  const operaciones = useOperacionesTrading(nombre, abierta);

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo={bot.motor.display_name}
      descripcion={`Simulación contra ${bot.motor.simula_contra}. Ninguna de estas operaciones existe fuera del panel.`}
      tamano="lg"
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cerrar
          </Boton>
        </PieDeHoja>
      }
    >
      <div className="space-y-6">
        {rendimiento.isPending && <EsqueletoLista filas={4} />}
        {rendimiento.isError && (
          <EstadoError
            titulo="No pudimos cargar los resultados"
            mensaje={mensajeDeError(rendimiento.error, "Inténtalo de nuevo en un momento.")}
            onReintentar={() => void rendimiento.refetch()}
          />
        )}
        {rendimiento.data && <ResumenRendimiento datos={rendimiento.data} />}

        {operaciones.isPending && <EsqueletoLista filas={3} />}
        {operaciones.data && !operaciones.data.disponible && (
          <Aviso tono="aviso">
            El motor no respondió a la consulta de operaciones. Vuelve a intentarlo cuando esté en
            marcha.
          </Aviso>
        )}
        {operaciones.data?.disponible && (
          <Lista
            titulo="Operaciones"
            nota={
              operaciones.data.items.length > 0
                ? `Las ${operaciones.data.items.length} más recientes.`
                : undefined
            }
          >
            {operaciones.data.items.length === 0 ? (
              <Vacio
                titulo="Todavía no hay operaciones"
                descripcion="En cuanto el bot encuentre una oportunidad según su estrategia, aparecerá aquí."
                icono={<IconoTrading className="size-6" />}
              />
            ) : (
              operaciones.data.items.map((operacion, indice) => (
                <FilaOperacion
                  key={`${operacion.instrumento}-${operacion.abierta_en ?? indice}`}
                  operacion={operacion}
                />
              ))
            )}
          </Lista>
        )}
      </div>
    </Hoja>
  );
}

/* --------------------------------------------------------------- un motor -- */

function TarjetaBot({ bot, nivel }: { bot: BotTrading; nivel: NivelTrading }) {
  const interruptor = useInterruptorTrading();
  const avisos = useAvisos();
  const [config, setConfig] = useState(false);
  const [detalle, setDetalle] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { motor } = bot;
  const puedeOperar = nivel === "operator";
  const estado = estadoDeBot(bot);
  const sinInstrumentos = bot.config.instrumentos.length === 0;

  const cambiar = async (encendido: boolean) => {
    setError(null);
    try {
      const actualizado = await interruptor.mutateAsync({
        bot: motor.bot_name,
        enabled: encendido,
        version: bot.version,
      });
      if (encendido && !actualizado.estado.alcanzable) {
        // La intención quedó guardada aunque el motor no respondiera: decirlo
        // es más útil que fingir que todo salió bien.
        avisos.exito(`Encendimos ${motor.display_name}, pero aún no responde.`);
      } else {
        avisos.exito(
          encendido ? `${motor.display_name} está encendido.` : `${motor.display_name} está apagado.`,
        );
      }
    } catch (excepcion) {
      setError(mensajeDeError(excepcion, "No pudimos cambiar el estado del bot."));
    }
  };

  return (
    <>
      <Lista
        titulo={motor.display_name}
        nota={`${motor.clase_activo} · simula contra ${motor.simula_contra}`}
        accion={<Insignia tono={estado.tono} latiendo={estado.latiendo}>{estado.texto}</Insignia>}
      >
        {error && (
          <Fila>
            <Aviso tono="alerta" className="w-full">
              {error}
            </Aviso>
          </Fila>
        )}

        {puedeOperar ? (
          <Fila>
            <Interruptor
              checked={bot.enabled}
              onChange={(valor) => void cambiar(valor)}
              etiqueta="Bot encendido"
              descripcion={
                sinInstrumentos && !bot.enabled
                  ? `Añade al menos un ${motor.termino_singular} antes de encenderlo.`
                  : bot.estado.detalle
              }
              disabled={interruptor.isPending || (sinInstrumentos && !bot.enabled)}
            />
          </Fila>
        ) : (
          <FilaValor
            etiqueta="Bot encendido"
            valor={bot.enabled ? "Sí" : "No"}
            descripcion={bot.estado.detalle}
          />
        )}

        <FilaValor
          etiqueta="Configuración"
          valor={`${bot.config.instrumentos.length}/${motor.max_instrumentos} · ${bot.config.timeframe}`}
          descripcion={
            sinInstrumentos
              ? `Sin ${motor.termino_plural}`
              : bot.config.instrumentos.join(", ")
          }
          onClick={() => setConfig(true)}
        />

        <FilaValor
          etiqueta="Resultados y operaciones"
          valor={
            bot.estado.posiciones_abiertas > 0
              ? plural(bot.estado.posiciones_abiertas, "posición abierta", "posiciones abiertas")
              : "Ver"
          }
          descripcion="Rendimiento simulado y últimas operaciones."
          onClick={() => setDetalle(true)}
        />

        <FilaValor
          etiqueta="Última edición"
          valor={bot.updated_at ? relativo(bot.updated_at) : "Sin cambios"}
          descripcion={
            bot.updated_at
              ? `${bot.updated_by_email || "Alguien"} · ${fechaHora(bot.updated_at)}`
              : "Nadie ha tocado esta configuración todavía."
          }
        />
      </Lista>

      <EditorConfig
        abierta={config}
        bot={bot}
        soloLectura={!puedeOperar}
        onCerrar={() => setConfig(false)}
      />
      <DetalleBot abierta={detalle} bot={bot} onCerrar={() => setDetalle(false)} />
    </>
  );
}

/* -------------------------------------------------------------- pantalla -- */

export function Trading() {
  const { data, isPending, isError, error, refetch } = useBotsTrading();

  return (
    <Pantalla
      titulo="Trading"
      descripcion="Bots de trading simulado, compartidos entre todos los operadores."
    >
      <div className="space-y-6">
        <Aviso tono="info" titulo="Todo esto es simulado">
          Los bots operan con dinero ficticio contra precios reales. No hay ninguna cuenta con
          fondos conectada y el sistema no puede ejecutar órdenes reales.
        </Aviso>

        {data?.nivel === "viewer" && (
          <Aviso tono="aviso" titulo="Tienes acceso de solo lectura">
            Puedes ver el estado, la configuración y las operaciones. Para encender, apagar o
            cambiar la configuración, pídele a un administrador que te dé permiso de operador.
          </Aviso>
        )}

        {isPending && <EsqueletoLista filas={4} />}

        {isError && (
          <EstadoError
            titulo="No pudimos cargar los bots"
            mensaje={mensajeDeError(error, "Inténtalo de nuevo en un momento.")}
            onReintentar={() => void refetch()}
          />
        )}

        {data && data.items.length === 0 && (
          <Vacio
            titulo="No hay motores configurados"
            descripcion="Cuando se instale un motor de trading en el servidor, aparecerá aquí."
            icono={<IconoTrading className="size-6" />}
          />
        )}

        {data?.items.map((bot) => (
          <TarjetaBot key={bot.motor.bot_name} bot={bot} nivel={data.nivel} />
        ))}
      </div>
    </Pantalla>
  );
}
