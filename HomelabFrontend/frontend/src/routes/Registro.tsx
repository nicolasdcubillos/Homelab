import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campos";
import { Aviso } from "@/components/Estados";
import { MarcoAcceso } from "@/components/MarcoAcceso";
import { useRegistro } from "@/lib/consultas";
import { aplicarErroresDeApi } from "@/lib/errores";
import { esquemaRegistro, LARGO_MINIMO_PASSWORD, type DatosRegistro } from "@/lib/validacion";

/** La zona del navegador acierta casi siempre; el usuario puede cambiarla luego. */
function zonaDelNavegador(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Bogota";
  } catch {
    return "America/Bogota";
  }
}

export function Registro() {
  const registro = useRegistro();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [creada, setCreada] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<DatosRegistro>({
    resolver: zodResolver(esquemaRegistro),
    defaultValues: { email: "", password: "", timezone: zonaDelNavegador() },
  });

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    try {
      const respuesta = await registro.mutateAsync(datos);
      setCreada(respuesta.mensaje);
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, ["email", "password", "timezone"]));
    }
  });

  if (creada) {
    return (
      <MarcoAcceso
        titulo="Cuenta creada"
        descripcion={creada}
        pie={
          <Link to="/entrar" className="font-medium text-accent hover:underline">
            Ir a iniciar sesión
          </Link>
        }
      >
        <Aviso tono="ok" titulo="Ya puedes entrar">
          Entra con tu correo y deja todo configurado. Tus vigilancias empezarán a correr solas
          en cuanto un administrador apruebe la cuenta.
        </Aviso>
      </MarcoAcceso>
    );
  }

  return (
    <MarcoAcceso
      titulo="Crea tu cuenta"
      descripcion="Vigila precios y sigue tu portafolio sin tocar un archivo de configuración."
      pie={
        <>
          ¿Ya tienes cuenta?{" "}
          <Link to="/entrar" className="font-medium text-accent hover:underline">
            Entrar
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
          autoComplete="new-password"
          descripcion={`Mínimo ${LARGO_MINIMO_PASSWORD} caracteres, con al menos una letra y un número.`}
          error={errors.password?.message}
          requerido
        />

        <input type="hidden" {...register("timezone")} />

        <Boton type="submit" tono="primario" tamano="lg" ancho cargando={isSubmitting}>
          Crear cuenta
        </Boton>

        <p className="text-footnote text-muted">
          Las cuentas nuevas quedan pendientes de aprobación. Podrás configurarlo todo desde el
          primer momento.
        </p>
      </form>
    </MarcoAcceso>
  );
}
