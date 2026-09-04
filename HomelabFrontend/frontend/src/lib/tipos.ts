/**
 * Nombres de dominio para los tipos generados del esquema OpenAPI.
 *
 * Los componentes se re-exportan con el nombre que usa la interfaz para que
 * ningún componente de React tenga que escribir
 * `components["schemas"]["..."]` ni importar el archivo generado.
 */

import type { components } from "./api-schema";

type S = components["schemas"];

/* Identidad ---------------------------------------------------------------- */
export type Usuario = S["UsuarioOut"];
export type Sesion = S["SesionOut"];

// El backend serializa estos campos como `str` para no acoplar el esquema a
// la enumeración de la base, pero los valores posibles son cerrados y la UI
// enciende ramas distintas con cada uno, así que aquí sí los estrechamos.
export type Rol = "user" | "admin";
export type EstadoUsuario = "pending" | "active" | "suspended";
export type Canal = "whatsapp" | "email";

/* Notificaciones ----------------------------------------------------------- */
export type Notificaciones = S["NotificacionesOut"];
export type NotificacionesEntrada = S["NotificacionesIn"];
export type PreferenciasEntrada = S["PreferenciasIn"];

/* StockWatcher ------------------------------------------------------------- */
export type Watch = S["WatchOut"];
export type WatchEntrada = S["WatchIn"];
export type Watches = S["WatchesOut"];
export type Genero = "mens" | "womens" | "unisex";

/* PortfolioWatcher --------------------------------------------------------- */
export type Portafolio = S["PortafolioOut"];
export type Holding = S["HoldingOut"];
export type HoldingEntrada = S["HoldingIn"];
export type PosicionCerrada = S["PosicionCerradaOut"];
export type PosicionCerradaEntrada = S["PosicionCerradaIn"];
export type PerfilRiesgo = S["PerfilRiesgoOut"];
export type PerfilRiesgoEntrada = S["PerfilRiesgoIn"];
export type Tolerancia = "conservative" | "moderate" | "aggressive";
export type Horizonte = "short_term" | "medium_term" | "long_term";

/* Apps y ejecución --------------------------------------------------------- */
export type App = S["AppOut"];
export type Apps = S["AppsOut"];
export type Comando = S["ComandoOut"];
export type Ejecucion = S["EjecucionOut"];
export type Ejecuciones = S["EjecucionesOut"];
export type EstadoEjecucion = "running" | "success" | "error" | "skipped" | "cancelled";
export type Disparador = "manual" | "schedule";
export type Log = S["LogOut"];
export type Readiness = S["ReadinessAppOut"];
export type ReadinessGlobal = S["ReadinessGlobalOut"];
export type Motivo = S["MotivoOut"];
export type Preview = S["PreviewOut"];

/* Automatización ----------------------------------------------------------- */
export type Programacion = S["ProgramacionOut"];
export type Programaciones = S["ProgramacionesOut"];
export type ProgramacionEntrada = S["ProgramacionIn"];
export type TipoProgramacion = "interval" | "cron";

/* Administración ----------------------------------------------------------- */
export type UsuarioAdmin = S["UsuarioAdminOut"];
export type UsuariosAdmin = S["UsuariosAdminOut"];
export type UsuarioDetalle = S["UsuarioDetalleOut"];
export type CanalResumen = S["CanalResumenOut"];
export type Metricas = S["MetricasOut"];
export type Bitacora = S["BitacoraOut"];
export type EntradaBitacora = S["EntradaBitacoraOut"];
export type EjecucionAdmin = S["EjecucionAdminOut"];
export type EjecucionesAdmin = S["EjecucionesAdminOut"];

/* Trading ------------------------------------------------------------------ */
export type BotTrading = S["BotTradingOut"];
export type BotsTrading = S["BotsTradingOut"];
export type MotorTrading = S["MotorInfoOut"];
export type EstadoMotor = S["EstadoMotorOut"];
export type ConfigTrading = S["ConfigTradingOut"];
export type ConfigTradingEntrada = S["ConfigTradingIn"];
export type OperacionTrading = S["OperacionOut"];
export type OperacionesTrading = S["OperacionesOut"];
export type RendimientoTrading = S["RendimientoOut"];
export type AccesoTrading = S["AccesoTradingOut"];
export type AccesosTrading = S["AccesosTradingOut"];

// El nivel decide la mitad de la pantalla de trading: un `viewer` ve
// exactamente lo mismo que un `operator`, pero sin un solo control activo.
export type NivelTrading = "viewer" | "operator";
// Solo hay un modo y es deliberado: el bot no puede operar con dinero real.
// Se tipa igual para que añadir uno nuevo rompa la compilación antes que la UI.
export type ModoTrading = "paper";
// En español porque los motores hablan idiomas distintos y el backend ya los
// traduce: Freqtrade dice `is_short` y TradingLab escribe la palabra directa.
// La UI recibe un solo vocabulario, no el del motor que tocó responder.
export type LadoOperacion = "compra" | "venta";
