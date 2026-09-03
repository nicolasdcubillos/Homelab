import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campos";
import { Aviso } from "@/components/Estados";
import { MarcoAcceso } from "@/components/MarcoAcceso";
import { useCambiarPassword, useLogout, useSesion } from "@/lib/consultas";
import { aplicarErroresDeApi } from "@/lib/errores";
import {
  esquemaCambioPassword,
  LARGO_MINIMO_PASSWORD,
  type DatosCambioPassword,
} from "@/lib/validacion";

/**
 * Cambio de contraseña.
 *
 * Sirve para dos situaciones: el cambio voluntario desde Ajustes y el forzado
 * cuando un administrador reinició la contraseña. En el caso forzado la actual
 * puede no existir —el administrador la borró— así que el campo se oculta y no
 * se le pide al usuario algo que no puede saber.
 */
export function CambiarPassword() {
  const { data: sesion } = useSesion();
  const cambiar = useCambiarPassword();
  const logout = useLogout();
  const navegar = useNavigate();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const forzado = sesion?.user.must_change_password ?? false;

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosCambioPassword>({
    resolver: zodResolver(esquemaCambioPassword),
    defaultValues: { password_actual: "", password_nueva: "", repetir: "" },
  });

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    try {
      await cambiar.mutateAsync({
        password_actual: datos.password_actual || null,
        password_nueva: datos.password_nueva,
      });
      navegar("/", { replace: true });
    } catch (error) {
      setErrorGeneral(
        aplicarErroresDeApi(error, setError, ["password_actual", "password_nueva", "repetir"]),
      );
    }
  });

  return (
    <MarcoAcceso
      titulo={forzado ? "Elige una contraseña nueva" : "Cambiar contraseña"}
      descripcion={
        forzado
          ? "Un administrador reinició tu acceso. Define una contraseña para continuar."
          : undefined
      }
      pie={
        forzado ? (
          <button
            type="button"
            onClick={() => logout.mutate(undefined, { onSettled: () => navegar("/entrar") })}
            className="font-medium text-accent hover:underline"
          >
            Cerrar sesión
          </button>
        ) : undefined
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-4">
        {errorGeneral && <Aviso tono="alerta">{errorGeneral}</Aviso>}

        {/* El nombre de usuario oculto le da contexto al gestor de contraseñas
            para que ofrezca guardar la nueva en la cuenta correcta. */}
        <input
          type="text"
          name="username"
          autoComplete="username"
          value={sesion?.user.email ?? ""}
          readOnly
          hidden
        />

        {!forzado && (
          <Campo
            {...register("password_actual")}
            etiqueta="Contraseña actual"
            type="password"
            autoComplete="current-password"
            error={errors.password_actual?.message}
            requerido
          />
        )}

        <Campo
          {...register("password_nueva")}
          etiqueta="Contraseña nueva"
          type="password"
          autoComplete="new-password"
          descripcion={`Mínimo ${LARGO_MINIMO_PASSWORD} caracteres, con al menos una letra y un número.`}
          error={errors.password_nueva?.message}
          requerido
        />

        <Campo
          {...register("repetir")}
          etiqueta="Repite la contraseña nueva"
          type="password"
          autoComplete="new-password"
          error={errors.repetir?.message}
          requerido
        />

        <Boton type="submit" tono="primario" tamano="lg" ancho cargando={isSubmitting}>
          Guardar contraseña
        </Boton>
      </form>
    </MarcoAcceso>
  );
}
