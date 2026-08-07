'use strict';

// ============================================================
//  Roblox Launcher — proceso principal (Electron)
// ============================================================
//  Se encarga de:
//   • Detectar la versión instalada de Roblox (carpeta Versions)
//   • Consultar la última versión oficial (API de Roblox)
//   • Lanzar el cliente / un juego por ID
//   • Abrir carpetas y forzar la actualización
// ============================================================

const { app, BrowserWindow, ipcMain, shell, Menu, dialog } = require('electron');
const { execFile, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const { autoUpdater } = require('electron-updater');

// ---- Configuración ------------------------------------------------------

const APP_ID = 'com.robloxlauncher.app';
// API oficial de Roblox: última versión del cliente de Windows
const VERSION_API = 'https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer';
const FETCH_TIMEOUT_MS = 10000;

// ---- Rutas de instalación de Roblox --------------------------------------

function robloxRoot() {
  return path.join(os.homedir(), 'AppData', 'Local', 'Roblox');
}

function versionsDir() {
  return path.join(robloxRoot(), 'Versions');
}

function playerExePath(versionFolder) {
  return path.join(versionsDir(), versionFolder, 'RobloxPlayerBeta.exe');
}

// ---- Utilidades ------------------------------------------------------------

// Compara "2.656.0.6560723" contra "2.651.0.6510000" por tokens numéricos.
function compareVersionTokens(latest, installed) {
  const toks = (v) => String(v).toLowerCase().split(/[^0-9]+/).filter(Boolean).map(Number);
  const a = toks(latest);
  const b = toks(installed);
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

function runPowerShell(script) {
  return new Promise((resolve) => {
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      { windowsHide: true, timeout: 10000, maxBuffer: 4 * 1024 * 1024 },
      (err, stdout) => {
        if (err) return resolve(null);
        // Normaliza separadores decimales según la configuración regional
        // (p. ej. "0, 733, 0, 7330989" → "0.733.0.7330989")
        resolve(String(stdout).trim().replace(/[,;\s]+/g, '.'));
      }
    );
  });
}

// Lee la versión numérica (ProductVersion) de un .exe de Windows.
async function readExeVersion(exePath) {
  const escaped = exePath.replace(/'/g, "''");
  const out = await runPowerShell(
    `(Get-Item -LiteralPath '${escaped}').VersionInfo.ProductVersion`
  );
  return out || null;
}

// Última versión oficial desde el CDN de Roblox.
// Solo tratamos como versión numérica lo que realmente lo es
// (evita comparar hashes como "version-d584fb6c717a43d9").
function looksNumeric(v) {
  return /^[0-9]+(\.[0-9]+)*$/.test(String(v || ''));
}

async function fetchLatestVersion() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(VERSION_API, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // clientVersionUpload: "version-2.656.0.6560723"
    // version:             "2.656.0.6560723"
    const folder = data.clientVersionUpload || null;
    if (!folder) throw new Error('La API no devolvió clientVersionUpload');
    let version = data.version || '';
    // Fallback: extraer el número del nombre de carpeta solo si parece "version-2.x.y.z"
    if (!looksNumeric(version)) {
      const m = String(folder).match(/^version-([0-9.]+)$/i);
      version = m ? m[1] : '';
    }
    return { folder, version };
  } finally {
    clearTimeout(timer);
  }
}

// Versión instalada: recorre "Versions" buscando carpetas con
// RobloxPlayerBeta.exe y se queda con la más reciente.
async function getInstalledVersion() {
  let entries;
  try {
    entries = await fs.promises.readdir(versionsDir(), { withFileTypes: true });
  } catch {
    return null; // Roblox no está instalado
  }

  const folders = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const exe = playerExePath(entry.name);
    try {
      await fs.promises.access(exe);
      const stat = await fs.promises.stat(exe);
      folders.push({ folder: entry.name, exe, mtime: stat.mtimeMs });
    } catch {
      /* esta carpeta no tiene RobloxPlayerBeta.exe */
    }
  }
  if (!folders.length) return null;

  folders.sort((a, b) => b.mtime - a.mtime);
  const newest = folders[0];
  const version = await readExeVersion(newest.exe);
  return { folder: newest.folder, exe: newest.exe, version };
}

// ---- Comprobación de versión ----------------------------------------------

async function checkVersion() {
  const installed = await getInstalledVersion();

  let latest = null;
  let error = null;
  try {
    latest = await fetchLatestVersion();
  } catch (e) {
    error = e.message;
  }

  // Solo comparamos versiones cuando ambas son numéricas de verdad.
  const installedNumeric = installed && looksNumeric(installed.version) ? installed.version : null;
  const latestNumeric = latest && looksNumeric(latest.version) ? latest.version : null;

  let status = 'unknown';
  if (!installed) {
    status = 'missing';
  } else if (!installedNumeric) {
    status = 'unknown'; // no se pudo leer la versión numérica instalada
  } else if (latestNumeric) {
    const cmp = compareVersionTokens(latestNumeric, installedNumeric);
    status = cmp === 1 ? 'outdated' : cmp === 0 ? 'ok' : 'newer-than-latest';
  }

  // Si la versión activa está protegida, el usuario está en un downgrade intencional:
  // la UI lo mostrará como "Downgrade activo" en vez de "¡Desactualizado!".
  let downgraded = false;
  if (status === 'outdated') {
    try { downgraded = (await getProtectionState()).protected; } catch { /* no */ }
  }

  return {
    ok: true,
    status,
    downgraded,
    error,
    installed: installed
      ? { folder: installed.folder, version: installedNumeric || installed.folder }
      : null,
    latest: latest ? { folder: latest.folder, version: latestNumeric || latest.folder } : null,
    checkedAt: Date.now(),
  };
}

// ---- Lanzamiento -------------------------------------------------------------

async function resolvePlayerExe() {
  const info = await getInstalledVersion();
  return info ? info.exe : null;
}

function spawnPlayer(exe, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(exe, args, { detached: true, stdio: 'ignore', windowsHide: true });
    // Espera a que el proceso arranque de verdad (o falle) antes de resolver,
    // para no informar éxito cuando el spawn ha fallado.
    const done = (err) => {
      child.removeListener('error', onError);
      child.removeListener('spawn', onSpawn);
      if (err) reject(err);
      else resolve(true);
    };
    const onError = (err) => done(err);
    const onSpawn = () => done(null);
    child.once('error', onError);
    child.once('spawn', onSpawn);
    child.unref();
  });
}

async function launchClient() {
  const exe = await resolvePlayerExe();
  if (!exe) {
    await shell.openExternal('https://www.roblox.com/download');
    return { ok: false, launched: false, reason: 'not-installed' };
  }
  await spawnPlayer(exe, []);
  return { ok: true, launched: true };
}

// Lanza el cliente de UNA carpeta concreta de Versions (para elegir versión).
async function launchClientFromFolder(folderName) {
  const name = String(folderName || '');
  if (!/^version-[0-9a-f]{16}$/i.test(name)) {
    return { ok: false, reason: 'invalid-folder' };
  }
  const exe = playerExePath(name);
  try {
    await fs.promises.access(exe);
  } catch {
    return { ok: false, reason: 'not-version', folder: name };
  }
  await spawnPlayer(exe, []);
  let version = null;
  try { version = await readExeVersion(exe); } catch { /* no */ }
  return { ok: true, launched: true, folder: name, version };
}

async function playGame(rawPlaceId) {
  const placeId = String(rawPlaceId || '').trim().replace(/[^0-9]/g, '');
  if (!/^[0-9]{5,}$/.test(placeId)) {
    return { ok: false, launched: false, reason: 'invalid-id' };
  }
  const webUrl = `https://www.roblox.com/games/${placeId}`;
  const exe = await resolvePlayerExe();
  if (!exe) {
    await shell.openExternal(webUrl); // el navegador dispara el protocolo de Roblox
    return { ok: false, launched: false, reason: 'not-installed' };
  }
  // RobloxPlayerBeta.exe NO acepta URLs web como argumento. El método fiable
  // es el protocolo roblox://, que lanza el juego directamente en el cliente
  // (requiere sesión iniciada en el cliente).
  await shell.openExternal(`roblox://placeId=${placeId}`);
  return { ok: true, launched: true, placeId };
}

// ---- Cerrar Roblox si está abierto -----------------------------------------

function isProcessRunning(name) {
  return new Promise((resolve) => {
    execFile('tasklist.exe', ['/FI', `IMAGENAME eq ${name}`, '/NH'], {
      windowsHide: true,
      timeout: 8000,
      maxBuffer: 2 * 1024 * 1024,
    }, (err, stdout) => {
      if (err) return resolve(false);
      const out = String(stdout);
      resolve(out.includes(name) && !/no tasks/i.test(out));
    });
  });
}

function runTaskkill(args) {
  return new Promise((resolve) => {
    execFile('taskkill.exe', args, { windowsHide: true, timeout: 8000 }, (err) => resolve(!err));
  });
}

// Cierre suave (WM_CLOSE) y, si sigue abierto a los 1,5 s, cierre forzado.
async function closeRoblox() {
  const NAME = 'RobloxPlayerBeta.exe';
  if (!(await isProcessRunning(NAME))) {
    return { ok: true, wasRunning: false };
  }
  await runTaskkill(['/IM', NAME]);
  await new Promise((r) => setTimeout(r, 1500));
  let stillRunning = await isProcessRunning(NAME);
  if (stillRunning) {
    await runTaskkill(['/F', '/IM', NAME]);
    stillRunning = await isProcessRunning(NAME);
  }
  return { ok: true, wasRunning: true, closed: !stillRunning };
}

// ---- Descarga e instalación de una versión concreta -------------------------
// Método REAL del bootstrapper oficial (verificado de extremo a extremo):
//   1. Manifest de la versión: setup.rbxcdn.com/version-<hash>-rbxPkgManifest.txt
//      (líneas de 4: nombre, MD5, tamaño empaquetado, tamaño descomprimido)
//   2. Paquetes: setup.rbxcdn.com/version-<hash>-<nombre>.zip (HTTP 200)
//   3. Verificar MD5 y descomprimir cada zip dentro de Versions/version-<hash>/
// Así se puede bajar CUALQUIER versión pasada 100% desde el CDN oficial.

// Normaliza "version-145f189a6a974303" o "145f189a6a974303" → hash de 16 hex.
function normalizeVersionHash(raw) {
  const h = String(raw || '').trim().replace(/^version[-_]/i, '').toLowerCase();
  return /^[0-9a-f]{16}$/.test(h) ? h : null;
}

function versionFolderPath(hash) {
  return path.join(versionsDir(), `version-${hash}`);
}

// Comprueba si la carpeta de esa versión ya está instalada y es un cliente válido.
async function getVersionInstalled(hash) {
  const h = normalizeVersionHash(hash);
  if (!h) return { installed: false, reason: 'invalid-hash' };
  const dir = versionFolderPath(h); // .../Versions/version-<hash>
  try {
    await fs.promises.access(path.join(dir, 'RobloxPlayerBeta.exe'));
  } catch {
    return { installed: false, hash: h };
  }
  const [version, sizeMB] = await Promise.all([readExeVersion(path.join(dir, 'RobloxPlayerBeta.exe')), dirSizeMB(dir)]);
  return { installed: true, hash: h, folder: `version-${h}`, version, sizeMB };
}

// Lee el manifest de paquetes de una versión.
async function getVersionManifest(hash) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const res = await fetch(`https://setup.rbxcdn.com/version-${hash}-rbxPkgManifest.txt`, {
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const lines = (await res.text()).split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const packages = [];
    for (let i = 1; i + 3 < lines.length; i += 4) {
      packages.push({
        name: lines[i],
        md5: lines[i + 1],
        packed: Number(lines[i + 2]) || 0,
        unpacked: Number(lines[i + 3]) || 0,
      });
    }
    return packages;
  } finally {
    clearTimeout(timer);
  }
}

function md5File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('md5');
    const stream = fs.createReadStream(file);
    stream.on('data', (d) => hash.update(d));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

async function downloadToFile(url, file) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300000);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    await fs.promises.writeFile(file, buffer);
    return true;
  } finally {
    clearTimeout(timer);
  }
}

// Extrae un paquete en la carpeta de versión. Los paquetes son .zip, salvo
// algunos archivos sueltos (p. ej. RobloxPlayerInstaller.exe) que van tal cual.
async function extractZip(zipPath, destDir) {
  await fs.promises.mkdir(destDir, { recursive: true });
  // Firma de un zip: "PK" (0x50 0x4B). Si no es zip, se copia como está.
  const head = Buffer.alloc(2);
  try {
    const fd = await fs.promises.open(zipPath, 'r');
    await fd.read(head, 0, 2, 0);
    await fd.close();
  } catch {
    return false;
  }
  if (!(head[0] === 0x50 && head[1] === 0x4b)) {
    await fs.promises.copyFile(zipPath, path.join(destDir, path.basename(zipPath).replace(/^rl-pkg-[0-9a-f]{16}-/i, '')));
    return true;
  }
  const tryExec = (cmd, args) => new Promise((resolve) => {
    execFile(cmd, args, { windowsHide: true, timeout: 180000 }, (err) => resolve(!err));
  });
  if (await tryExec('tar.exe', ['-xf', zipPath, '-C', destDir])) return true;
  return tryExec('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    `Expand-Archive -LiteralPath '${zipPath.replace(/'/g, "''")}' -DestinationPath '${destDir.replace(/'/g, "''")}' -Force`]);
}

function emitInstallProgress(data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('version:install-progress', data);
  }
}

// Instala una versión concreta: manifest → paquetes → MD5 → descomprimir.
async function installVersion(raw, opts = {}) {
  const h = normalizeVersionHash(raw);
  if (!h) return { ok: false, reason: 'invalid-hash' };
  try {
    const existing = await getVersionInstalled(h);
    if (existing.installed && !opts.force) return { ok: true, already: true, ...existing };

    emitInstallProgress({ stage: 'manifest' });
    const packages = await getVersionManifest(h);
    if (!packages.length) return { ok: false, reason: 'no-manifest', hash: h };

    // El runtime de WebView2 no hace falta para jugar (Windows ya lo trae);
    // se salta para no descargar ~150 MB de más.
    const skip = new Set(['WebView2RuntimeInstaller.zip']);
    const todo = packages.filter((p) => !skip.has(p.name));

    const dest = versionFolderPath(h);
    await fs.promises.mkdir(dest, { recursive: true });
    const tmp = app.getPath('temp');

    for (let i = 0; i < todo.length; i++) {
      const pkg = todo[i];
      emitInstallProgress({ stage: 'package', index: i + 1, total: todo.length, name: pkg.name });

      const zipPath = path.join(tmp, `rl-pkg-${h}-${pkg.name}`);
      let ok = false;
      for (let attempt = 0; attempt < 3 && !ok; attempt++) {
        try {
          await downloadToFile(`https://setup.rbxcdn.com/version-${h}-${pkg.name}`, zipPath);
          const md5 = await md5File(zipPath);
          ok = md5.toLowerCase() === pkg.md5.toLowerCase();
        } catch {
          ok = false;
        }
        if (!ok) await fs.promises.unlink(zipPath).catch(() => {});
      }
      if (!ok) {
        return { ok: false, reason: 'download-failed', package: pkg.name, index: i + 1, total: todo.length };
      }
      if (!(await extractZip(zipPath, dest))) {
        return { ok: false, reason: 'extract-failed', package: pkg.name };
      }
      await fs.promises.unlink(zipPath).catch(() => {});
    }

    const st = await getVersionInstalled(h);
    return { ok: true, ...st, packages: todo.length };
  } catch (e) {
    return { ok: false, reason: 'install-failed', error: e.message };
  }
}

// "Activar" una versión instalada: copia su carpeta sobre la carpeta activa
// (la que Windows lanza según el hash de la API) y queda como versión en uso.
async function activateVersion(raw) {
  const h = normalizeVersionHash(raw);
  if (!h) return { ok: false, reason: 'invalid-hash' };
  try {
    const activeFolder = await activeVersionFolder();
    if (!activeFolder) return { ok: false, reason: 'not-installed' };
    if (await isProcessRunning('RobloxPlayerBeta.exe')) {
      return { ok: false, reason: 'roblox-running' };
    }
    if (activeFolder === `version-${h}`) {
      return { ok: true, noop: true, folder: activeFolder, hash: h };
    }
    const src = versionFolderPath(h); // .../Versions/version-<hash>
    try {
      await fs.promises.access(path.join(src, 'RobloxPlayerBeta.exe'));
    } catch {
      return { ok: false, reason: 'not-version', hash: h };
    }
    await copyDir(src, path.join(versionsDir(), activeFolder));
    const version = await readExeVersion(playerExePath(activeFolder));
    return { ok: true, folder: activeFolder, version, hash: h };
  } catch (e) {
    return { ok: false, reason: 'activate-failed', error: e.message };
  }
}

// Busca el instalador oficial de Roblox (raíz de Versions o subcarpetas de versión).
// Nota: si la carpeta está protegida, el instalador se llama .bak y no se encontrará;
// updateRoblox entonces descargará del CDN oficial, que es el comportamiento correcto.
async function findRobloxInstaller() {
  const candidates = [];
  try {
    const entries = await fs.promises.readdir(versionsDir(), { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        candidates.push(path.join(versionsDir(), entry.name, 'RobloxPlayerInstaller.exe'));
      } else if (entry.name === 'RobloxPlayerInstaller.exe') {
        candidates.push(path.join(versionsDir(), entry.name));
      }
    }
  } catch {
    return null; // Roblox no está instalado
  }
  for (const candidate of candidates) {
    try {
      await fs.promises.access(candidate);
      return candidate;
    } catch { /* no existe */ }
  }
  return null;
}

// Descarga el instalador oficial directamente del CDN de Roblox (sin abrir la web)
// y lo guarda en la carpeta temporal.
async function downloadInstaller() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const res = await fetch('https://www.roblox.com/download/client', {
      redirect: 'follow',
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    const target = path.join(app.getPath('temp'), 'RobloxPlayerInstaller.exe');
    await fs.promises.writeFile(target, buffer);
    return target;
  } finally {
    clearTimeout(timer);
  }
}

// Actualización real y fiable: compara con la última versión oficial y, si hace
// falta, instala SUS paquetes oficiales (manifest) directamente sobre la carpeta
// activa. El instalador ejecutable de Roblox solo abre el cliente, por eso no
// servía para actualizar.
async function updateRoblox() {
  // Si la versión está protegida (downgrade), primero hay que desproteger.
  try {
    const prot = await getProtectionState();
    if (prot.protected) return { ok: false, reason: 'protected' };
  } catch { /* sin estado de protección: se continúa */ }
  if (await isProcessRunning('RobloxPlayerBeta.exe')) {
    return { ok: false, reason: 'roblox-running' };
  }
  const latest = await fetchLatestVersion().catch(() => null);
  if (!latest || !looksNumeric(latest.version)) {
    return { ok: false, reason: 'no-latest' };
  }
  const inst = await getInstalledVersion();
  const installedVersion = inst && looksNumeric(inst.version) ? inst.version : null;
  if (installedVersion && compareVersionTokens(latest.version, installedVersion) <= 0) {
    return { ok: true, alreadyUpToDate: true, version: installedVersion };
  }
  // Descarga e instala la última versión oficial sobre la carpeta activa.
  return installVersion(latest.folder, { force: true });
}

// ---- Gestión de versiones: respaldos, downgrade, protección -------------------
// El downgrade real funciona así: Roblox instala cada actualización en una carpeta
// nueva (version-<hash>) y Windows siempre lanza la carpeta cuyo hash coincide con
// el de la API. Si metes los archivos de una versión antigua en esa carpeta y la
// proteges contra sobrescritura, el cliente viejo sigue funcionando.
// Este módulo aporta: respaldos (copiar la versión activa), restaurar respaldos,
// importar carpetas y proteger/desproteger contra la auto-actualización.

const BACKUPS_DIR = () => path.join(app.getPath('userData'), 'backups');

// Tamaño de un directorio en MB.
async function dirSizeMB(dir) {
  let total = 0;
  try {
    const entries = await fs.promises.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      try {
        if (entry.isDirectory()) total += await dirSizeMB(full);
        else if (entry.isFile()) total += (await fs.promises.stat(full)).size;
      } catch { /* sin permisos */ }
    }
  } catch { /* no existe */ }
  return Math.round(total / (1024 * 1024));
}

// Copia un directorio excluyendo la carpeta de volcados de crash del WebView2
// (no hace falta para jugar y ahorra bastante espacio).
async function copyDir(src, dest) {
  const entries = await fs.promises.readdir(src, { withFileTypes: true });
  await fs.promises.mkdir(dest, { recursive: true });
  for (const entry of entries) {
    if (entry.name === 'RobloxPlayerBeta.exe.WebView2') continue; // volcados de crash
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      await copyDir(s, d);
    } else {
      // Si el destino está protegido (solo-lectura), se hace escribible para poder copiar.
      try { await fs.promises.chmod(d, 0o644); } catch { /* no existe aún */ }
      await fs.promises.copyFile(s, d);
    }
  }
}

// Todas las carpetas de Versions con RobloxPlayerBeta.exe, con versión y tamaño.
async function listInstalledVersions() {
  const active = await activeVersionFolder();
  let entries;
  try {
    entries = await fs.promises.readdir(versionsDir(), { withFileTypes: true });
  } catch {
    return [];
  }
  const list = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const exe = playerExePath(entry.name);
    try {
      await fs.promises.access(exe);
    } catch {
      continue; // sin cliente de jugador
    }
    const [version, sizeMB] = await Promise.all([
      readExeVersion(exe),
      dirSizeMB(path.join(versionsDir(), entry.name)),
    ]);
    let mtimeMs = 0;
    try { mtimeMs = (await fs.promises.stat(exe)).mtimeMs; } catch { /* no */ }
    list.push({
      folder: entry.name,
      version,
      sizeMB,
      mtimeMs,
      active: !!active && active === entry.name,
    });
  }
  list.sort((a, b) => (a.active ? -1 : 0) - (b.active ? -1 : 0) || b.mtimeMs - a.mtimeMs);
  return list;
}

function backupManifestPath(folder) {
  return path.join(BACKUPS_DIR(), folder, 'manifest.json');
}

// Valida que un nombre de respaldo sea seguro y devuelve su ruta dentro
// de BACKUPS_DIR, o null si no lo es (evita path traversal en los IPC).
function safeBackupPath(folder) {
  const name = String(folder || '');
  if (!/^[a-zA-Z0-9._-]+$/.test(name)) return null;
  const base = path.resolve(BACKUPS_DIR());
  const full = path.resolve(base, name);
  return full.startsWith(base + path.sep) ? full : null;
}

// Copia la versión activa a la carpeta de respaldos con su manifiesto.
async function createBackup() {
  const info = await getInstalledVersion();
  if (!info) return { ok: false, reason: 'not-installed' };
  if (await isProcessRunning('RobloxPlayerBeta.exe')) {
    return { ok: false, reason: 'roblox-running' };
  }
  const dest = path.join(BACKUPS_DIR(), info.folder);
  await copyDir(path.join(versionsDir(), info.folder), dest);
  const manifest = {
    folder: info.folder,
    version: info.version,
    created: Date.now(),
  };
  await fs.promises.writeFile(backupManifestPath(info.folder), JSON.stringify(manifest, null, 2));
  const sizeMB = await dirSizeMB(dest);
  return { ok: true, folder: info.folder, version: info.version, sizeMB };
}

async function listBackups() {
  const base = BACKUPS_DIR();
  let entries;
  try {
    entries = await fs.promises.readdir(base, { withFileTypes: true });
  } catch {
    return [];
  }
  const list = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    let manifest = null;
    try {
      manifest = JSON.parse(await fs.promises.readFile(backupManifestPath(entry.name), 'utf8'));
    } catch { /* sin manifiesto */ }
    list.push({
      folder: entry.name,
      version: manifest ? manifest.version : null,
      created: manifest ? manifest.created : 0,
      sizeMB: await dirSizeMB(path.join(base, entry.name)),
    });
  }
  list.sort((a, b) => b.created - a.created);
  return list;
}

// La carpeta "activa" de verdad es la que Windows lanza: la que coincide con el
// hash que devuelve la API oficial. Si no se puede consultar (sin internet), se
// usa como fallback la carpeta más reciente por fecha.
let apiActiveFolderCache = { at: 0, folder: null };

async function getApiActiveFolder() {
  if (Date.now() - apiActiveFolderCache.at < 60000) return apiActiveFolderCache.folder;
  apiActiveFolderCache.at = Date.now();
  apiActiveFolderCache.folder = null;
  try {
    const latest = await fetchLatestVersion();
    const f = String(latest.folder || '');
    if (/^version-[0-9a-f]{16}$/i.test(f)) {
      try {
        await fs.promises.access(playerExePath(f));
        apiActiveFolderCache.folder = f;
      } catch { /* la carpeta de la API no existe en disco */ }
    }
  } catch { /* sin conexión */ }
  return apiActiveFolderCache.folder;
}

async function activeVersionFolder() {
  const fromApi = await getApiActiveFolder();
  if (fromApi) return fromApi;
  const info = await getInstalledVersion();
  return info ? info.folder : null;
}

// Restaura un respaldo sobre la carpeta activa (el downgrade en sí).
async function restoreBackup(folder) {
  const bkp = safeBackupPath(folder);
  if (!bkp) return { ok: false, reason: 'invalid-folder' };
  try {
    await fs.promises.access(bkp);
  } catch {
    return { ok: false, reason: 'missing-backup' };
  }
  if (await isProcessRunning('RobloxPlayerBeta.exe')) {
    return { ok: false, reason: 'roblox-running' };
  }
  const activeFolder = await activeVersionFolder();
  if (!activeFolder) return { ok: false, reason: 'not-installed' };
  await copyDir(bkp, path.join(versionsDir(), activeFolder));
  const version = await readExeVersion(playerExePath(activeFolder));
  return { ok: true, folder: activeFolder, version };
}

async function deleteBackup(folder) {
  const bkp = safeBackupPath(folder);
  if (!bkp) return { ok: false, reason: 'invalid-folder' };
  try {
    await fs.promises.rm(bkp, { recursive: true, force: true });
    return { ok: true, folder };
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}

// Importa una carpeta de versión elegida por el usuario (p. ej. una versión
// antigua conseguida en otra parte) copiándola dentro de Versions.
async function importVersion() {
  if (!mainWindow) return { ok: false, reason: 'no-window' };
  const res = await dialog.showOpenDialog(mainWindow, {
    title: 'Elegir carpeta de versión de Roblox',
    properties: ['openDirectory'],
  });
  if (res.canceled || !res.filePaths.length) return { ok: false, canceled: true };
  const src = res.filePaths[0];
  const base = path.basename(src);
  if (!/^version-/i.test(base)) {
    return { ok: false, reason: 'not-version-folder', folder: base };
  }
  let dest = path.join(versionsDir(), base);
  let n = 1;
  while (true) {
    try {
      await fs.promises.access(dest);
      dest = path.join(versionsDir(), `${base}-${n++}`);
    } catch {
      break; // no existe: sitio libre
    }
  }
  await copyDir(src, dest);
  const exe = path.join(dest, 'RobloxPlayerBeta.exe');
  let version = null;
  try { await fs.promises.access(exe); version = await readExeVersion(exe); } catch { /* no es un cliente */ }
  return { ok: true, folder: path.basename(dest), version, sizeMB: await dirSizeMB(dest) };
}

// ---- Protección contra auto-actualización --------------------------------------
// Método conocido: marcar como solo-lectura los binarios que el actualizador
// sobrescribe (exe/dll) y apartar el instalador para que no pueda ejecutarse.
const PROTECTED_FILES = ['RobloxPlayerBeta.exe', 'RobloxPlayerBeta.dll', 'AppSettings.xml'];

async function getProtectionState() {
  const folder = await activeVersionFolder();
  if (!folder) return { protected: false, folder: null };
  const dir = path.join(versionsDir(), folder);
  let readonly = 0;
  for (const f of PROTECTED_FILES) {
    try {
      const st = await fs.promises.stat(path.join(dir, f));
      if (!(st.mode & 0o222)) readonly++; // sin bits de escritura
    } catch { /* no existe */ }
  }
  let installerMoved = false;
  try { await fs.promises.access(path.join(dir, 'RobloxPlayerInstaller.exe.bak')); installerMoved = true; } catch { /* no */ }
  return {
    protected: readonly === PROTECTED_FILES.length || installerMoved,
    folder,
    filesProtected: readonly,
    installerMoved,
  };
}

async function setProtection(enabled) {
  const folder = await activeVersionFolder();
  if (!folder) return { ok: false, reason: 'not-installed' };
  if (await isProcessRunning('RobloxPlayerBeta.exe')) {
    return { ok: false, reason: 'roblox-running' };
  }
  const dir = path.join(versionsDir(), folder);
  const mode = enabled ? 0o444 : 0o644;
  for (const f of PROTECTED_FILES) {
    try { await fs.promises.chmod(path.join(dir, f), mode); } catch { /* no existe */ }
  }
  const installer = path.join(dir, 'RobloxPlayerInstaller.exe');
  const bak = path.join(dir, 'RobloxPlayerInstaller.exe.bak');
  try {
    if (enabled) {
      // Si ya existe un .bak (p. ej. tras activar otra versión), se reemplaza.
      await fs.promises.rm(bak, { force: true }).catch(() => {});
      await fs.promises.rename(installer, bak);
    } else {
      await fs.promises.rename(bak, installer);
    }
  } catch { /* puede no existir el instalador */ }
  return { ok: true, protected: enabled, ...(await getProtectionState()) };
}

// ---- FastFlags (optimización del cliente de Roblox) -------------------------------
// Roblox lee un archivo ClientAppSettings.json desde la carpeta de la versión activa
// al arrancar. Aquí se ofrece un conjunto de flags conocidos por la comunidad para
// mejorar rendimiento, gráficos y red. Cada flag se aplica de inmediato al abrir el
// cliente; para que surta efecto hay que reiniciar Roblox.

// Presets curados por categoría. `key` es el nombre real del flag que lee Roblox.
const FASTFLAG_PRESETS = {
  fpsUnlock: {
    category: 'performance',
    key: 'DFIntTaskSchedulerTargetFps',
    type: 'int',
    label: 'Desbloquear FPS',
    hint: 'Quita el límite de 60 FPS (valor en FPS).',
    default: 240,
  },
  vulkan: {
    category: 'performance',
    key: 'FFlagDebugGraphicsPreferVulkan',
    type: 'bool',
    label: 'Usar Vulkan',
    hint: 'Cambia el renderizador a Vulkan (mejor rendimiento en varias GPUs).',
  },
  renderTime: {
    category: 'performance',
    key: 'FIntRenderFrameTimePercentage',
    type: 'int',
    label: 'Frame time de render',
    hint: 'Porcentaje del frame dedicado a renderizar (90 por defecto).',
    default: 90,
  },
  gpuParticles: {
    category: 'performance',
    key: 'FFlagGraphicsDisableGpuParticles',
    type: 'bool',
    label: 'Desactivar partículas GPU',
    hint: 'Reduce carga de partículas pesadas.',
  },
  postFx: {
    category: 'effects',
    key: 'FFlagDisablePostFx',
    type: 'bool',
    label: 'Desactivar PostFX',
    hint: 'Quita efectos de post-procesado (blur, bloom) para más FPS.',
  },
  shadows: {
    category: 'effects',
    key: 'FFlagDebugGraphicsDisableShadowMap',
    type: 'bool',
    label: 'Desactivar sombras',
    hint: 'Desactiva el mapa de sombras (mejora FPS en PC baja).',
  },
  mtu: {
    category: 'network',
    key: 'DFIntConnectionMTU',
    type: 'int',
    label: 'MTU de red',
    hint: 'Tamaño de paquete de red (1400 por defecto).',
    default: 1400,
  },
};

function fastFlagsFilePath(folder) {
  return path.join(versionsDir(), folder, 'ClientAppSettings.json');
}

// Lee el archivo de FastFlags de la versión activa (si existe).
async function readFastFlags() {
  const folder = await activeVersionFolder();
  if (!folder) return { ok: false, reason: 'not-installed', folder: null, flags: {} };
  const file = fastFlagsFilePath(folder);
  let flags = {};
  try {
    flags = JSON.parse(await fs.promises.readFile(file, 'utf8'));
  } catch { /* no existe o no es JSON válido */ }
  return { ok: true, folder, file, flags };
}

// Aplica cambios: cada clave con valor null elimina el flag; si quedan 0 flags,
// se borra el archivo. Devuelve el estado final.
async function writeFastFlags(changes) {
  const folder = await activeVersionFolder();
  if (!folder) return { ok: false, reason: 'not-installed' };
  const file = fastFlagsFilePath(folder);
  let flags = {};
  try {
    flags = JSON.parse(await fs.promises.readFile(file, 'utf8'));
  } catch { /* no existe aún */ }
  for (const [key, val] of Object.entries(changes || {})) {
    if (val === null || val === undefined || val === '') delete flags[key];
    else flags[key] = val;
  }
  try {
    if (Object.keys(flags).length === 0) {
      await fs.promises.rm(file, { force: true }).catch(() => {});
    } else {
      await fs.promises.mkdir(path.dirname(file), { recursive: true });
      await fs.promises.writeFile(file, JSON.stringify(flags, null, 2));
    }
  } catch (e) {
    return { ok: false, reason: 'write-failed', error: e.message };
  }
  return { ok: true, folder, flags };
}

// Borra todos los flags gestionados por el launcher (deja el archivo vacío/limpio).
async function clearFastFlags() {
  const folder = await activeVersionFolder();
  if (!folder) return { ok: false, reason: 'not-installed' };
  const file = fastFlagsFilePath(folder);
  try {
    await fs.promises.rm(file, { force: true });
  } catch (e) {
    return { ok: false, reason: 'write-failed', error: e.message };
  }
  return { ok: true, folder, flags: {} };
}

// ---- Auto-actualización de la app ------------------------------------------------
// Flujo estilo apps de Windows: al arrancar se consulta el canal de actualizaciones
// (GitHub Releases por defecto); si hay una versión nueva se avisa al renderer, el
// usuario pulsa "Actualizar", se descarga con progreso y al terminar se cierra la
// app, se instala en silencio y se vuelve a abrir sola (quitAndInstall).

function sendToRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

// ¿Está configurado el canal de publicaciones de verdad?
// (Mientras sea el placeholder de plantilla, se omite la auto-actualización
// para no dar un error falso de red en cada arranque.)
function isPublishConfigured() {
  try {
    const cfg = fs.readFileSync(path.join(process.resourcesPath, 'app-update.yml'), 'utf8');
    return !cfg.includes('TU_USUARIO_DE_GITHUB');
  } catch {
    return false;
  }
}

// Escribe los eventos del updater en un archivo (userData/updater.log) para
// poder depurar qué pasó si algo falla, aunque la app esté empaquetada.
function logUpdater(line) {
  try {
    fs.appendFileSync(path.join(app.getPath('userData'), 'updater.log'),
      `[${new Date().toISOString()}] ${line}\n`);
  } catch { /* no importa */ }
}

function setupAutoUpdater() {
  // En desarrollo (npm start) no hay canal de actualizaciones: se omite.
  if (!app.isPackaged) return;

  // Como las apps de Windows: al detectar la versión nueva, la descarga
  // empieza sola en segundo plano y el banner muestra el progreso. Sin
  // descarga diferencial (blockmap), que falla a menudo con instaladores
  // sin firmar: se baja el .exe completo, mucho más fiable.
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.disableDifferentialDownload = true;

  autoUpdater.on('checking-for-update', () => {
    logUpdater('comprobando actualizaciones…');
    sendToRenderer('app:update-status', { stage: 'checking' });
  });
  autoUpdater.on('update-available', (info) => {
    logUpdater(`versión nueva disponible: ${info.version} — descarga automática en marcha`);
    console.log('[updater] versión nueva disponible:', info.version);
    sendToRenderer('app:update-status', { stage: 'available', version: info.version });
  });
  autoUpdater.on('update-not-available', () => {
    logUpdater('ya estás al día');
    console.log('[updater] ya estás al día');
    sendToRenderer('app:update-status', { stage: 'uptodate' });
  });
  autoUpdater.on('download-progress', (p) => {
    const percent = Math.round(p.percent || 0);
    if (percent % 10 === 0 || percent === 1) {
      logUpdater(`descargando… ${percent}%`);
    }
    sendToRenderer('app:update-status', {
      stage: 'downloading',
      percent,
      speed: p.bytesPerSecond || 0,
    });
  });
  autoUpdater.on('update-downloaded', (info) => {
    logUpdater(`descarga completa, lista para instalar: ${info.version}`);
    console.log('[updater] descarga completa, lista para instalar:', info.version);
    sendToRenderer('app:update-status', { stage: 'downloaded', version: info.version });
  });
  autoUpdater.on('error', (err) => {
    const msg = err && err.message ? err.message : 'desconocido';
    logUpdater(`ERROR: ${msg}`);
    console.error('[updater] error:', msg);
    sendToRenderer('app:update-status', { stage: 'error', message: msg });
  });
  autoUpdater.on('before-quit-for-update', () => {
    logUpdater('la app se cierra para instalar la actualización…');
  });
}

// ---- Ventana -------------------------------------------------------------------

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: '#0b0d12',
    show: false,
    autoHideMenuBar: true,
    // titleBarStyle 'hidden' (NO frame:false): oculta la barra nativa pero
    // conserva el marco de Windows, así el DWM mantiene las animaciones
    // fluidas de minimizar/maximizar, Aero Snap, esquinas redondeadas
    // y sombra de la ventana (igual que Discord, Spotify, etc.).
    // Los controles (min/max/close) los dibuja la propia app en la barra.
    titleBarStyle: 'hidden',
    title: 'Roblox Launcher',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });

  // Nunca permitir navegar a otra página desde dentro de la ventana.
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) event.preventDefault();
  });

  // Informa al renderer del estado de maximizado (icono restaurar/maximizar).
  const sendMaxState = () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('window:maximize-change', mainWindow.isMaximized());
    }
  };
  mainWindow.on('maximize', sendMaxState);
  mainWindow.on('unmaximize', sendMaxState);

  // Enlaces externos siempre al navegador del sistema, nunca dentro de la ventana.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ---- IPC -----------------------------------------------------------------------

ipcMain.handle('version:check', () => checkVersion());
ipcMain.handle('launch:client', () => launchClient());
ipcMain.handle('launch:client-version', (_e, folder) => launchClientFromFolder(folder));
ipcMain.handle('launch:game', (_event, placeId) => playGame(placeId));
ipcMain.handle('open:versions', async () => {
  const err = await shell.openPath(versionsDir());
  return { ok: !err, error: err || null };
});
ipcMain.handle('open:roblox', async () => {
  const err = await shell.openPath(robloxRoot());
  return { ok: !err, error: err || null };
});
ipcMain.handle('window:minimize', () => { if (mainWindow) mainWindow.minimize(); });
ipcMain.handle('window:toggle-maximize', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.handle('window:close', () => { if (mainWindow) mainWindow.close(); });
ipcMain.handle('window:is-maximized', () => (mainWindow ? mainWindow.isMaximized() : false));
ipcMain.handle('close:roblox', () => closeRoblox());
ipcMain.handle('is:roblox-running', () => isProcessRunning('RobloxPlayerBeta.exe'));
ipcMain.handle('update:roblox', () => updateRoblox());
ipcMain.handle('open:external', (_event, url) => {
  const target = String(url || '');
  if (/^https?:\/\//i.test(target)) return shell.openExternal(target);
  return false;
});

// ---- IPC de la pestaña Downgrade ----
ipcMain.handle('versions:list', () => listInstalledVersions());
ipcMain.handle('backup:create', () => createBackup());
ipcMain.handle('backup:list', () => listBackups());
ipcMain.handle('backup:restore', (_e, folder) => restoreBackup(folder));
ipcMain.handle('backup:delete', (_e, folder) => deleteBackup(folder));
ipcMain.handle('backup:open', async () => {
  await fs.promises.mkdir(BACKUPS_DIR(), { recursive: true });
  const err = await shell.openPath(BACKUPS_DIR());
  return { ok: !err, error: err || null };
});
ipcMain.handle('version:import', () => importVersion());
ipcMain.handle('protection:get', () => getProtectionState());
ipcMain.handle('protection:set', (_e, enabled) => setProtection(!!enabled));
ipcMain.handle('version:get-installed', (_e, hash) => getVersionInstalled(hash));
ipcMain.handle('version:install', (_e, hash) => installVersion(hash));
ipcMain.handle('version:activate', (_e, hash) => activateVersion(hash));

// ---- IPC de la pestaña FastFlags ----
ipcMain.handle('fastflags:get', () => readFastFlags());
ipcMain.handle('fastflags:set', (_e, changes) => writeFastFlags(changes));
ipcMain.handle('fastflags:clear', () => clearFastFlags());

// ---- IPC de auto-actualización ----
ipcMain.handle('app:update-current-version', () => ({ version: app.getVersion() }));
ipcMain.handle('app:update-check', async () => {
  if (!app.isPackaged) return { ok: true, dev: true };
  try {
    await autoUpdater.checkForUpdates();
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e && e.message ? e.message : 'desconocido' };
  }
});
ipcMain.handle('app:update-download', async () => {
  if (!app.isPackaged) return { ok: false, dev: true };
  // No esperamos a que termine la descarga (podría tardar minutos): la
  // lanzamos en segundo plano y los eventos de progreso/error van solos
  // al renderer. Así el botón nunca se queda colgado.
  autoUpdater.downloadUpdate().catch((e) => {
    logUpdater(`descarga manual falló: ${e && e.message ? e.message : 'desconocido'}`);
  });
  return { ok: true, started: true };
});
ipcMain.handle('app:update-install', () => {
  if (!app.isPackaged) return { ok: false, dev: true };
  logUpdater('usuario pulsa Reiniciar e instalar → quitAndInstall');
  // Cierra la app, instala y la vuelve a abrir sola. isSilent=false: el
  // instalador NSIS muestra su ventana de progreso y SIEMPRE relanza la app
  // al terminar (en modo silencioso /S el relanzamiento fallaba).
  try {
    // Verifica que la actualización esté realmente descargada antes de
    // intentar instalarla. Si no lo está, avisamos en vez de quedarnos
    // en silencio ("no pasa nada").
    const helper = autoUpdater.downloadedUpdateHelper;
    const ready = !!autoUpdater.installerPath && !!(helper && helper.downloadedFileInfo);
    if (!ready) {
      logUpdater('ERROR: no hay actualización descargada lista para instalar');
      return { ok: false, reason: 'no-update-downloaded' };
    }
    autoUpdater.quitAndInstall(false, true);
    return { ok: true, quitting: true };
  } catch (e) {
    const msg = e && e.message ? e.message : 'desconocido';
    logUpdater(`ERROR quitAndInstall: ${msg}`);
    return { ok: false, reason: 'quit-failed', error: msg };
  }
});

// ---- Modo instalación por CLI -------------------------------------------------------
// Ejecutar: npx electron . --install-version=145f189a6a974303
// Instala esa versión con el mismo código que el botón de la app, mostrando el
// progreso por consola, y sale con código 0/1. (No crea ventana.)
const INSTALL_CLI = (() => {
  const arg = process.argv.find((a) => a.startsWith('--install-version='));
  return arg ? arg.split('=')[1] : null;
})();
const ACTIVATE_CLI = (() => {
  const arg = process.argv.find((a) => a.startsWith('--activate-version='));
  return arg ? arg.split('=')[1] : null;
})();
const PROTECT_CLI = process.argv.includes('--protect');
const UPDATE_CLI = process.argv.includes('--update');

// ---- Modo smoke-test (validación automática) --------------------------------------
// Ejecutar: npx electron . --smoke
// Crea la ventana, comprueba la versión real y cierra solo tras unos segundos.
const SMOKE = process.argv.includes('--smoke');

if (INSTALL_CLI || ACTIVATE_CLI || PROTECT_CLI || UPDATE_CLI) {
  app.whenReady().then(async () => {
    const onProgress = (p) => {
      if (!p) return;
      if (p.stage === 'manifest') console.log('[install] Consultando manifest…');
      else if (p.stage === 'package') console.log(`[install] Paquete ${p.index}/${p.total}: ${p.name}`);
    };
    emitInstallProgress = (data) => { onProgress(data); if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('version:install-progress', data); };
    const res = INSTALL_CLI
      ? await installVersion(INSTALL_CLI)
      : ACTIVATE_CLI
        ? await activateVersion(ACTIVATE_CLI)
        : UPDATE_CLI
          ? await updateRoblox()
          : await setProtection(true);
    console.log('[install] resultado:', JSON.stringify(res));
    app.exit(res && res.ok ? 0 : 1);
  });
} else if (SMOKE) {
  app.whenReady().then(() => {
    // Verifica que la ventana se creó de verdad (antes daba falsos positivos).
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        console.log('[smoke] La ventana se creó correctamente. Cerrando…');
        app.exit(0);
      } else {
        console.error('[smoke] ERROR: la ventana no se creó.');
        app.exit(1);
      }
    }, 4000);
    checkVersion()
      .then((r) => console.log('[smoke] checkVersion:', JSON.stringify({
        status: r.status, downgraded: r.downgraded, installed: r.installed, latest: r.latest, error: r.error,
      })))
      .catch((e) => console.error('[smoke] checkVersion error:', e.message));
    // Solo diagnóstico (no ejecuta el instalador): confirma la ruta del instalador local.
    findRobloxInstaller()
      .then((p) => console.log('[smoke] instalador local:', p || 'no encontrado (se descargaría del CDN)'))
      .catch(() => {});

    // Selector de versión: la guardia de carpetas válidas debe rechazar basura sin lanzar.
    launchClientFromFolder('version-zzzz-not-real')
      .then((r) => console.log('[smoke] launch-version-guard:', JSON.stringify(r)))
      .catch(() => {});

    // Downgrade: lista de versiones instaladas, respaldos y estado de protección.
    listInstalledVersions()
      .then((vs) => console.log('[smoke] versions-list:', JSON.stringify(vs)))
      .catch((e) => console.error('[smoke] versions-list error:', e.message));
    listBackups()
      .then((b) => console.log('[smoke] backups-list:', JSON.stringify(b)))
      .catch((e) => console.error('[smoke] backups-list error:', e.message));
    getProtectionState()
      .then((p) => console.log('[smoke] protection-state:', JSON.stringify(p)))
      .catch((e) => console.error('[smoke] protection-state error:', e.message));

    // Descarga de versiones: comprueba el manifest oficial de una versión concreta.
    getVersionManifest('145f189a6a974303')
      .then((pkgs) => console.log('[smoke] manifest-packages:', pkgs.length,
        pkgs[0] ? `| primero: ${pkgs[0].name} (${pkgs[0].md5})` : ''))
      .catch((e) => console.error('[smoke] manifest error:', e.message));

    // Verifica que la cabecera sticky se quede pegada arriba al hacer scroll.
    setTimeout(() => {
      mainWindow.webContents.executeJavaScript(`(async () => {
        window.scrollTo(0, 600);
        await new Promise((r) => setTimeout(r, 300));
        const h = document.querySelector('.app-header').getBoundingClientRect();
        return { headerTop: Math.round(h.top), scrollY: Math.round(window.scrollY) };
      })()`)
        .then((res) => console.log('[smoke] scroll-check:', JSON.stringify(res)))
        .catch(() => {});
    }, 1200);

    // Con titleBarStyle 'hidden' el maximizado debe funcionar con la ventana real.
    setTimeout(() => {
      mainWindow.maximize();
      setTimeout(() => {
        console.log('[smoke] maximize-check:', JSON.stringify({
          maximized: mainWindow.isMaximized(),
        }));
        mainWindow.unmaximize();
      }, 600);
    }, 2000);
  });
}

// ---- Arranque --------------------------------------------------------------------

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    // En modo CLI no se abre ventana (solo se instala/activa/protege/actualiza).
    if (INSTALL_CLI || ACTIVATE_CLI || PROTECT_CLI || UPDATE_CLI) return;
    app.setAppUserModelId(APP_ID);
    // Sin barra de menú (File/Edit/…) en la ventana.
    Menu.setApplicationMenu(null);
    createWindow();
    setupAutoUpdater();

    // Al arrancar (app instalada), comprueba actualizaciones en segundo plano
    // y avisa al renderer si hay una versión nueva.
    if (app.isPackaged && !SMOKE && isPublishConfigured()) {
      setTimeout(() => {
        autoUpdater.checkForUpdates().catch(() => {});
      }, 4000);
    }

    // Errores del renderer visibles en consola durante el smoke-test
    if (SMOKE) {
      mainWindow.webContents.on('console-message', (_e, level, message) => {
        if (level >= 2) console.log('[renderer]', message);
      });
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
}
