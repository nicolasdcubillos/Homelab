/**
 * Automatización de una app.
 *
 * La frecuencia se elige con atajos («cada hora», «diario a las 8:00») porque
 * eso es lo que la gente quiere de verdad; el cron queda disponible para quien
 * necesite precisión, pero no se le pone delante a nadie.
 */

import { useEffect, useState } from "react";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Campo, Interruptor } from "@/components/Campos";
import { Aviso, Esqueleto } from "@/components/Estados";
import { Hoja, PieDeHoja } from "@/components/Hoja";
import { Lista, FilaValor } from "@/components/Lista";
import { useGuardarProgramacion, useProgramaciones } from "@/lib/consultas";
import { mensajeDeError } from "@/lib/errores";
import { cadaCuanto, fechaHora, relativo } from "@/lib/formato";
import type { Programacion } from "@/lib/tipos";

/** Atajos de frecuencia. `cron` se resuelve en la zona horaria del usuario. */
const PRESETS = [
  { id: "1h", texto: "Cada hora", kind: "interval", interval_minutes: 60 },
  { id: "4h", texto: "Cada 4 horas", kind: "interval", interval_minutes: 240 },
  { id: "12h", texto: "Cada 12 horas", kind: "interval", interval_minutes: 720 },
  { id: "diario", texto: "Todos los días a las 8:00", kind: "cron", cron_expr: "0 8 * * *" },
  { id: "laboral", texto: "De lunes a viernes a las 8:00", kind: "cron", cron_expr: "0 8 * * 1-5" },
  { id: "semanal", texto: "Los lunes a las 8:00", kind: "cron", cron_expr: "0 8 * * 1" },
] as const;

type Preset = (typeof PRESETS)[number];

function presetDe(programacion: Programacion): Preset["id"] | "personalizado" {
  const encontrado = PRESETS.find((preset) =>
    preset.kind === "interval"
      ? programacion.kind === "interval" && programacion.interval_minutes === preset.interval_minutes
      : programacion.kind === "cron" && programacion.cron_expr === preset.cron_expr,
  );
  return encontrado?.id ?? "personalizado";
}

function descripcion(programacion: Programacion): string {
  if (!programacion.enabled) return "Desactivada";
  if (programacion.kind === "cron") {
    const preset = PRESETS.find((p) => p.kind === "cron" && p.cron_expr === programacion.cron_expr);
    return preset?.texto ?? `Cron: ${programacion.cron_expr}`;
  }
  return cadaCuanto(programacion.interval_minutes);
}

/* -------------------------------------------------------------------------- */

function EditorProgramacion({
  abierta,
  programacion,
  zona,
  onCerrar,
}: {
  abierta: boolean;
  programacion: Programacion | null;
  zona: string;
  onCerrar: () => void;
}) {
  const guardar = useGuardarProgramacion();
  const avisos = useAvisos();

  const [activa, setActiva] = useState(false);
  const [preset, setPreset] = useState<string>("1h");
  const [cron, setCron] = useState("0 8 * * *");
  const [minutos, setMinutos] = useState("60");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!abierta || !programacion) return;
    // La hoja se reutiliza entre programaciones: hay que recargar sus campos
    // locales al abrirla, y un efecto es el único enganche a esa transición.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setError(null);
    setActiva(programacion.enabled);
    const elegido = presetDe(programacion);
    setPreset(elegido);
    setCron(programacion.cron_expr ?? "0 8 * * *");
    setMinutos(String(programacion.interval_minutes ?? 60));
  }, [abierta, programacion]);

  if (!programacion) return null;

  const enviar = async () => {
    setError(null);
    const elegido = PRESETS.find((p) => p.id === preset);

    const cuerpo =
      preset === "personalizado"
        ? { enabled: activa, kind: "cron" as const, cron_expr: cron.trim(), interval_minutes: null }
        : elegido?.kind === "cron"
          ? { enabled: activa, kind: "cron" as const, cron_expr: elegido.cron_expr, interval_minutes: null }
          : {
              enabled: activa,
              kind: "interval" as const,
              interval_minutes: elegido?.interval_minutes ?? Number(minutos),
              cron_expr: null,
            };

    try {
      await guardar.mutateAsync({
        app: programacion.app_name,
        command_key: programacion.command_key,
        datos: cuerpo,
      });
      avisos.exito(activa ? "Automatización actualizada." : "Automatización desactivada.");
      onCerrar();
    } catch (excepcion) {
      setError(mensajeDeError(excepcion, "No pudimos guardar la programación."));
    }
  };

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo="Frecuencia"
      descripcion={`Los horarios se calculan en ${zona}.`}
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton tono="primario" onClick={() => void enviar()} cargando={guardar.isPending}>
            Guardar
          </Boton>
        </PieDeHoja>
      }
    >
      <div className="space-y-5">
        {error && <Aviso tono="alerta">{error}</Aviso>}

        <Interruptor
          checked={activa}
          onChange={setActiva}
          etiqueta="Ejecutar automáticamente"
          descripcion="Si la apagas, la app solo corre cuando tú se lo pidas."
        />

        <fieldset disabled={!activa} className="space-y-4 disabled:opacity-50">
          <legend className="sr-only">Frecuencia</legend>

          <div role="radiogroup" aria-label="Frecuencia" className="space-y-1.5">
            {PRESETS.map((opcion) => (
              <label
                key={opcion.id}
                className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-1 text-body"
              >
                <input
                  type="radio"
                  name="preset"
                  value={opcion.id}
                  checked={preset === opcion.id}
                  onChange={() => setPreset(opcion.id)}
                  className="size-5 shrink-0 accent-[var(--c-accent)]"
                />
                {opcion.texto}
              </label>
            ))}

            <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-1 text-body">
              <input
                type="radio"
                name="preset"
                value="personalizado"
                checked={preset === "personalizado"}
                onChange={() => setPreset("personalizado")}
                className="size-5 shrink-0 accent-[var(--c-accent)]"
              />
              Personalizado (cron)
            </label>
          </div>

          {preset === "personalizado" && (
            <Campo
              etiqueta="Expresión cron"
              value={cron}
              onChange={(evento) => setCron(evento.target.value)}
              placeholder="0 8 * * 1-5"
              descripcion="Cinco campos: minuto, hora, día del mes, mes y día de la semana."
              autoComplete="off"
              spellCheck={false}
            />
          )}
        </fieldset>
      </div>
    </Hoja>
  );
}

/* -------------------------------------------------------------------------- */

export function PanelAutomatizacion({ app }: { app: string }) {
  const programaciones = useProgramaciones();
  const [editando, setEditando] = useState<Programacion | null>(null);

  const items = (programaciones.data?.items ?? []).filter((item) => item.app_name === app);
  const zona = programaciones.data?.timezone ?? "UTC";

  if (programaciones.isPending) {
    return <Esqueleto className="h-28 w-full rounded-lg" />;
  }

  if (items.length === 0) return null;

  return (
    <>
      <Lista
        titulo="Automatización"
        nota={
          items.some((item) => item.enabled)
            ? `Se ejecuta sola según la frecuencia que elijas, en ${zona}.`
            : "Ahora mismo solo corre cuando tú se lo pidas."
        }
      >
        {items.map((item) => (
          <FilaValor
            key={item.command_key}
            etiqueta={item.command_label}
            descripcion={
              item.enabled && item.next_run_at
                ? `Próxima ${relativo(item.next_run_at)} · ${fechaHora(item.next_run_at)}`
                : undefined
            }
            valor={descripcion(item)}
            onClick={() => setEditando(item)}
          />
        ))}
      </Lista>

      <EditorProgramacion
        abierta={editando !== null}
        programacion={editando}
        zona={zona}
        onCerrar={() => setEditando(null)}
      />
    </>
  );
}
