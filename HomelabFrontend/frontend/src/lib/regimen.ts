import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type OpcionesPeticion } from "./api";
import { claves, useSesion } from "./consultas";
import { CLASIFICACION_REGIMEN } from "./etiquetas";
import type {
  AccesoRegimen, AccesosRegimen, CoberturaRegimen, ConfigRegimen,
  ConfigRegimenEntrada, EjecucionRegimen, EjecucionRegimenEntrada,
  EjecucionesRegimen, EntregasRegimen, FuentesRegimen, HistoriaRegimen,
  InformeRegimen, InformesRegimen, NivelRegimen, ResumenRegimen,
  ResultadoHorizonte,
  SnapshotRegimen, SuscripcionRegimen, SuscripcionRegimenEntrada,
} from "./tipos";

const BASE = "/market-regime";
export const RANGOS_REGIMEN = [
  { valor: "1w", texto: "1 semana" }, { valor: "1m", texto: "1 mes" },
  { valor: "3m", texto: "3 meses" }, { valor: "6m", texto: "6 meses" },
  { valor: "12m", texto: "12 meses" },
] as const;
export type RangoRegimen = (typeof RANGOS_REGIMEN)[number]["valor"];

export const clavesRegimen = {
  raiz: ["regimen"] as const,
  usuario: (id: string) => ["regimen", id] as const,
  consulta: (id: string, ruta: string, filtros: OpcionesPeticion["query"] = {}) =>
    ["regimen", id, ruta, filtros] as const,
};

export function usePermisoRegimen() {
  const sesion = useSesion();
  const usuario = sesion.data?.user;
  const activo = usuario?.status === "active" && !usuario.must_change_password;
  const admin = activo && usuario.role === "admin";
  const nivel = admin ? "operator" : usuario?.regime_level;
  return {
    id: usuario?.id ?? "", cargando: sesion.isPending,
    permitido: Boolean(activo && nivel), operador: Boolean(activo && nivel === "operator"),
    admin: Boolean(admin),
  };
}

type Permiso = "viewer" | "operator" | "admin";
function useAutorizacion(permiso: Permiso) {
  const acceso = usePermisoRegimen();
  return { ...acceso, autorizado: permiso === "admin" ? acceso.admin
    : permiso === "operator" ? acceso.operador : acceso.permitido };
}

function useConsultaRegimen<T>(
  ruta: string, enabled = true, filtros?: OpcionesPeticion["query"],
  permiso: Permiso = "viewer",
) {
  const acceso = useAutorizacion(permiso);
  return useQuery({
    queryKey: clavesRegimen.consulta(acceso.id, ruta, filtros),
    queryFn: ({ signal }) => api.get<T>(`${BASE}${ruta}`, { signal, query: filtros }),
    enabled: enabled && acceso.autorizado,
  });
}

export const useResumenRegimen = () => useConsultaRegimen<ResumenRegimen>("/overview");
export const useFuentesRegimen = () => useConsultaRegimen<FuentesRegimen>("/sources");
export const useCoberturaRegimen = () => useConsultaRegimen<CoberturaRegimen>("/coverage");
export const useConfigRegimen = () => useConsultaRegimen<ConfigRegimen>("/config");
export const useHistoriaRegimen = (range: RangoRegimen, offset = 0, limit = 20) =>
  useConsultaRegimen<HistoriaRegimen>("/history", true, { range, offset, limit });
export const useSnapshotRegimen = (id: string | null) =>
  useConsultaRegimen<SnapshotRegimen>(`/snapshots/${encodeURIComponent(id ?? "")}`, Boolean(id));
export const useInformesRegimen = (offset = 0, limit = 10) =>
  useConsultaRegimen<InformesRegimen>("/reports", true, { offset, limit });
export const useInformeRegimen = (id: string | null) =>
  useConsultaRegimen<InformeRegimen>(`/reports/${encodeURIComponent(id ?? "")}`, Boolean(id));
export const useSuscripcionRegimen = () => useConsultaRegimen<SuscripcionRegimen>("/me/subscription");
export const useEntregasRegimen = () => useConsultaRegimen<EntregasRegimen>("/me/deliveries");
export const useAccesosRegimen = (enabled = true) =>
  useConsultaRegimen<AccesosRegimen>("/access", enabled, undefined, "admin");

export function ejecucionActiva(estado?: string) {
  return ["queued", "pending", "running", "PENDIENTE", "EJECUTANDO"].includes(estado ?? "");
}

export function estadoHorizonte(resultado?: ResultadoHorizonte) {
  if (!resultado || resultado.data_status === "SIN_DATOS") return "Sin datos";
  if (resultado.data_status === "INCOMPLETO") return "Incompleto";
  return resultado.regime ? CLASIFICACION_REGIMEN[resultado.regime] : "No evaluable";
}

export function tonoHorizonte(resultado?: ResultadoHorizonte) {
  if (!resultado || resultado.data_status === "SIN_DATOS") return "neutro" as const;
  if (resultado.data_status === "INCOMPLETO") return "aviso" as const;
  return resultado.regime === "RISK_ON" ? "ok" as const
    : resultado.regime === "RISK_OFF" ? "alerta" as const : "neutro" as const;
}

export function useOperacionesRegimen() {
  const acceso = usePermisoRegimen();
  return useQuery({
    queryKey: clavesRegimen.consulta(acceso.id, "/operations"),
    queryFn: ({ signal }) => api.get<EjecucionesRegimen>(`${BASE}/operations`, { signal }),
    enabled: acceso.operador,
    refetchInterval: (query) => query.state.data?.items.some((run) => ejecucionActiva(run.status))
      ? 2_000 : false,
  });
}

export function useEjecucionRegimen(id: string | null) {
  const acceso = usePermisoRegimen();
  return useQuery({
    queryKey: clavesRegimen.consulta(acceso.id, `/runs/${id ?? ""}`),
    queryFn: ({ signal }) =>
      api.get<EjecucionRegimen>(`${BASE}/runs/${encodeURIComponent(id!)}`, { signal }),
    enabled: acceso.operador && Boolean(id),
    refetchInterval: (query) => ejecucionActiva(query.state.data?.status) ? 2_000 : false,
  });
}

function useMutacionRegimen<Entrada, Salida>(
  permiso: Permiso, mutar: (entrada: Entrada) => Promise<Salida>,
  ruta?: string,
) {
  const cliente = useQueryClient();
  const acceso = useAutorizacion(permiso);
  return useMutation({
    mutationFn: (entrada: Entrada) => {
      if (!acceso.autorizado) throw new ApiError(403, "forbidden", "No tienes permiso para esta acción.");
      return mutar(entrada);
    },
    onMutate: async () => {
      await cliente.cancelQueries({ queryKey: clavesRegimen.usuario(acceso.id) });
    },
    onSuccess: async (salida) => {
      await cliente.cancelQueries({ queryKey: clavesRegimen.usuario(acceso.id) });
      if (ruta) cliente.setQueryData(clavesRegimen.consulta(acceso.id, ruta), salida);
      // No se comparte caché privada entre cuentas, ni se invalida Trading.
      await cliente.invalidateQueries({ queryKey: clavesRegimen.usuario(acceso.id) });
      if (permiso === "admin") {
        await cliente.invalidateQueries({ queryKey: claves.sesion });
        await cliente.invalidateQueries({ queryKey: ["admin", "usuario"] });
      }
    },
  });
}

export const useGuardarConfigRegimen = () =>
  useMutacionRegimen<ConfigRegimenEntrada, ConfigRegimen>("operator",
    (datos) => api.patch(`${BASE}/config`, datos), "/config");
export const useIniciarRegimen = () =>
  useMutacionRegimen<EjecucionRegimenEntrada, EjecucionRegimen>("operator",
    (datos) => api.post(`${BASE}/runs`, datos));
export const useGuardarSuscripcionRegimen = () =>
  useMutacionRegimen<SuscripcionRegimenEntrada, SuscripcionRegimen>("viewer",
    (datos) => api.put(`${BASE}/me/subscription`, datos), "/me/subscription");
export const useConcederRegimen = () =>
  useMutacionRegimen<{ id: string; level: NivelRegimen }, AccesoRegimen>("admin",
    ({ id, level }) => api.put(`${BASE}/access/${encodeURIComponent(id)}`, { level }));
export const useRevocarRegimen = () =>
  useMutacionRegimen<string, void>("admin",
    (id) => api.delete(`${BASE}/access/${encodeURIComponent(id)}`));

export function fechaRegimen(valor?: string | null) {
  if (!valor) return "No disponible";
  const fecha = new Date(valor);
  if (!Number.isFinite(fecha.getTime())) return "Fecha no disponible";
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium", timeStyle: "short", timeZone: "UTC",
  }).format(fecha) + " UTC";
}

export function numeroRegimen(valor?: number | null, unidad = "") {
  if (valor == null || !Number.isFinite(valor)) return "No disponible";
  const numero = new Intl.NumberFormat("es", { maximumFractionDigits: 2 }).format(valor);
  return unidad ? `${numero} ${unidad}` : numero;
}

export function urlFuente(valor?: string | null) {
  if (!valor) return null;
  try {
    const url = new URL(valor);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url.href : null;
  } catch {
    return null;
  }
}
