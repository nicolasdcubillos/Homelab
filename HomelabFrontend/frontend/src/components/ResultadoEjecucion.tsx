/**
 * Resultado estructurado de una corrida.
 *
 * StockWatcher publica, además del log de texto, un resumen JSON con cada
 * hallazgo nuevo (producto, tienda, talla, precio, imagen). Esta tarjeta lo
 * pinta con los mismos componentes del resto del panel — nada de volver a
 * leer el log como texto plano cuando ya tenemos los datos.
 */

import { Insignia } from "@/components/Insignia";
import { IconoEnlaceExterno, IconoImagen } from "@/components/iconos";
import { cx } from "@/lib/cx";
import type { Resultado } from "@/lib/tipos";

type Props = {
  resultado: Resultado | null | undefined;
  className?: string;
};

export function ResultadoEjecucion({ resultado, className }: Props) {
  if (!resultado) return null;

  const hits = resultado.hit_details ?? [];

  return (
    <div className={cx("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-footnote text-muted">
        <span>
          <span className="font-semibold text-fg">{resultado.new_hits ?? 0}</span>{" "}
          {(resultado.new_hits ?? 0) === 1 ? "hallazgo nuevo" : "hallazgos nuevos"}
        </span>
        <span>
          {resultado.stores_scanned ?? 0} {(resultado.stores_scanned ?? 0) === 1 ? "tienda" : "tiendas"} revisadas
        </span>
        {(resultado.stores_failed ?? 0) > 0 && (
          <span className="text-warn">
            {resultado.stores_failed} {resultado.stores_failed === 1 ? "tienda falló" : "tiendas fallaron"}
          </span>
        )}
      </div>

      {hits.length === 0 ? (
        <p className="rounded-md bg-neutral-soft px-3 py-2 text-footnote text-muted">
          No hubo novedades de stock en esta corrida.
        </p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {hits.map((hit, indice) => (
            <TarjetaHit key={`${hit.url}-${indice}`} hit={hit} />
          ))}
        </ul>
      )}
    </div>
  );
}

function TarjetaHit({ hit }: { hit: Resultado["hit_details"][number] }) {
  return (
    <li className="flex gap-3 rounded-lg border border-line bg-surface p-3 shadow-e1">
      <div className="size-16 shrink-0 overflow-hidden rounded-md bg-neutral-soft">
        {hit.image ? (
          <img
            src={hit.image}
            alt=""
            className="size-full object-cover"
            loading="lazy"
            onError={(evento) => {
              evento.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-faint">
            <IconoImagen className="size-6" />
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-subhead font-medium">{hit.product}</p>
        <p className="mt-0.5 truncate text-footnote text-muted">
          {hit.store} · {hit.variant}
        </p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {hit.price && (
            <span className="text-subhead font-semibold text-accent">{hit.price}</span>
          )}
          {!hit.color_matched && (
            <Insignia tono="aviso" punto={false}>
              Color distinto
            </Insignia>
          )}
        </div>

        <a
          href={hit.url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1.5 inline-flex items-center gap-1 text-footnote font-medium text-accent hover:underline"
        >
          Ver producto
          <IconoEnlaceExterno className="size-3.5" />
        </a>
      </div>
    </li>
  );
}
