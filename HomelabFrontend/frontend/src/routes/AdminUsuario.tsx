/**
 * Ficha de usuario (admin).
 *
 * Todo lo que un administrador necesita para entender y actuar sobre una
 * cuenta ajena: qué tiene configurado, cómo le ha ido, y las acciones que
 * pueden cambiar su acceso. Las destructivas piden confirmación escrita.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAvisos } from "@/components/Avisos";
import { Boton } from "@/components/Boton";
import { Campo, Interruptor, Selector } from "@/components/Campos";
import { Confirmar } from "@/components/Confirmar";
import { EstadoError, Esqueleto } from "@/components/Estados";
import { Hoja, PieDeHoja } from "@/components/Hoja";
import { Insignia } from "@/components/Insignia";
import { Lista, Fila, FilaValor } from "@/components/Lista";
import { Pantalla } from "@/components/Pantalla";
import { IconoAtras } from "@/components/iconos";
import {
  useAccesosTrading,
  useCambiarUsuarioAdmin,
  useConcederAccesoTrading,
  useEliminarUsuarioAdmin,
  usePasswordAdmin,
  useRevocarAccesoTrading,
  useUsuarioAdmin,
} from "@/lib/consultas";
import { mensajeDeError } from "@/lib/errores";
import { CANAL, DESCRIPCION_ESTADO_USUARIO, DESCRIPCION_NIVEL_TRADING, DISPARADOR, ESTADO_EJECUCION, ESTADO_USUARIO, NIVEL_TRADING, ROL, TONO_EJECUCION } from "@/lib/etiquetas";
import { cadaCuanto, fechaHora, plural, relativo } from "@/lib/formato";
import type { EstadoEjecucion, EstadoUsuario, NivelTrading, Rol } from "@/lib/tipos";

const TONO_ESTADO: Record<EstadoUsuario, "ok" | "aviso" | "neutro"> = {
  active: "ok",
  pending: "aviso",
  suspended: "neutro",
};

const OPCIONES_TRADING = [
  { valor: "", texto: "Sin acceso" },
  { valor: "viewer", texto: NIVEL_TRADING.viewer },
  { valor: "operator", texto: NIVEL_TRADING.operator },
] as const;

/**
 * Permiso sobre el módulo de trading.
 *
 * Va en su propio bloque y no junto al rol porque no es lo mismo: el rol dice
 * quién es esta persona en la app, y esto dice qué puede hacerle a un recurso
 * que comparte con todos los demás. Conceder «operador» aquí deja a alguien
 * cambiar la configuración que ve el resto, así que la nota lo dice sin rodeos.
 */
function PermisoTrading({ id, esAdmin }: { id: string; esAdmin: boolean }) {
  const accesos = useAccesosTrading(!esAdmin);
  const conceder = useConcederAccesoTrading();
  const revocar = useRevocarAccesoTrading();
  const avisos = useAvisos();

  if (esAdmin) {
    return (
      <Lista titulo="Trading">
        <FilaValor
          etiqueta="Acceso"
          valor={NIVEL_TRADING.operator}
          descripcion="Los administradores operan los bots sin necesitar un permiso aparte."
        />
      </Lista>
    );
  }

  const actual = (accesos.data?.items.find((a) => a.user_id === id)?.level ?? "") as
    | NivelTrading
    | "";
  const pendiente = accesos.isPending || conceder.isPending || revocar.isPending;

  const cambiar = async (valor: string) => {
    try {
      if (valor === "") {
        await revocar.mutateAsync(id);
        avisos.exito("Le quitamos el acceso al trading.");
      } else {
        await conceder.mutateAsync({ id, level: valor });
        avisos.exito(`Ahora tiene acceso de ${NIVEL_TRADING[valor as NivelTrading].toLowerCase()}.`);
      }
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos cambiar el acceso al trading."));
    }
  };

  return (
    <Lista
      titulo="Trading"
      nota="Los bots son compartidos. Quien tenga permiso de operador puede encenderlos y cambiar la configuración que ven todos los demás."
    >
      <Fila className="py-3">
        <Selector
          etiqueta="Acceso al trading"
          descripcion={
            actual ? DESCRIPCION_NIVEL_TRADING[actual] : "No verá la sección de trading."
          }
          opciones={OPCIONES_TRADING}
          value={actual}
          onChange={(evento) => void cambiar(evento.target.value)}
          disabled={pendiente}
          className="w-full"
        />
      </Fila>
    </Lista>
  );
}

function BotonAtras() {
  return (
    <Link
      to="/admin"
      aria-label="Volver a administración"
      className="-ml-2 flex size-11 items-center justify-center rounded-full text-muted hover:bg-neutral-soft hover:text-fg active:bg-line"
    >
      <IconoAtras className="size-5" />
    </Link>
  );
}

/* -------------------------------------------------------------- password -- */

function HojaPassword({
  abierta,
  onCerrar,
  userId,
}: {
  abierta: boolean;
  onCerrar: () => void;
  userId: string;
}) {
  const cambiar = usePasswordAdmin();
  const avisos = useAvisos();
  const [modo, setModo] = useState<"nueva" | "reset">("nueva");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const enviar = async () => {
    setError(null);
    try {
      if (modo === "reset") {
        await cambiar.mutateAsync({ id: userId, datos: { force_reset: true } });
        avisos.exito("Forzamos el reseteo. El usuario deberá elegir una contraseña nueva al entrar.");
      } else {
        await cambiar.mutateAsync({ id: userId, datos: { new_password: password } });
        avisos.exito("Contraseña actualizada.");
      }
      onCerrar();
    } catch (excepcion) {
      setError(mensajeDeError(excepcion, "No pudimos completar la acción."));
    }
  };

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo="Contraseña del usuario"
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton
            tono={modo === "reset" ? "peligro" : "primario"}
            onClick={() => void enviar()}
            cargando={cambiar.isPending}
            disabled={modo === "nueva" && password.trim().length < 10}
          >
            {modo === "reset" ? "Forzar reseteo" : "Fijar contraseña"}
          </Boton>
        </PieDeHoja>
      }
    >
      <div className="space-y-4">
        {error && (
          <p role="alert" className="text-subhead text-danger">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setModo("nueva")}
            className={
              "flex-1 rounded-md border px-3 py-2 text-subhead font-medium " +
              (modo === "nueva"
                ? "border-transparent bg-accent text-on-accent"
                : "border-line-strong text-muted")
            }
          >
            Fijar una nueva
          </button>
          <button
            type="button"
            onClick={() => setModo("reset")}
            className={
              "flex-1 rounded-md border px-3 py-2 text-subhead font-medium " +
              (modo === "reset"
                ? "border-transparent bg-accent text-on-accent"
                : "border-line-strong text-muted")
            }
          >
            Forzar reseteo
          </button>
        </div>

        {modo === "nueva" ? (
          <Campo
            etiqueta="Contraseña nueva"
            type="password"
            value={password}
            onChange={(evento) => setPassword(evento.target.value)}
            descripcion="Mínimo 10 caracteres, con al menos una letra y un número. Compártela por un canal seguro."
            autoFocus
          />
        ) : (
          <p className="text-subhead text-muted">
            La cuenta quedará sin contraseña válida. La próxima vez que el usuario intente entrar,
            deberá establecer una nueva antes de poder usar el panel.
          </p>
        )}
      </div>
    </Hoja>
  );
}

/* -------------------------------------------------------------- pantalla -- */

export function AdminUsuario() {
  const { id } = useParams<{ id: string }>();
  const navegar = useNavigate();
  const avisos = useAvisos();

  const detalle = useUsuarioAdmin(id ?? null);
  const cambiarEstado = useCambiarUsuarioAdmin();
  const eliminar = useEliminarUsuarioAdmin();

  const [hojaPassword, setHojaPassword] = useState(false);
  const [confirmandoEliminar, setConfirmandoEliminar] = useState(false);

  if (!id) return null;

  if (detalle.isPending) {
    return (
      <Pantalla titulo="Usuario" atras={<BotonAtras />}>
        <div className="space-y-4">
          <Esqueleto className="h-24 w-full rounded-lg" />
          <Esqueleto className="h-40 w-full rounded-lg" />
        </div>
      </Pantalla>
    );
  }

  if (detalle.isError || !detalle.data) {
    return (
      <Pantalla titulo="Usuario" atras={<BotonAtras />}>
        <EstadoError
          mensaje={mensajeDeError(detalle.error, "No pudimos cargar este usuario.")}
          onReintentar={() => void detalle.refetch()}
        />
      </Pantalla>
    );
  }

  const { user, watches, watches_enabled, holdings, closed_positions, total_runs, channels, schedules, recent_runs } =
    detalle.data;

  const cambiarRol = async (role: "user" | "admin") => {
    try {
      await cambiarEstado.mutateAsync({ id, datos: { role } });
      avisos.exito(role === "admin" ? "Ahora es administrador." : "Ya no es administrador.");
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos cambiar el rol."));
    }
  };

  const cambiarEstadoCuenta = async (status: "active" | "suspended") => {
    try {
      await cambiarEstado.mutateAsync({ id, datos: { status } });
      avisos.exito(status === "suspended" ? "Usuario suspendido." : "Usuario reactivado.");
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos cambiar el estado."));
    }
  };

  const confirmarEliminacion = async () => {
    try {
      await eliminar.mutateAsync(id);
      avisos.info(`Eliminamos la cuenta de ${user.email}.`);
      navegar("/admin", { replace: true });
    } catch (error) {
      avisos.error(mensajeDeError(error, "No pudimos eliminar el usuario."));
    }
  };

  return (
    <Pantalla titulo={user.email} atras={<BotonAtras />}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <Insignia tono={TONO_ESTADO[user.status as EstadoUsuario]}>{ESTADO_USUARIO[user.status as EstadoUsuario]}</Insignia>
          <Insignia tono={user.role === "admin" ? "activo" : "neutro"}>{ROL[user.role as Rol]}</Insignia>
          {user.must_change_password && <Insignia tono="aviso">Debe cambiar su contraseña</Insignia>}
        </div>

        <Lista titulo="Cuenta">
          <FilaValor etiqueta="Registrado" valor={fechaHora(user.created_at)} />
          <FilaValor
            etiqueta="Último acceso"
            valor={user.last_login_at ? relativo(user.last_login_at) : "Nunca"}
          />
          <FilaValor etiqueta="Estado" descripcion={DESCRIPCION_ESTADO_USUARIO[user.status as EstadoUsuario]} valor={ESTADO_USUARIO[user.status as EstadoUsuario]} />
        </Lista>

        <Lista titulo="Configuración">
          <FilaValor etiqueta="Vigilancias" valor={`${watches_enabled} de ${plural(watches, "activa", "activas")}`} />
          <FilaValor etiqueta="Portafolio" valor={plural(holdings, "activo", "activos")} />
          <FilaValor etiqueta="Posiciones cerradas" valor={String(closed_positions)} />
          <FilaValor etiqueta="Ejecuciones totales" valor={String(total_runs)} />
          <FilaValor
            etiqueta="Notificaciones"
            valor={
              channels.length > 0
                ? channels.map((c) => CANAL[c.channel as "whatsapp" | "email"] ?? c.channel).join(", ")
                : "Sin configurar"
            }
          />
        </Lista>

        <PermisoTrading id={id} esAdmin={user.role === "admin"} />

        {schedules.length > 0 && (
          <Lista titulo="Automatización">
            {schedules.map((programacion) => (
              <FilaValor
                key={`${programacion.app_name}-${programacion.command_key}`}
                etiqueta={programacion.command_label}
                valor={
                  !programacion.enabled
                    ? "Desactivada"
                    : programacion.kind === "cron"
                      ? programacion.cron_expr ?? ""
                      : cadaCuanto(programacion.interval_minutes)
                }
              />
            ))}
          </Lista>
        )}

        {recent_runs.length > 0 && (
          <Lista titulo="Últimas ejecuciones">
            {recent_runs.map((run) => (
              <Fila key={run.id} className="flex items-center justify-between gap-3">
                <span className="min-w-0 flex-1">
                  <span className="block text-body">{run.command_label}</span>
                  <span className="block text-footnote text-muted">
                    {run.started_at ? relativo(run.started_at) : "Sin iniciar"} ·{" "}
                    {DISPARADOR[run.trigger] ?? run.trigger}
                  </span>
                </span>
                <Insignia tono={TONO_EJECUCION[run.status as EstadoEjecucion] ?? "neutro"}>
                  {ESTADO_EJECUCION[run.status as EstadoEjecucion] ?? run.status}
                </Insignia>
              </Fila>
            ))}
          </Lista>
        )}

        <Lista titulo="Acciones">
          <FilaValor etiqueta="Cambiar o resetear contraseña" onClick={() => setHojaPassword(true)} />
          <Fila className="flex items-center justify-between gap-3 py-3">
            <span className="text-body">Es administrador</span>
            <Interruptor
              checked={user.role === "admin"}
              onChange={(valor) => void cambiarRol(valor ? "admin" : "user")}
              etiqueta="Es administrador"
              disabled={cambiarEstado.isPending}
            />
          </Fila>
          {user.status === "pending" ? (
            <>
              <FilaValor
                tono="normal"
                etiqueta="Aprobar cuenta"
                descripcion="Activa la cuenta para que pueda configurar y ejecutar con normalidad."
                onClick={() => void cambiarEstadoCuenta("active")}
              />
              <FilaValor
                tono="peligro"
                etiqueta="Rechazar cuenta"
                descripcion="Suspende la cuenta sin activarla."
                onClick={() => void cambiarEstadoCuenta("suspended")}
              />
            </>
          ) : (
            <FilaValor
              tono={user.status === "suspended" ? "normal" : "peligro"}
              etiqueta={user.status === "suspended" ? "Reactivar cuenta" : "Suspender cuenta"}
              onClick={() =>
                void cambiarEstadoCuenta(user.status === "suspended" ? "active" : "suspended")
              }
            />
          )}
        </Lista>

        <Lista titulo="Zona de riesgo">
          <FilaValor
            tono="peligro"
            etiqueta="Eliminar usuario"
            descripcion="Borra la cuenta y todos sus datos. No se puede deshacer."
            onClick={() => setConfirmandoEliminar(true)}
          />
        </Lista>
      </div>

      <HojaPassword abierta={hojaPassword} onCerrar={() => setHojaPassword(false)} userId={id} />

      <Confirmar
        abierta={confirmandoEliminar}
        onCerrar={() => setConfirmandoEliminar(false)}
        onConfirmar={() => void confirmarEliminacion()}
        titulo="Eliminar este usuario"
        descripcion={`Se borrará la cuenta de ${user.email} y toda su configuración: vigilancias, portafolio, historial y programaciones.`}
        textoConfirmar="Eliminar usuario"
        palabraClave={user.email}
        etiquetaPalabraClave="Escribe el correo para confirmar"
        cargando={eliminar.isPending}
      />
    </Pantalla>
  );
}
