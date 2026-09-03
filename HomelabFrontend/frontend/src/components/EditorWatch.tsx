/**
 * Editor de una vigilancia de StockWatcher.
 *
 * Vive en una hoja para que crear y editar sean la misma superficie y para que
 * en el teléfono se sienta como una app nativa. Los campos van en el orden en
 * que uno piensa la vigilancia: qué busco, qué descarto, en qué forma lo
 * quiero, hasta cuánto pago y dónde me avisan.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Boton } from "@/components/Boton";
import { Area, Campo, Casilla, Interruptor, Selector } from "@/components/Campos";
import { Aviso } from "@/components/Estados";
import { Hoja, PieDeHoja } from "@/components/Hoja";
import { useCrearWatch, useActualizarWatch } from "@/lib/consultas";
import { aplicarErroresDeApi } from "@/lib/errores";
import { GENERO } from "@/lib/etiquetas";
import type { Canal, Watch } from "@/lib/tipos";
import { aLista, deLista, esquemaWatch, type DatosWatch } from "@/lib/validacion";

const GENEROS = [
  { valor: "unisex", texto: GENERO.unisex },
  { valor: "mens", texto: GENERO.mens },
  { valor: "womens", texto: GENERO.womens },
] as const;

const VACIO: DatosWatch = {
  name: "",
  enabled: true,
  match_terms: "",
  exclude_terms: "",
  variants: "",
  colors: "",
  countries: "",
  gender: "unisex",
  max_price: "",
  currency: "USD",
  notify_channels: [],
};

type Props = {
  abierta: boolean;
  watch: Watch | null;
  canalesDisponibles: Canal[];
  onCerrar: () => void;
  onGuardado: (mensaje: string) => void;
};

export function EditorWatch({ abierta, watch, canalesDisponibles, onCerrar, onGuardado }: Props) {
  const crear = useCrearWatch();
  const actualizar = useActualizarWatch();
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch: observar,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<DatosWatch>({ resolver: zodResolver(esquemaWatch), defaultValues: VACIO });

  useEffect(() => {
    if (!abierta) return;
    setErrorGeneral(null);
    reset(
      watch
        ? {
            name: watch.name,
            enabled: watch.enabled,
            match_terms: deLista(watch.match_terms),
            exclude_terms: deLista(watch.exclude_terms),
            variants: deLista(watch.variants),
            colors: deLista(watch.colors),
            countries: deLista(watch.countries),
            gender: watch.gender as DatosWatch["gender"],
            max_price: watch.max_price ?? "",
            currency: watch.currency,
            notify_channels: watch.notify_channels as DatosWatch["notify_channels"],
          }
        : VACIO,
    );
  }, [abierta, watch, reset]);

  const canales = observar("notify_channels") ?? [];
  const activa = observar("enabled");

  const alternarCanal = (canal: Canal, activo: boolean) => {
    const siguiente = activo
      ? [...canales.filter((c) => c !== canal), canal]
      : canales.filter((c) => c !== canal);
    setValue("notify_channels", siguiente, { shouldDirty: true });
  };

  const enviar = handleSubmit(async (datos) => {
    setErrorGeneral(null);
    const cuerpo = {
      name: datos.name,
      enabled: datos.enabled,
      match_terms: aLista(datos.match_terms),
      exclude_terms: aLista(datos.exclude_terms),
      variants: aLista(datos.variants),
      colors: aLista(datos.colors),
      countries: aLista(datos.countries),
      gender: datos.gender,
      max_price: datos.max_price?.trim() ? datos.max_price.trim() : null,
      currency: datos.currency,
      notify_channels: datos.notify_channels,
    };

    try {
      if (watch) {
        await actualizar.mutateAsync({ id: watch.id, datos: cuerpo });
        onGuardado(`Guardamos los cambios de «${datos.name}».`);
      } else {
        await crear.mutateAsync(cuerpo);
        onGuardado(`Ya estamos vigilando «${datos.name}».`);
      }
      onCerrar();
    } catch (error) {
      setErrorGeneral(aplicarErroresDeApi(error, setError, Object.keys(VACIO) as Array<keyof DatosWatch>));
    }
  });

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo={watch ? "Editar vigilancia" : "Nueva vigilancia"}
      pie={
        <PieDeHoja>
          <Boton tono="sutil" onClick={onCerrar} type="button">
            Cancelar
          </Boton>
          <Boton tono="primario" onClick={() => void enviar()} cargando={isSubmitting}>
            {watch ? "Guardar cambios" : "Crear vigilancia"}
          </Boton>
        </PieDeHoja>
      }
    >
      <form onSubmit={enviar} noValidate className="space-y-5">
        {errorGeneral && <Aviso tono="alerta">{errorGeneral}</Aviso>}

        <Campo
          {...register("name")}
          etiqueta="Nombre"
          placeholder="Air Max 1 Patta"
          descripcion="Solo para que la reconozcas en tu lista."
          error={errors.name?.message}
          requerido
          autoFocus
        />

        <Area
          {...register("match_terms")}
          etiqueta="Términos que debe contener"
          placeholder={"air max 1\npatta"}
          descripcion="Uno por línea. El producto debe contenerlos todos."
          error={errors.match_terms?.message}
          rows={3}
          requerido
        />

        <Area
          {...register("exclude_terms")}
          etiqueta="Términos que lo descartan"
          placeholder={"kids\ntoddler"}
          descripcion="Opcional. Si aparece alguno, se ignora el producto."
          error={errors.exclude_terms?.message}
          rows={2}
        />

        <div className="grid gap-5 sm:grid-cols-2">
          <Area
            {...register("variants")}
            etiqueta="Tallas"
            placeholder={"42\n42.5\n43"}
            descripcion="Una por línea. Vacío = cualquier talla."
            error={errors.variants?.message}
            rows={3}
          />
          <Area
            {...register("colors")}
            etiqueta="Colores"
            placeholder={"negro\nblanco"}
            descripcion="Opcional, uno por línea."
            error={errors.colors?.message}
            rows={3}
          />
        </div>

        <Selector
          {...register("gender")}
          etiqueta="Género"
          opciones={GENEROS}
          error={errors.gender?.message}
        />

        <div className="grid grid-cols-[1fr_auto] gap-3">
          <Campo
            {...register("max_price")}
            etiqueta="Precio máximo"
            inputMode="decimal"
            placeholder="180"
            descripcion="Opcional. Por encima de este precio no te avisamos."
            error={errors.max_price?.message}
          />
          <Campo
            {...register("currency")}
            etiqueta="Moneda"
            placeholder="USD"
            maxLength={3}
            className="w-24 uppercase"
            error={errors.currency?.message}
          />
        </div>

        <Campo
          {...register("countries")}
          etiqueta="Países"
          placeholder="CO, US, ES"
          descripcion="Códigos de dos letras separados por coma. Vacío = los de tu configuración general."
          error={errors.countries?.message}
        />

        <fieldset className="space-y-2">
          <legend className="mb-2 text-subhead font-medium text-fg">Avisarme por</legend>
          {canalesDisponibles.map((canal) => (
            <Casilla
              key={canal}
              etiqueta={canal === "whatsapp" ? "WhatsApp" : "Correo"}
              checked={canales.includes(canal)}
              onChange={(marcado) => alternarCanal(canal, marcado)}
            />
          ))}
          <p className="pt-1 text-footnote text-muted">
            Si no marcas ninguno se usan los canales que tengas activos para StockWatcher.
          </p>
        </fieldset>

        <Interruptor
          checked={activa}
          onChange={(valor) => setValue("enabled", valor, { shouldDirty: true })}
          etiqueta="Vigilancia activa"
          descripcion="Puedes pausarla sin borrar su configuración."
        />

        {/* Permite enviar con Intro desde cualquier campo sin duplicar el botón. */}
        <button type="submit" className="sr-only" tabIndex={-1} aria-hidden="true" />
      </form>
    </Hoja>
  );
}
