import { useAvisos } from "@/components/Avisos";
import { Selector } from "@/components/Campos";
import { EstadoError, EsqueletoLista } from "@/components/Estados";
import { Fila, FilaValor, Lista } from "@/components/Lista";
import { mensajeDeError } from "@/lib/errores";
import { NIVEL_REGIMEN } from "@/lib/etiquetas";
import { useAccesosRegimen, useConcederRegimen, useRevocarRegimen } from "@/lib/regimen";
import type { NivelRegimen } from "@/lib/tipos";

const OPCIONES = [
  { valor: "", texto: "Sin acceso" },
  { valor: "viewer", texto: NIVEL_REGIMEN.viewer },
  { valor: "operator", texto: NIVEL_REGIMEN.operator },
];

export function PermisoRegimen({ id, esAdmin }: { id: string; esAdmin: boolean }) {
  const accesos = useAccesosRegimen(!esAdmin);
  const conceder = useConcederRegimen();
  const revocar = useRevocarRegimen();
  const avisos = useAvisos();
  if (esAdmin) return <Lista titulo="Régimen de mercado">
    <FilaValor etiqueta="Acceso" valor="Operador (heredado)"
      descripcion="Los administradores heredan operación de régimen. No depende del permiso de trading." />
  </Lista>;
  if (accesos.isPending) return <EsqueletoLista filas={1} />;
  if (accesos.isError) return <EstadoError className="[&_button]:min-h-11" mensaje="No pudimos leer el permiso de régimen."
    onReintentar={() => void accesos.refetch()} />;
  const actual = accesos.data?.items.find((item) => item.user_id === id)?.level ?? "";
  const cambiar = async (valor: string) => {
    try {
      if (!valor) await revocar.mutateAsync(id);
      else await conceder.mutateAsync({ id, level: valor as NivelRegimen });
      avisos.exito(valor ? "Permiso de régimen actualizado." : "Acceso a régimen revocado.");
    } catch (causa) {
      avisos.error(mensajeDeError(causa, "No pudimos cambiar el permiso de régimen."));
    }
  };
  return <Lista titulo="Régimen de mercado"
    nota="Permiso independiente de Trading y vigilancias. El operador cambia el modelo compartido; el lector consulta y gestiona solo su propia suscripción.">
    <Fila className="py-3">
      <Selector etiqueta="Acceso al régimen de mercado" opciones={OPCIONES}
        value={actual} onChange={(evento) => void cambiar(evento.target.value)}
        disabled={conceder.isPending || revocar.isPending} className="w-full" />
    </Fila>
  </Lista>;
}
