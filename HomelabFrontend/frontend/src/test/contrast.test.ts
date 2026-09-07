/**
 * El contraste del sistema visual se mide, no se estima.
 *
 * Este test lee `theme.css` como fuente de verdad y comprueba cada pareja
 * primer plano / fondo que la interfaz usa de verdad, en los dos temas. Si
 * alguien retoca un token y rompe WCAG AA, falla aquí y no en producción.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { contrastRatio, parseOklch, type Rgb } from "@/lib/color";

// En jsdom `import.meta.url` es una URL http, así que la ruta se resuelve
// desde la raíz del proyecto, que es el cwd con el que corre Vitest.
const css = readFileSync(resolve(process.cwd(), "src/styles/theme.css"), "utf8");

function bloque(selector: string): Record<string, string> {
  const inicio = css.indexOf(selector + " {");
  if (inicio < 0) throw new Error(`No encontré el bloque ${selector}`);
  const fin = css.indexOf("\n}", inicio);
  const cuerpo = css.slice(inicio, fin);

  const tokens: Record<string, string> = {};
  for (const linea of cuerpo.split("\n")) {
    const m = /^\s*(--c-[\w-]+):\s*(.+);\s*$/.exec(linea);
    if (m) tokens[m[1]!] = m[2]!.trim();
  }
  return tokens;
}

const temas = {
  claro: bloque(":root"),
  oscuro: bloque('[data-theme="dark"]'),
};

function color(tema: Record<string, string>, token: string): Rgb {
  const crudo = tema[token];
  if (!crudo) throw new Error(`Falta el token ${token}`);
  const parsed = parseOklch(crudo);
  if (!parsed) throw new Error(`No pude interpretar ${token}: ${crudo}`);
  return parsed.rgb;
}

/** Texto normal: 4.5:1. Texto grande, iconos y controles: 3:1. */
const PAREJAS: Array<[string, string, number]> = [
  ["--c-fg", "--c-bg", 4.5],
  ["--c-fg", "--c-surface", 4.5],
  ["--c-fg", "--c-surface-sunken", 4.5],
  ["--c-fg", "--c-surface-raised", 4.5],
  ["--c-fg-secondary", "--c-bg", 4.5],
  ["--c-fg-secondary", "--c-surface", 4.5],
  ["--c-fg-secondary", "--c-surface-raised", 4.5],
  ["--c-fg-tertiary", "--c-bg", 4.5],
  ["--c-fg-tertiary", "--c-surface", 4.5],
  ["--c-fg-tertiary", "--c-surface-sunken", 4.5],
  ["--c-fg-tertiary", "--c-surface-raised", 4.5],
  ["--c-accent", "--c-bg", 4.5],
  ["--c-accent", "--c-surface", 4.5],
  ["--c-accent-hover", "--c-surface", 4.5],
  ["--c-fg-on-accent", "--c-accent", 4.5],
  ["--c-fg-on-accent", "--c-danger", 4.5],
  ["--c-fg-on-accent", "--c-danger-hover", 4.5],
  ["--c-ok", "--c-surface", 4.5],
  ["--c-ok", "--c-ok-soft", 4.5],
  ["--c-warn", "--c-surface", 4.5],
  ["--c-warn", "--c-warn-soft", 4.5],
  ["--c-danger", "--c-surface", 4.5],
  ["--c-danger", "--c-danger-soft", 4.5],
  ["--c-accent-quiet", "--c-accent-soft", 4.5],
  ["--c-fg-secondary", "--c-neutral-soft", 4.5],
  ["--c-border-strong", "--c-surface", 3],
  ["--c-border-strong", "--c-bg", 3],
];

describe.each(Object.entries(temas))("tema %s", (nombre, tema) => {
  it.each(PAREJAS)("%s sobre %s cumple AA", (frente, fondo, minimo) => {
    const razon = contrastRatio(color(tema, frente), color(tema, fondo));
    expect(
      razon,
      `${nombre}: ${frente} sobre ${fondo} da ${razon.toFixed(2)}:1, necesita ${minimo}:1`,
    ).toBeGreaterThanOrEqual(minimo);
  });

  it("el borde ordinario se distingue de la superficie", () => {
    // Un separador no es un control: no necesita 3:1, pero sí ser visible.
    const razon = contrastRatio(color(tema, "--c-border"), color(tema, "--c-surface"));
    expect(razon).toBeGreaterThan(1.15);
  });
});
