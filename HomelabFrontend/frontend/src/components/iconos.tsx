/**
 * Iconos de la interfaz.
 *
 * Dibujados con la misma retícula de 24, el mismo grosor de trazo y las mismas
 * terminaciones redondeadas, para que la barra de pestañas se lea como un
 * conjunto y no como iconos de sitios distintos.
 */

type Props = { className?: string };

const BASE = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function IconoInicio({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M3.5 10.5 12 4l8.5 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-3.5V15h-7v5.5H5A1.5 1.5 0 0 1 3.5 19v-8.5Z" />
    </svg>
  );
}

export function IconoRegimen({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h16" />
      <circle cx="8" cy="6" r="2" fill="var(--c-surface)" />
      <circle cx="16" cy="12" r="2" fill="var(--c-surface)" />
      <circle cx="11" cy="18" r="2" fill="var(--c-surface)" />
    </svg>
  );
}

export function IconoMenuMas({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="5" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="19" cy="12" r="1.5" />
    </svg>
  );
}

export function IconoVigilancia({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
      <path d="M11 8.5v2.5l1.75 1.25" />
    </svg>
  );
}

export function IconoPortafolio({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M4 19.5V13m5 6.5V7.5m5 12v-4.5m5 4.5V4.5" />
    </svg>
  );
}

/** Velas japonesas: se lee como «mercado» sin chocar con el gráfico de barras
 *  del portafolio ni con la línea de actividad. */
export function IconoTrading({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M8 4v3.5m0 8V19M16 6v3.5m0 7V20" />
      <rect x="5.5" y="7.5" width="5" height="8" rx="1" />
      <rect x="13.5" y="9.5" width="5" height="7" rx="1" />
    </svg>
  );
}

export function IconoActividad({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M3.5 12h4l2-5 3.5 10 2.5-6.5 1.5 3h3.5" />
    </svg>
  );
}

export function IconoAjustes({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2m0 13v2M20.5 12h-2m-13 0h-2m12.02-6.02-1.42 1.42M7.9 16.1l-1.42 1.42m11.62 0-1.42-1.42M7.9 7.9 6.48 6.48" />
    </svg>
  );
}

export function IconoAdmin({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M12 3.5 4.5 6.5v5c0 4.2 3 8.1 7.5 9.5 4.5-1.4 7.5-5.3 7.5-9.5v-5L12 3.5Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

export function IconoMas({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M12 5.5v13M5.5 12h13" />
    </svg>
  );
}

export function IconoJugar({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M7.5 5.5v13l11-6.5-11-6.5Z" fill="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

export function IconoDetener({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

export function IconoReloj({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function IconoAtras({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M14.5 5.5 8 12l6.5 6.5" />
    </svg>
  );
}

export function IconoBuscar({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  );
}

export function IconoDocumento({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M6.5 3.5h7l4.5 4.5v12a1 1 0 0 1-1 1h-10.5a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1Z" />
      <path d="M13.5 3.5V8h4.5M8.5 12.5h7M8.5 16h4.5" />
    </svg>
  );
}

export function IconoPapelera({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M4.5 6.5h15M9.5 6.5V4.75a1.25 1.25 0 0 1 1.25-1.25h2.5a1.25 1.25 0 0 1 1.25 1.25V6.5M6.5 6.5l.8 12.1a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12.1" />
    </svg>
  );
}

export function IconoEditar({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M4.5 19.5h3l9.75-9.75a2.12 2.12 0 0 0-3-3L4.5 16.5v3Z" />
    </svg>
  );
}

export function IconoSalir({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M14 7.5V5.25A1.75 1.75 0 0 0 12.25 3.5H5.25A1.75 1.75 0 0 0 3.5 5.25v13.5A1.75 1.75 0 0 0 5.25 20.5h7A1.75 1.75 0 0 0 14 18.75V16.5M9.5 12h11m0 0-3-3m3 3-3 3" />
    </svg>
  );
}

export function IconoCampana({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5s1.5-1.5 1.5-5.5Z" />
      <path d="M10 18.5a2 2 0 0 0 4 0" />
    </svg>
  );
}

export function IconoSol({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v1.5M12 19.5V21M21 12h-1.5M4.5 12H3m14.36-6.36-1.06 1.06M7.7 16.3l-1.06 1.06m10.72 0-1.06-1.06M7.7 7.7 6.64 6.64" />
    </svg>
  );
}

export function IconoLuna({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
    </svg>
  );
}

export function IconoEnlaceExterno({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <path d="M10 6H6.5A2.5 2.5 0 0 0 4 8.5v9A2.5 2.5 0 0 0 6.5 20h9a2.5 2.5 0 0 0 2.5-2.5V14M14 4h6v6M20 4l-9 9" />
    </svg>
  );
}

export function IconoImagen({ className }: Props) {
  return (
    <svg {...BASE} className={className} aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <circle cx="9" cy="10" r="1.75" />
      <path d="m5 18 4.5-5 3.5 3.5 2.5-3 4.5 5.5" />
    </svg>
  );
}
