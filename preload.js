'use strict';

// ============================================================
//  Roblox Launcher — preload (puente seguro)
// ============================================================
//  Expone una API mínima y segura al renderer mediante
//  contextBridge. El renderer nunca toca Node directamente.
// ============================================================

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('robloxAPI', {
  checkVersion: () => ipcRenderer.invoke('version:check'),
  launchClient: () => ipcRenderer.invoke('launch:client'),
  launchClientVersion: (folder) => ipcRenderer.invoke('launch:client-version', folder),
  playGame: (placeId) => ipcRenderer.invoke('launch:game', placeId),
  openVersionsFolder: () => ipcRenderer.invoke('open:versions'),
  openRobloxFolder: () => ipcRenderer.invoke('open:roblox'),
  closeRoblox: () => ipcRenderer.invoke('close:roblox'),
  isRobloxRunning: () => ipcRenderer.invoke('is:roblox-running'),
  getMultiInstance: () => ipcRenderer.invoke('multi-instance:get'),
  setMultiInstance: (enabled) => ipcRenderer.invoke('multi-instance:set', enabled),
  updateRoblox: () => ipcRenderer.invoke('update:roblox'),
  openExternal: (url) => ipcRenderer.invoke('open:external', url),
  // Pestaña Downgrade: respaldos, versiones instaladas, importar y protección
  listInstalledVersions: () => ipcRenderer.invoke('versions:list'),
  createBackup: () => ipcRenderer.invoke('backup:create'),
  listBackups: () => ipcRenderer.invoke('backup:list'),
  restoreBackup: (folder) => ipcRenderer.invoke('backup:restore', folder),
  deleteBackup: (folder) => ipcRenderer.invoke('backup:delete', folder),
  openBackupsFolder: () => ipcRenderer.invoke('backup:open'),
  importVersion: () => ipcRenderer.invoke('version:import'),
  getProtection: () => ipcRenderer.invoke('protection:get'),
  setProtection: (enabled) => ipcRenderer.invoke('protection:set', enabled),
  getVersionInstalled: (hash) => ipcRenderer.invoke('version:get-installed', hash),
  installVersion: (hash) => ipcRenderer.invoke('version:install', hash),
  activateVersion: (hash) => ipcRenderer.invoke('version:activate', hash),
  onVersionInstallProgress: (callback) => {
    ipcRenderer.on('version:install-progress', (_event, data) => callback(data));
  },
  // MAC Spoofer (terminal elevada)
  spoofer: {
    launch: () => ipcRenderer.invoke('spoofer:launch'),
    status: () => ipcRenderer.invoke('spoofer:status'),
  },
  // FastFlags (optimización del cliente)
  fastFlags: {
    get: () => ipcRenderer.invoke('fastflags:get'),
    set: (changes) => ipcRenderer.invoke('fastflags:set', changes),
    clear: () => ipcRenderer.invoke('fastflags:clear'),
  },
  // Auto-actualización de la app
  appUpdate: {
    currentVersion: () => ipcRenderer.invoke('app:update-current-version'),
    check: () => ipcRenderer.invoke('app:update-check'),
    download: () => ipcRenderer.invoke('app:update-download'),
    install: () => ipcRenderer.invoke('app:update-install'),
    onStatus: (callback) => {
      ipcRenderer.on('app:update-status', (_event, data) => callback(data));
    },
  },
  // Controles de ventana (ventana sin marco)
  windowControls: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
    onMaximizeChange: (callback) => {
      ipcRenderer.on('window:maximize-change', (_event, isMax) => callback(isMax));
    },
  },
});
