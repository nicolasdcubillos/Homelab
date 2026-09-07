/* eslint-disable */
/**
 * ARCHIVO GENERADO. No lo edites a mano.
 *
 * Origen: esquema OpenAPI de FastAPI.
 * Regenerar con: npm run gen:api
 */

export interface paths {
    "/api/v1/admin/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Bitacora */
        get: operations["bitacora_api_v1_admin_audit_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Metricas */
        get: operations["metricas_api_v1_admin_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Ejecuciones */
        get: operations["listar_ejecuciones_api_v1_admin_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/runs/{run_id}/log": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Log */
        get: operations["ver_log_api_v1_admin_runs__run_id__log_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Usuarios */
        get: operations["listar_usuarios_api_v1_admin_users_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/users/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Usuario */
        get: operations["ver_usuario_api_v1_admin_users__user_id__get"];
        put?: never;
        post?: never;
        /** Eliminar Usuario */
        delete: operations["eliminar_usuario_api_v1_admin_users__user_id__delete"];
        options?: never;
        head?: never;
        /** Cambiar Usuario */
        patch: operations["cambiar_usuario_api_v1_admin_users__user_id__patch"];
        trace?: never;
    };
    "/api/v1/admin/users/{user_id}/apps/{app_name}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Lanzar */
        post: operations["lanzar_api_v1_admin_users__user_id__apps__app_name__runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/users/{user_id}/apps/{app_name}/runs/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Cancelar */
        delete: operations["cancelar_api_v1_admin_users__user_id__apps__app_name__runs_current_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/users/{user_id}/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cambiar Password */
        post: operations["cambiar_password_api_v1_admin_users__user_id__password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/csrf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Csrf
         * @description Devuelve el token CSRF de la sesi�n actual y reafirma la cookie.
         *
         *     Existe para que la SPA se recupere si el usuario borr� solo la cookie
         *     legible, sin obligarlo a volver a entrar.
         */
        get: operations["csrf_api_v1_auth_csrf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description Cierra la sesi�n actual. Es idempotente: sin sesi�n tambi�n responde OK
         *     y limpia las cookies, para que la SPA pueda 'salir' de un estado roto.
         */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Yo
         * @description Usuario en sesi�n. Es la primera llamada de la SPA al arrancar.
         */
        get: operations["yo_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cambiar Password
         * @description Cambio de contrase�a propio.
         *
         *     Si el usuario ven�a de un reset forzado por un admin, no se le pide la
         *     contrase�a anterior (no la conoce). En cualquier otro caso s�.
         */
        post: operations["cambiar_password_api_v1_auth_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Actualizar Perfil
         * @description Ajustes de la propia cuenta que no son credenciales.
         */
        put: operations["actualizar_perfil_api_v1_auth_profile_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Registrar
         * @description Alta abierta. El usuario nace `pending` y no puede ejecutar nada hasta
         *     que un administrador lo active.
         *
         *     Excepci�n: si la instalaci�n est� vac�a, el primer registro se convierte en
         *     admin activo. Evita que una instalaci�n reci�n desplegada quede sin nadie
         *     que pueda aprobar a nadie.
         */
        post: operations["registrar_api_v1_auth_register_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/access": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Access List */
        get: operations["access_list_api_v1_market_regime_access_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/access/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Grant */
        put: operations["grant_api_v1_market_regime_access__user_id__put"];
        post?: never;
        /** Revoke */
        delete: operations["revoke_api_v1_market_regime_access__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Config */
        get: operations["config_api_v1_market_regime_config_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Change Config */
        patch: operations["change_config_api_v1_market_regime_config_patch"];
        trace?: never;
    };
    "/api/v1/market-regime/coverage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Coverage */
        get: operations["coverage_api_v1_market_regime_coverage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_api_v1_market_regime_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/me/deliveries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Deliveries */
        get: operations["deliveries_api_v1_market_regime_me_deliveries_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/me/subscription": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Subscription */
        get: operations["subscription_api_v1_market_regime_me_subscription_get"];
        /** Update Subscription */
        put: operations["update_subscription_api_v1_market_regime_me_subscription_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/operations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Operations */
        get: operations["operations_api_v1_market_regime_operations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Overview */
        get: operations["overview_api_v1_market_regime_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/reports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reports */
        get: operations["reports_api_v1_market_regime_reports_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/reports/{report_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Report */
        get: operations["report_api_v1_market_regime_reports__report_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/reports/{report_id}/html": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Report Html */
        get: operations["report_html_api_v1_market_regime_reports__report_id__html_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Run */
        post: operations["create_run_api_v1_market_regime_runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Run */
        get: operations["run_api_v1_market_regime_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/snapshots/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Snapshot */
        get: operations["snapshot_api_v1_market_regime_snapshots__snapshot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/market-regime/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Sources */
        get: operations["sources_api_v1_market_regime_sources_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/apps": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Listar Apps
         * @description Todo lo que la pantalla de inicio necesita, en una sola llamada.
         */
        get: operations["listar_apps_api_v1_me_apps_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/apps/{app_name}/config-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Previsualizar Config
         * @description El YAML que se le pasar�a al watcher con la configuraci�n actual.
         *
         *     Devuelve transparencia sin reabrir la edici�n de YAML a mano. No escribe
         *     nada en disco: solo calcula la ruta de destino para mostrarla.
         */
        get: operations["previsualizar_config_api_v1_me_apps__app_name__config_preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/apps/{app_name}/readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Readiness */
        get: operations["ver_readiness_api_v1_me_apps__app_name__readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/apps/{app_name}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Lanzar Ejecucion */
        post: operations["lanzar_ejecucion_api_v1_me_apps__app_name__runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/apps/{app_name}/runs/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Cancelar Ejecucion */
        delete: operations["cancelar_ejecucion_api_v1_me_apps__app_name__runs_current_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/data": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Borrar Mis Datos
         * @description Borra toda la configuraci�n del usuario sin borrar la cuenta.
         *
         *     Se exige la contrase�a: es una acci�n irreversible y la cookie de sesi�n
         *     por s� sola no basta para autorizarla.
         */
        delete: operations["borrar_mis_datos_api_v1_me_data_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Notificaciones */
        get: operations["ver_notificaciones_api_v1_me_notifications_get"];
        /**
         * Guardar Notificaciones
         * @description Guarda los destinos. Una cadena vac�a borra el canal.
         */
        put: operations["guardar_notificaciones_api_v1_me_notifications_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/notifications/preferences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Guardar Preferencias
         * @description Reemplaza los canales activos de una app.
         */
        put: operations["guardar_preferencias_api_v1_me_notifications_preferences_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Portafolio */
        get: operations["ver_portafolio_api_v1_me_portfolio_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio/closed-positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Crear Cerrada */
        post: operations["crear_cerrada_api_v1_me_portfolio_closed_positions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio/closed-positions/{cerrada_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Editar Cerrada */
        put: operations["editar_cerrada_api_v1_me_portfolio_closed_positions__cerrada_id__put"];
        post?: never;
        /** Borrar Cerrada */
        delete: operations["borrar_cerrada_api_v1_me_portfolio_closed_positions__cerrada_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio/holdings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Crear Holding */
        post: operations["crear_holding_api_v1_me_portfolio_holdings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio/holdings/{holding_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Editar Holding */
        put: operations["editar_holding_api_v1_me_portfolio_holdings__holding_id__put"];
        post?: never;
        /** Borrar Holding */
        delete: operations["borrar_holding_api_v1_me_portfolio_holdings__holding_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/portfolio/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Guardar Perfil */
        put: operations["guardar_perfil_api_v1_me_portfolio_profile_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Ver Readiness Global
         * @description Estado de todas las apps de una sola vez.
         *
         *     La pantalla de inicio las necesita juntas; pedirlas una por una
         *     multiplicar�a las peticiones desde el m�vil.
         */
        get: operations["ver_readiness_global_api_v1_me_readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Ejecuciones */
        get: operations["listar_ejecuciones_api_v1_me_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Ejecucion */
        get: operations["ver_ejecucion_api_v1_me_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/runs/{run_id}/log": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Log */
        get: operations["ver_log_api_v1_me_runs__run_id__log_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/schedules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Programaciones */
        get: operations["listar_programaciones_api_v1_me_schedules_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/schedules/{app_name}/{command_key}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Guardar Programacion
         * @description Crea o actualiza la programaci�n de un comando.
         *
         *     Se acepta programar aunque el usuario todav�a no est� listo para ejecutar:
         *     dejar la automatizaci�n armada mientras se completa la configuraci�n es
         *     parte del onboarding. El pre-vuelo del scheduler decide en cada disparo.
         */
        put: operations["guardar_programacion_api_v1_me_schedules__app_name___command_key__put"];
        post?: never;
        /** Borrar Programacion */
        delete: operations["borrar_programacion_api_v1_me_schedules__app_name___command_key__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/stockwatcher/watches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Watches */
        get: operations["listar_watches_api_v1_me_stockwatcher_watches_get"];
        /** Reordenar Watches */
        put: operations["reordenar_watches_api_v1_me_stockwatcher_watches_put"];
        /** Crear Watch */
        post: operations["crear_watch_api_v1_me_stockwatcher_watches_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/stockwatcher/watches/{watch_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ver Watch */
        get: operations["ver_watch_api_v1_me_stockwatcher_watches__watch_id__get"];
        /** Editar Watch */
        put: operations["editar_watch_api_v1_me_stockwatcher_watches__watch_id__put"];
        post?: never;
        /** Borrar Watch */
        delete: operations["borrar_watch_api_v1_me_stockwatcher_watches__watch_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me/timezone": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Cambiar Zona Horaria
         * @description Cambia la zona horaria y recalcula lo programado con cron.
         *
         *     Sin el rec�lculo, un �diario a las 8:00� seguir�a dispar�ndose a la hora
         *     de la zona anterior hasta la siguiente edici�n manual.
         */
        put: operations["cambiar_zona_horaria_api_v1_me_timezone_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/access": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Accesos */
        get: operations["listar_accesos_api_v1_trading_access_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/access/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Conceder Acceso */
        put: operations["conceder_acceso_api_v1_trading_access__user_id__put"];
        post?: never;
        /**
         * Revocar Acceso
         * @description Revocar es borrar la fila.
         *
         *     No hay una columna `enabled` a prop�sito: un permiso "concedido pero
         *     desactivado" es un estado ambiguo que tarde o temprano alguien interpreta
         *     mal. O est� la fila, o no hay acceso.
         */
        delete: operations["revocar_acceso_api_v1_trading_access__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Bots */
        get: operations["listar_bots_api_v1_trading_bots_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots/{bot_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Obtener Bot */
        get: operations["obtener_bot_api_v1_trading_bots__bot_name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots/{bot_name}/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Guardar Config */
        put: operations["guardar_config_api_v1_trading_bots__bot_name__config_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots/{bot_name}/performance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Rendimiento */
        get: operations["rendimiento_api_v1_trading_bots__bot_name__performance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots/{bot_name}/switch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Interruptor
         * @description Enciende o apaga el bot compartido.
         *
         *     Encender exige que haya al menos un instrumento configurado: un motor sin
         *     nada que vigilar arrancar�a, no har�a nada y aparecer�a como "operando",
         *     que es la peor combinaci�n posible para quien mira el panel.
         */
        post: operations["interruptor_api_v1_trading_bots__bot_name__switch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trading/bots/{bot_name}/trades": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listar Operaciones */
        get: operations["listar_operaciones_api_v1_trading_bots__bot_name__trades_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccesosTradingOut */
        AccesosTradingOut: {
            /** Items */
            items: components["schemas"]["AccesoTradingOut"][];
        };
        /** AccesoTradingIn */
        AccesoTradingIn: {
            /**
             * Level
             * @enum {string}
             */
            level: "viewer" | "operator";
        };
        /** AccesoTradingOut */
        AccesoTradingOut: {
            /** Email */
            email: string;
            /**
             * Granted At
             * Format: date-time
             */
            granted_at: string;
            /** Granted By Email */
            granted_by_email: string;
            /**
             * Level
             * @enum {string}
             */
            level: "viewer" | "operator";
            /** User Id */
            user_id: string;
        };
        /** AccessesOut */
        AccessesOut: {
            /** Items */
            items: components["schemas"]["AccessOut"][];
        };
        /** AccessIn */
        AccessIn: {
            /**
             * Level
             * @enum {string}
             */
            level: "viewer" | "operator";
        };
        /** AccessOut */
        AccessOut: {
            /**
             * Level
             * @enum {string}
             */
            level: "viewer" | "operator";
            /** User Id */
            user_id: string;
        };
        /** AppOut */
        AppOut: {
            /** App Name */
            app_name: string;
            /** Commands */
            commands: components["schemas"]["ComandoOut"][];
            /** Display Name */
            display_name: string;
            /** Installed */
            installed: boolean;
            last_run?: components["schemas"]["EjecucionOut"] | null;
            /** Next Run At */
            next_run_at?: string | null;
            readiness: components["schemas"]["ReadinessAppOut"];
            /** Running */
            running: boolean;
        };
        /** AppsOut */
        AppsOut: {
            /** Items */
            items: components["schemas"]["AppOut"][];
        };
        /** BitacoraOut */
        BitacoraOut: {
            /** Items */
            items: components["schemas"]["EntradaBitacoraOut"][];
        };
        /** BotsTradingOut */
        BotsTradingOut: {
            /** Items */
            items: components["schemas"]["BotTradingOut"][];
            /**
             * Nivel
             * @enum {string}
             */
            nivel: "viewer" | "operator";
        };
        /**
         * BotTradingOut
         * @description Todo lo que la UI necesita de un motor en una sola respuesta.
         */
        BotTradingOut: {
            config: components["schemas"]["ConfigTradingOut"];
            /** Config Aplicada */
            config_aplicada: boolean;
            /** Enabled */
            enabled: boolean;
            estado: components["schemas"]["EstadoMotorOut"];
            /** Modo */
            modo: string;
            motor: components["schemas"]["MotorInfoOut"];
            /** Updated At */
            updated_at?: string | null;
            /** Updated By Email */
            updated_by_email: string;
            /** Version */
            version: number;
        };
        /**
         * CambiarUsuarioIn
         * @description Cambios de estado y rol. Ambos campos son opcionales: la UI manda solo
         *     el que el admin toc�.
         */
        CambiarUsuarioIn: {
            /** Role */
            role?: ("user" | "admin") | null;
            /** Status */
            status?: ("pending" | "active" | "suspended") | null;
        };
        /** CambioPasswordIn */
        CambioPasswordIn: {
            /** Password Actual */
            password_actual?: string | null;
            /** Password Nueva */
            password_nueva: string;
        };
        /** CanalResumenOut */
        CanalResumenOut: {
            /** Channel */
            channel: string;
            /** Destination */
            destination: string;
        };
        /** CategoryResult */
        CategoryResult: {
            /** Category */
            category: string;
            /** Contribution */
            contribution?: number | null;
            /** Evidence */
            evidence?: components["schemas"]["Evidence"][];
            /** Reason */
            reason: string;
            /** Value */
            value?: number | null;
            /** Weight */
            weight: number;
        };
        /** ComandoOut */
        ComandoOut: {
            /** Key */
            key: string;
            /** Label */
            label: string;
        };
        /** ConfigIn */
        ConfigIn: {
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Enabled */
            enabled: boolean;
            /** Version */
            version: number;
        };
        /** ConfigOut */
        ConfigOut: {
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /** Enabled */
            enabled: boolean;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Version */
            version: number;
        };
        /**
         * ConfigTradingIn
         * @description Configuraci�n propuesta.
         *
         *     `extra="forbid"` (heredado de `Esquema`) hace aqu� un trabajo de seguridad
         *     real y no solo de higiene: es lo que impide que llegue un `dry_run: false`
         *     o una clave de API colada en el cuerpo. `trading.validar_config` vuelve a
         *     rechazarlas expl�citamente por si este esquema cambiara.
         */
        ConfigTradingIn: {
            /** Capital Simulado */
            capital_simulado: number;
            /**
             * Estrategia
             * @default
             */
            estrategia: string;
            /** Instrumentos */
            instrumentos?: string[];
            /** Max Perdida Diaria Pct */
            max_perdida_diaria_pct: number;
            /** Max Posiciones Abiertas */
            max_posiciones_abiertas: number;
            /** Stop Loss Pct */
            stop_loss_pct: number;
            /** Take Profit Pct */
            take_profit_pct: number;
            /** Timeframe */
            timeframe: string;
            /** Version */
            version: number;
        };
        /** ConfigTradingOut */
        ConfigTradingOut: {
            /** Capital Simulado */
            capital_simulado: number;
            /** Estrategia */
            estrategia: string;
            /** Instrumentos */
            instrumentos: string[];
            /** Max Perdida Diaria Pct */
            max_perdida_diaria_pct: number;
            /** Max Posiciones Abiertas */
            max_posiciones_abiertas: number;
            /** Stop Loss Pct */
            stop_loss_pct: number;
            /** Take Profit Pct */
            take_profit_pct: number;
            /** Timeframe */
            timeframe: string;
        };
        /**
         * ConfirmarPasswordIn
         * @description Confirmaci�n para acciones destructivas sobre datos propios.
         */
        ConfirmarPasswordIn: {
            /** Password */
            password: string;
        };
        /** CoverageItem */
        CoverageItem: {
            /**
             * Available
             * @default false
             */
            available: boolean;
            /** Ingested At */
            ingested_at?: string | null;
            /** Name */
            name: string;
            /** Observed At */
            observed_at?: string | null;
            /** Published At */
            published_at?: string | null;
            /**
             * Reason
             * @default
             */
            reason: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
            /** Series Id */
            series_id: string;
            /** Source Id */
            source_id: string;
            /**
             * Source Url
             * @default
             */
            source_url: string;
        };
        /** CoverageOut */
        CoverageOut: {
            /** Items */
            items: components["schemas"]["CoverageItem"][];
        };
        /** CsrfOut */
        CsrfOut: {
            /** Csrf Token */
            csrf_token: string;
        };
        /** DeliveriesOut */
        DeliveriesOut: {
            /** Items */
            items: components["schemas"]["DeliveryOut"][];
        };
        /** DeliveryOut */
        DeliveryOut: {
            /** Attempts */
            attempts: number;
            /** Channel */
            channel: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Detail */
            detail: string;
            /** Id */
            id: string;
            /** Report Id */
            report_id: string;
            /** Status */
            status: string;
        };
        /** EjecucionAdminOut */
        EjecucionAdminOut: {
            /** App Name */
            app_name: string;
            /** Command Key */
            command_key: string;
            /** Command Label */
            command_label: string;
            /** Duration Seconds */
            duration_seconds: number | null;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: number;
            result?: components["schemas"]["ResultadoOut"] | null;
            /** Return Code */
            return_code: number | null;
            /** Skip Reason */
            skip_reason: string | null;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
            /** Trigger */
            trigger: string;
            /** User Email */
            user_email?: string | null;
            /** User Id */
            user_id: string | null;
        };
        /** EjecucionesAdminOut */
        EjecucionesAdminOut: {
            /** Items */
            items: components["schemas"]["EjecucionAdminOut"][];
        };
        /** EjecucionesOut */
        EjecucionesOut: {
            /** Items */
            items: components["schemas"]["EjecucionOut"][];
        };
        /** EjecucionOut */
        EjecucionOut: {
            /** App Name */
            app_name: string;
            /** Command Key */
            command_key: string;
            /** Command Label */
            command_label: string;
            /** Duration Seconds */
            duration_seconds: number | null;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: number;
            result?: components["schemas"]["ResultadoOut"] | null;
            /** Return Code */
            return_code: number | null;
            /** Skip Reason */
            skip_reason: string | null;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
            /** Trigger */
            trigger: string;
        };
        /** EntradaBitacoraOut */
        EntradaBitacoraOut: {
            /** Action */
            action: string;
            /** Actor Email */
            actor_email: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Detail Json */
            detail_json: {
                [key: string]: unknown;
            };
            /** Id */
            id: number;
            /** Target Email */
            target_email: string;
        };
        /** EstadoMotorOut */
        EstadoMotorOut: {
            /** Alcanzable */
            alcanzable: boolean;
            /** Config Version */
            config_version?: number | null;
            /** Corriendo */
            corriendo: boolean;
            /** Detalle */
            detalle: string;
            /**
             * Estado
             * @enum {string}
             */
            estado: "desconocido" | "operando" | "pausado" | "esperando" | "detenido" | "error" | "bloqueado" | "stale";
            /** Latido En */
            latido_en?: string | null;
            /** Modo */
            modo: string;
            /** Posiciones Abiertas */
            posiciones_abiertas: number | null;
            /** Version */
            version?: string | null;
        };
        /**
         * EstrategiaInfoOut
         * @description Una estrategia ofrecida por un motor con cat�logo cerrado.
         */
        EstrategiaInfoOut: {
            /** Descripcion */
            descripcion: string;
            /** Etiqueta */
            etiqueta: string;
            /** Nombre */
            nombre: string;
        };
        /** Evidence */
        Evidence: {
            /** Available At */
            available_at?: string | null;
            /**
             * Direction
             * @enum {string}
             */
            direction: "FAVORABLE" | "ADVERSA" | "MIXTA" | "NO_EVALUABLE";
            /** Observation Ids */
            observation_ids?: number[];
            /** Observed At */
            observed_at?: string | null;
            /** Reading */
            reading: string;
            /** Series Id */
            series_id: string;
            /**
             * Source Url
             * @default
             */
            source_url: string;
            /**
             * Unit
             * @default
             */
            unit: string;
            /** Value */
            value?: number | null;
        };
        /** HistoryOut */
        HistoryOut: {
            /** First Available At */
            first_available_at: string | null;
            /** Items */
            items: components["schemas"]["SnapshotOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /**
             * Requested From
             * Format: date-time
             */
            requested_from: string;
            /** Total */
            total: number;
            /** Unavailable Before First */
            unavailable_before_first: boolean;
        };
        /**
         * HitDetalleOut
         * @description Un hallazgo nuevo de StockWatcher, tal como lo publica ``hit_detail``.
         *
         *     Espejo deliberado de lo que ya recibe el correo (mismo shape que
         *     ``notifiers.base.summarize`` + la imagen): la tarjeta que pinta la SPA y
         *     la del email deben mostrar lo mismo, solo que una en HTML de tabla y la
         *     otra en componentes React.
         */
        HitDetalleOut: {
            /**
             * Color Matched
             * @default true
             */
            color_matched: boolean;
            /** Image */
            image?: string | null;
            /** Price */
            price?: string | null;
            /** Product */
            product: string;
            /** Store */
            store: string;
            /** Url */
            url: string;
            /** Variant */
            variant: string;
            /** Watch */
            watch: string;
        };
        /** HoldingIn */
        HoldingIn: {
            /** Avg Cost */
            avg_cost: number;
            /** Quantity */
            quantity: number;
            /**
             * Sector Hint
             * @default unknown
             */
            sector_hint: string;
            /** Ticker */
            ticker: string;
        };
        /** HoldingOut */
        HoldingOut: {
            /** Avg Cost */
            avg_cost: number;
            /** Cost Basis */
            readonly cost_basis: number;
            /** Id */
            id: string;
            /** Quantity */
            quantity: number;
            /** Sector Hint */
            sector_hint: string;
            /** Ticker */
            ticker: string;
        };
        /** HorizonResult */
        HorizonResult: {
            /**
             * Calibration Status
             * @default HEURISTICO_NO_VALIDADO
             * @constant
             */
            calibration_status: "HEURISTICO_NO_VALIDADO";
            /** Categories */
            categories?: components["schemas"]["CategoryResult"][];
            /** Changes */
            changes?: string[];
            /**
             * Confidence
             * @default NO_EVALUABLE
             * @enum {string}
             */
            confidence: "BAJA" | "MEDIA" | "ALTA" | "NO_EVALUABLE";
            /** Contradictions */
            contradictions?: string[];
            /**
             * Data Status
             * @enum {string}
             */
            data_status: "SIN_DATOS" | "INCOMPLETO" | "COMPLETO";
            /** Drivers */
            drivers?: string[];
            /**
             * Horizon
             * @enum {string}
             */
            horizon: "SHORT" | "MEDIUM" | "LONG";
            /** Missing */
            missing?: string[];
            /** Previous Regime */
            previous_regime?: ("RISK_ON" | "RISK_OFF" | "NEUTRAL") | null;
            /** Regime */
            regime?: ("RISK_ON" | "RISK_OFF" | "NEUTRAL") | null;
            /** Score */
            score?: number | null;
            /**
             * Transition Status
             * @default NO_EVALUABLE
             * @enum {string}
             */
            transition_status: "ESTABLE" | "EN_TRANSICION" | "NO_EVALUABLE";
            /** Would Change */
            would_change?: string[];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** InterruptorIn */
        InterruptorIn: {
            /** Enabled */
            enabled: boolean;
            /** Version */
            version: number;
        };
        /** LanzarIn */
        LanzarIn: {
            /** Command Key */
            command_key: string;
            /**
             * Dry Run
             * @default false
             */
            dry_run: boolean;
        };
        /** LoginIn */
        LoginIn: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
        };
        /** LogOut */
        LogOut: {
            /** Content */
            content: string;
            /** Run Id */
            run_id: number;
            /** Running */
            running: boolean;
            /** Status */
            status: string;
        };
        /** MetricasOut */
        MetricasOut: {
            /** Admins */
            admins: number;
            /** Jobs Running */
            jobs_running: number;
            /** Recent Failures */
            recent_failures: number;
            /** Runs Last 24H */
            runs_last_24h: number;
            /** Users By Status */
            users_by_status: {
                [key: string]: number;
            };
            /** Users Total */
            users_total: number;
            /** Window Hours */
            window_hours: number;
        };
        /** MotivoOut */
        MotivoOut: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /**
         * MotorInfoOut
         * @description Descripci�n est�tica de un motor, para que la UI se adapte sola.
         */
        MotorInfoOut: {
            /** Bot Name */
            bot_name: string;
            /** Clase Activo */
            clase_activo: string;
            /** Display Name */
            display_name: string;
            /** Ejemplo Instrumento */
            ejemplo_instrumento: string;
            /**
             * Estrategias
             * @default []
             */
            estrategias: components["schemas"]["EstrategiaInfoOut"][];
            /** Max Instrumentos */
            max_instrumentos: number;
            /** Motivo Bloqueo */
            motivo_bloqueo: string;
            /** Permite Encender */
            permite_encender: boolean;
            /** Proyecto */
            proyecto: string;
            /** Simula Contra */
            simula_contra: string;
            /** Termino Plural */
            termino_plural: string;
            /** Termino Singular */
            termino_singular: string;
            /** Timeframes */
            timeframes: string[];
        };
        /**
         * NotificacionesIn
         * @description Destinos de notificaci�n. Cadena vac�a o `null` borra el canal.
         */
        NotificacionesIn: {
            /**
             * Email
             * @default
             */
            email: string | null;
            /**
             * Whatsapp
             * @default
             */
            whatsapp: string | null;
        };
        /**
         * NotificacionesOut
         * @description Forma plana, pensada para mapear directo a un formulario.
         *
         *     `supported` existe para que la UI nunca tenga que hardcodear qu� canales
         *     ofrece cada app: se deriva de `WatcherSpec.canales_soportados` en
         *     `watchers.py`, as� que si alg�n watcher no implementara un canal (o deja
         *     de implementarlo), la UI lo refleja sin ning�n cambio de frontend.
         */
        NotificacionesOut: {
            /** Email */
            email?: string | null;
            /** Preferences */
            preferences?: {
                [key: string]: string[];
            };
            /** Supported */
            supported?: {
                [key: string]: string[];
            };
            /** Whatsapp */
            whatsapp?: string | null;
        };
        /** OfficialEvent */
        OfficialEvent: {
            /**
             * Available At
             * Format: date-time
             */
            available_at: string;
            /**
             * Event At
             * Format: date-time
             */
            event_at: string;
            /** Event Id */
            event_id: string;
            /**
             * Kind
             * @default release
             * @enum {string}
             */
            kind: "release" | "meeting" | "minutes" | "projection";
            /** Published At */
            published_at?: string | null;
            /**
             * Scheduled
             * @default false
             */
            scheduled: boolean;
            /** Source Id */
            source_id: string;
            /** Source Url */
            source_url: string;
            /**
             * Timestamp Precision
             * @default date
             * @enum {string}
             */
            timestamp_precision: "exact" | "date" | "observed";
            /** Title */
            title: string;
        };
        /** OkOut */
        OkOut: {
            /**
             * Mensaje
             * @default
             */
            mensaje: string;
            /**
             * Ok
             * @default true
             */
            ok: boolean;
        };
        /** OperacionesOut */
        OperacionesOut: {
            /**
             * Disponible
             * @default true
             */
            disponible: boolean;
            /** Items */
            items: components["schemas"]["OperacionOut"][];
        };
        /** OperacionOut */
        OperacionOut: {
            /** Abierta */
            abierta: boolean;
            /** Abierta En */
            abierta_en: string | null;
            /** Cantidad */
            cantidad: number;
            /** Cerrada En */
            cerrada_en: string | null;
            /** Instrumento */
            instrumento: string;
            /** Lado */
            lado: string;
            /** Pnl Absoluto */
            pnl_absoluto: number | null;
            /** Pnl Pct */
            pnl_pct: number | null;
            /** Precio Entrada */
            precio_entrada: number;
            /** Precio Salida */
            precio_salida: number | null;
        };
        /** OverviewOut */
        OverviewOut: {
            /** Calendar Status */
            calendar_status: string;
            /** Coverage */
            coverage: components["schemas"]["CoverageItem"][];
            /** Deliveries Enabled */
            deliveries_enabled: boolean;
            /** Enabled */
            enabled: boolean;
            /** Engine Enabled */
            engine_enabled: boolean;
            /** First Snapshot At */
            first_snapshot_at?: string | null;
            /** Next Report At */
            next_report_at?: string | null;
            snapshot?: components["schemas"]["SnapshotData"] | null;
            /** Snapshot Id */
            snapshot_id?: string | null;
            /**
             * Warning
             * @default Score heuristico no validado; no es probabilidad de ganancias.
             */
            warning: string;
        };
        /**
         * PasswordAdminIn
         * @description O se fija una contrase�a nueva, o se invalida la actual.
         *
         *     `force_reset` existe para el caso �no quiero conocer su contrase�a�: deja
         *     la cuenta sin acceso hasta que se le asigne una.
         */
        PasswordAdminIn: {
            /**
             * Force Reset
             * @default false
             */
            force_reset: boolean;
            /** New Password */
            new_password?: string | null;
        };
        /** PerfilIn */
        PerfilIn: {
            /** Timezone */
            timezone: string;
        };
        /** PerfilRiesgoIn */
        PerfilRiesgoIn: {
            /**
             * Analysis Interval Days
             * @default 7
             */
            analysis_interval_days: number;
            /**
             * Horizon
             * @default long_term
             */
            horizon: string;
            /**
             * Notes
             * @default
             */
            notes: string;
            /**
             * Tolerance
             * @default moderate
             */
            tolerance: string;
        };
        /** PerfilRiesgoOut */
        PerfilRiesgoOut: {
            /** Analysis Interval Days */
            analysis_interval_days: number;
            /** Horizon */
            horizon: string;
            /** Notes */
            notes: string;
            /** Tolerance */
            tolerance: string;
        };
        /** PortafolioOut */
        PortafolioOut: {
            /** Closed Positions */
            closed_positions: components["schemas"]["PosicionCerradaOut"][];
            /** Cost Basis Total */
            cost_basis_total: number;
            /** Holdings */
            holdings: components["schemas"]["HoldingOut"][];
            profile: components["schemas"]["PerfilRiesgoOut"];
        };
        /** PosicionCerradaIn */
        PosicionCerradaIn: {
            /**
             * Note
             * @default
             */
            note: string;
            /** Ticker */
            ticker: string;
        };
        /** PosicionCerradaOut */
        PosicionCerradaOut: {
            /** Id */
            id: string;
            /** Note */
            note: string;
            /** Ticker */
            ticker: string;
        };
        /**
         * PreferenciasIn
         * @description Canales activos de una app. Reemplaza el conjunto completo.
         */
        PreferenciasIn: {
            /** App Name */
            app_name: string;
            /** Channels */
            channels?: string[];
        };
        /** PreviewOut */
        PreviewOut: {
            /** App Name */
            app_name: string;
            /** Filename */
            filename: string;
            /** Path */
            path: string;
            /** Yaml */
            yaml: string;
        };
        /** ProgramacionesOut */
        ProgramacionesOut: {
            /** Items */
            items: components["schemas"]["ProgramacionOut"][];
            /** Timezone */
            timezone: string;
        };
        /**
         * ProgramacionIn
         * @description C�mo debe automatizarse un comando concreto.
         *
         *     `kind` decide qu� campo manda: `interval` usa `interval_minutes` y `cron`
         *     usa `cron_expr`. La coherencia entre ambos la valida el scheduler, que es
         *     quien conoce los l�mites reales.
         */
        ProgramacionIn: {
            /** Cron Expr */
            cron_expr?: string | null;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Interval Minutes */
            interval_minutes?: number | null;
            /**
             * Kind
             * @default interval
             * @enum {string}
             */
            kind: "interval" | "cron";
        };
        /** ProgramacionOut */
        ProgramacionOut: {
            /** App Name */
            app_name: string;
            /** Command Key */
            command_key: string;
            /** Command Label */
            command_label: string;
            /** Cron Expr */
            cron_expr: string | null;
            /** Enabled */
            enabled: boolean;
            /** Interval Minutes */
            interval_minutes: number | null;
            /** Kind */
            kind: string;
            /** Last Run At */
            last_run_at: string | null;
            /** Next Run At */
            next_run_at: string | null;
        };
        /** ReadinessAppOut */
        ReadinessAppOut: {
            /** App Name */
            app_name: string;
            /** Display Name */
            display_name: string;
            /** Ready */
            ready: boolean;
            /** Reasons */
            reasons: components["schemas"]["MotivoOut"][];
        };
        /** ReadinessGlobalOut */
        ReadinessGlobalOut: {
            /** Apps */
            apps: {
                [key: string]: components["schemas"]["ReadinessAppOut"];
            };
        };
        /** RegistroIn */
        RegistroIn: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
            /**
             * Timezone
             * @default America/Bogota
             */
            timezone: string;
        };
        /** RegistroOut */
        RegistroOut: {
            /** Mensaje */
            mensaje: string;
            user: components["schemas"]["UsuarioOut"];
        };
        /** RendimientoOut */
        RendimientoOut: {
            /** Capital Actual */
            capital_actual: number;
            /** Capital Inicial */
            capital_inicial: number;
            /** Costos Simulados */
            costos_simulados: number | null;
            /**
             * Disponible
             * @default true
             */
            disponible: boolean;
            /** Ganadoras */
            ganadoras: number;
            /** Mejor Pct */
            mejor_pct: number | null;
            /** Operaciones Cerradas */
            operaciones_cerradas: number;
            /** Peor Pct */
            peor_pct: number | null;
            /** Perdedoras */
            perdedoras: number;
            /** Pnl Absoluto */
            pnl_absoluto: number;
            /** Pnl Pct */
            pnl_pct: number;
            /** Win Rate */
            win_rate: number | null;
        };
        /** ReordenarIn */
        ReordenarIn: {
            /** Ids */
            ids: string[];
        };
        /** ReportData */
        ReportData: {
            /** Brief */
            brief: string;
            /** Html */
            html: string;
            /** Matrix */
            matrix: components["schemas"]["Evidence"][];
            /**
             * Narrative Status
             * @default DESHABILITADO
             * @enum {string}
             */
            narrative_status: "DESHABILITADO" | "ERROR" | "COMPLETO";
            /** Sections */
            sections: components["schemas"]["ReportSection"][];
            /** Snapshot Ids */
            snapshot_ids?: string[];
            /** Text */
            text: string;
            /** Title */
            title: string;
        };
        /** ReportOut */
        ReportOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            data: components["schemas"]["ReportData"];
            /** Id */
            id: string;
            /** Sha256 */
            sha256: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Week Key */
            week_key: string;
        };
        /** ReportSection */
        ReportSection: {
            /** Number */
            number: number;
            /** Text */
            text: string;
            /** Title */
            title: string;
        };
        /** ReportsOut */
        ReportsOut: {
            /** Items */
            items: components["schemas"]["ReportOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /**
         * ResultadoOut
         * @description Subconjunto de ``RunSummary.as_dict()`` que vale la pena mostrar en la
         *     SPA. Ausente en corridas que no publican JSON estructurado (hoy, solo
         *     ``stockwatcher run``).
         */
        ResultadoOut: {
            /**
             * Hit Details
             * @default []
             */
            hit_details: components["schemas"]["HitDetalleOut"][];
            /**
             * New Hits
             * @default 0
             */
            new_hits: number;
            /**
             * Stores Failed
             * @default 0
             */
            stores_failed: number;
            /**
             * Stores Scanned
             * @default 0
             */
            stores_scanned: number;
        };
        /** RunIn */
        RunIn: {
            /**
             * Kind
             * @default ingest
             * @enum {string}
             */
            kind: "ingest" | "snapshot" | "report";
        };
        /** RunOut */
        RunOut: {
            /** Detail */
            detail: string;
            /** Finished At */
            finished_at: string | null;
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Result */
            result: {
                [key: string]: unknown;
            };
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
        };
        /** RunsOut */
        RunsOut: {
            /** Items */
            items: components["schemas"]["RunOut"][];
        };
        /**
         * SesionOut
         * @description Respuesta de `/auth/me` y del login.
         */
        SesionOut: {
            /** Csrf Token */
            csrf_token: string;
            user: components["schemas"]["UsuarioOut"];
        };
        /** SnapshotData */
        SnapshotData: {
            /**
             * As Of
             * Format: date-time
             */
            as_of: string;
            /** Context */
            context: string;
            /** Coverage */
            coverage: components["schemas"]["CoverageItem"][];
            /** Events */
            events?: components["schemas"]["OfficialEvent"][];
            /** Horizons */
            horizons: components["schemas"]["HorizonResult"][];
            /**
             * Mode
             * @default OPERACIONAL
             * @enum {string}
             */
            mode: "OPERACIONAL" | "RECONSTRUCCION";
            /** Model Version */
            model_version: string;
        };
        /** SnapshotOut */
        SnapshotOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            data: components["schemas"]["SnapshotData"];
            /** Id */
            id: string;
            /** Sha256 */
            sha256: string;
        };
        /** SourceInfo */
        SourceInfo: {
            /**
             * Detail
             * @default
             */
            detail: string;
            /** Id */
            id: string;
            /** Last Success At */
            last_success_at?: string | null;
            /** Name */
            name: string;
            /**
             * Requires Key
             * @default false
             */
            requires_key: boolean;
            /**
             * Restricted
             * @default false
             */
            restricted: boolean;
            /** Series */
            series?: string[];
            /**
             * Status
             * @default PENDIENTE
             * @enum {string}
             */
            status: "DISPONIBLE" | "NO_CONFIGURADO" | "BLOQUEADO_LICENCIA" | "ERROR" | "PENDIENTE";
            /** Terms Url */
            terms_url: string;
            /** Url */
            url: string;
        };
        /** SourcesOut */
        SourcesOut: {
            /** Items */
            items: components["schemas"]["SourceInfo"][];
        };
        /** SubscriptionIn */
        SubscriptionIn: {
            /**
             * Accept Consent
             * @default false
             */
            accept_consent: boolean;
            /**
             * Email
             * @default false
             */
            email: boolean;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /** Horizons */
            horizons?: ("SHORT" | "MEDIUM" | "LONG")[];
            /**
             * Whatsapp
             * @default false
             */
            whatsapp: boolean;
        };
        /** SubscriptionOut */
        SubscriptionOut: {
            /**
             * Consent Version
             * @default market-regime-v1
             */
            consent_version: string;
            /**
             * Detail
             * @default
             */
            detail: string;
            /** Email */
            email: boolean;
            /**
             * Email Ready
             * @default false
             */
            email_ready: boolean;
            /** Enabled */
            enabled: boolean;
            /** Horizons */
            horizons: ("SHORT" | "MEDIUM" | "LONG")[];
            /** Whatsapp */
            whatsapp: boolean;
            /**
             * Whatsapp Ready
             * @default false
             */
            whatsapp_ready: boolean;
        };
        /** UsuarioAdminOut */
        UsuarioAdminOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Email */
            email: string;
            /** Id */
            id: string;
            /** Last Login At */
            last_login_at: string | null;
            /** Locked Until */
            locked_until: string | null;
            /** Must Change Password */
            must_change_password: boolean;
            /** Role */
            role: string;
            /** Status */
            status: string;
            /** Timezone */
            timezone: string;
        };
        /** UsuarioDetalleOut */
        UsuarioDetalleOut: {
            /** Channels */
            channels: components["schemas"]["CanalResumenOut"][];
            /** Closed Positions */
            closed_positions: number;
            /** Holdings */
            holdings: number;
            /** Recent Runs */
            recent_runs: components["schemas"]["EjecucionOut"][];
            /** Schedules */
            schedules: components["schemas"]["ProgramacionOut"][];
            /** Total Runs */
            total_runs: number;
            user: components["schemas"]["UsuarioAdminOut"];
            /** Watches */
            watches: number;
            /** Watches Enabled */
            watches_enabled: number;
        };
        /**
         * UsuarioOut
         * @description Representaci�n p�blica del usuario en sesi�n.
         */
        UsuarioOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Email */
            email: string;
            /** Id */
            id: string;
            /** Last Login At */
            last_login_at: string | null;
            /** Must Change Password */
            must_change_password: boolean;
            /** Regime Level */
            regime_level?: ("viewer" | "operator") | null;
            /** Role */
            role: string;
            /** Status */
            status: string;
            /** Timezone */
            timezone: string;
            /** Trading Level */
            trading_level?: ("viewer" | "operator") | null;
        };
        /** UsuariosAdminOut */
        UsuariosAdminOut: {
            /** Items */
            items: components["schemas"]["UsuarioAdminOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, unknown>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * WatchesOut
         * @description Sobre con `items` en vez de una lista desnuda: deja sitio para
         *     metadatos (l�mite, contador) sin romper el contrato.
         */
        WatchesOut: {
            /** Items */
            items: components["schemas"]["WatchOut"][];
            /** Limit */
            limit: number;
        };
        /** WatchIn */
        WatchIn: {
            /** Colors */
            colors?: string[];
            /** Countries */
            countries?: string[];
            /**
             * Currency
             * @default USD
             */
            currency: string;
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Exclude Terms */
            exclude_terms?: string[];
            /**
             * Gender
             * @default unisex
             */
            gender: string;
            /** Match Terms */
            match_terms: string[];
            /** Max Price */
            max_price?: string | null;
            /** Name */
            name: string;
            /** Notify Channels */
            notify_channels?: string[];
            /** Variants */
            variants?: string[];
        };
        /** WatchOut */
        WatchOut: {
            /** Colors */
            colors: string[];
            /** Countries */
            countries: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Currency */
            currency: string;
            /** Enabled */
            enabled: boolean;
            /** Exclude Terms */
            exclude_terms: string[];
            /** Gender */
            gender: string;
            /** Id */
            id: string;
            /** Match Terms */
            match_terms: string[];
            /** Max Price */
            max_price: string | null;
            /** Name */
            name: string;
            /** Notify Channels */
            notify_channels: string[];
            /** Position */
            position: number;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Variants */
            variants: string[];
        };
        /** ZonaHorariaIn */
        ZonaHorariaIn: {
            /** Timezone */
            timezone: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    bitacora_api_v1_admin_audit_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BitacoraOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    metricas_api_v1_admin_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetricasOut"];
                };
            };
        };
    };
    listar_ejecuciones_api_v1_admin_runs_get: {
        parameters: {
            query?: {
                app_name?: string | null;
                limit?: number;
                status?: string | null;
                user_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EjecucionesAdminOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_log_api_v1_admin_runs__run_id__log_get: {
        parameters: {
            query?: {
                lines?: number;
            };
            header?: never;
            path: {
                run_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LogOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_usuarios_api_v1_admin_users_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
                order?: string;
                q?: string | null;
                role?: string | null;
                sort?: string;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsuariosAdminOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_usuario_api_v1_admin_users__user_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsuarioDetalleOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    eliminar_usuario_api_v1_admin_users__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cambiar_usuario_api_v1_admin_users__user_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CambiarUsuarioIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsuarioAdminOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lanzar_api_v1_admin_users__user_id__apps__app_name__runs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LanzarIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EjecucionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancelar_api_v1_admin_users__user_id__apps__app_name__runs_current_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cambiar_password_api_v1_admin_users__user_id__password_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PasswordAdminIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    csrf_api_v1_auth_csrf_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CsrfOut"];
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SesionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OkOut"];
                };
            };
        };
    };
    yo_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SesionOut"];
                };
            };
        };
    };
    cambiar_password_api_v1_auth_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CambioPasswordIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OkOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    actualizar_perfil_api_v1_auth_profile_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PerfilIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsuarioOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registrar_api_v1_auth_register_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegistroIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RegistroOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    access_list_api_v1_market_regime_access_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccessesOut"];
                };
            };
        };
    };
    grant_api_v1_market_regime_access__user_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccessIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccessOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_api_v1_market_regime_access__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    config_api_v1_market_regime_config_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConfigOut"];
                };
            };
        };
    };
    change_config_api_v1_market_regime_config_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConfigIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConfigOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    coverage_api_v1_market_regime_coverage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoverageOut"];
                };
            };
        };
    };
    history_api_v1_market_regime_history_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
                range?: "1w" | "1m" | "3m" | "6m" | "12m";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HistoryOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deliveries_api_v1_market_regime_me_deliveries_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeliveriesOut"];
                };
            };
        };
    };
    subscription_api_v1_market_regime_me_subscription_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubscriptionOut"];
                };
            };
        };
    };
    update_subscription_api_v1_market_regime_me_subscription_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubscriptionIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubscriptionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    operations_api_v1_market_regime_operations_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunsOut"];
                };
            };
        };
    };
    overview_api_v1_market_regime_overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverviewOut"];
                };
            };
        };
    };
    reports_api_v1_market_regime_reports_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportsOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    report_api_v1_market_regime_reports__report_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                report_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    report_html_api_v1_market_regime_reports__report_id__html_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                report_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/html": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_run_api_v1_market_regime_runs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RunIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_api_v1_market_regime_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    snapshot_api_v1_market_regime_snapshots__snapshot_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sources_api_v1_market_regime_sources_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourcesOut"];
                };
            };
        };
    };
    listar_apps_api_v1_me_apps_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppsOut"];
                };
            };
        };
    };
    previsualizar_config_api_v1_me_apps__app_name__config_preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PreviewOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_readiness_api_v1_me_apps__app_name__readiness_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadinessAppOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lanzar_ejecucion_api_v1_me_apps__app_name__runs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LanzarIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EjecucionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancelar_ejecucion_api_v1_me_apps__app_name__runs_current_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    borrar_mis_datos_api_v1_me_data_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConfirmarPasswordIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_notificaciones_api_v1_me_notifications_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionesOut"];
                };
            };
        };
    };
    guardar_notificaciones_api_v1_me_notifications_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotificacionesIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    guardar_preferencias_api_v1_me_notifications_preferences_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PreferenciasIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificacionesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_portafolio_api_v1_me_portfolio_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortafolioOut"];
                };
            };
        };
    };
    crear_cerrada_api_v1_me_portfolio_closed_positions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PosicionCerradaIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PosicionCerradaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    editar_cerrada_api_v1_me_portfolio_closed_positions__cerrada_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cerrada_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PosicionCerradaIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PosicionCerradaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    borrar_cerrada_api_v1_me_portfolio_closed_positions__cerrada_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                cerrada_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    crear_holding_api_v1_me_portfolio_holdings_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HoldingIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    editar_holding_api_v1_me_portfolio_holdings__holding_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HoldingIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HoldingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    borrar_holding_api_v1_me_portfolio_holdings__holding_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                holding_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    guardar_perfil_api_v1_me_portfolio_profile_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PerfilRiesgoIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PerfilRiesgoOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_readiness_global_api_v1_me_readiness_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadinessGlobalOut"];
                };
            };
        };
    };
    listar_ejecuciones_api_v1_me_runs_get: {
        parameters: {
            query?: {
                app_name?: string | null;
                limit?: number;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EjecucionesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_ejecucion_api_v1_me_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EjecucionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_log_api_v1_me_runs__run_id__log_get: {
        parameters: {
            query?: {
                lines?: number;
            };
            header?: never;
            path: {
                run_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LogOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_programaciones_api_v1_me_schedules_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProgramacionesOut"];
                };
            };
        };
    };
    guardar_programacion_api_v1_me_schedules__app_name___command_key__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
                command_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProgramacionIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProgramacionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    borrar_programacion_api_v1_me_schedules__app_name___command_key__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_name: string;
                command_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_watches_api_v1_me_stockwatcher_watches_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchesOut"];
                };
            };
        };
    };
    reordenar_watches_api_v1_me_stockwatcher_watches_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReordenarIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    crear_watch_api_v1_me_stockwatcher_watches_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WatchIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ver_watch_api_v1_me_stockwatcher_watches__watch_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                watch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    editar_watch_api_v1_me_stockwatcher_watches__watch_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                watch_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WatchIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    borrar_watch_api_v1_me_stockwatcher_watches__watch_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                watch_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cambiar_zona_horaria_api_v1_me_timezone_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ZonaHorariaIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProgramacionesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_accesos_api_v1_trading_access_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccesosTradingOut"];
                };
            };
        };
    };
    conceder_acceso_api_v1_trading_access__user_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccesoTradingIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccesoTradingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revocar_acceso_api_v1_trading_access__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_bots_api_v1_trading_bots_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BotsTradingOut"];
                };
            };
        };
    };
    obtener_bot_api_v1_trading_bots__bot_name__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                bot_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BotTradingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    guardar_config_api_v1_trading_bots__bot_name__config_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                bot_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConfigTradingIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BotTradingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rendimiento_api_v1_trading_bots__bot_name__performance_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                bot_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RendimientoOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    interruptor_api_v1_trading_bots__bot_name__switch_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                bot_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InterruptorIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BotTradingOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    listar_operaciones_api_v1_trading_bots__bot_name__trades_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                bot_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OperacionesOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
