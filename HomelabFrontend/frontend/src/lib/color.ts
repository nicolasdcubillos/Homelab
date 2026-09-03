/**
 * Conversión OKLCH → sRGB y razón de contraste WCAG 2.1.
 *
 * Está en el código de producción (y no solo en los tests) porque el test de
 * contraste debe medir exactamente los mismos valores que sirve el navegador:
 * si la conversión viviera solo en el test, podría divergir del CSS real.
 */

export type Rgb = { r: number; g: number; b: number };

function oklabToLinearSrgb(L: number, a: number, b: number): Rgb {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;

  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;

  return {
    r: 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    g: -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    b: -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  };
}

function gamma(channel: number): number {
  const c = channel <= 0.0031308 ? 12.92 * channel : 1.055 * Math.pow(channel, 1 / 2.4) - 0.055;
  return Math.min(1, Math.max(0, c));
}

/** Convierte `oklch(L C H)` (L en 0..1, H en grados) a sRGB 0..1. */
export function oklchToRgb(L: number, C: number, H: number): Rgb {
  const hRad = (H * Math.PI) / 180;
  const lin = oklabToLinearSrgb(L, C * Math.cos(hRad), C * Math.sin(hRad));
  return { r: gamma(lin.r), g: gamma(lin.g), b: gamma(lin.b) };
}

/** Acepta `oklch(0.52 0.196 272)` y también `oklch(0 0 0 / 0.4)`. */
export function parseOklch(value: string): { rgb: Rgb; alpha: number } | null {
  const match = /oklch\(\s*([\d.]+%?)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+%?)\s*)?\)/i.exec(
    value,
  );
  if (!match) return null;

  const [, rawL, rawC, rawH, rawAlpha] = match;
  const L = rawL!.endsWith("%") ? Number.parseFloat(rawL!) / 100 : Number.parseFloat(rawL!);
  const alpha = rawAlpha
    ? rawAlpha.endsWith("%")
      ? Number.parseFloat(rawAlpha) / 100
      : Number.parseFloat(rawAlpha)
    : 1;

  return { rgb: oklchToRgb(L, Number.parseFloat(rawC!), Number.parseFloat(rawH!)), alpha };
}

function relativeLuminance({ r, g, b }: Rgb): number {
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** Razón de contraste WCAG 2.1 entre dos colores opacos. */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Compone un color con alfa sobre un fondo opaco. */
export function over(fg: Rgb, alpha: number, bg: Rgb): Rgb {
  return {
    r: fg.r * alpha + bg.r * (1 - alpha),
    g: fg.g * alpha + bg.g * (1 - alpha),
    b: fg.b * alpha + bg.b * (1 - alpha),
  };
}
