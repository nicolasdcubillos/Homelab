import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BotTrading, BotsTrading, RendimientoTrading } from "@/lib/tipos";
import { esquemaConfigTrading, separarInstrumentos } from "@/lib/validacion";
import { Trading } from "@/routes/Trading";

const dobles = vi.hoisted(() => ({
  bots: vi.fn(), rendimiento: vi.fn(), operaciones: vi.fn(),
  guardar: vi.fn(), cambiar: vi.fn(), exito: vi.fn(), info: vi.fn(),
}));

vi.mock("@/lib/consultas", () => ({
  useBotsTrading: dobles.bots,
  useRendimientoTrading: dobles.rendimiento,
  useOperacionesTrading: dobles.operaciones,
  useGuardarConfigTrading: () => ({ mutateAsync: dobles.guardar }),
  useInterruptorTrading: () => ({ mutateAsync: dobles.cambiar, isPending: false }),
}));
vi.mock("@/components/Avisos", () => ({
  useAvisos: () => ({ exito: dobles.exito, info: dobles.info }),
}));

function bot(): BotTrading {
  return {
    motor: {
      bot_name: "lumibot", display_name: "Acciones y ETFs", proyecto: "Lumibot",
      clase_activo: "acciones", termino_singular: "ticker", termino_plural: "tickers",
      ejemplo_instrumento: "AAPL", timeframes: ["5m", "1h", "1d"], max_instrumentos: 25,
      simula_contra: "Simulador local", permite_encender: true, motivo_bloqueo: "",
      estrategias: [{ nombre: "cruce_medias", etiqueta: "Cruce de medias", descripcion: "Ejemplo" }],
    },
    enabled: false, modo: "paper", version: 1, config_aplicada: false,
    config: {
      instrumentos: ["AAPL"], estrategia: "cruce_medias", timeframe: "1h",
      capital_simulado: 10000, max_posiciones_abiertas: 3, stop_loss_pct: 5,
      take_profit_pct: 10, max_perdida_diaria_pct: 8,
    },
    estado: {
      alcanzable: true, corriendo: false, detalle: "Detalle observado", modo: "paper",
      estado: "pausado", posiciones_abiertas: 0, config_version: null,
    },
    updated_by_email: "operador@ejemplo.com",
  };
}

function consulta<T>(data: T, isError = false) {
  return { data, isPending: false, isError, error: null, refetch: vi.fn() };
}

function publicar(valor: BotTrading, nivel: BotsTrading["nivel"] = "operator", error = false) {
  dobles.bots.mockReturnValue(consulta({ items: [valor], nivel }, error));
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true, value() { this.setAttribute("open", ""); },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true, value() { this.removeAttribute("open"); },
  });
  publicar(bot());
  dobles.rendimiento.mockReturnValue(consulta(undefined));
  dobles.operaciones.mockReturnValue(consulta({ items: [], disponible: true }));
  dobles.guardar.mockResolvedValue(bot());
  dobles.cambiar.mockResolvedValue(bot());
});
afterEach(cleanup);

describe("Estado honesto y permisos compartidos", () => {
  it("no confunde un error fresco con estar operando", () => {
    const valor = bot();
    valor.enabled = true;
    valor.estado.estado = "error";
    valor.estado.detalle = "No se pudo leer la configuración";
    publicar(valor);
    render(<Trading />);
    expect(screen.getAllByText("Error del motor").length).toBeGreaterThan(0);
    expect(screen.queryByText("Operando")).not.toBeInTheDocument();
    expect(screen.getAllByText("No se pudo leer la configuración").length).toBeGreaterThan(0);
  });

  it("una parada solicitada no afirma que el motor haya parado", () => {
    const valor = bot();
    valor.estado.corriendo = true;
    valor.estado.estado = "operando";
    publicar(valor);
    render(<Trading />);
    expect(screen.getAllByText("Parada sin confirmar").length).toBeGreaterThan(0);
  });

  it("Freqtrade bloquea el encendido pero permite solicitar apagado", () => {
    const valor = bot();
    valor.motor.permite_encender = false;
    valor.motor.motivo_bloqueo = "Configuración de Freqtrade no aplicada";
    publicar(valor);
    const vista = render(<Trading />);
    expect(screen.getByRole("switch")).toBeDisabled();
    valor.enabled = true;
    publicar({ ...valor });
    vista.rerender(<Trading />);
    expect(screen.getByRole("switch")).toBeEnabled();
  });

  it("viewer puede revisar pero no editar ni accionar", async () => {
    publicar(bot(), "viewer");
    render(<Trading />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Configuración/ }));
    expect(screen.getByLabelText("Capital simulado")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Guardar" })).not.toBeInTheDocument();
  });

  it("un refetch fallido no mantiene la insignia operando ni controles activos", () => {
    const valor = bot();
    valor.enabled = true;
    valor.estado.corriendo = true;
    valor.estado.estado = "operando";
    publicar(valor);
    const vista = render(<Trading />);
    publicar(valor, "operator", true);
    vista.rerender(<Trading />);
    expect(screen.queryByText("Operando")).not.toBeInTheDocument();
    expect(screen.getAllByText("Datos desactualizados").length).toBeGreaterThan(0);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("el aviso del interruptor confirma solo la solicitud", async () => {
    render(<Trading />);
    await userEvent.click(screen.getByRole("switch"));
    expect(dobles.cambiar).toHaveBeenCalledWith({ bot: "lumibot", enabled: true, version: 1 });
    expect(dobles.info).toHaveBeenCalledWith(expect.stringContaining("solicitud de encendido"));
    expect(dobles.exito).not.toHaveBeenCalled();
  });
});

describe("Borradores y resultados", () => {
  it("permite retirar todos los tickers sin pausar y explica el cierre solicitado", async () => {
    const usuario = userEvent.setup();
    const valor = bot();
    valor.enabled = true;
    publicar(valor);
    render(<Trading />);
    await usuario.click(screen.getByRole("button", { name: /^Configuración/ }));
    expect(screen.getByText("Retirar tickers no requiere pausar")).toBeInTheDocument();
    expect(screen.getByText(/La pausa no liquida posiciones ni supervisa sus stops/)).toBeInTheDocument();
    expect(screen.getByText(/Cambiarlo no recarga el saldo/)).toBeInTheDocument();
    await usuario.clear(screen.getByLabelText("Tickers"));
    await usuario.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(dobles.guardar).toHaveBeenCalledWith({
      bot: "lumibot", datos: expect.objectContaining({ instrumentos: [], version: 1 }),
    }));
    expect(dobles.cambiar).not.toHaveBeenCalled();
  });

  it("un sondeo conserva el borrador y la versión con que se abrió", async () => {
    const usuario = userEvent.setup();
    const vista = render(<Trading />);
    await usuario.click(screen.getByRole("button", { name: /^Configuración/ }));
    const campo = screen.getByLabelText("Capital simulado");
    await usuario.clear(campo);
    await usuario.type(campo, "12000");
    const actualizado = bot();
    actualizado.version = 2;
    actualizado.config.capital_simulado = 15000;
    publicar(actualizado);
    vista.rerender(<Trading />);
    expect(campo).toHaveValue("12000");
    expect(screen.getByText("La configuración compartida cambió")).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(dobles.guardar).toHaveBeenCalledWith({
      bot: "lumibot", datos: expect.objectContaining({ version: 1, capital_simulado: 12000 }),
    }));
  });

  it("recargar el borrador exige una acción explícita", async () => {
    const usuario = userEvent.setup();
    const vista = render(<Trading />);
    await usuario.click(screen.getByRole("button", { name: /^Configuración/ }));
    const nuevo = bot();
    nuevo.version = 2;
    nuevo.config.capital_simulado = 15000;
    publicar(nuevo);
    vista.rerender(<Trading />);
    await usuario.click(screen.getByRole("button", { name: "Descartar borrador y recargar" }));
    expect(screen.getByLabelText("Capital simulado")).toHaveValue("15000");
  });

  it("convierte win_rate a porcentaje y no inventa costos", async () => {
    const datos: RendimientoTrading = {
      capital_inicial: 10000, capital_actual: 10250, pnl_absoluto: 250, pnl_pct: 2.5,
      operaciones_cerradas: 4, ganadoras: 3, perdedoras: 1, win_rate: 0.75,
      mejor_pct: null, peor_pct: null, costos_simulados: null, disponible: true,
    };
    dobles.rendimiento.mockReturnValue(consulta(datos));
    render(<Trading />);
    await userEvent.click(screen.getByRole("button", { name: /^Resultados y operaciones/ }));
    const dialogo = within(screen.getByRole("dialog"));
    expect(dialogo.getByText("75 %")).toBeInTheDocument();
    expect(dialogo.getByText("Sin información")).toBeInTheDocument();
    expect(dialogo.getByText("No incluye ganancias ni pérdidas de posiciones abiertas.")).toBeInTheDocument();
  });

  it("un fallo de operaciones se muestra y oculta la caché anterior", async () => {
    dobles.operaciones.mockReturnValue(consulta({
      items: [{
        instrumento: "DATO_ANTERIOR", lado: "compra", cantidad: 1, precio_entrada: 10,
        precio_salida: null, pnl_absoluto: null, pnl_pct: null, abierta: true,
        abierta_en: null, cerrada_en: null,
      }], disponible: true,
    }, true));
    render(<Trading />);
    await userEvent.click(screen.getByRole("button", { name: /^Resultados y operaciones/ }));
    expect(screen.getByText("No pudimos cargar las operaciones")).toBeInTheDocument();
    expect(screen.queryByText("DATO_ANTERIOR")).not.toBeInTheDocument();
  });
});

describe("Validación de trading", () => {
  const esquema = esquemaConfigTrading({
    maxInstrumentos: 25, timeframes: ["1h"], estrategias: ["cruce_medias"],
  });
  const valido = {
    instrumentos: "AAPL", estrategia: "cruce_medias", timeframe: "1h",
    capital_simulado: "10000", max_posiciones_abiertas: "3",
    stop_loss_pct: "5", take_profit_pct: "10", max_perdida_diaria_pct: "8",
  };
  it.each([
    ["capital_simulado", "NaN"], ["capital_simulado", "0x1000"],
    ["capital_simulado", "Infinity"], ["capital_simulado", ""],
    ["max_posiciones_abiertas", "1.5"], ["max_posiciones_abiertas", "true"],
    ["estrategia", "no_existe"], ["timeframe", "1s"],
    ["max_perdida_diaria_pct", "1"],
  ])("rechaza %s = %s", (campo, valor) => {
    expect(esquema.safeParse({ ...valido, [campo]: valor }).success).toBe(false);
  });
  it("acepta decimales españoles y normaliza duplicados", () => {
    expect(esquema.safeParse({ ...valido, stop_loss_pct: "2,5" }).success).toBe(true);
    expect(separarInstrumentos("aapl, AAPL; spy")).toEqual(["AAPL", "SPY"]);
  });
  it("admite lista vacía para solicitar la salida sin deshabilitar el bot", () => {
    expect(esquema.safeParse({ ...valido, instrumentos: " , " }).success).toBe(true);
    expect(separarInstrumentos(" , ")).toEqual([]);
  });
});
