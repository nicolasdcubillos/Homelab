import { BotonEnlace } from "@/components/Boton";
import { Pantalla } from "@/components/Pantalla";

export function NoEncontrado() {
  return (
    <Pantalla
      titulo="Esta página no existe"
      descripcion="Puede que el enlace esté mal escrito o que la sección se haya movido."
    >
      <BotonEnlace to="/" tono="primario">
        Volver al inicio
      </BotonEnlace>
    </Pantalla>
  );
}
