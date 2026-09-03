/**
 * Ajustes.
 *
 * Cuatro bloques: notificaciones, canales por app, cuenta y apariencia.
 * El acceso a Admin solo aparece si el rol lo permite; no hay que ocultarlo
 * con CSS, se omite del árbol directamente.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Campo, Casilla } from "@/components/Campos";
import { Confirmar } from "@/components/Confirmar";
import { Aviso, Esqueleto } from "@/components/Estados";
import { Lista, Fila, FilaValor } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";
import { IconoAdmin, IconoLuna, IconoSalir, IconoSol } from "@/components/iconos";
import {
  useBorrarMisDatos,
  useGuardarNotificaciones,
  useGuardarPreferencias,
  useGuardarZonaHoraria,
  useLogout,
  useNotificaciones,
  useSesion,
} from "@/lib/consultas";
import { cx } from "@/lib/cx";
import { aplicarErroresDeApi, mensajeDeError } from "@/lib/errores";
import { CANAL, ROL } from "@/lib/etiquetas";
import { esquemaNotificaciones, type DatosNotificaciones } from "@/lib/validacion";
import type { Apariencia } from "@/lib/tema";
import { useTema } from "@/lib/tema";
import type { Canal, Rol } from "@/lib/tipos";

const ZONAS_HABITUALES = [
  "America/Bogota",
  "America/Mexico_City",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/Madrid",
  "UTC",
];

/* ------------------------------------------------------- notificaciones -- */

function BloqueNotificaciones() {
  const notificaciones = useNotificaciones();
  const guardar = useGuardarNotificaciones();
  const avisos = useAvisos();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<DatosNotificaciones>({
    resolver: zodResolver(esquemaNotificaciones),
    defaultValues: { whatsapp: "", email: "" },
  });

  useEffect(() => {
    if (notificaciones.data) {
      reset({ whatsapp: notificaciones.data.whatsapp ?? "", email: notificaciones.data.email ?? "" });
    }
  }, [notificaciones.data, reset]);

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    try {
      await guardar.mutateAsync({ whatsapp: datos.whatsapp || null, email: datos.email || null });
      avisos.exito("Notificaciones actualizadas.");
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, ["whatsapp", "email"]));
    }
  });

  if (notificaciones.isPending) return <Esqueleto className="h-40 w-full rounded-lg" />;

  return (
    <form onSubmit={enviar} noValidate>
      <Lista titulo="Notificaciones" nota="Dónde te avisamos cuando algo relevante ocurra.">
        <Fila className="space-y-4 py-4">
          {errorGeneral && <Aviso tono="alerta">{errorGeneral}</Aviso>}

          <Campo
            {...register("whatsapp")}
            etiqueta="WhatsApp"
            type="tel"
            inputMode="tel"
            placeholder="+573001234567"
            descripcion="En formato internacional, con el signo más."
            error={errors.whatsapp?.message}
          />
          <Campo
            {...register("email")}
            etiqueta="Correo"
            type="email"
            autoComplete="email"
            placeholder="tu@correo.com"
            error={errors.email?.message}
          />

          <Boton type="submit" tono="primario" tamano="sm" cargando={isSubmitting} disabled={!isDirty}>
            Guardar
          </Boton>
        </Fila>
      </Lista>
    </form>
  );
}

/* ----------------------------------------------------------- preferencias -- */

function FilaCanalesApp({
  app,
  titulo,
  activos,
  soportados,
}: {
  app: string;
  titulo: string;
  activos: Canal[];
  soportados: Canal[];
}) {
  const guardar = useGuardarPreferencias();
  const avisos = useAvisos();

  const alternar = async (canal: Canal, marcado: boolean) => {
    const siguiente = marcado ? [...activos.filter((c) => c !== canal), canal] : activos.filter((c) => c !== canal);
    try {
      await guardar.mutateAsync({ app_name: app, channels: siguiente });
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos actualizar el canal."));
    }
  };

  if (soportados.length === 0) return null;

  return (
    <Fila className="space-y-2 py-3">
      <p className="text-body font-medium">{titulo}</p>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        {soportados.map((canal) => (
          <Casilla
            key={canal}
            etiqueta={CANAL[canal]}
            checked={activos.includes(canal)}
            onChange={(marcado) => void alternar(canal, marcado)}
            disabled={guardar.isPending}
          />
        ))}
      </div>
    </Fila>
  );
}

function BloquePreferencias() {
  const notificaciones = useNotificaciones();
  if (notificaciones.isPending || !notificaciones.data) return null;

  const preferences = notificaciones.data.preferences ?? {};
  const supported = notificaciones.data.supported ?? {};
  const apps = Object.keys(supported);
  if (apps.length === 0) return null;

  return (
    <Lista titulo="Canales por app" nota="Si no activas ninguno, no se te notificará desde esa app.">
      <FilaCanalesApp
        app="stockwatcher"
        titulo="Vigilancias"
        activos={(preferences.stockwatcher ?? []) as Canal[]}
        soportados={(supported.stockwatcher ?? []) as Canal[]}
      />
      <FilaCanalesApp
        app="portfoliowatcher"
        titulo="Portafolio"
        activos={(preferences.portfoliowatcher ?? []) as Canal[]}
        soportados={(supported.portfoliowatcher ?? []) as Canal[]}
      />
    </Lista>
  );
}

/* ------------------------------------------------------------------ cuenta -- */

function BloqueCuenta() {
  const { data: sesion } = useSesion();
  const guardarZona = useGuardarZonaHoraria();
  const logout = useLogout();
  const borrarDatos = useBorrarMisDatos();
  const avisos = useAvisos();
  const navegar = useNavigate();

  const [confirmando, setConfirmando] = useState(false);

  if (!sesion) return null;

  const cambiarZona = async (zona: string) => {
    try {
      await guardarZona.mutateAsync(zona);
      avisos.exito("Zona horaria actualizada.");
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos actualizar la zona horaria."));
    }
  };

  const confirmarBorrado = async (password: string) => {
    try {
      await borrarDatos.mutateAsync({ password });
      avisos.info("Borramos toda tu configuración.");
      setConfirmando(false);
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos borrar tus datos."));
    }
  };

  return (
    <>
      <Lista titulo="Cuenta">
        <Fila className="flex items-center justify-between gap-3 py-3">
          <span className="text-body">Correo</span>
          <span className="text-body text-muted">{sesion.user.email}</span>
        </Fila>

        <Fila className="space-y-2 py-3">
          <label htmlFor="zona-horaria" className="block text-body">
            Zona horaria
          </label>
          <select
            id="zona-horaria"
            value={sesion.user.timezone}
            onChange={(evento) => void cambiarZona(evento.target.value)}
            disabled={guardarZona.isPending}
            className={cx(
              "min-h-11 w-full rounded-md border border-line-strong bg-surface px-3 text-body",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--c-accent)]",
            )}
          >
            {!ZONAS_HABITUALES.includes(sesion.user.timezone) && (
              <option value={sesion.user.timezone}>{sesion.user.timezone}</option>
            )}
            {ZONAS_HABITUALES.map((zona) => (
              <option key={zona} value={zona}>
                {zona}
              </option>
            ))}
          </select>
          <p className="text-footnote text-muted">Se usa para calcular tus horarios automáticos.</p>
        </Fila>

        <FilaValor etiqueta="Rol" valor={ROL[sesion.user.role as Rol]} />
        <FilaValor etiqueta="Cambiar contraseña" href="/cambiar-password" />

        {sesion.user.role === "admin" && (
          <FilaValor
            icono={<IconoAdmin className="size-5" />}
            etiqueta="Panel de administración"
            href="/admin"
          />
        )}

        <FilaValor
          icono={<IconoSalir className="size-5" />}
          etiqueta="Cerrar sesión"
          onClick={() => logout.mutate(undefined, { onSuccess: () => navegar("/entrar") })}
        />
      </Lista>

      <Lista titulo="Zona de riesgo">
        <FilaValor
          tono="peligro"
          etiqueta="Borrar toda mi configuración"
          descripcion="Elimina tus vigilancias, portafolio y programaciones. No borra tu cuenta."
          onClick={() => setConfirmando(true)}
        />
      </Lista>

      <ConfirmarBorrado
        abierta={confirmando}
        cargando={borrarDatos.isPending}
        onCancelar={() => setConfirmando(false)}
        onConfirmar={confirmarBorrado}
      />
    </>
  );
}

function ConfirmarBorrado({
  abierta,
  cargando,
  onCancelar,
  onConfirmar,
}: {
  abierta: boolean;
  cargando: boolean;
  onCancelar: () => void;
  onConfirmar: (password: string) => void;
}) {
  const [password, setPassword] = useState("");

  useEffect(() => {
    // La hoja se reutiliza entre aperturas: hay que vaciar la contraseña
    // tecleada al volver a abrirla, y un efecto es el único enganche a esa
    // transición.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (abierta) setPassword("");
  }, [abierta]);

  return (
    <Confirmar
      abierta={abierta}
      onCerrar={onCancelar}
      onConfirmar={() => onConfirmar(password)}
      titulo="Borrar toda tu configuración"
      descripcion={
        <div className="space-y-3">
          <p>
            Se eliminarán tus vigilancias, tu portafolio, tus preferencias de notificación y tus
            programaciones. Tu cuenta seguirá existiendo. Esto no se puede deshacer.
          </p>
          <Campo
            etiqueta="Confirma tu contraseña"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(evento) => setPassword(evento.target.value)}
            autoFocus
          />
        </div>
      }
      textoConfirmar="Borrar todo"
      confirmarDeshabilitado={password.trim().length === 0}
      cargando={cargando}
    />
  );
}

/* -------------------------------------------------------------- apariencia -- */

const OPCIONES_APARIENCIA: Array<{ valor: Apariencia; texto: string }> = [
  { valor: "sistema", texto: "Automática" },
  { valor: "claro", texto: "Clara" },
  { valor: "oscuro", texto: "Oscura" },
];

function BloqueApariencia() {
  const { apariencia, cambiar, resuelto } = useTema();

  return (
    <Lista titulo="Apariencia">
      <Fila className="py-3">
        <div role="radiogroup" aria-label="Apariencia" className="flex gap-2">
          {OPCIONES_APARIENCIA.map((opcion) => (
            <button
              key={opcion.valor}
              type="button"
              role="radio"
              aria-checked={apariencia === opcion.valor}
              onClick={() => cambiar(opcion.valor)}
              className={cx(
                "flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-md border px-3 text-subhead font-medium",
                "transition-colors duration-150",
                apariencia === opcion.valor
                  ? "border-transparent bg-accent text-on-accent"
                  : "border-line-strong text-muted hover:text-fg",
              )}
            >
              {opcion.valor === "oscuro" && <IconoLuna className="size-4" />}
              {opcion.valor === "claro" && <IconoSol className="size-4" />}
              {opcion.texto}
            </button>
          ))}
        </div>
      </Fila>
      {apariencia === "sistema" && (
        <p className="px-4 pb-3 text-footnote text-muted">
          Ahora mismo se ve en {resuelto === "oscuro" ? "oscuro" : "claro"}, según tu sistema.
        </p>
      )}
    </Lista>
  );
}

/* -------------------------------------------------------------- pantalla -- */

export function Ajustes() {
  return (
    <Pantalla titulo="Ajustes" descripcion="Notificaciones, cuenta y apariencia.">
      <div className="space-y-6">
        <BloqueNotificaciones />
        <BloquePreferencias />
        <BloqueApariencia />
        <BloqueCuenta />
      </div>
    </Pantalla>
  );
}
