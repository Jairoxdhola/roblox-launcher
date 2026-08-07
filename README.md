# Roblox Launcher 🎮

Un launcher de escritorio para Roblox, hecho con **Electron**, con todo organizado en pestañas.

## Funciones

| Pestaña | Qué hace |
| --- | --- |
| **Inicio** | Estado de tu Roblox, botón grande para jugar, **cerrar Roblox si está abierto** y accesos rápidos (carpetas, actualizar, web). |
| **Jugar** | Lanza cualquier juego pegando su ID, juegos populares con un clic, historial y botón para **cerrar Roblox**. |
| **Versión** | Comprueba si tienes la **última versión oficial** (API de Roblox) frente a la que tienes instalada, abre la carpeta de versiones y actualiza con un clic. |
| **Downgrade** | **Descargar e instalar** cualquier versión pasada desde el CDN oficial, **respaldos**, **restaurar/activar** versiones y **protección anti-actualización**. |
| **Spoofer** | Abre el **MAC Address Spoofer** (incluido en la app) en una terminal de Windows elevada (UAC): ver/cambiar la MAC, restaurar, flushear DNS, limpiar el DeviceID de Roblox, etc. |
| **Ajustes** | Comprobación automática al iniciar, notificaciones y gestión del historial. |

## Cómo ejecutarlo

```bash
npm install   # instala Electron (solo la primera vez)
npm start     # abre el launcher
```

## Cómo funciona

- **Detección de versión instalada:** escanea `%LOCALAPPDATA%\Roblox\Versions`, encuentra la carpeta con `RobloxPlayerBeta.exe` y lee su versión (ProductVersion).
- **Última versión oficial:** consulta `https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer`.
- **Lanzar juegos:** usa el protocolo `roblox://placeId=<id>`, que abre el juego directamente en el cliente instalado (el cliente no acepta URLs web como argumento).
- **Cerrar Roblox:** detecta el proceso con `tasklist` y lo cierra con `taskkill` (suave y, si hace falta, forzado).
- **Actualizar:** busca el `RobloxPlayerInstaller.exe` local y lo ejecuta; si no existe, lo **descarga directamente del CDN oficial** y lo lanza. Nunca abre el navegador.

> **Nota:** Roblox Launcher es una app independiente, sin relación con Roblox Corporation. Solo abre el cliente de Roblox que ya tienes instalado.

## Downgrade (cómo funciona de verdad)

Roblox instala cada versión en una carpeta nueva `version-<hash>` y Windows siempre lanza la que coincide con el servidor. Por eso la pestaña **Downgrade** funciona así:

1. **Descargar versión:** pega el hash de cualquier versión pasada (ej. `145f189a6a974303`) y el launcher usa el **método real del bootstrapper oficial**: baja el manifest de esa build (`setup.rbxcdn.com/version-<hash>-rbxPkgManifest.txt`), descarga los ~21 paquetes (RobloxApp.zip + contenidos) desde el CDN oficial, verifica sus MD5 y los descomprime en `Versions/version-<hash>/`.
2. **Activar:** cuando la carpeta instalada aparezca en la lista, pulsa **Activar** para copiarla sobre la versión activa. Roblox debe estar cerrado.
3. **Proteger:** marca los binarios como solo-lectura y aparta el instalador, para que la auto-actualización no sobrescriba la versión elegida. Desprotégela para volver a actualizar.
4. También puedes **guardar respaldos** de tu versión actual, **restaurar** un respaldo o **importar** una carpeta `version-…` de otra PC.

> ✅ El CDN oficial sirve los paquetes exactos de cualquier versión pasada (`setup.rbxcdn.com/version-<hash>-<paquete>.zip`), listados en su manifest. El launcher los instala tal cual lo hace el cliente oficial: downgrade 100% oficial.

También hay modos CLI (sin abrir la ventana):

```bash
npx electron . --install-version=145f189a6a974303   # descarga e instala la versión
npx electron . --activate-version=145f189a6a974303   # activa la versión instalada
npx electron . --protect                             # protege la versión activa
```

## Compartir como .exe y actualizaciones automáticas

### Empaquetar para tu amigo

```bash
npm install
npm run dist            # genera dist/Roblox-Launcher-Setup-1.0.0.exe
```

Ese `.exe` es el **instalador**: tu amigo lo ejecuta, lo instala y ya tiene la app con acceso directo en el escritorio y el menú Inicio. No necesita Node ni nada más.

### Publicar una actualización (el flujo de "apps de Windows")

La app usa `electron-updater` con **GitHub Releases**: al abrirla comprueba si hay una versión nueva, te avisa con un banner, descargas la actualización con progreso y al terminar **se cierra sola, instala y se vuelve a abrir**.

1. Sube el proyecto a GitHub (repositorio `roblox-launcher`) y cambia `owner`/`repo` en el bloque `build.publish` de `package.json` por los tuyos.
2. Cuando quieras publicar una versión nueva:
   ```bash
   npm version patch        # sube la versión a 1.0.1 (crea commit + tag)
   $env:GH_TOKEN = "tu_token_de_github"   # token con permiso repo (GitHub → Settings → Developer settings → Tokens)
   npm run publish          # compila el instalador y publica la release (exe + blockmap + latest.yml)
   git push origin main --tags   # sube el commit y el tag a GitHub
   ```
3. Los amigos que tengan la app instalada verán el banner **"Hay una nueva versión…"** y al pulsarlo la app se actualiza sola.

> ℹ️ `npm run publish` usa `scripts/publish.js` (crea la release por la API de GitHub y sube los 3 assets). No usa el `--publish` de electron-builder, que dejaba releases duplicadas en draft.

> ⚠️ La primera vez, Windows SmartScreen mostrará un aviso ("Windows protegió su PC") porque el .exe no está firmado. Tu amigo debe pulsar **Más información → Ejecutar de todas formas**. Es normal en apps sin certificado de pago.

## Seguridad

- `contextIsolation: true`, `nodeIntegration: false` y `sandbox: true`.
- El renderer solo habla con el proceso principal mediante una API mínima expuesta con `contextBridge`.
- Todos los enlaces externos se abren en el navegador del sistema, nunca dentro de la app.

## Estructura

```
├── main.js             # Proceso principal (detección, lanzamiento, carpetas)
├── preload.js          # Puente seguro entre el renderer y el main
├── renderer/
│   └── index.html      # Interfaz completa (4 pestañas, estilos y lógica inline)
└── package.json
```

> El renderer es un único HTML autocontenido: puedes abrirlo en cualquier navegador y verás la interfaz en modo demo (sin lanzar nada de verdad).
