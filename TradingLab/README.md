# TradingLab

Motor de trading **simulado** de acciones y ETFs para el dashboard del homelab.

Lee la configuración que los usuarios autorizados guardan desde el panel, opera
contra **Alpaca Paper** a través de [Lumibot](https://lumibot.lumiwealth.com/) y
publica su estado en un SQLite que el dashboard lee en solo lectura.

> **Solo dinero simulado.** No hay ninguna ruta de código que toque una cuenta
> real, y la tabla de configuración del dashboard tiene un `CHECK` que solo
> admite `'paper'`. Habilitar dinero real exigiría otra migración, que es
> justamente la fricción que se busca.

## Cómo encaja con el dashboard

```
┌──────────────────┐   escribe    ┌────────────────┐   lee (ro)   ┌────────────┐
│  Panel web       │─────────────▶│  dashboard.db  │─────────────▶│ TradingLab │
│  (HomelabFrontend)│              │ trading_bot_   │              │            │
└──────────────────┘              │ config         │              └─────┬──────┘
         ▲                        └────────────────┘                    │
         │                                                              │ escribe
         │           lee (ro)     ┌────────────────┐                    │
         └────────────────────────│ tradinglab.db  │◀───────────────────┘
                                  │ estado_motor   │
                                  │ operaciones    │
                                  └────────────────┘
```

Ninguna de las dos aplicaciones escribe en la base de la otra. Nadie le ordena
a TradingLab arrancar o parar: el dashboard publica `enabled`, y este proceso lo
relee en cada vuelta. La consecuencia práctica es que **apagar el bot desde el
celular funciona aunque el proceso esté a mitad de una decisión**, porque no hay
ninguna orden que se pueda perder.

El contrato completo está en
[`HomelabFrontend/docs/trading.md`](../HomelabFrontend/docs/trading.md).

## Instalación

```bash
cd TradingLab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # núcleo + herramientas de desarrollo
pip install -e ".[alpaca,dev]"   # además, el motor real
```

El núcleo **no tiene dependencias**: el bucle, el contrato con el dashboard y la
contabilidad corren y se prueban sin instalar Lumibot.

> ⚠️ **Lumibot es pesado.** Arrastra más de cincuenta dependencias directas
> (`pyarrow`, `polars`, `scipy`, `boto3`, `ccxt`, `duckdb`, `matplotlib`…) y
> ocupa varios cientos de megabytes en disco. Comprueba el espacio de la VM
> antes de instalarlo, no solo la RAM.

## Uso

```bash
tradinglab correr                # bucle de supervisión (lo que corre en systemd)
tradinglab correr --simulado     # contra precios inventados, sin Alpaca ni credenciales
tradinglab correr --una-vez      # una sola vuelta y salir
tradinglab estado                # último latido y posiciones abiertas
tradinglab operaciones           # las últimas operaciones registradas
tradinglab doctor                # comprueba el entorno sin enviar una sola orden
```

`--simulado` sirve para **arrancar antes de tener credenciales**: el dashboard
empieza a recibir latidos y operaciones de verdad contra precios generados con
una semilla fija, lo que verifica todo el contrato menos la última milla.

## Variables de entorno

| Variable                   | Por defecto            | Para qué                                            |
| -------------------------- | ---------------------- | --------------------------------------------------- |
| `TRADINGLAB_DASHBOARD_DB`  | `data/dashboard.db`    | Base del dashboard, de donde se lee la configuración |
| `TRADINGLAB_DB`            | `data/tradinglab.db`   | Base propia; debe coincidir con `DASHBOARD_TRADINGLAB_DB` |
| `ALPACA_API_KEY`           | —                      | Credenciales de Alpaca Paper                        |
| `ALPACA_API_SECRET`        | —                      | Credenciales de Alpaca Paper                        |
| `LUMIBOT_DISABLE_DOTENV`   | `1` (se fija solo)     | Evita que importar Lumibot escanee el disco buscando `.env` |

Las credenciales van en el `Environment=` de la unidad de systemd y **nunca en
la base de datos**: la configuración compartida la puede editar cualquier
usuario autorizado desde el celular.

## Configuración

Toda la configuración se edita desde el panel, no desde archivos. Los campos son
los que valida `HomelabFrontend/src/homelab_dashboard/trading.py`:

| Campo                     | Qué hace                                                  |
| ------------------------- | --------------------------------------------------------- |
| `instrumentos`            | Hasta 25 tickers (`AAPL`, `SPY`…)                          |
| `estrategia`              | `cruce_medias` o `reversion_rsi`; vacío usa la primera     |
| `timeframe`               | `5m`, `15m`, `30m`, `1h` o `1d`                            |
| `capital_simulado`        | Cuánto dinero de mentira se reparte entre las posiciones   |
| `max_posiciones_abiertas` | Cupo simultáneo; también define el capital por posición    |
| `stop_loss_pct`           | Cierre por pérdida, medido sobre el precio de entrada      |
| `take_profit_pct`         | Cierre por ganancia                                        |
| `max_perdida_diaria_pct`  | Freno diario: bloquea entradas nuevas, nunca salidas       |

## Estrategias

| Identificador   | Qué hace                                                        |
| --------------- | --------------------------------------------------------------- |
| `cruce_medias`  | Entra cuando la media de 20 cruza por encima de la de 50, y sale al revés. Acierta en tendencias. |
| `reversion_rsi` | Compra con RSI ≤ 30 y suelta con RSI ≥ 70. Acierta en rangos.    |

Están las dos y no una sola porque fallan en situaciones opuestas: el cruce
pierde en mercados laterales, la reversión pierde en tendencias fuertes.

Un nombre desconocido **no mata el bot**: se usa la estrategia por defecto y el
aviso viaja hasta el detalle que se ve en el panel. Una errata al configurar no
debería dejar el motor muerto sin explicación.

Ese comportamiento es la red de seguridad, no el mecanismo principal: el panel
ofrece estas dos en un **selector**, así que en la práctica no se teclean. La
lista está escrita también en `_ESTRATEGIAS_LUMIBOT`
(`HomelabFrontend/src/homelab_dashboard/trading.py`) porque son dos procesos que
no se importan entre sí, y hay un test a cada lado para que renombrar una aquí
rompa la compilación mental de alguien antes que la elección del usuario.

## Decisiones de diseño

**El latido va separado del ciclo de trading.** El bot late cada minuto, pase lo
que pase, y evalúa el mercado cada `timeframe`. Mezclarlos estaría mal por dos
motivos: el dashboard da por caído a un motor que lleva más de 90 minutos sin
latir, así que un bot en velas diarias aparecería como muerto 22 horas de cada
24; y en sentido contrario, un latido que solo ocurre al evaluar responde a la
pregunta equivocada —lo que el panel quiere saber es si el proceso está vivo, no
cuándo miró los precios por última vez.

**Sin WAL en la base propia.** Un lector que abre con `mode=ro` necesita poder
escribir el archivo `-shm` para acceder a una base en WAL. El dashboard abre
justo así, y si los dos procesos no comparten usuario fallaría con un «unable to
open database file» dificilísimo de diagnosticar. Aquí se escriben unas pocas
filas por hora: la concurrencia no es el problema a optimizar.

**Todas las marcas de tiempo son ISO-8601 UTC con `+00:00`, nunca `Z`.** El
dashboard ordena con `ORDER BY abierta_en DESC`, y en ese formato el orden
alfabético coincide con el cronológico.

**Solo posiciones largas.** El esquema admite `venta` porque el contrato es
común con Freqtrade, que sí opera en corto; pero vender acciones en corto exige
localización de títulos.

**Acciones enteras.** Alpaca admite fraccionarias solo en algunos tickers y con
reglas propias. Redondear hacia abajo es aburrido, funciona siempre y deja la
contabilidad exacta.

**El deslizamiento vive en el corredor, no en el ciclo.** Alpaca Paper ya
devuelve un precio de llenado con deslizamiento real incorporado; añadirlo
encima lo contaría dos veces. El corredor simulado sí se lo inventa, o la
simulación mentiría sistemáticamente a favor.

**El freno diario frena entradas, no salidas**, y cuenta solo el PnL cerrado:
una posición abierta que va perdiendo todavía puede darse la vuelta.

## Estructura

```
src/tradinglab/
  config.py           lee la configuración compartida del dashboard
  estado.py           publica estado_motor y operaciones (el contrato visible)
  estrategia.py       indicadores y estrategias — decisiones puras, sin dependencias
  ciclo.py            riesgo, órdenes y contabilidad
  corredor.py         protocolos Corredor y Motor + el corredor simulado
  corredor_alpaca.py  el único archivo que sabe que Lumibot existe
  supervisor.py       el bucle que corre bajo systemd
  trm.py              la tasa del día, best-effort, solo biblioteca estándar
  cli.py              correr / estado / operaciones / doctor
```

## Desarrollo

```bash
ruff check .
ruff format --check .
pytest -q
```

Los tests **no importan Lumibot** a propósito: todo lo que se puede probar sin
credenciales se prueba de verdad, y el camino de Alpaca se valida en la VM con
`tradinglab doctor`.

## Despliegue

Unidad de systemd, con lo que no es opcional:

```ini
[Service]
Type=simple
WorkingDirectory=/opt/tradinglab
Environment=TRADINGLAB_DASHBOARD_DB=/var/lib/homelab/dashboard.db
Environment=TRADINGLAB_DB=/var/lib/homelab/tradinglab.db
Environment=LUMIBOT_DISABLE_DOTENV=1
EnvironmentFile=/etc/tradinglab/secrets.env   # ALPACA_API_KEY, ALPACA_API_SECRET
ExecStart=/opt/tradinglab/.venv/bin/tradinglab correr
Restart=always
RestartSec=30
MemoryMax=600M
KillSignal=SIGINT
```

- `WorkingDirectory=` porque Lumibot escribe sus logs relativos al CWD.
- `KillSignal=SIGINT` porque Lumibot instala su propio manejador de SIGINT y no
  de SIGTERM. (TradingLab atiende ambas, pero esto evita depender de ello.)
- `MemoryMax=` porque la VM la comparten cuatro aplicaciones.
