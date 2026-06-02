const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const HOST = process.env.HAPA_DRAMA_HOST || '127.0.0.1';
const REQUESTED_PORT = Number(process.env.HAPA_DRAMA_PORT || '8758');
let activePort = Number.isFinite(REQUESTED_PORT) && REQUESTED_PORT > 0 ? REQUESTED_PORT : 8758;
const RUNTIME_FILE = process.env.HAPA_DRAMA_RUNTIME_FILE || path.join(ROOT_DIR, 'artifacts', 'runtime', 'hapa_drama_runtime.json');
const DEV_MODE = process.env.HAPA_DRAMA_ELECTRON_DEV === '1';

let mainWindow = null;
let serverProcess = null;
let serverStartedByElectron = false;

function baseUrl() {
  return `http://${HOST}:${activePort}`;
}

function pythonCandidates() {
  const venvPython = path.join(ROOT_DIR, '.venv', 'bin', 'python');
  return [
    process.env.HAPA_DRAMA_PYTHON,
    fs.existsSync(venvPython) ? venvPython : null,
    '/opt/homebrew/bin/python3.11',
    '/usr/local/bin/python3.11',
    'python3.11',
    'python3',
  ].filter(Boolean);
}

function commandExists(command) {
  return new Promise((resolve) => {
    const child = spawn(command, ['--version'], { stdio: 'ignore' });
    child.on('error', () => resolve(false));
    child.on('exit', (code) => resolve(code === 0));
  });
}

function pythonIsCompatible(command) {
  return new Promise((resolve) => {
    const child = spawn(command, ['-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'], { stdio: 'ignore' });
    child.on('error', () => resolve(false));
    child.on('exit', (code) => resolve(code === 0));
  });
}

async function resolvePython() {
  for (const candidate of pythonCandidates()) {
    if (path.isAbsolute(candidate) && fs.existsSync(candidate) && await pythonIsCompatible(candidate)) return candidate;
    if (!path.isAbsolute(candidate) && await commandExists(candidate) && await pythonIsCompatible(candidate)) return candidate;
  }
  throw new Error('No usable Python >=3.11 found. Run scripts/launch_hapa_drama.sh --doctor.');
}

function fetchJson(url, timeoutMs = 1200, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs, headers }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          const payload = JSON.parse(body);
          if (Number(res.statusCode || 0) >= 200 && Number(res.statusCode || 0) < 300) {
            resolve(payload);
            return;
          }
          reject(new Error(`HTTP ${res.statusCode} from ${url}: ${body.slice(0, 200)}`));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on('timeout', () => {
      req.destroy(new Error(`Timeout waiting for ${url}`));
    });
    req.on('error', reject);
  });
}

function isPortListening(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: HOST, port }, () => {
      socket.end();
      resolve(true);
    });
    socket.setTimeout(250);
    socket.on('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.on('error', () => resolve(false));
  });
}

async function healthIsDrama() {
  try {
    const health = await fetchJson(`${baseUrl()}/health`);
    const version = String((health.runtime && health.runtime.python_version) || '');
    const majorMinor = version.split('.').slice(0, 2).map((part) => Number(part));
    const pythonOk = majorMinor.length === 2 && (majorMinor[0] > 3 || (majorMinor[0] === 3 && majorMinor[1] >= 11));
    return health && health.ok === true && health.service === 'hapa-drama' && health.node === '.hapaDrama' && health.auth && health.auth.local_session === '/local/session' && pythonOk;
  } catch (_) {
    return false;
  }
}

async function supportsDesktopProtocol() {
  try {
    const session = await fetchJson(`${baseUrl()}/local/session`);
    const token = session && session.token;
    if (!token || session.node !== '.hapaDrama') return false;
    const capabilities = await fetchJson(`${baseUrl()}/capabilities`, 1200, { Authorization: `Bearer ${token}` });
    const telemetry = await fetchJson(`${baseUrl()}/v1/telemetry`, 1200, { Authorization: `Bearer ${token}` });
    return Boolean(
      capabilities.node === '.hapaDrama' &&
        capabilities.hapa_protocol &&
        capabilities.hapa_protocol.ui_cli_api_parity === true &&
        capabilities.hapa_protocol.local_session === true &&
        (capabilities.capability_ids || []).includes('hapa.telemetry.process_state') &&
        telemetry.node === '.hapaDrama' &&
        telemetry.status === 'online',
    );
  } catch (_) {
    return false;
  }
}

async function waitForDrama(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = '';
  while (Date.now() < deadline) {
    try {
      const health = await fetchJson(`${baseUrl()}/health`, 1200);
      if (health && health.ok === true && health.service === 'hapa-drama' && health.node === '.hapaDrama') return health;
      lastError = `Unexpected health payload: ${JSON.stringify(health)}`;
    } catch (error) {
      lastError = error.message || String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Hapa Drama did not become healthy at ${baseUrl()}: ${lastError}`);
}

async function resolveAvailablePort(startPort, maxOffset = 40) {
  for (let candidate = startPort; candidate <= startPort + maxOffset; candidate += 1) {
    if (!(await isPortListening(candidate))) return candidate;
  }
  throw new Error(`No free Hapa Drama port found on ${HOST} in range ${startPort}-${startPort + maxOffset}`);
}

async function ensureServer() {
  if (await healthIsDrama()) {
    if (await supportsDesktopProtocol()) return;
  }

  const resolvedPort = await resolveAvailablePort(activePort);
  if (resolvedPort !== activePort) {
    process.stdout.write(`[desktop] Port ${activePort} is occupied on ${HOST}. Using HAPA_DRAMA_PORT=${resolvedPort}\n`);
    activePort = resolvedPort;
  }

  const python = await resolvePython();
  const env = {
    ...process.env,
    PYTHONPATH: [path.join(ROOT_DIR, 'python'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    HAPA_DRAMA_HOST: HOST,
    HAPA_DRAMA_PORT: String(activePort),
    HAPA_DRAMA_RUNTIME_FILE: RUNTIME_FILE,
  };
  const args = ['-m', 'hapa_drama_node.cli', 'serve', '--host', HOST, '--port', String(activePort)];
  if (DEV_MODE) args.push('--reload');
  serverProcess = spawn(python, args, {
    cwd: ROOT_DIR,
    env,
    stdio: DEV_MODE ? 'inherit' : ['ignore', 'pipe', 'pipe'],
  });
  serverStartedByElectron = true;

  if (!DEV_MODE) {
    const logDir = path.join(ROOT_DIR, 'artifacts', 'logs');
    fs.mkdirSync(logDir, { recursive: true });
    const logPath = path.join(logDir, 'hapa_drama_electron_server.log');
    const log = fs.createWriteStream(logPath, { flags: 'a' });
    serverProcess.stdout.pipe(log);
    serverProcess.stderr.pipe(log);
  }

  serverProcess.on('exit', (code, signal) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('hapa-drama-server-exit', { code, signal });
    }
  });

  await waitForDrama();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 920,
    minWidth: 1040,
    minHeight: 720,
    title: 'Hapa Drama',
    backgroundColor: '#07111f',
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(baseUrl())) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadURL(`${baseUrl()}/?desktop=electron&v=${Date.now()}`);
  if (DEV_MODE) mainWindow.webContents.openDevTools({ mode: 'detach' });
}

async function boot() {
  try {
    await ensureServer();
    createWindow();
  } catch (error) {
    await dialog.showMessageBox({
      type: 'error',
      title: 'Hapa Drama failed to launch',
      message: error.message || String(error),
      detail: `Root: ${ROOT_DIR}\nURL: ${baseUrl()}`,
    });
    app.quit();
  }
}

app.whenReady().then(boot);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('before-quit', () => {
  if (serverStartedByElectron && serverProcess && !serverProcess.killed) {
    serverProcess.kill('SIGTERM');
  }
});
