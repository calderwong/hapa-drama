const state = {
  token: '',
  capabilities: null,
  defaultRoute: null,
  lastGeneration: null,
  selectedGenerationId: null,
  voiceProfiles: [],
  telemetry: null,
  pollTimer: null,
  audioObjectUrl: null,
  audioPreviewPath: null,
  recorder: { recording: false, chunks: [], sampleRate: 48000, blob: null, objectUrl: null, stream: null, context: null, source: null, processor: null, startedAt: null },
};
const $ = (id) => document.getElementById(id);
const UI_VERSION = 'docs-readme-1';

function print(value) {
  $('output').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function appendText(parent, tag, text, className = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function appendInlineMarkdown(parent, text) {
  const linkPattern = /\[([^\]]+)\]\(([^)]+)\)/g;
  let lastIndex = 0;
  let match;
  while ((match = linkPattern.exec(text)) !== null) {
    if (match.index > lastIndex) parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    const label = match[1];
    const href = match[2];
    const safeHref = /^(https?:\/\/|\/)/.test(href) ? href : '';
    if (safeHref) {
      const link = document.createElement('a');
      link.textContent = label;
      link.href = safeHref;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      parent.appendChild(link);
    } else {
      parent.appendChild(document.createTextNode(label));
    }
    lastIndex = linkPattern.lastIndex;
  }
  if (lastIndex < text.length) parent.appendChild(document.createTextNode(text.slice(lastIndex)));
}

function safeMarkdownToHtml(markdown) {
  const fragment = document.createDocumentFragment();
  const lines = String(markdown || '').split(/\r?\n/);
  let list = null;
  let code = null;
  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, '');
    if (line.startsWith('```')) {
      if (code) {
        fragment.appendChild(code);
        code = null;
      } else {
        code = document.createElement('pre');
      }
      continue;
    }
    if (code) {
      code.textContent += `${line}\n`;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      list = null;
      appendText(fragment, `h${heading[1].length}`, heading[2]);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      if (!list) {
        list = document.createElement('ul');
        fragment.appendChild(list);
      }
      const item = document.createElement('li');
      appendInlineMarkdown(item, bullet[1]);
      list.appendChild(item);
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const p = document.createElement('p');
    appendInlineMarkdown(p, line.replace(/`([^`]+)`/g, '$1'));
    fragment.appendChild(p);
  }
  if (code) fragment.appendChild(code);
  return fragment;
}

async function loadDocs() {
  const viewer = $('docsContent');
  const provenance = $('docsProvenance');
  viewer.textContent = 'Loading README.md...';
  try {
    const data = await fetch('/docs/readme', { cache: 'no-store' }).then((res) => {
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json();
    });
    viewer.textContent = '';
    viewer.appendChild(safeMarkdownToHtml(data.content || ''));
    provenance.textContent = `${data.document_id} from ${data.source_path} • sha256 ${String(data.sha256 || '').slice(0, 12)} • safe Markdown: no HTML/script passthrough`;
  } catch (err) {
    viewer.textContent = `README viewer failed: ${err.message || err}`;
    provenance.textContent = 'Docs endpoint unavailable.';
  }
}

function valueOrNull(id) {
  const value = $(id).value.trim();
  return value ? value : null;
}

function numberOrNull(id) {
  const value = $(id).value.trim();
  return value ? Number(value) : null;
}

function parseJsonField(id) {
  const raw = $(id).value.trim();
  if (!raw) return {};
  return JSON.parse(raw);
}

function slug(value, fallback) {
  const normalized = String(value || fallback || 'voice-profile').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return normalized || fallback;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',').pop() : value);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function mergeFloat32(chunks) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const samples = new Float32Array(length);
  let offset = 0;
  chunks.forEach((chunk) => {
    samples.set(chunk, offset);
    offset += chunk.length;
  });
  return samples;
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
}

function encodeWav(samples, sampleRate) {
  const channels = 1;
  const bytesPerSample = 2;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * bytesPerSample, true);
  view.setUint16(32, channels * bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: 'audio/wav' });
}

function setBadge(id, text, variant = 'muted') {
  const node = $(id);
  node.textContent = text;
  node.className = `pill ${variant}`;
}

function statusVariant(status) {
  if (status === 'succeeded' || status === 'online') return 'good';
  if (status === 'failed') return 'bad';
  if (status === 'running' || status === 'submitting') return 'active';
  return 'muted';
}

function formatTime(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleTimeString();
  } catch {
    return value;
  }
}

function formatDuration(value) {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return `${seconds.toFixed(seconds < 10 ? 2 : 1)}s`;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { ...options, headers, cache: 'no-store' });
  const type = res.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) throw new Error(typeof data === 'string' ? data : data.detail || `${res.status} ${res.statusText}`);
  return data;
}

function renderAssets(generation) {
  const actions = $('assetActions');
  actions.innerHTML = '';
  if (!generation || !generation.generation_id) return;
  const links = [
    ['Audio WAV', `/v1/generations/${generation.generation_id}/audio`, `${generation.generation_id}.wav`],
    ['Card JSON', `/v1/generations/${generation.generation_id}/card`, `${generation.card_id || generation.generation_id}.json`],
    ['Cymatica Manifest', `/v1/generations/${generation.generation_id}/cymatica-manifest`, `${generation.generation_id}-cymatica.json`],
    ['Cymatica Handoff Zip', `/v1/generations/${generation.generation_id}/cymatica-handoff`, `${generation.generation_id}.hapaBundle.zip`],
  ];
  for (const [label, href, filename] of links) {
    const button = document.createElement('button');
    button.textContent = label;
    button.className = 'asset-link';
    button.addEventListener('click', () => downloadAsset(href, filename));
    actions.appendChild(button);
  }
}

async function downloadAsset(path, filename) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(path, { headers, cache: 'no-store' });
  if (!res.ok) {
    print(`Download failed: ${res.status} ${res.statusText}`);
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function resetAudioPreview() {
  const preview = $('audioPreview');
  const player = $('audioPlayer');
  if (state.audioObjectUrl) {
    URL.revokeObjectURL(state.audioObjectUrl);
    state.audioObjectUrl = null;
  }
  state.audioPreviewPath = null;
  player.removeAttribute('src');
  player.load();
  preview.className = 'audio-preview idle';
  $('audioPreviewTitle').textContent = 'No audio selected';
  $('audioPreviewMeta').textContent = 'Generate or select a completed run to preview audio.';
}

async function previewAudio(path, label, autoplay = true) {
  const preview = $('audioPreview');
  const player = $('audioPlayer');
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (!autoplay && state.audioPreviewPath === path && player.getAttribute('src')) return;
  preview.className = 'audio-preview loading';
  $('audioPreviewTitle').textContent = 'Loading audio preview...';
  $('audioPreviewMeta').textContent = label || path;
  const res = await fetch(path, { headers, cache: 'no-store' });
  if (!res.ok) {
    preview.className = 'audio-preview failed';
    $('audioPreviewTitle').textContent = 'Audio preview failed';
    $('audioPreviewMeta').textContent = `${res.status} ${res.statusText}`;
    return;
  }
  const blob = await res.blob();
  if (state.audioObjectUrl) URL.revokeObjectURL(state.audioObjectUrl);
  state.audioObjectUrl = URL.createObjectURL(blob);
  state.audioPreviewPath = path;
  player.src = state.audioObjectUrl;
  preview.className = 'audio-preview ready';
  $('audioPreviewTitle').textContent = label || 'Generated audio preview';
  $('audioPreviewMeta').textContent = `${Math.round(blob.size / 1024)} KB WAV • ready to play`;
  player.load();
  if (!autoplay) {
    $('audioPreviewMeta').textContent = `${Math.round(blob.size / 1024)} KB WAV • press play to preview`;
    return;
  }
  try {
    await player.play();
  } catch {
    $('audioPreviewMeta').textContent = `${Math.round(blob.size / 1024)} KB WAV • press play to preview`;
  }
}

function renderAssetButtons(process) {
  const actions = $('assetActions');
  actions.innerHTML = '';
  const generationId = (process || {}).generation_id || (state.lastGeneration || {}).generation_id;
  if (!generationId) {
    resetAudioPreview();
    return;
  }
  const assets = (process || {}).assets && process.assets.length ? process.assets : [
    { label: 'Audio WAV', path: `/v1/generations/${generationId}/audio`, kind: 'audio' },
    { label: 'Card JSON', path: `/v1/generations/${generationId}/card`, kind: 'card' },
    { label: 'Cymatica Manifest', path: `/v1/generations/${generationId}/cymatica-manifest`, kind: 'cymatica_manifest' },
    { label: 'Cymatica Handoff Zip', path: `/v1/generations/${generationId}/cymatica-handoff`, kind: 'cymatica_handoff_zip' },
  ];
  const audioAsset = assets.find((asset) => asset.kind === 'audio');
  const audioLabel = audioAsset && audioAsset.duration_seconds ? `Generation ${generationId} • ${formatDuration(audioAsset.duration_seconds)}` : `Generation ${generationId}`;
  if (audioAsset && (process || {}).status === 'succeeded') {
    const preview = document.createElement('button');
    preview.textContent = 'Preview Audio';
    preview.className = 'asset-link preview';
    preview.addEventListener('click', () => previewAudio(audioAsset.path, audioLabel, true));
    actions.appendChild(preview);
  }
  for (const asset of assets) {
    const button = document.createElement('button');
    button.textContent = asset.label || asset.kind;
    button.className = 'asset-link';
    button.addEventListener('click', () => downloadAsset(asset.path, `${generationId}-${asset.kind || 'asset'}`));
    actions.appendChild(button);
  }
  if (audioAsset && (process || {}).status === 'succeeded') {
    previewAudio(audioAsset.path, audioLabel, false).catch((err) => print(`Audio preview failed: ${err.message || err}`));
  }
}

function syntheticProcess(status, stage, command = null) {
  return {
    status,
    stage,
    progress: status === 'submitting' ? 0.06 : 0,
    generation_id: state.selectedGenerationId,
    command_id: command && command.command_id,
    mode: (command && command.mode) || $('mode').value,
    engine: 'selecting',
    voice_id: valueOrNull('voiceId'),
    voice_profile_id: valueOrNull('voiceProfile'),
    updated_at: new Date().toISOString(),
    assets: [],
    outcome: { succeeded: false, failed: false },
    timeline: [{ kind: 'ui.command.submitted', time: new Date().toISOString(), payload: { kind: (command && command.kind) || 'synthesize' } }],
  };
}

function renderProfiles() {
  const select = $('voiceProfile');
  select.innerHTML = '<option value="">No profile</option>';
  const library = $('library');
  if (!state.voiceProfiles.length) {
    library.textContent = 'No profiles loaded yet.';
    return;
  }
  library.innerHTML = '';
  const defaultProfileId = (state.defaultRoute || {}).voice_profile_id;
  for (const profile of state.voiceProfiles) {
    const isDefault = Boolean(defaultProfileId && defaultProfileId === profile.profile_id);
    const option = document.createElement('option');
    option.value = profile.profile_id;
    option.textContent = `${profile.display_name} (${profile.profile_id})${isDefault ? ' • default' : ''}`;
    select.appendChild(option);
    const card = document.createElement('div');
    card.className = 'profile-card';
    card.innerHTML = `<strong>${profile.display_name}${isDefault ? ' • default' : ''}</strong><span>${profile.profile_id}</span><small>voice=${profile.voice_id} mode=${profile.default_mode}</small>`;
    library.appendChild(card);
  }
}

function renderDefaultVoiceSummary() {
  const node = $('defaultVoiceSummary');
  if (!node) return;
  const route = state.defaultRoute || {};
  const label = route.voice_display_name || route.voice_profile_id || 'No saved default voice';
  const engine = route.tts_engine || 'engine pending';
  const mode = route.mode || 'auto';
  node.textContent = `${label} • ${mode} / ${engine}`;
}

function applyDefaultRouteControls() {
  const route = state.defaultRoute || {};
  if (route.voice_profile_id && $('voiceProfile')) {
    const exists = state.voiceProfiles.some((profile) => profile.profile_id === route.voice_profile_id);
    if (exists) {
      $('voiceProfile').value = route.voice_profile_id;
      $('voiceProfile').dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
  if (route.mode && $('mode')) $('mode').value = route.mode;
  if (route.tts_engine && $('ttsEngine')) $('ttsEngine').value = route.tts_engine;
  if (route.voice_id && $('voiceId') && !$('voiceId').value.trim()) $('voiceId').value = route.voice_id;
  if (route.reference_text && $('hintsJson')) {
    try {
      const hints = parseJsonField('hintsJson');
      const updatedHints = { ...hints, preferred_engine: route.tts_engine };
      if (route.reference_text_is_transcript) updatedHints.reference_text = route.reference_text;
      $('hintsJson').value = JSON.stringify(updatedHints, null, 2);
    } catch {}
  }
  const badge = $('defaultRouteBadge');
  if (badge) {
    const profile = route.voice_profile_id || 'profile pending';
    const engine = route.tts_engine || 'engine pending';
    badge.textContent = `${route.mode || 'auto'} / ${engine} / ${profile}`;
    badge.className = route.voice_clip_path ? 'pill good' : 'pill warn';
  }
  renderDefaultVoiceSummary();
}

async function refreshDefaultRoute() {
  const data = await api('/v1/default-route');
  state.defaultRoute = data.default_route || state.defaultRoute;
  renderProfiles();
  applyDefaultRouteControls();
  return data;
}

async function refreshProfiles() {
  const data = await api('/v1/voice-profiles');
  state.voiceProfiles = data.voice_profiles || [];
  renderProfiles();
  applyDefaultRouteControls();
  return data;
}

async function setDefaultRouteFromProfile(profileId) {
  const profile = state.voiceProfiles.find((item) => item.profile_id === profileId);
  if (!profile) {
    print('Select or save a voice profile first.');
    return null;
  }
  const mode = profile.default_mode && profile.default_mode !== 'auto' ? profile.default_mode : 'drama';
  const hints = profile.request_hints || {};
  const refTextMarked = ['reference_text_is_transcript', 'ref_text_is_transcript', 'voice_clip_text_is_transcript']
    .some((key) => ['1', 'true', 'yes', 'on'].includes(String(hints[key] || profile[key] || '').trim().toLowerCase()))
    || ['reference_text_source', 'ref_text_source']
      .some((key) => ['transcript', 'caption', 'manual_transcript', 'manual-caption'].includes(String(hints[key] || profile[key] || '').trim().toLowerCase()));
  const referenceText = refTextMarked ? (hints.reference_text || hints.ref_text || hints.voice_clip_text || null) : null;
  const body = {
    mode,
    tts_engine: valueOrNull('ttsEngine') || (state.defaultRoute || {}).tts_engine || 'dramabox',
    voice_profile_id: profile.profile_id,
    voice_id: profile.voice_id,
    voice_display_name: profile.display_name,
    voice_clip_path: profile.clip_audio_path,
    reference_text: referenceText,
    reference_text_is_transcript: Boolean(referenceText),
  };
  const data = await api('/v1/default-route', { method: 'PUT', body: JSON.stringify(body) });
  state.defaultRoute = data.default_route || body;
  renderProfiles();
  applyDefaultRouteControls();
  return data;
}

function setRecordStatus(text, variant = 'muted') {
  const status = $('recordStatus');
  if (!status) return;
  status.textContent = text;
  status.className = `pill ${variant}`;
}

function fillRecordedProfileFields(blob) {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '').replace('T', '-');
  const base = `recorded-${stamp}`;
  $('profileId').value = `profile-${base}`;
  $('profileName').value = 'Recorded Voice';
  $('profileVoiceId').value = `voice-${base}`;
  $('profileDefaultMode').value = 'drama';
  $('profileDescription').value = 'Recorded in Hapa Drama.';
  $('traitsJson').value = JSON.stringify({ tone: 'recorded', source: 'browser_microphone' }, null, 2);
  $('hintsJson').value = JSON.stringify({ best_for: 'dialogue', reference_note: 'Browser microphone voice sample recorded in Hapa Drama.' }, null, 2);
  $('recordMeta').textContent = `${Math.round((blob || {}).size / 1024)} KB WAV captured.`;
}

async function startVoiceRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    print('Microphone recording is not available in this browser context.');
    return;
  }
  if (state.recorder.recording) return;
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextCtor();
  await context.resume();
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);
  state.recorder = {
    recording: true,
    chunks: [],
    sampleRate: context.sampleRate,
    blob: null,
    objectUrl: state.recorder.objectUrl,
    stream,
    context,
    source,
    processor,
    startedAt: Date.now(),
  };
  processor.onaudioprocess = (event) => {
    if (!state.recorder.recording) return;
    state.recorder.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    event.outputBuffer.getChannelData(0).fill(0);
  };
  source.connect(processor);
  processor.connect(context.destination);
  $('recordStart').disabled = true;
  $('recordStop').disabled = false;
  $('recordSave').disabled = true;
  setRecordStatus('recording', 'active');
  $('recordMeta').textContent = 'Recording...';
}

async function stopVoiceRecording() {
  const recorder = state.recorder;
  if (!recorder.recording) return;
  recorder.recording = false;
  try { recorder.processor && recorder.processor.disconnect(); } catch {}
  try { recorder.source && recorder.source.disconnect(); } catch {}
  try { recorder.stream && recorder.stream.getTracks().forEach((track) => track.stop()); } catch {}
  try { recorder.context && await recorder.context.close(); } catch {}
  const samples = mergeFloat32(recorder.chunks || []);
  const blob = encodeWav(samples, recorder.sampleRate || 48000);
  if (state.recorder.objectUrl) URL.revokeObjectURL(state.recorder.objectUrl);
  const objectUrl = URL.createObjectURL(blob);
  state.recorder = { ...recorder, recording: false, blob, objectUrl, stream: null, context: null, source: null, processor: null };
  $('recordedAudio').src = objectUrl;
  $('recordedAudio').load();
  fillRecordedProfileFields(blob);
  $('recordStart').disabled = false;
  $('recordStop').disabled = true;
  $('recordSave').disabled = false;
  setRecordStatus('captured', 'good');
}

async function uploadVoiceProfileBlob(blob, filename, source) {
  const clipBase64 = await blobToBase64(blob);
  const profileId = valueOrNull('profileId') || `profile-${slug(filename.replace(/\.[^.]+$/, ''), 'recorded-voice')}`;
  const body = {
    profile_id: profileId,
    voice_id: valueOrNull('profileVoiceId') || `voice-${profileId.replace(/^profile-/, '')}`,
    display_name: valueOrNull('profileName') || filename.replace(/\.[^.]+$/, '') || 'Recorded Voice',
    description: valueOrNull('profileDescription'),
    default_mode: $('profileDefaultMode').value,
    filename,
    clip_base64: clipBase64,
    traits: { ...parseJsonField('traitsJson'), source },
    request_hints: parseJsonField('hintsJson'),
  };
  const data = await api('/v1/voice-profiles/upload', { method: 'POST', body: JSON.stringify(body) });
  await refreshProfiles();
  $('voiceProfile').value = data.voice_profile.profile_id;
  $('voiceProfile').dispatchEvent(new Event('change', { bubbles: true }));
  return data;
}

async function saveRecordedVoice() {
  if (!state.recorder.blob) {
    print('Record a voice sample first.');
    return;
  }
  setRecordStatus('saving', 'active');
  const profileId = valueOrNull('profileId') || 'profile-recorded-voice';
  const data = await uploadVoiceProfileBlob(state.recorder.blob, `${profileId}.wav`, 'browser_microphone');
  let defaultResult = null;
  if ($('recordMakeDefault').checked) {
    defaultResult = await setDefaultRouteFromProfile(data.voice_profile.profile_id);
  }
  await refreshRuntime();
  setRecordStatus('saved', 'good');
  print({ ...data, default_route: defaultResult && defaultResult.default_route });
}

function renderProcess(process) {
  if (!process) {
    setBadge('processBadge', 'no generation yet', 'muted');
    $('currentStatus').textContent = 'idle';
    $('currentStage').textContent = 'waiting';
    $('currentEngine').textContent = '—';
    $('currentVoice').textContent = '—';
    $('progressFill').style.width = '0%';
    $('progressText').textContent = '0%';
    $('currentGenerationId').textContent = 'No generation selected.';
    $('currentUpdated').textContent = '—';
    $('outcomeCard').className = 'outcome-card idle';
    $('outcomeCard').textContent = 'Submit a generation to see success/failure, assets, provenance, and errors here.';
    $('timeline').innerHTML = '';
    renderAssetButtons(null);
    return;
  }
  state.selectedGenerationId = process.generation_id || state.selectedGenerationId;
  const progress = Math.max(0, Math.min(1, Number(process.progress || 0)));
  const status = process.status || 'unknown';
  const stage = process.stage || 'unknown';
  setBadge('processBadge', `${status}: ${stage}`, statusVariant(status));
  $('currentStatus').textContent = status;
  $('currentStage').textContent = stage;
  $('currentEngine').textContent = `${process.mode || '—'} / ${process.engine || '—'}`;
  $('currentVoice').textContent = process.voice_profile_id || process.voice_id || '—';
  $('progressFill').style.width = `${Math.round(progress * 100)}%`;
  $('progressText').textContent = `${Math.round(progress * 100)}%`;
  $('currentGenerationId').textContent = process.generation_id ? `generation ${process.generation_id}` : 'No generation id yet.';
  $('currentUpdated').textContent = `updated ${formatTime(process.updated_at)}`;
  renderOutcome(process);
  renderTimeline(process.timeline || [], status);
  renderAssetButtons(process);
}

function renderOutcome(process) {
  const card = $('outcomeCard');
  const outcome = process.outcome || {};
  if (outcome.succeeded) {
    card.className = 'outcome-card succeeded';
    const metadata = outcome.engine_metadata || {};
    const duration = formatDuration(outcome.duration_seconds);
    const voice = metadata.macos_voice ? ` • ${metadata.macos_voice}` : '';
    card.innerHTML = `<strong>Generation succeeded.</strong><span>${duration ? `Duration: ${duration}${voice}` : `Engine: ${process.engine || '—'}${voice}`}</span><span>Audio SHA: ${outcome.audio_sha256 || '—'}</span><span>Card: ${outcome.card_id || '—'}</span><span>Assets ready: ${(process.assets || []).length}</span>`;
    return;
  }
  if (outcome.failed || process.status === 'failed') {
    card.className = 'outcome-card failed';
    card.innerHTML = `<strong>Generation failed.</strong><span>${outcome.error || 'No error detail returned.'}</span>`;
    return;
  }
  card.className = 'outcome-card running';
  card.innerHTML = `<strong>Generation in progress.</strong><span>${process.stage || 'working'}...</span>`;
}

function renderTimeline(events, status) {
  const timeline = $('timeline');
  if (!events.length) {
    timeline.innerHTML = '<div class="timeline-empty">No process events yet.</div>';
    return;
  }
  timeline.innerHTML = '';
  events.forEach((event, index) => {
    const item = document.createElement('div');
    const failed = String(event.kind || '').includes('failed');
    const active = index === events.length - 1 && status === 'running';
    item.className = `timeline-item ${failed ? 'failed' : active ? 'active' : 'done'}`;
    const payload = event.payload || {};
    const detail = payload.error || payload.status || payload.engine || payload.card_id || payload.handoff_zip_path || payload.generation_id || '';
    item.innerHTML = `<span class="timeline-dot"></span><div><strong>${event.kind}</strong><small>${formatTime(event.time)} ${detail ? `• ${detail}` : ''}</small></div>`;
    timeline.appendChild(item);
  });
}

function renderRecentProcesses(processes = []) {
  const node = $('recentGenerations');
  if (!processes.length) {
    node.textContent = 'No generations yet.';
    return;
  }
  node.innerHTML = '';
  for (const process of processes) {
    const card = document.createElement('button');
    card.className = `process-card ${statusVariant(process.status)}`;
    card.innerHTML = `<strong>${process.status}</strong><span>${process.stage}</span><small>${process.generation_id}</small><small>${Math.round(Number(process.progress || 0) * 100)}% • ${process.mode || '—'} / ${process.engine || '—'}</small>`;
    card.addEventListener('click', async () => {
      state.selectedGenerationId = process.generation_id;
      renderProcess(await fetchProcess(process.generation_id));
    });
    node.appendChild(card);
  }
}

async function fetchProcess(generationId) {
  const data = await api(`/v1/generations/${generationId}/process`);
  return data.process;
}

async function refreshRuntime({ renderSelected = true } = {}) {
  const health = await fetch('/health', { cache: 'no-store' }).then((res) => res.json());
  const engines = health.engines || {};
  const readyLabels = Object.entries(engines).filter(([, value]) => value && value.enabled && value.ready).map(([key]) => key.replace('_', '-'));
  setBadge('healthBadge', health.ok ? `health ok ${readyLabels.length ? `• ${readyLabels.join(', ')}` : ''}` : 'health failed', health.ok ? 'good' : 'bad');
  const telemetry = await api('/v1/telemetry');
  state.telemetry = telemetry;
  const metrics = telemetry.metrics || {};
  setBadge('telemetryBadge', `telemetry seq ${metrics.latest_event_seq ?? 0}`, telemetry.status === 'online' ? 'good' : 'warn');
  renderRecentProcesses(telemetry.recent_processes || []);
  if (renderSelected && state.selectedGenerationId) {
    renderProcess(await fetchProcess(state.selectedGenerationId));
  } else if (renderSelected && telemetry.recent_processes && telemetry.recent_processes.length && !state.selectedGenerationId) {
    renderProcess(telemetry.recent_processes[0]);
  }
  return telemetry;
}

function startProcessPolling(generationId) {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.selectedGenerationId = generationId;
  state.pollTimer = setInterval(async () => {
    try {
      const process = await fetchProcess(generationId);
      renderProcess(process);
      await refreshRuntime({ renderSelected: false });
      if (['succeeded', 'failed'].includes(process.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
    } catch (err) {
      print(`Process poll failed: ${err.message || err}`);
    }
  }, 1200);
}

async function bootstrap() {
  $('emotionIntensity').addEventListener('input', () => {
    $('emotionValue').textContent = Number($('emotionIntensity').value).toFixed(2);
  });
  $('refreshDocs').addEventListener('click', () => loadDocs());
  try {
    await loadDocs();
    const session = await fetch('/local/session', { cache: 'no-store' }).then((res) => res.json());
    if (session.ok && session.token) {
      state.token = session.token;
      $('token').value = session.token;
      setBadge('serviceStatus', `${session.service} token loaded`, 'good');
      $('sessionHint').textContent = `Token source: ${session.token_path}`;
    }
    state.capabilities = await api('/capabilities');
    state.defaultRoute = session.default_route || state.capabilities.default_route || null;
    await refreshDefaultRoute().catch(() => {});
    await refreshProfiles();
    await refreshRuntime();
    print({ ready: true, ui_version: UI_VERSION, token_autofill: Boolean(state.token), telemetry: state.telemetry, capabilities: state.capabilities });
  } catch (err) {
    setBadge('serviceStatus', 'Manual token required', 'warn');
    print(`Token bootstrap failed: ${err.message || err}`);
  }
}

$('token').addEventListener('input', () => {
  state.token = $('token').value.trim();
});

$('voiceProfile').addEventListener('change', () => {
  const profile = state.voiceProfiles.find((item) => item.profile_id === $('voiceProfile').value);
  if (!profile) return;
  $('voiceId').value = profile.voice_id || '';
  $('mode').value = 'auto';
  $('profileId').value = profile.profile_id || '';
  $('profileName').value = profile.display_name || '';
  $('profileVoiceId').value = profile.voice_id || '';
  $('profileDefaultMode').value = profile.default_mode || 'auto';
});

$('voiceClipFile').addEventListener('change', () => {
  const file = $('voiceClipFile').files[0];
  if (!file) return;
  const base = slug(file.name.replace(/\.[^.]+$/, ''), 'uploaded-voice');
  if (!$('profileId').value.trim()) $('profileId').value = `profile-${base}`;
  if (!$('profileName').value.trim()) $('profileName').value = file.name.replace(/\.[^.]+$/, '') || 'Uploaded Voice';
  if (!$('profileVoiceId').value.trim()) $('profileVoiceId').value = `voice-${base}`;
  if (!$('profileDescription').value.trim()) $('profileDescription').value = `Uploaded from ${file.name}`;
});

$('recordStart').addEventListener('click', async () => {
  try {
    await startVoiceRecording();
  } catch (err) {
    setRecordStatus('mic blocked', 'bad');
    print(`Recording failed: ${err.message || err}`);
  }
});

$('recordStop').addEventListener('click', async () => {
  try {
    await stopVoiceRecording();
  } catch (err) {
    setRecordStatus('failed', 'bad');
    print(`Recording stop failed: ${err.message || err}`);
  }
});

$('recordSave').addEventListener('click', async () => {
  try {
    state.token = $('token').value.trim();
    await saveRecordedVoice();
  } catch (err) {
    setRecordStatus('failed', 'bad');
    print(`Save recording failed: ${err.message || err}`);
  }
});

$('setSelectedDefault').addEventListener('click', async () => {
  try {
    state.token = $('token').value.trim();
    const profileId = valueOrNull('voiceProfile') || valueOrNull('profileId');
    const data = await setDefaultRouteFromProfile(profileId);
    if (data) print(data);
  } catch (err) {
    print(`Set default failed: ${err.message || err}`);
  }
});

$('generate').addEventListener('click', async () => {
  state.token = $('token').value.trim();
  const payload = {
    text: $('text').value,
    voice_id: valueOrNull('voiceId'),
    voice_profile_id: valueOrNull('voiceProfile'),
    emotion: {
      style: valueOrNull('emotionStyle') || 'neutral',
      intensity: Number($('emotionIntensity').value),
    },
    timing: {
      bpm: numberOrNull('bpm'),
      start_seconds: numberOrNull('startSeconds') || 0,
      target_duration_seconds: numberOrNull('targetDuration'),
    },
    output: {
      format: 'wav',
      mint_card: $('mintCard').checked,
      cymatica_bundle: $('cymaticaBundle').checked,
    },
  };
  const ttsEngine = valueOrNull('ttsEngine');
  if (ttsEngine) payload.tts_engine = ttsEngine;
  if ($('chatterboxModel').value) payload.chatterbox_model = $('chatterboxModel').value;
  const requesterNode = valueOrNull('requesterNode');
  if (requesterNode) payload.request = { requested_by: requesterNode };
  const command = {
    api_version: 'v1',
    command_id: crypto.randomUUID(),
    actor: valueOrNull('actor') || 'ui:hapa-drama',
    kind: 'synthesize',
    mode: $('mode').value,
    payload,
    provenance: { source_node: 'hapa-drama', surface: 'web-ui' },
    options: { async: false },
  };
  renderProcess(syntheticProcess('submitting', 'sending command envelope', command));
  print({ status: 'submitting', command });
  try {
    const data = await api('/v1/commands', { method: 'POST', body: JSON.stringify(command) });
    state.lastGeneration = data.generation || null;
    if (state.lastGeneration) {
      state.selectedGenerationId = state.lastGeneration.generation_id;
      $('clipGenerationId').value = state.lastGeneration.generation_id;
      if (!$('profileName').value.trim()) $('profileName').value = 'New Voice Profile';
      if (!$('profileId').value.trim()) $('profileId').value = `profile-${state.lastGeneration.generation_id.slice(0, 8)}`;
      if (!$('profileVoiceId').value.trim()) $('profileVoiceId').value = `voice-${state.lastGeneration.generation_id.slice(0, 8)}`;
      $('entangleVoiceId').value = state.lastGeneration.voice_id || $('profileVoiceId').value;
      renderProcess(data.process);
      startProcessPolling(state.lastGeneration.generation_id);
    }
    await refreshRuntime({ renderSelected: Boolean(state.selectedGenerationId) });
    print(data);
  } catch (err) {
    renderProcess({ ...syntheticProcess('failed', 'request failed', command), outcome: { failed: true, error: err.message || String(err) }, timeline: [{ kind: 'ui.command.failed', time: new Date().toISOString(), payload: { error: err.message || String(err) } }] });
    print(`Error: ${err.message || err}`);
  }
});

$('simpleGenerate').addEventListener('click', async () => {
  state.token = $('token').value.trim();
  const route = state.defaultRoute || {};
  const command = {
    api_version: 'v1',
    command_id: crypto.randomUUID(),
    actor: valueOrNull('actor') || 'ui:hapa-drama-simple',
    kind: 'synthesize',
    mode: route.mode || 'drama',
    payload: {
      text: $('simpleText').value,
      tts_engine: route.tts_engine || 'dramabox',
      voice_profile_id: route.voice_profile_id || valueOrNull('voiceProfile'),
      voice_id: route.voice_id || valueOrNull('voiceId'),
      ref_text: route.reference_text || null,
      emotion: { style: 'neutral', intensity: Number($('emotionIntensity').value) },
      timing: {
        bpm: numberOrNull('bpm'),
        start_seconds: numberOrNull('startSeconds') || 0,
        target_duration_seconds: numberOrNull('targetDuration'),
      },
      output: {
        format: 'wav',
        mint_card: $('mintCard').checked,
        cymatica_bundle: $('cymaticaBundle').checked,
      },
    },
    provenance: { source_node: 'hapa-drama', surface: 'web-ui-simple' },
    options: { async: false },
  };
  renderProcess(syntheticProcess('submitting', 'sending simple mode command', command));
  print({ status: 'submitting simple mode', command });
  try {
    const data = await api('/v1/commands', { method: 'POST', body: JSON.stringify(command) });
    state.lastGeneration = data.generation || null;
    if (state.lastGeneration) {
      state.selectedGenerationId = state.lastGeneration.generation_id;
      $('clipGenerationId').value = state.lastGeneration.generation_id;
      renderProcess(data.process);
      startProcessPolling(state.lastGeneration.generation_id);
    }
    await refreshRuntime({ renderSelected: Boolean(state.selectedGenerationId) });
    print(data);
  } catch (err) {
    renderProcess({ ...syntheticProcess('failed', 'simple mode failed', command), outcome: { failed: true, error: err.message || String(err) }, timeline: [{ kind: 'ui.simple.failed', time: new Date().toISOString(), payload: { error: err.message || String(err) } }] });
    print(`Error: ${err.message || err}`);
  }
});

$('saveProfile').addEventListener('click', async () => {
  try {
    state.token = $('token').value.trim();
    const command = {
      api_version: 'v1',
      command_id: crypto.randomUUID(),
      actor: valueOrNull('actor') || 'ui:hapa-drama',
      kind: 'voice.profile.create',
      mode: 'auto',
      payload: {
        profile_id: valueOrNull('profileId'),
        voice_id: valueOrNull('profileVoiceId'),
        display_name: valueOrNull('profileName') || 'Voice Profile',
        description: valueOrNull('profileDescription'),
        default_mode: $('profileDefaultMode').value,
        clip_generation_id: valueOrNull('clipGenerationId') || (state.lastGeneration || {}).generation_id,
        traits: parseJsonField('traitsJson'),
        request_hints: parseJsonField('hintsJson'),
      },
      provenance: { source_node: 'hapa-drama', surface: 'web-ui' },
      options: {},
    };
    const data = await api('/v1/commands', { method: 'POST', body: JSON.stringify(command) });
    await refreshProfiles();
    await refreshRuntime();
    print(data);
  } catch (err) {
    print(`Error: ${err.message || err}`);
  }
});

$('uploadClip').addEventListener('click', async () => {
  try {
    state.token = $('token').value.trim();
    const file = $('voiceClipFile').files[0];
    if (!file) {
      print('Choose a voice clip file first.');
      return;
    }
    print({ status: 'uploading voice clip', filename: file.name, profile_id: valueOrNull('profileId') });
    const data = await uploadVoiceProfileBlob(file, file.name, 'uploaded_clip');
    await refreshRuntime();
    print(data);
  } catch (err) {
    print(`Error: ${err.message || err}`);
  }
});

$('refreshProfiles').addEventListener('click', async () => {
  try {
    print(await refreshProfiles());
  } catch (err) {
    print(`Error: ${err.message || err}`);
  }
});

$('refreshRuntime').addEventListener('click', async () => {
  try {
    print(await refreshRuntime());
  } catch (err) {
    print(`Error: ${err.message || err}`);
  }
});

$('entangleVoice').addEventListener('click', async () => {
  const voiceId = valueOrNull('entangleVoiceId');
  if (!voiceId) {
    print('Voice ID required for entanglement.');
    return;
  }
  const command = {
    api_version: 'v1',
    command_id: crypto.randomUUID(),
    actor: valueOrNull('actor') || 'ui:hapa-drama',
    kind: 'voice.entangle',
    mode: 'auto',
    payload: { voice_id: voiceId, xp_delta: Number($('xpDelta').value || 25) },
    provenance: { source_node: 'hapa-drama', surface: 'web-ui' },
    options: {},
  };
  try {
    const data = await api('/v1/commands', { method: 'POST', body: JSON.stringify(command) });
    await refreshRuntime();
    print(data);
  } catch (err) {
    print(`Error: ${err.message || err}`);
  }
});

bootstrap();
setInterval(() => refreshRuntime({ renderSelected: Boolean(state.selectedGenerationId) }).catch(() => {}), 5000);
