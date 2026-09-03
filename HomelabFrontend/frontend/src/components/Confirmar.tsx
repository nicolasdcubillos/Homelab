/**
 * Confirmación de una acción destructiva.
 *
 * Para lo irreversible de verdad —borrar una cuenta ajena o toda la propia
 * configuración— no basta un "¿seguro?": se exige teclear una palabra. La
 * fricción es deliberada y proporcional al daño.
 */

import { useEffect, useId, useState } from "react";

import { Boton } from "./Boton";
import { Campo } from "./Campos";
import { Hoja } from "./Hoja";

type Props = {
  abierta: boolean;
  onCerrar: () => void;
  onConfirmar: () => void;
  titulo: string;
  descripcion: React.ReactNode;
  textoConfirmar?: string;
  /** Si se indica, hay que teclearlo exactamente para habilitar el botón. */
  palabraClave?: string;
  etiquetaPalabraClave?: string;
  /**
   * Condición extra para habilitar el botón, además de `palabraClave`. Úsalo
   * cuando la confirmación depende de un campo propio de quien llama (por
   * ejemplo una contraseña, que no se puede comparar en el cliente).
   */
  confirmarDeshabilitado?: boolean;
  cargando?: boolean;
};

export function Confirmar({
  abierta,
  onCerrar,
  onConfirmar,
  titulo,
  descripcion,
  textoConfirmar = "Eliminar",
  palabraClave,
  etiquetaPalabraClave,
  confirmarDeshabilitado = false,
  cargando = false,
}: Props) {
  const [escrito, setEscrito] = useState("");
  const idCampo = useId();

  useEffect(() => {
    // La hoja se reutiliza entre aperturas: hay que vaciar el campo tecleado
    // al volver a abrirla, y un efecto es el único enganche a esa transición.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (abierta) setEscrito("");
  }, [abierta]);

  const habilitado =
    (!palabraClave || escrito.trim() === palabraClave) && !confirmarDeshabilitado;

  return (
    <Hoja
      abierta={abierta}
      onCerrar={onCerrar}
      titulo={titulo}
      pie={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Boton tono="secundario" onClick={onCerrar} disabled={cargando}>
            Cancelar
          </Boton>
          <Boton
            tono="peligro"
            onClick={onConfirmar}
            disabled={!habilitado}
            cargando={cargando}
          >
            {textoConfirmar}
          </Boton>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="text-body text-muted">{descripcion}</div>

        {palabraClave && (
          <Campo
            id={idCampo}
            etiqueta={etiquetaPalabraClave ?? `Escribe «${palabraClave}» para confirmar`}
            value={escrito}
            onChange={(evento) => setEscrito(evento.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder={palabraClave}
          />
        )}
      </div>
    </Hoja>
  );
}
