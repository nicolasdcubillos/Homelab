import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campos";
import { Aviso } from "@/components/Estados";
import { MarcoAcceso } from "@/components/MarcoAcceso";
import { useLogin } from "@/lib/consultas";
import { aplicarErroresDeApi } from "@/lib/errores";
import { esquemaLogin, type DatosLogin } from "@/lib/validacion";

export function Login() {
  const login = useLogin();
  const navegar = useNavigate();
  const ubicacion = useLocation();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosLogin>({
    resolver: zodResolver(esquemaLogin),
    defaultValues: { email: "", password: "" },
  });

  const destino = (ubicacion.state as { destino?: string } | null)?.destino ?? "/";

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    try {
      const sesion = await login.mutateAsync(datos);
      navegar(sesion.user.must_change_password ? "/cambiar-password" : destino, { replace: true });
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, ["email", "password"]));
    }
  });

  return (
    <MarcoAcceso
      titulo="Entra a tu panel"
      descripcion="Tus vigilancias y tu portafolio, en un solo sitio."
      pie={
        <>
          ¿Todavía no tienes cuenta?{" "}
          <Link to="/registro" className="font-medium text-accent hover:underline">
            Crear una
          </Link>
        </>
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-4">
        {errorGeneral && <Aviso tono="alerta">{errorGeneral}</Aviso>}

        <Campo
          {...register("email")}
          etiqueta="Correo"
          type="email"
          inputMode="email"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          placeholder="tu@correo.com"
          error={errors.email?.message}
          requerido
        />

        <Campo
          {...register("password")}
          etiqueta="Contraseña"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          requerido
        />

        <Boton type="submit" tono="primario" tamano="lg" ancho cargando={isSubmitting}>
          Entrar
        </Boton>
      </form>
    </MarcoAcceso>
  );
}
