/**
 * Marco común de las pantallas con sesión iniciada.
 *
 * Además de la navegación, aquí viven dos avisos de estado de cuenta que deben
 * verse en cualquier sección: la cuenta pendiente de aprobación y la cuenta
 * suspendida. Explican por qué algunos botones no responden, en vez de dejar
 * al usuario descubrirlo a base de errores.
 */

import { Outlet, useNavigate } from "react-router-dom";

import { useLogout, useSesion } from "@/lib/consultas";

import { Boton } from "./Boton";
import { Aviso } from "./Estados";
import { IconoSalir } from "./iconos";
import { BarraLateral, BarraPestanas } from "./Navegacion";

export function Disposicion() {
  const { data: sesion } = useSesion();
  const logout = useLogout();
  const navegar = useNavigate();

  const usuario = sesion?.user;
  const admin = usuario?.role === "admin";

  const salir = () => {
    logout.mutate(undefined, { onSettled: () => navegar("/entrar", { replace: true }) });
  };

  return (
    <div className="min-h-dvh bg-bg">
      <BarraLateral
        admin={admin}
        email={usuario?.email ?? ""}
        pie={
          <Boton
            tono="sutil"
            tamano="sm"
            ancho
            onClick={salir}
            cargando={logout.isPending}
            icono={<IconoSalir className="size-4" />}
            className="justify-start"
          >
            Cerrar sesión
          </Boton>
        }
      />

      <div className="lg:pl-64">
        {usuario?.status === "pending" && (
          <div className="mx-auto max-w-4xl px-4 pt-4 sm:px-6">
            <Aviso tono="aviso" titulo="Tu cuenta está pendiente de aprobación">
              Puedes dejar todo configurado desde ya. En cuanto un administrador la active,
              tus vigilancias empezarán a correr solas.
            </Aviso>
          </div>
        )}

        {usuario?.status === "suspended" && (
          <div className="mx-auto max-w-4xl px-4 pt-4 sm:px-6">
            <Aviso tono="alerta" titulo="Tu cuenta está suspendida">
              No se ejecutará nada hasta que un administrador la reactive.
            </Aviso>
          </div>
        )}

        <main id="contenido">
          <Outlet />
        </main>
      </div>

      <BarraPestanas admin={admin} />
    </div>
  );
}
