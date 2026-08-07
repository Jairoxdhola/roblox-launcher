'use strict';

// ============================================================
//  Publica la release de GitHub manualmente (sin drafts dobles)
// ============================================================
//  electron-builder con `--publish always` crea DOS releases
//  draft duplicadas y deja los assets partidos entre ellas.
//  En su lugar: electron-builder solo compila (npm run dist) y
//  este script crea la release real por API y sube los 3 assets
//  (exe + blockmap + latest.yml) en una sola release pública.
//
//  Uso:
//    $env:GH_TOKEN = "tu_token"
//    npm run publish
// ============================================================

const fs = require('fs');
const path = require('path');
const https = require('https');

const ROOT = path.join(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const VERSION = pkg.version;
const TAG = `v${VERSION}`;

const OWNER = pkg.build.publish.owner;
const REPO = pkg.build.publish.repo;

const TOKEN = process.env.GH_TOKEN;
if (!TOKEN) {
  console.error('[publish] ERROR: variable GH_TOKEN no definida.');
  console.error('[publish]   Configúrala así (PowerShell): $env:GH_TOKEN = "tu_token"');
  process.exit(1);
}

const API = 'api.github.com';
const UPLOADS = 'uploads.github.com';

function request(method, host, apiPath, body, headers = {}, isBinary = false) {
  return new Promise((resolve, reject) => {
    const data = body == null ? null : (isBinary ? body : Buffer.from(JSON.stringify(body)));
    const req = https.request(
      {
        host,
        method,
        path: apiPath,
        headers: {
          Authorization: `token ${TOKEN}`,
          Accept: 'application/vnd.github+json',
          'User-Agent': 'roblox-launcher-publisher',
          ...(data ? { 'Content-Length': data.length } : {}),
          ...(!isBinary ? { 'Content-Type': 'application/json' } : headers),
        },
      },
      (res) => {
        let chunks = '';
        res.on('data', (c) => { chunks += c; });
        res.on('end', () => {
          let parsed = null;
          try { parsed = JSON.parse(chunks); } catch { /* no es JSON */ }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve({ status: res.statusCode, data: parsed, raw: chunks });
          } else {
            const msg = parsed && parsed.message ? parsed.message : chunks.slice(0, 300);
            reject(new Error(`HTTP ${res.statusCode} en ${host}${apiPath}: ${msg}`));
          }
        });
      }
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

// Assets esperados: exactamente los que genera electron-builder para NSIS.
function findAsset(namePart) {
  const files = fs.readdirSync(path.join(ROOT, 'dist'));
  return files.find((f) => f === namePart) || null;
}

const EXE = `Roblox-Launcher-Setup-${VERSION}.exe`;
const BLOCKMAP = `${EXE}.blockmap`;
const YML = 'latest.yml';

async function ensureRelease() {
  const list = await request('GET', API, `/repos/${OWNER}/${REPO}/releases?per_page=100`);
  const existing = (list.data || []).find((r) => r.tag_name === TAG);
  if (existing) {
    console.log(`[publish] Release ya existe (${TAG}), id=${existing.id}`);
    return existing;
  }
  const created = await request('POST', API, `/repos/${OWNER}/${REPO}/releases`, {
    tag_name: TAG,
    target_commitish: 'main',
    name: VERSION,
    body: `Roblox Launcher ${VERSION}`,
    draft: false,
    prerelease: false,
  });
  console.log(`[publish] Release creada: ${TAG} (id=${created.data.id})`);
  return created.data;
}

async function uploadAsset(release, name) {
  const local = findAsset(name);
  if (!local) {
    console.error(`[publish] ERROR: no existe dist/${name}`);
    process.exit(1);
  }
  // Si el asset ya existe en la release, lo borra antes (GitHub no permite
  // re-subir con el mismo nombre). Así volver a publicar es idempotente.
  const existing = (release.assets || []).find((a) => a.name === name);
  if (existing) {
    await request('DELETE', API, `/repos/${OWNER}/${REPO}/releases/assets/${existing.id}`);
    console.log(`[publish] Asset existente eliminado: ${name}`);
  }
  const bytes = fs.readFileSync(path.join(ROOT, 'dist', local));
  // upload_url viene con la plantilla {?name,label}: se recorta.
  const base = release.upload_url.replace(/\{[^}]*\}$/, '');
  const url = `${base}?name=${encodeURIComponent(name)}`;
  const res = await request('POST', UPLOADS, url.replace(/^https?:\/\/[^/]+/, ''), bytes, {
    'Content-Type': 'application/octet-stream',
  }, true);
  const asset = res.data;
  console.log(`[publish] Subido ${asset.name} (${(asset.size / 1048576).toFixed(1)} MB)`);
}

(async () => {
  try {
    console.log(`[publish] Roblox Launcher ${VERSION} → ${OWNER}/${REPO}`);
    const release = await ensureRelease();
    await uploadAsset(release, YML);
    await uploadAsset(release, BLOCKMAP);
    await uploadAsset(release, EXE);
    console.log('[publish] Publicación completa.');
  } catch (e) {
    console.error('[publish] ERROR:', e.message);
    process.exit(1);
  }
})();
