/**
 * Pantalla de espera de la primera carga.
 *
 * Deliberadamente sobria: aparece solo mientras se comprueba si hay sesión, y
 * un movimiento llamativo aquí solo haría notar la espera.
 */

export function Cargando() {
  return (
    <div
      className="flex min-h-dvh items-center justify-center bg-bg"
      role="status"
      aria-live="polite"
    >
      <span className="sr-only">Cargando…</span>
      <span
        aria-hidden="true"
        className="size-6 animate-[hl-spin_0.8s_linear_infinite] rounded-full border-2 border-line-strong border-t-accent"
      />
    </div>
  );
}
