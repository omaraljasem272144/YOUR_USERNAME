'use strict';

// CONNECT HUB — explicit, user-controlled screen sharing.
// No capture starts without a user click and an OS permission prompt.
const el = (id) => document.getElementById(id);
const startButton = el('start');
const stopButton = el('stop');
const compat = el('compat');
const statusEl = el('msg');
const preview = el('preview');
const placeholder = el('placeholder');
const token = location.pathname.split('/').filter(Boolean).pop();

const supported = Boolean(window.isSecureContext &&
  navigator.mediaDevices &&
  typeof navigator.mediaDevices.getDisplayMedia === 'function' &&
  typeof RTCPeerConnection === 'function' &&
  typeof WebSocket === 'function');

let socket = null;
let peer = null;
let stream = null;
let viewerReady = false;
let pendingIce = [];
let generation = 0;

function status(message) {
  statusEl.textContent = message;
}
function send(data) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(data));
  }
}
function buttons(sharing) {
  startButton.classList.toggle('hidden', sharing);
  stopButton.classList.toggle('hidden', !sharing);
  placeholder.classList.toggle('hidden', sharing);
  startButton.disabled = !supported || sharing;
}
function disconnectPeer() {
  if (peer) {
    peer.onicecandidate = null;
    peer.onconnectionstatechange = null;
    peer.close();
    peer = null;
  }
  pendingIce = [];
}
function stopSharing(message = 'تم إيقاف مشاركة الشاشة', notify = true) {
  ++generation;
  if (notify) send({ type: 'stopped' });
  disconnectPeer();
  if (socket) {
    const old = socket;
    socket = null;
    old.close();
  }
  if (stream) {
    const current = stream;
    stream = null;
    current.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
  }
  preview.srcObject = null;
  viewerReady = false;
  buttons(false);
  status(message);
}

async function offerToViewer(expectedGeneration) {
  if (!stream || !viewerReady || !socket ||
      socket.readyState !== WebSocket.OPEN ||
      generation !== expectedGeneration) return;

  disconnectPeer();
  const connection = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
  });
  peer = connection;

  stream.getTracks().forEach((track) => connection.addTrack(track, stream));
  connection.onicecandidate = (event) => {
    if (event.candidate && peer === connection) {
      send({ type: 'candidate', candidate: event.candidate.toJSON() });
    }
  };
  connection.onconnectionstatechange = () => {
    if (peer !== connection) return;
    if (connection.connectionState === 'connected') {
      status('البث مباشر — شاشتك ظاهرة للمشاهد. يمكنك الإيقاف في أي وقت.');
    } else if (connection.connectionState === 'failed') {
      status('تعذّر اتصال الفيديو بين الشبكتين. قد يلزم خادم TURN.');
    } else if (connection.connectionState === 'disconnected') {
      status('انقطع اتصال الفيديو مؤقتاً. يمكنك إيقاف المشاركة.');
    }
  };

  const offer = await connection.createOffer();
  await connection.setLocalDescription(offer);
  if (peer === connection && generation === expectedGeneration) {
    send({ type: 'offer', sdp: connection.localDescription });
    status('تم السماح بمشاركة الشاشة. بانتظار اتصال الفيديو...');
  }
}

function connectSignaling() {
  const currentGeneration = generation;
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const connection = new WebSocket(
    scheme + '//' + location.host + '/ws?role=sender&token=' +
    encodeURIComponent(token)
  );
  socket = connection;

  connection.onopen = () => {
    if (socket === connection) status('المشاركة مفعّلة؛ بانتظار المشاهد.');
  };
  connection.onmessage = async (event) => {
    if (socket !== connection || generation !== currentGeneration) return;
    let message;
    try { message = JSON.parse(event.data); } catch { return; }

    try {
      if (message.type === 'peer-ready') {
        viewerReady = true;
        await offerToViewer(currentGeneration);
      } else if (message.type === 'answer' && peer) {
        await peer.setRemoteDescription(message.sdp);
        for (const candidate of pendingIce) {
          await peer.addIceCandidate(candidate);
        }
        pendingIce = [];
      } else if (message.type === 'candidate' && peer) {
        if (peer.remoteDescription) {
          await peer.addIceCandidate(message.candidate);
        } else {
          pendingIce.push(message.candidate);
        }
      } else if (message.type === 'peer-left') {
        viewerReady = false;
        disconnectPeer();
        status('المشاهد خرج؛ المشاركة ما زالت مفعّلة. اضغط إيقاف لإنهائها.');
      } else if (message.type === 'ended') {
        stopSharing('أنهى المشاهد الجلسة.', false);
      }
    } catch (error) {
      status('مشكلة في الاتصال: ' + error.message);
    }
  };
  connection.onclose = () => {
    if (socket === connection && generation === currentGeneration) {
      stopSharing('انقطع الاتصال بالخادم وتوقفت المشاركة.', false);
    }
  };
  connection.onerror = () => {
    if (socket === connection) status('تعذّر الاتصال بخادم البث.');
  };
}

compat.textContent = supported
  ? 'جهازك يدعم طلب مشاركة الشاشة. يبدأ البث فقط بعد سماحك من نظام الهاتف.'
  : 'هذا المتصفح لا يدعم بث الشاشة الكاملة من صفحة ويب. جرّب Safari 27 أو متصفحاً يدعم مشاركة الشاشة.';
buttons(false);

startButton.addEventListener('click', async () => {
  if (!supported || stream) return;
  startButton.disabled = true;
  try {
    // This must be called directly from a user gesture.
    const selected = await navigator.mediaDevices.getDisplayMedia({
      video: true, audio: false
    });
    const track = selected.getVideoTracks()[0];
    if (!track) {
      selected.getTracks().forEach(t => t.stop());
      status('لم يتم اختيار شاشة للبث.');
      startButton.disabled = false;
      return;
    }
    stream = selected;
    ++generation;
    track.onended = () => stopSharing('أوقفت مشاركة الشاشة من النظام.');
    preview.srcObject = selected;
    preview.play().catch(() => {});
    buttons(true);
    status('مشاركة الشاشة نشطة. يمكنك إيقافها من هذا الزر في أي وقت.');
    connectSignaling();
  } catch (error) {
    startButton.disabled = false;
    status(error.name === 'NotAllowedError'
      ? 'لم تبدأ المشاركة لأن الإذن لم يُمنح.'
      : 'تعذّر بدء المشاركة: ' + error.message);
  }
});
stopButton.addEventListener('click', () => stopSharing());
window.addEventListener('pagehide', () => {
  if (stream) stopSharing('تم إغلاق الصفحة وتوقفت المشاركة.');
});
