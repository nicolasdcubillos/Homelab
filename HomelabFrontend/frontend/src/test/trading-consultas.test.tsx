import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useBotsTrading, useGuardarConfigTrading } from "@/lib/consultas";
import type { BotsTrading, ConfigTradingEntrada } from "@/lib/tipos";

vi.mock("@/lib/api", () => ({ api: { get: vi.fn(), put: vi.fn() } }));

function lista(version = 1): BotsTrading {
  return {
    nivel: "operator",
    items: [{ enabled: false, version, motor: { bot_name: "lumibot" } }],
  } as BotsTrading;
}

let cliente: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  cliente = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
});
afterEach(() => {
  cleanup();
  cliente.clear();
  vi.useRealTimers();
});

function Proveedor({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={cliente}>{children}</QueryClientProvider>;
}

it("sondea aunque todos los bots estén apagados para detectar cambios compartidos", async () => {
  vi.useFakeTimers();
  vi.mocked(api.get).mockResolvedValue(lista());
  renderHook(() => useBotsTrading(), { wrapper: Proveedor });
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(api.get).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(api.get).toHaveBeenCalledTimes(2);
});

it("una lectura en vuelo no pisa la versión que devuelve una mutación", async () => {
  let resolverVieja: (valor: BotsTrading) => void = () => {};
  const lecturaVieja = new Promise<BotsTrading>((resolver) => { resolverVieja = resolver; });
  vi.mocked(api.get)
    .mockResolvedValueOnce(lista())
    .mockReturnValueOnce(lecturaVieja)
    .mockResolvedValue(lista(2));
  vi.mocked(api.put).mockResolvedValue(lista(2).items[0]);
  const { result } = renderHook(
    () => ({ bots: useBotsTrading(), guardar: useGuardarConfigTrading() }),
    { wrapper: Proveedor },
  );
  await waitFor(() => expect(result.current.bots.isSuccess).toBe(true));
  act(() => { void result.current.bots.refetch(); });
  const signal = vi.mocked(api.get).mock.calls[1]?.[1]?.signal;
  await act(async () => {
    await result.current.guardar.mutateAsync({
      bot: "lumibot", datos: { version: 1 } as ConfigTradingEntrada,
    });
  });
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolverVieja(lista()); });
  await waitFor(() => expect(result.current.bots.data?.items[0]?.version).toBe(2));
});
