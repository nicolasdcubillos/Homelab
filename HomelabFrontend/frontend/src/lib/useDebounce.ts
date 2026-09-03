/**
 * Retrasa un valor cambiante. Se usa en la búsqueda del panel de admin para
 * no disparar una petición por cada tecla.
 */

import { useEffect, useState } from "react";

export function useDebounce<T>(valor: T, ms: number): T {
  const [retrasado, setRetrasado] = useState(valor);

  useEffect(() => {
    const id = setTimeout(() => setRetrasado(valor), ms);
    return () => clearTimeout(id);
  }, [valor, ms]);

  return retrasado;
}
