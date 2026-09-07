/**
 * Consultas y mutaciones de la API.
 *
 * Todas las claves de caché viven aquí para que invalidar sea explícito: una
 * mutación declara qué deja obsoleto, en vez de que cada pantalla lo adivine.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api, ApiError } from "./api";
import type {
  AccesosTrading,
  AccesoTrading,
  App,
  Apps,
  Bitacora,
  BotTrading,
  BotsTrading,
  ConfigTradingEntrada,
  Ejecuciones,
  EjecucionesAdmin,
  Log,
  Metricas,
  Notificaciones,
  OperacionesTrading,
  Portafolio,
  Preview,
  Programaciones,
  ReadinessGlobal,
  RendimientoTrading,
  Sesion,
  UsuarioDetalle,
  UsuariosAdmin,
  Watches,
} from "./tipos";

export const claves = {
  sesion: ["sesion"] as const,
  notificaciones: ["notificaciones"] as const,
  watches: ["watches"] as const,
  portafolio: ["portafolio"] as const,
  apps: ["apps"] as const,
  programaciones: ["programaciones"] as const,
  readiness: ["readiness"] as const,
  ejecuciones: (filtros?: Record<string, unknown>) => ["ejecuciones", filtros ?? {}] as const,
  log: (id: number) => ["log", id] as const,
  preview: (app: string) => ["preview", app] as const,
  adminUsuarios: (filtros?: Record<string, unknown>) => ["admin", "usuarios", filtros ?? {}] as const,
  adminUsuario: (id: string) => ["admin", "usuario", id] as const,
  adminMetricas: ["admin", "metricas"] as const,
  adminEjecuciones: (filtros?: Record<string, unknown>) =>
    ["admin", "ejecuciones", filtros ?? {}] as const,
  adminBitacora: (filtros?: Record<string, unknown>) => ["admin", "bitacora", filtros ?? {}] as const,
  trading: ["trading"] as const,
  tradingOperaciones: (bot: string) => ["trading", "operaciones", bot] as const,
  tradingRendimiento: (bot: string) => ["trading", "rendimiento", bot] as const,
  tradingAccesos: ["trading", "accesos"] as const,
};

/** Lo que queda obsoleto cuando cambia la configuración de un usuario. */
const DEPENDE_DE_CONFIG = [claves.apps, claves.readiness, claves.programaciones];

/* -------------------------------------------------------------------------- */
/* Sesión                                                                      */
/* -------------------------------------------------------------------------- */

export function useSesion(opciones?: Partial<UseQueryOptions<Sesion | null, ApiError>>) {
  return useQuery<Sesion | null, ApiError>({
    queryKey: claves.sesion,
    queryFn: async () => {
      try {
        return await api.get<Sesion>("/auth/me");
      } catch (error) {
        // Que no haya sesión no es un fallo: es el estado "aún no entró".
        if (error instanceof ApiError && error.esNoAutenticado) return null;
        throw error;
      }
    },
    staleTime: 30_000,
    retry: false,
    ...opciones,
  });
}

export function useLogin() {
  const cliente = useQueryClient();
  return useMutation<Sesion, ApiError, { email: string; password: string }>({
    mutationFn: (datos) => api.post<Sesion>("/auth/login", datos),
    onSuccess: (sesion) => {
      cliente.setQueryData(claves.sesion, sesion);
      // Los datos del usuario anterior no pueden sobrevivir a un cambio de
      // sesión: sería una fuga entre cuentas dentro del mismo navegador.
      void cliente.invalidateQueries();
    },
  });
}

export function useRegistro() {
  return useMutation<
    { user: { email: string }; mensaje: string },
    ApiError,
    { email: string; password: string; timezone?: string }
  >({
    mutationFn: (datos) => api.post("/auth/register", datos),
  });
}

export function useLogout() {
  const cliente = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSettled: () => {
      cliente.setQueryData(claves.sesion, null);
      cliente.clear();
    },
  });
}

export function useCambiarPassword() {
  const cliente = useQueryClient();
  return useMutation<
    unknown,
    ApiError,
    { password_actual?: string | null; password_nueva: string }
  >({
    mutationFn: (datos) => api.post("/auth/password", datos),
    onSuccess: () => cliente.invalidateQueries({ queryKey: claves.sesion }),
  });
}

export function useActualizarPerfil() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { timezone?: string }>({
    mutationFn: (datos) => api.put("/auth/profile", datos),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.sesion });
      void cliente.invalidateQueries({ queryKey: claves.programaciones });
      void cliente.invalidateQueries({ queryKey: claves.apps });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Notificaciones                                                              */
/* -------------------------------------------------------------------------- */

export function useNotificaciones() {
  return useQuery<Notificaciones, ApiError>({
    queryKey: claves.notificaciones,
    queryFn: () => api.get<Notificaciones>("/me/notifications"),
  });
}

export function useGuardarNotificaciones() {
  const cliente = useQueryClient();
  return useMutation<Notificaciones, ApiError, { whatsapp?: string | null; email?: string | null }>({
    mutationFn: (datos) => api.put<Notificaciones>("/me/notifications", datos),
    onSuccess: (datos) => {
      cliente.setQueryData(claves.notificaciones, datos);
      DEPENDE_DE_CONFIG.forEach((clave) => void cliente.invalidateQueries({ queryKey: clave }));
    },
  });
}

export function useGuardarPreferencias() {
  const cliente = useQueryClient();
  return useMutation<Notificaciones, ApiError, { app_name: string; channels: string[] }>({
    mutationFn: (datos) => api.put<Notificaciones>("/me/notifications/preferences", datos),
    onSuccess: (datos) => {
      cliente.setQueryData(claves.notificaciones, datos);
      DEPENDE_DE_CONFIG.forEach((clave) => void cliente.invalidateQueries({ queryKey: clave }));
    },
  });
}

/* -------------------------------------------------------------------------- */
/* StockWatcher                                                                */
/* -------------------------------------------------------------------------- */

export function useWatches() {
  return useQuery<Watches, ApiError>({
    queryKey: claves.watches,
    queryFn: () => api.get<Watches>("/me/stockwatcher/watches"),
  });
}

function invalidarWatches(cliente: ReturnType<typeof useQueryClient>) {
  void cliente.invalidateQueries({ queryKey: claves.watches });
  DEPENDE_DE_CONFIG.forEach((clave) => void cliente.invalidateQueries({ queryKey: clave }));
  void cliente.invalidateQueries({ queryKey: claves.preview("stockwatcher") });
}

export function useCrearWatch() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, Record<string, unknown>>({
    mutationFn: (datos) => api.post("/me/stockwatcher/watches", datos),
    onSuccess: () => invalidarWatches(cliente),
  });
}

export function useActualizarWatch() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { id: string; datos: Record<string, unknown> }>({
    mutationFn: ({ id, datos }) => api.put(`/me/stockwatcher/watches/${id}`, datos),
    onSuccess: () => invalidarWatches(cliente),
  });
}

export function useBorrarWatch() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (id) => api.delete(`/me/stockwatcher/watches/${id}`),
    onSuccess: () => invalidarWatches(cliente),
  });
}

export function useReordenarWatches() {
  const cliente = useQueryClient();
  return useMutation<Watches, ApiError, string[]>({
    mutationFn: (ids) => api.put<Watches>("/me/stockwatcher/watches", { ids }),
    onSuccess: (datos) => {
      cliente.setQueryData(claves.watches, datos);
      void cliente.invalidateQueries({ queryKey: claves.preview("stockwatcher") });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* PortfolioWatcher                                                            */
/* -------------------------------------------------------------------------- */

export function usePortafolio() {
  return useQuery<Portafolio, ApiError>({
    queryKey: claves.portafolio,
    queryFn: () => api.get<Portafolio>("/me/portfolio"),
  });
}

function invalidarPortafolio(cliente: ReturnType<typeof useQueryClient>) {
  void cliente.invalidateQueries({ queryKey: claves.portafolio });
  DEPENDE_DE_CONFIG.forEach((clave) => void cliente.invalidateQueries({ queryKey: clave }));
  void cliente.invalidateQueries({ queryKey: claves.preview("portfoliowatcher") });
}

export function useGuardarPerfilRiesgo() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, Record<string, unknown>>({
    mutationFn: (datos) => api.put("/me/portfolio/profile", datos),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useCrearHolding() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, Record<string, unknown>>({
    mutationFn: (datos) => api.post("/me/portfolio/holdings", datos),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useActualizarHolding() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { id: string; datos: Record<string, unknown> }>({
    mutationFn: ({ id, datos }) => api.put(`/me/portfolio/holdings/${id}`, datos),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useBorrarHolding() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (id) => api.delete(`/me/portfolio/holdings/${id}`),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useCrearPosicionCerrada() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, Record<string, unknown>>({
    mutationFn: (datos) => api.post("/me/portfolio/closed-positions", datos),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useActualizarPosicionCerrada() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { id: string; datos: Record<string, unknown> }>({
    mutationFn: ({ id, datos }) => api.put(`/me/portfolio/closed-positions/${id}`, datos),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

export function useBorrarPosicionCerrada() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (id) => api.delete(`/me/portfolio/closed-positions/${id}`),
    onSuccess: () => invalidarPortafolio(cliente),
  });
}

/* -------------------------------------------------------------------------- */
/* Apps, ejecuciones y logs                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Mientras algo esté corriendo la lista se refresca sola cada 4 s. Cuando no,
 * se deja quieta: sondear un panel inactivo solo gasta batería.
 */
export function useApps() {
  return useQuery<Apps, ApiError>({
    queryKey: claves.apps,
    queryFn: () => api.get<Apps>("/me/apps"),
    refetchInterval: (consulta) =>
      consulta.state.data?.items.some((app: App) => app.running) ? 4_000 : false,
  });
}

export function useReadiness() {
  return useQuery<ReadinessGlobal, ApiError>({
    queryKey: claves.readiness,
    queryFn: () => api.get<ReadinessGlobal>("/me/readiness"),
  });
}

export function usePreview(app: string, habilitado = true) {
  return useQuery<Preview, ApiError>({
    queryKey: claves.preview(app),
    queryFn: () => api.get<Preview>(`/me/apps/${app}/config-preview`),
    enabled: habilitado,
    retry: false,
  });
}

export function useEjecuciones(filtros: { app_name?: string; status?: string; limit?: number } = {}) {
  return useQuery<Ejecuciones, ApiError>({
    queryKey: claves.ejecuciones(filtros),
    queryFn: () => api.get<Ejecuciones>("/me/runs", { query: filtros }),
    refetchInterval: (consulta) =>
      consulta.state.data?.items.some((run) => run.status === "running") ? 4_000 : false,
  });
}

export function useLog(id: number | null, corriendo: boolean) {
  return useQuery<Log, ApiError>({
    queryKey: claves.log(id ?? -1),
    queryFn: () => api.get<Log>(`/me/runs/${id}/log`, { query: { lines: 500 } }),
    enabled: id !== null,
    refetchInterval: corriendo ? 3_000 : false,
  });
}

export function useLanzar() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { app: string; command_key: string; dry_run?: boolean }>({
    mutationFn: ({ app, ...datos }) => api.post(`/me/apps/${app}/runs`, datos),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.apps });
      void cliente.invalidateQueries({ queryKey: ["ejecuciones"] });
    },
  });
}

export function useCancelar() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (app) => api.delete(`/me/apps/${app}/runs/current`),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.apps });
      void cliente.invalidateQueries({ queryKey: ["ejecuciones"] });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Automatización                                                              */
/* -------------------------------------------------------------------------- */

export function useProgramaciones() {
  return useQuery<Programaciones, ApiError>({
    queryKey: claves.programaciones,
    queryFn: () => api.get<Programaciones>("/me/schedules"),
  });
}

export function useGuardarProgramacion() {
  const cliente = useQueryClient();
  return useMutation<
    unknown,
    ApiError,
    { app: string; command_key: string; datos: Record<string, unknown> }
  >({
    mutationFn: ({ app, command_key, datos }) =>
      api.put(`/me/schedules/${app}/${command_key}`, datos),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.programaciones });
      void cliente.invalidateQueries({ queryKey: claves.apps });
    },
  });
}

export function useBorrarProgramacion() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { app: string; command_key: string }>({
    mutationFn: ({ app, command_key }) => api.delete(`/me/schedules/${app}/${command_key}`),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.programaciones });
      void cliente.invalidateQueries({ queryKey: claves.apps });
    },
  });
}

export function useGuardarZonaHoraria() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (timezone) => api.put("/me/timezone", { timezone }),
    onSuccess: () => {
      void cliente.invalidateQueries({ queryKey: claves.sesion });
      void cliente.invalidateQueries({ queryKey: claves.programaciones });
      void cliente.invalidateQueries({ queryKey: claves.apps });
    },
  });
}

export function useBorrarMisDatos() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { password: string }>({
    mutationFn: (datos) => api.delete("/me/data", { body: datos }),
    onSuccess: () => void cliente.invalidateQueries(),
  });
}

/* -------------------------------------------------------------------------- */
/* Administración                                                              */
/* -------------------------------------------------------------------------- */

export type FiltrosUsuarios = {
  q?: string;
  status?: string;
  role?: string;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
};

export function useUsuariosAdmin(filtros: FiltrosUsuarios) {
  return useQuery<UsuariosAdmin, ApiError>({
    queryKey: claves.adminUsuarios(filtros),
    queryFn: () => api.get<UsuariosAdmin>("/admin/users", { query: filtros }),
    placeholderData: (anterior) => anterior,
  });
}

export function useUsuarioAdmin(id: string | null) {
  return useQuery<UsuarioDetalle, ApiError>({
    queryKey: claves.adminUsuario(id ?? ""),
    queryFn: () => api.get<UsuarioDetalle>(`/admin/users/${id}`),
    enabled: Boolean(id),
  });
}

export function useMetricasAdmin() {
  return useQuery<Metricas, ApiError>({
    queryKey: claves.adminMetricas,
    queryFn: () => api.get<Metricas>("/admin/metrics"),
    refetchInterval: 15_000,
  });
}

export function useEjecucionesAdmin(filtros: Record<string, string | number | undefined> = {}) {
  return useQuery<EjecucionesAdmin, ApiError>({
    queryKey: claves.adminEjecuciones(filtros),
    queryFn: () => api.get<EjecucionesAdmin>("/admin/runs", { query: filtros }),
    placeholderData: (anterior) => anterior,
  });
}

export function useBitacoraAdmin(filtros: Record<string, string | number | undefined> = {}) {
  return useQuery<Bitacora, ApiError>({
    queryKey: claves.adminBitacora(filtros),
    queryFn: () => api.get<Bitacora>("/admin/audit", { query: filtros }),
  });
}

function invalidarAdmin(cliente: ReturnType<typeof useQueryClient>, id?: string) {
  void cliente.invalidateQueries({ queryKey: ["admin"] });
  if (id) void cliente.invalidateQueries({ queryKey: claves.adminUsuario(id) });
}

export function useCambiarUsuarioAdmin() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { id: string; datos: { status?: string; role?: string } }>({
    mutationFn: ({ id, datos }) => api.patch(`/admin/users/${id}`, datos),
    onSuccess: (_datos, { id }) => invalidarAdmin(cliente, id),
  });
}

export function usePasswordAdmin() {
  const cliente = useQueryClient();
  return useMutation<
    unknown,
    ApiError,
    { id: string; datos: { new_password?: string; force_reset?: boolean } }
  >({
    mutationFn: ({ id, datos }) => api.post(`/admin/users/${id}/password`, datos),
    onSuccess: (_datos, { id }) => invalidarAdmin(cliente, id),
  });
}

export function useEliminarUsuarioAdmin() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, string>({
    mutationFn: (id) => api.delete(`/admin/users/${id}`),
    onSuccess: () => invalidarAdmin(cliente),
  });
}

export function useLanzarComoAdmin() {
  const cliente = useQueryClient();
  return useMutation<
    unknown,
    ApiError,
    { id: string; app: string; command_key: string; dry_run?: boolean }
  >({
    mutationFn: ({ id, app, ...datos }) => api.post(`/admin/users/${id}/apps/${app}/runs`, datos),
    onSuccess: (_datos, { id }) => invalidarAdmin(cliente, id),
  });
}

export function useCancelarComoAdmin() {
  const cliente = useQueryClient();
  return useMutation<unknown, ApiError, { id: string; app: string }>({
    mutationFn: ({ id, app }) => api.delete(`/admin/users/${id}/apps/${app}/runs/current`),
    onSuccess: (_datos, { id }) => invalidarAdmin(cliente, id),
  });
}

/* -------------------------------------------------------------------------- */
/* Trading                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * El bot es compartido: otro operador puede encenderlo mientras miras.
 *
 * Por eso esta consulta se refresca sola cada 10 s cuando hay algún motor
 * encendido, y cada 30 s cuando están apagados: otro operador puede cambiarlos.
 */
export function useBotsTrading(habilitado = true) {
  return useQuery<BotsTrading, ApiError>({
    queryKey: claves.trading,
    queryFn: ({ signal }) => api.get<BotsTrading>("/trading/bots", { signal }),
    enabled: habilitado,
    refetchInterval: (consulta) =>
      consulta.state.data?.items.some((bot: BotTrading) => bot.enabled) ? 10_000 : 30_000,
    retry: false,
  });
}

export function useOperacionesTrading(bot: string, habilitado = true) {
  return useQuery<OperacionesTrading, ApiError>({
    queryKey: claves.tradingOperaciones(bot),
    queryFn: ({ signal }) =>
      api.get<OperacionesTrading>(`/trading/bots/${bot}/trades`, { query: { limit: 50 }, signal }),
    enabled: habilitado,
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useRendimientoTrading(bot: string, habilitado = true) {
  return useQuery<RendimientoTrading, ApiError>({
    queryKey: claves.tradingRendimiento(bot),
    queryFn: ({ signal }) => api.get<RendimientoTrading>(`/trading/bots/${bot}/performance`, { signal }),
    enabled: habilitado,
    refetchInterval: 10_000,
    retry: false,
  });
}

/**
 * Toda mutación devuelve el bot ya actualizado, incluida su nueva `version`.
 *
 * Se siembra en la caché en vez de solo invalidar para que el formulario
 * recupere al instante el número de versión que necesita para el siguiente
 * guardado. Si solo invalidáramos, un segundo guardado rápido saldría con la
 * versión vieja y el backend lo rechazaría por conflicto.
 */
function sembrarBot(cliente: ReturnType<typeof useQueryClient>, bot: BotTrading) {
  cliente.setQueryData<BotsTrading>(claves.trading, (previo) =>
    previo
      ? {
          ...previo,
          items: previo.items.map((item) =>
            item.motor.bot_name === bot.motor.bot_name ? bot : item,
          ),
        }
      : previo,
  );
  void cliente.invalidateQueries({ queryKey: claves.tradingRendimiento(bot.motor.bot_name) });
  void cliente.invalidateQueries({ queryKey: claves.tradingOperaciones(bot.motor.bot_name) });
}

export function useGuardarConfigTrading() {
  const cliente = useQueryClient();
  return useMutation<BotTrading, ApiError, { bot: string; datos: ConfigTradingEntrada }>({
    mutationFn: ({ bot, datos }) => api.put<BotTrading>(`/trading/bots/${bot}/config`, datos),
    onMutate: () => cliente.cancelQueries({ queryKey: claves.trading }),
    onSuccess: (bot) => sembrarBot(cliente, bot),
    onSettled: () => { void cliente.invalidateQueries({ queryKey: claves.trading }); },
  });
}

export function useInterruptorTrading() {
  const cliente = useQueryClient();
  return useMutation<BotTrading, ApiError, { bot: string; enabled: boolean; version: number }>({
    mutationFn: ({ bot, ...datos }) => api.post<BotTrading>(`/trading/bots/${bot}/switch`, datos),
    onMutate: () => cliente.cancelQueries({ queryKey: claves.trading }),
    onSuccess: (bot) => sembrarBot(cliente, bot),
    onSettled: () => { void cliente.invalidateQueries({ queryKey: claves.trading }); },
  });
}

export function useAccesosTrading(habilitado = true) {
  return useQuery<AccesosTrading, ApiError>({
    queryKey: claves.tradingAccesos,
    queryFn: () => api.get<AccesosTrading>("/trading/access"),
    enabled: habilitado,
  });
}

export function useConcederAccesoTrading() {
  const cliente = useQueryClient();
  return useMutation<AccesoTrading, ApiError, { id: string; level: string }>({
    mutationFn: ({ id, level }) => api.put<AccesoTrading>(`/trading/access/${id}`, { level }),
    onSuccess: (_datos, { id }) => {
      void cliente.invalidateQueries({ queryKey: claves.tradingAccesos });
      invalidarAdmin(cliente, id);
    },
  });
}

export function useRevocarAccesoTrading() {
  const cliente = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (id) => api.delete<void>(`/trading/access/${id}`),
    onSuccess: (_datos, id) => {
      void cliente.invalidateQueries({ queryKey: claves.tradingAccesos });
      invalidarAdmin(cliente, id);
    },
  });
}
