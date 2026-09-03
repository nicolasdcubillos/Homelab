/** Une clases condicionales sin arrastrar una dependencia para ello. */
export function cx(...partes: Array<string | false | null | undefined>): string {
  return partes.filter(Boolean).join(" ");
}
