import { act, cleanup, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";
import type * as ApiModule from "@/lib/api";
import { claves } from "@/lib/consultas";
import {
  clavesRegimen, fechaRegimen, numeroRegimen, useEjecucionRegimen,
  useGuardarConfigRegimen, useHistoriaRegimen, useOperacionesRegimen, urlFuente,
} from "@/lib/regimen";
import type {
  ConfigRegimen, DatosSnapshotRegimen, EjecucionRegimen, HistoriaRegimen,
  InformeRegimen, ResumenRegimen, Sesion, SuscripcionRegimen,
} from "@/lib/tipos";
import { Regimen } from "@/routes/Regimen";
import { ProveedorAvisos } from "@/components/Avisos";
import { PermisoRegimen } from "@/components/regimen/PermisoRegimen";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof ApiModule>();
  return { ...original, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});

const FECHA = "2026-09-07T18:00:00Z";
let cliente: QueryClient;
let sesion: Sesion;
let resumen: ResumenRegimen;
let config: ConfigRegimen;
let suscripcion: SuscripcionRegimen;
let historia: HistoriaRegimen;

function snapshot(): DatosSnapshotRegimen {
  const base = { calibration_status: "HEURISTICO_NO_VALIDADO", confidence: "NO_EVALUABLE", transition_status: "NO_EVALUABLE" } as const;
  return {
    as_of: FECHA, model_version: "fixture-v1", mode: "OPERACIONAL",
    context: "Evidencia sintética de prueba; cobertura parcial.", coverage: [],
    horizons: [
      { ...base, horizon: "SHORT", data_status: "SIN_DATOS", score: null, regime: null },
      { ...base, horizon: "MEDIUM", data_status: "INCOMPLETO", score: null, regime: null },
      { ...base, horizon: "LONG", data_status: "COMPLETO", score: 50, regime: "NEUTRAL" },
    ],
  };
}

function trabajo(status: string): EjecucionRegimen {
  return { id: "run-fixture", kind: "ingest", status, requested_at: FECHA,
    started_at: null, finished_at: status === "success" ? FECHA : null,
    detail: "Resultado sintético de prueba.", result: {} };
}

function apiJson(ruta: string): unknown {
  if (ruta === "/auth/me") return sesion;
  switch (ruta.replace("/market-regime", "")) {
    case "/overview": return resumen;
    case "/config": return config;
    case "/coverage": return { items: [] };
    case "/sources": return { items: [] };
    case "/history": return historia;
    case "/reports": return { items: [], total: 0, limit: 10, offset: 0 };
    case "/operations": return { items: [] };
    case "/me/subscription": return suscripcion;
    case "/me/deliveries": return { items: [] };
    default: throw new Error(`Ruta no simulada: ${ruta}`);
  }
}

function Proveedor({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={cliente}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>;
}

function nivel(level: "viewer" | "operator" | null, status = "active") {
  sesion = { csrf_token: "fixture-csrf", user: { id: "usuario-prueba", role: "user", status, regime_level: level,
    trading_level: null, must_change_password: false, email: "fixture@example.test",
    created_at: FECHA, last_login_at: null, timezone: "UTC" } };
  cliente.setQueryData(claves.sesion, sesion);
}

beforeEach(() => {
  vi.clearAllMocks();
  cliente = new QueryClient({ defaultOptions: {
    queries: { retry: false, gcTime: Infinity, staleTime: 30_000 },
    mutations: { retry: false },
  } });
  nivel("viewer");
  resumen = { enabled: true, engine_enabled: true, deliveries_enabled: false,
    snapshot_id: null, snapshot: null, coverage: [], first_snapshot_at: null,
    next_report_at: null, calendar_status: "No disponible", warning: "Advertencia de prueba." };
  config = { version: 1, enabled: true, config: { model_version: "fixture-v1" }, updated_at: FECHA };
  suscripcion = { enabled: false, email: false, whatsapp: false, horizons: ["SHORT", "MEDIUM", "LONG"],
    email_ready: true, whatsapp_ready: false, detail: "", consent_version: "market-regime-v1" };
  historia = { items: [], first_available_at: null, requested_from: FECHA,
    unavailable_before_first: false, total: 0, limit: 20, offset: 0 };
  vi.mocked(api.get).mockImplementation(async (ruta) => apiJson(ruta) as never);
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true, value() { this.setAttribute("open", ""); },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true, value() { this.removeAttribute("open"); },
  });
});

afterEach(() => {
  cleanup(); cliente.clear(); vi.useRealTimers();
});

describe("Estados y evidencia honesta", () => {
  it("distingue sin datos, incompleto y neutral sin convertir null en cero", async () => {
    resumen.snapshot = snapshot();
    render(<Regimen />, { wrapper: Proveedor });
    const corto = await screen.findByRole("article", { name: "Corto plazo" });
    expect(within(corto).getByText("Sin datos")).toBeInTheDocument();
    expect(within(corto).getByText("Score no disponible")).toBeInTheDocument();
    const medio = screen.getByRole("article", { name: "Mediano plazo" });
    expect(within(medio).getByText("Incompleto")).toBeInTheDocument();
    expect(within(medio).getByText("Score no disponible")).toBeInTheDocument();
    const largo = screen.getByRole("article", { name: "Largo plazo" });
    expect(within(largo).getByText("Neutral")).toBeInTheDocument();
    expect(within(largo).getByText("50")).toBeInTheDocument();
    expect(screen.queryByText("0 / 100")).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("muestra el estado vacío y un calendario desconocido sin inventar fechas", async () => {
    render(<Regimen />, { wrapper: Proveedor });
    expect(await screen.findByText("La historia aún no comenzó")).toBeInTheDocument();
    expect(screen.getAllByText("Score no disponible")).toHaveLength(3);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("expone carga y permite reintentar un error de backend", async () => {
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(() => {}));
    const vista = render(<Regimen />, { wrapper: Proveedor });
    expect(await screen.findByRole("status", { name: "Cargando" })).toBeInTheDocument();
    vista.unmount();
    await cliente.cancelQueries({ queryKey: clavesRegimen.raiz });
    cliente.removeQueries({ queryKey: clavesRegimen.raiz });
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(503, "unavailable", "Motor temporalmente no disponible."));
    render(<Regimen />, { wrapper: Proveedor });
    expect(await screen.findByRole("alert")).toHaveTextContent("Motor temporalmente no disponible.");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("La historia aún no comenzó")).toBeInTheDocument();
  });

  it("muestra restricciones de fuentes y nunca activa enlaces de protocolos inseguros", async () => {
    vi.mocked(api.get).mockImplementation(async (ruta) => ruta.endsWith("/sources")
      ? { items: [
        { id: "credit", name: "Fuente restringida de prueba", url: "https://example.test/source",
          terms_url: "https://example.test/terms", status: "BLOQUEADO_LICENCIA", detail: "Requiere autorización." },
        { id: "macro", name: "Fuente sin clave de prueba", url: "javascript:alert(1)",
          terms_url: "", status: "NO_CONFIGURADO" },
      ] } as never : apiJson(ruta) as never);
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Evidencia" }));
    expect(await screen.findByText("Bloqueado por licencia")).toBeInTheDocument();
    expect(screen.getByText("No configurado")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir fuente/ })).toHaveAttribute("href", "https://example.test/source");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});

describe("Permisos y privacidad", () => {
  it.each([null, "suspended", "pending"])("no hace lecturas de régimen sin acceso efectivo: %s", async (estado) => {
    nivel(estado === null ? null : "viewer", estado ?? "active");
    render(<Regimen />, { wrapper: Proveedor });
    expect(screen.getByText("Acceso no disponible")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("un viewer puede leer el modelo pero no operarlo", async () => {
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    const campo = await screen.findByRole("textbox", { name: "Modelo y reglas (JSON)" });
    expect(campo).toHaveAttribute("readonly");
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Ingestar fuentes" })).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith("/market-regime/operations", expect.anything());
  });

  it("incluye identidad y filtros en caché sin mezclar variantes ni Trading", () => {
    expect(clavesRegimen.consulta("a", "/history", { range: "1w", offset: 0 }))
      .not.toEqual(clavesRegimen.consulta("a", "/history", { range: "12m", offset: 0 }));
    expect(clavesRegimen.consulta("a", "/me/subscription"))
      .not.toEqual(clavesRegimen.consulta("b", "/me/subscription"));
    expect(clavesRegimen.raiz[0]).not.toBe("trading");
  });

  it("rechaza una mutación invocada por un viewer incluso fuera de los controles", async () => {
    const { result } = renderHook(() => useGuardarConfigRegimen(), { wrapper: Proveedor });
    await expect(result.current.mutateAsync(config)).rejects.toMatchObject({ status: 403 });
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("el administrador hereda operación sin permiso de trading", async () => {
    sesion.user.role = "admin"; sesion.user.regime_level = null;
    cliente.setQueryData(claves.sesion, sesion);
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    expect(await screen.findByRole("button", { name: "Ingestar fuentes" })).toBeEnabled();
  });

  it("el selector administrativo concede y revoca solo régimen", async () => {
    sesion.user.role = "admin"; cliente.setQueryData(claves.sesion, sesion);
    let items: { user_id: string; level: string }[] = [];
    vi.mocked(api.get).mockImplementation(async (ruta) => ruta.endsWith("/access")
      ? { items } as never : apiJson(ruta) as never);
    vi.mocked(api.put).mockImplementation(async () => {
      items = [{ user_id: "destinatario-fixture", level: "viewer" }];
      return items[0] as never;
    });
    vi.mocked(api.delete).mockImplementation(async () => { items = []; return undefined as never; });
    render(<ProveedorAvisos><PermisoRegimen id="destinatario-fixture" esAdmin={false} /></ProveedorAvisos>, { wrapper: Proveedor });
    const selector = await screen.findByRole("combobox", { name: "Acceso al régimen de mercado" });
    await userEvent.selectOptions(selector, "viewer");
    await waitFor(() => expect(selector).toHaveValue("viewer"));
    expect(api.put).toHaveBeenCalledWith("/market-regime/access/destinatario-fixture", { level: "viewer" });
    await userEvent.selectOptions(selector, "");
    await waitFor(() => expect(selector).toHaveValue(""));
    expect(api.delete).toHaveBeenCalledWith("/market-regime/access/destinatario-fixture");
    expect(vi.mocked(api.get).mock.calls.every(([ruta]) => !ruta.includes("/trading"))).toBe(true);
  });

  it("muestra herencia de administrador sin cargar preferencias ajenas", () => {
    sesion.user.role = "admin"; cliente.setQueryData(claves.sesion, sesion);
    render(<ProveedorAvisos><PermisoRegimen id="admin-fixture" esAdmin /></ProveedorAvisos>, { wrapper: Proveedor });
    expect(screen.getByText("Operador (heredado)")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});

describe("Historia e informes persistidos", () => {
  it("consulta cada rango real y explica el período no disponible", async () => {
    historia.first_available_at = FECHA;
    historia.unavailable_before_first = true;
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Historia" }));
    expect(await screen.findByText(/No disponible antes de/)).toBeInTheDocument();
    for (const [nombre, range] of [["1 semana", "1w"], ["3 meses", "3m"], ["6 meses", "6m"], ["12 meses", "12m"], ["1 mes", "1m"]]) {
      await userEvent.click(screen.getByRole("button", { name: nombre! }));
      await waitFor(() => expect(api.get).toHaveBeenCalledWith("/market-regime/history",
        expect.objectContaining({ query: { range, limit: 20, offset: 0 } })));
    }
    expect(screen.getByText("No hay snapshots en este rango")).toBeInTheDocument();
  });

  it("cancela el rango anterior al cambiar de consulta", async () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => {}));
    const hook = renderHook(({ rango }) => useHistoriaRegimen(rango),
      { wrapper: Proveedor, initialProps: { rango: "1w" as "1w" | "12m" } });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(api.get).mock.calls[0]?.[1]?.signal;
    hook.rerender({ rango: "12m" });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(signal?.aborted).toBe(true);
  });

  it("abre el snapshot exacto de la historia y conserva su trazabilidad", async () => {
    const item = { id: "snapshot-fixture", created_at: FECHA, sha256: "sha-fixture", data: snapshot() };
    historia.items = [item]; historia.total = 1;
    vi.mocked(api.get).mockImplementation(async (ruta) => ruta.endsWith("/snapshots/snapshot-fixture")
      ? item as never : apiJson(ruta) as never);
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Historia" }));
    await userEvent.click(await screen.findByRole("button", { name: /^Ver snapshot del/ }));
    const detalle = screen.getByRole("dialog", { name: "Snapshot registrado" });
    expect(await within(detalle).findByText("sha-fixture")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/market-regime/snapshots/snapshot-fixture", expect.anything());
  });

  it("abre las trece secciones y la matriz del informe sin renderizar HTML arbitrario", async () => {
    const informe: InformeRegimen = {
      id: "report-fixture", snapshot_id: "snapshot-fixture", week_key: "2026-W36",
      created_at: FECHA, sha256: "hash-fixture",
      data: {
        title: "Informe de prueba", brief: "Lectura breve de prueba.", narrative_status: "DESHABILITADO",
        sections: Array.from({ length: 13 }, (_, n) => ({ number: n + 1, title: `Sección ${n + 1}`, text: `Evidencia ${n + 1}` })),
        matrix: [{ series_id: "USDJPY-fixture", reading: "Cotización oficial demorada.", direction: "NO_EVALUABLE",
          value: 145.25, unit: "JPY por USD", source_url: "https://example.test/fed", observed_at: FECHA }],
        html: "<script>window.inseguro = true</script>", text: "Informe de prueba",
      },
    };
    vi.mocked(api.get).mockImplementation(async (ruta) => ruta.endsWith("/reports")
      ? { items: [informe], total: 1, offset: 0, limit: 10 } as never
      : ruta.endsWith("/reports/report-fixture") ? informe as never : apiJson(ruta) as never);
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Informes" }));
    expect(await screen.findByText("Lectura breve de prueba.")).toBeInTheDocument();
    expect(screen.getByText("13. Sección 13")).toBeInTheDocument();
    expect(screen.getByText("145,25 JPY por USD")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(api.get).toHaveBeenCalledWith("/market-regime/reports/report-fixture", expect.anything());
  });
});

describe("Suscripción y operación", () => {
  it("exige consentimiento separado y usa únicamente la ruta personal", async () => {
    vi.mocked(api.put).mockResolvedValue({ ...suscripcion, enabled: true, email: true });
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Mi suscripción" }));
    await userEvent.click(await screen.findByRole("switch", { name: "Recibir informes semanales" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Correo electrónico" }));
    expect(screen.getByRole("button", { name: "Guardar suscripción" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Acepto recibir/ }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar suscripción" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/market-regime/me/subscription", {
      enabled: true, email: true, whatsapp: false, horizons: ["SHORT", "MEDIUM", "LONG"], accept_consent: true,
    }));
    expect(api.post).not.toHaveBeenCalled();
  });

  it("permite darse de baja sin aceptar nuevamente consentimiento", async () => {
    suscripcion.enabled = true; suscripcion.email = true;
    vi.mocked(api.put).mockResolvedValue({ ...suscripcion, enabled: false });
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Mi suscripción" }));
    await userEvent.click(await screen.findByRole("switch", { name: "Recibir informes semanales" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar sin suscripción" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/market-regime/me/subscription",
      expect.objectContaining({ enabled: false, accept_consent: false })));
  });

  it("conserva borrador y versión ante 409, y ofrece recarga explícita", async () => {
    nivel("operator");
    vi.mocked(api.patch).mockRejectedValue(new ApiError(409, "version_conflict", "Versión distinta"));
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    const campo = await screen.findByRole("textbox", { name: "Modelo y reglas (JSON)" });
    await userEvent.clear(campo);
    await userEvent.type(campo, '{{"borrador": true}');
    await userEvent.click(screen.getByRole("button", { name: "Guardar configuración compartida" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tu borrador se conserva");
    expect(campo).toHaveValue('{"borrador": true}');
    expect(api.patch).toHaveBeenCalledWith("/market-regime/config", { version: 1, enabled: true, config: { borrador: true } });
    config = { ...config, version: 2, config: { server: true } };
    await userEvent.click(screen.getByRole("button", { name: "Cargar versión vigente y descartar borrador" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Modelo y reglas (JSON)" })).toHaveValue(JSON.stringify(config.config, null, 2)));
    expect(screen.getByRole("button", { name: "Guardar configuración compartida" })).toBeEnabled();
  });

  it("no avanza silenciosamente la versión de un borrador al refrescar el servidor", async () => {
    nivel("operator");
    vi.mocked(api.patch).mockResolvedValue({ ...config, version: 3 });
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    await screen.findByRole("textbox", { name: "Modelo y reglas (JSON)" });
    config = { ...config, version: 2 };
    await act(async () => { await cliente.invalidateQueries({ queryKey: clavesRegimen.consulta("usuario-prueba", "/config") }); });
    await userEvent.click(screen.getByRole("button", { name: "Guardar configuración compartida" }));
    expect(api.patch).toHaveBeenCalledWith("/market-regime/config", expect.objectContaining({ version: 1 }));
  });

  it("rechaza JSON inválido sin enviar una mutación", async () => {
    nivel("operator");
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    const campo = await screen.findByRole("textbox", { name: "Modelo y reglas (JSON)" });
    await userEvent.clear(campo); await userEvent.type(campo, "no-json");
    await userEvent.click(screen.getByRole("button", { name: "Guardar configuración compartida" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("objeto JSON válido");
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("solicita la ingesta manual y presenta el progreso real devuelto", async () => {
    nivel("operator");
    let solicitado = false;
    vi.mocked(api.post).mockImplementation(async () => { solicitado = true; return trabajo("PENDIENTE") as never; });
    vi.mocked(api.get).mockImplementation(async (ruta) => ruta.endsWith("/runs/run-fixture")
      ? trabajo("EJECUTANDO") as never
      : ruta.endsWith("/operations") ? { items: solicitado ? [trabajo("EJECUTANDO")] : [] } as never
        : apiJson(ruta) as never);
    render(<Regimen />, { wrapper: Proveedor });
    await userEvent.click(screen.getByRole("button", { name: "Modelo y operación" }));
    expect(api.post).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Ingestar fuentes" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/market-regime/runs", { kind: "ingest" }));
    expect((await screen.findAllByText("En curso")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Completado")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Crear snapshot" })).toBeDisabled();
  });

  it("solo sondea ejecuciones activas y se detiene al completar", async () => {
    nivel("operator"); vi.useFakeTimers();
    vi.mocked(api.get).mockResolvedValueOnce(trabajo("EJECUTANDO")).mockResolvedValue(trabajo("INCOMPLETO"));
    renderHook(() => useEjecucionRegimen("run-fixture"), { wrapper: Proveedor });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(api.get).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(api.get).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("no sondea una lista de operaciones inactiva", async () => {
    nivel("operator"); vi.useFakeTimers();
    vi.mocked(api.get).mockResolvedValue({ items: [trabajo("COMPLETO")] });
    renderHook(() => useOperacionesRegimen(), { wrapper: Proveedor });
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(api.get).toHaveBeenCalledTimes(1);
  });
});

it("formatea unidades y fechas sin inventar ceros ni aceptar enlaces inseguros", () => {
  expect(numeroRegimen(null)).toBe("No disponible");
  expect(numeroRegimen(NaN)).toBe("No disponible");
  expect(numeroRegimen(0, "pb")).toBe("0 pb");
  expect(fechaRegimen("fecha-rota")).toBe("Fecha no disponible");
  expect(fechaRegimen(FECHA)).toContain("UTC");
  expect(urlFuente("javascript:alert(1)")).toBeNull();
  expect(urlFuente("https://user:secret@example.test")).toBeNull();
});
