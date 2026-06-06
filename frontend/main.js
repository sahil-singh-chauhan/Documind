// ── Always start fresh on page load ──────────────────────────────────────────
sessionStorage.clear();

// ── State ─────────────────────────────────────────────────────────────────────
let currentSessionId = null;   // locked after first upload
let isPdfUploaded = false;
let uploadedDocs = [];     // [{ name, fileUrl, isPdf }] ordered

// ── DOM ───────────────────────────────────────────────────────────────────────
const docPanelEmpty = document.getElementById('doc-panel-empty');
const docPanelActive = document.getElementById('doc-panel-active');
const docTabsEl = document.getElementById('doc-tabs');
const docViewerEl = document.getElementById('doc-viewer');
const clearSessionBtn = document.getElementById('clear-session-btn');

// Main upload form (empty state)
const uploadFormMain = document.getElementById('upload-form-main');
const pdfFileMain = document.getElementById('pdf-file-main');
const uploadBtnMain = document.getElementById('upload-btn-main');
const dropZoneMain = document.getElementById('drop-zone-main');
const mainProgress = document.getElementById('main-progress');
const mainPct = document.getElementById('main-pct');
const mainBar = document.getElementById('main-bar');

// Drawer
const btnAddDoc = document.getElementById('btn-add-doc');
const uploadDrawer = document.getElementById('upload-drawer');
const drawerOverlay = document.getElementById('drawer-overlay');
const btnCloseDrawer = document.getElementById('btn-close-drawer');
const uploadFormDrawer = document.getElementById('upload-form-drawer');
const pdfFileDrawer = document.getElementById('pdf-file-drawer');
const uploadBtnDrawer = document.getElementById('upload-btn-drawer');
const dropZoneDrawer = document.getElementById('drop-zone-drawer');
const drawerProgress = document.getElementById('drawer-progress');
const drawerPct = document.getElementById('drawer-pct');
const drawerBar = document.getElementById('drawer-bar');

// Chat
const chatForm = document.getElementById('chat-form');
const questionInput = document.getElementById('question');
const sendBtn = document.getElementById('send-btn');
const chatBox = document.getElementById('chat-box');
const thinkingPopup = document.getElementById('thinking-popup');

// ── API ───────────────────────────────────────────────────────────────────────
const API_BASE_URL = 'https://documind-ac2q.onrender.com';

// ── Warn before reload if session is active ───────────────────────────────────
window.addEventListener('beforeunload', (e) => {
  if (isPdfUploaded) {
    e.preventDefault();
    e.returnValue = 'Your session will be cleared. Are you sure?';
  }
});

// ── Accepted extensions ───────────────────────────────────────────────────────
const ACCEPTED = ['.pdf', '.docx', '.doc', '.txt'];
const isPdfExt = (name) => name.toLowerCase().endsWith('.pdf');
const isOk = (name) => ACCEPTED.some(e => name.toLowerCase().endsWith(e));

// ═════════════════════════════════════════════════════════════════════════════
// DROP-ZONE WIRING  (works for both the main zone and the drawer zone)
// ═════════════════════════════════════════════════════════════════════════════
function wireDropZone(zone, input, btn, hintSelector = '.drop-hint') {
  const hint = zone.querySelector(hintSelector);

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); })
  );
  ['dragenter', 'dragover'].forEach(ev =>
    zone.addEventListener(ev, () => zone.classList.add('dragover'))
  );
  ['dragleave', 'drop'].forEach(ev =>
    zone.addEventListener(ev, () => zone.classList.remove('dragover'))
  );
  zone.addEventListener('drop', e => {
    const files = e.dataTransfer.files;
    if (files.length) { input.files = files; updateState(); }
  });
  input.addEventListener('change', updateState);

  function updateState() {
    const f = input.files[0];
    if (f && isOk(f.name)) {
      btn.disabled = false;
      hint.innerHTML = `Selected: <span>${f.name}</span>`;
    } else {
      btn.disabled = true;
      hint.innerHTML = `Drag & drop file here or <span>browse</span>`;
      if (f) alert(`Unsupported file type. Use: ${ACCEPTED.join(', ')}`);
    }
  }
}

wireDropZone(dropZoneMain, pdfFileMain, uploadBtnMain);
wireDropZone(dropZoneDrawer, pdfFileDrawer, uploadBtnDrawer);

// ═════════════════════════════════════════════════════════════════════════════
// UPLOAD LOGIC
// ═════════════════════════════════════════════════════════════════════════════
async function doUpload(file, { barEl, pctEl, progressEl, btnEl, afterSuccess }) {
  if (!file || !isOk(file.name)) return;

  btnEl.disabled = true;
  if (progressEl) progressEl.classList.remove('hidden');

  // Animate fake progress
  let prog = 0;
  if (barEl) barEl.style.width = '0%';
  if (pctEl) pctEl.textContent = '0%';
  const ticker = setInterval(() => {
    if (prog < 92) {
      prog += (92 - prog) * 0.05;
      if (barEl) barEl.style.width = `${Math.round(prog)}%`;
      if (pctEl) pctEl.textContent = `${Math.round(prog)}%`;
    }
  }, 300);

  try {
    const formData = new FormData();
    formData.append('file', file);

    const headers = {};
    if (currentSessionId) headers['x-session-id'] = currentSessionId;

    const res = await fetch(`${API_BASE_URL}/upload`, { method: 'POST', headers, body: formData });
    const data = await res.json();

    clearInterval(ticker);
    if (barEl) barEl.style.width = '100%';
    if (pctEl) pctEl.textContent = '100%';

    await new Promise(r => setTimeout(r, 400));
    if (progressEl) progressEl.classList.add('hidden');

    if (data.success) {
      // Lock in session ID on very first upload
      if (data.session_id && !currentSessionId) currentSessionId = data.session_id;

      // Track this document using the real backend URL
      const fileUrl = API_BASE_URL + data.file_url;
      const docEntry = { name: file.name, fileUrl, isPdf: isPdfExt(file.name) };
      if (!uploadedDocs.find(d => d.name === file.name)) {
        uploadedDocs.push(docEntry);
      }

      afterSuccess(docEntry);
    } else {
      alert(data.error || 'Upload failed.');
      btnEl.disabled = false;
    }
  } catch (err) {
    clearInterval(ticker);
    if (progressEl) progressEl.classList.add('hidden');
    btnEl.disabled = false;
    alert('Network error. Is the backend running on port 5000?');
  }
}

// ── Main form submit ──────────────────────────────────────────────────────────
uploadFormMain.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = pdfFileMain.files[0];

  // We use the main form's upload button itself as a progress indicator
  await doUpload(file, {
    barEl: mainBar,
    pctEl: mainPct,
    progressEl: mainProgress,
    btnEl: uploadBtnMain,
    afterSuccess: (doc) => {
      // Transition left panel from empty → active
      docPanelEmpty.classList.add('hidden');
      docPanelActive.classList.remove('hidden');

      addDocTab(doc, true);
      showDoc(doc);
      enableChat();

      // Show "Add Document" button in header
      btnAddDoc.classList.remove('hidden');

      // Reset input
      pdfFileMain.value = '';
      uploadBtnMain.disabled = true;
      dropZoneMain.querySelector('.drop-hint').innerHTML = `Drag & drop file here or <span>browse</span>`;
    }
  });
});

// ── Drawer form submit ────────────────────────────────────────────────────────
uploadFormDrawer.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = pdfFileDrawer.files[0];

  await doUpload(file, {
    barEl: drawerBar,
    pctEl: drawerPct,
    progressEl: drawerProgress,
    btnEl: uploadBtnDrawer,
    afterSuccess: (doc) => {
      addDocTab(doc, true);
      showDoc(doc);
      closeDrawer();

      // Reset drawer input
      pdfFileDrawer.value = '';
      uploadBtnDrawer.disabled = true;
      dropZoneDrawer.querySelector('.drop-hint').innerHTML = `Drag & drop file here or <span>browse</span>`;
    }
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// DOCUMENT TABS & VIEWER
// ═════════════════════════════════════════════════════════════════════════════
function addDocTab(doc, makeActive) {
  // Deactivate all tabs first if making this one active
  if (makeActive) {
    [...docTabsEl.querySelectorAll('.doc-tab')].forEach(t => t.classList.remove('active'));
  }

  const tab = document.createElement('div');
  tab.className = `doc-tab${makeActive ? ' active' : ''}`;
  tab.dataset.name = doc.name;

  const ext = doc.name.split('.').pop().toLowerCase();
  const iconMap = { pdf: 'file-text', docx: 'file', doc: 'file', txt: 'file-text' };
  const icon = iconMap[ext] || 'file';

  tab.innerHTML = `<i data-lucide="${icon}"></i><span title="${doc.name}">${doc.name}</span>`;
  tab.addEventListener('click', () => {
    [...docTabsEl.querySelectorAll('.doc-tab')].forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    showDoc(doc);
  });

  docTabsEl.appendChild(tab);
  lucide.createIcons();
}

let currentPdfDoc = null;

async function showDoc(doc) {
  const pdfContainer = document.getElementById('pdf-container');
  const placeholderContainer = document.getElementById('placeholder-container');

  pdfContainer.innerHTML = '';
  placeholderContainer.innerHTML = '';

  if (doc.isPdf) {
    pdfContainer.classList.remove('hidden');
    placeholderContainer.classList.add('hidden');

    try {
      // Load PDF via PDF.js
      const loadingTask = pdfjsLib.getDocument(doc.fileUrl);
      currentPdfDoc = await loadingTask.promise;

      // Render all pages
      for (let pageNum = 1; pageNum <= currentPdfDoc.numPages; pageNum++) {
        await renderPage(pageNum, pdfContainer, doc.name);
      }
    } catch (err) {
      console.error("Error loading PDF with PDF.js:", err);
      pdfContainer.innerHTML = `<div style="padding: 20px; color: red;">Failed to load PDF preview.</div>`;
    }
  } else {
    pdfContainer.classList.add('hidden');
    placeholderContainer.classList.remove('hidden');

    // Non-PDF: show a styled placeholder
    const ext = doc.name.split('.').pop().toUpperCase();
    placeholderContainer.innerHTML = `
      <div class="doc-placeholder">
        <i data-lucide="file-text"></i>
        <h3>${doc.name}</h3>
        <p>${ext} files cannot be previewed in the browser.</p>
        <p>The document has been uploaded and indexed — ask your questions on the right!</p>
      </div>`;
    lucide.createIcons();
  }
}

async function renderPage(pageNum, container, filename) {
  const page = await currentPdfDoc.getPage(pageNum);

  // Create wrapper
  const wrapper = document.createElement('div');
  wrapper.className = 'pdf-page-wrapper';
  wrapper.id = `pdf-page-${pageNum}`;
  wrapper.dataset.page = pageNum;
  wrapper.dataset.filename = filename;

  // Set scale
  const viewport = page.getViewport({ scale: 1.2 });
  wrapper.style.width = `${viewport.width}px`;
  wrapper.style.height = `${viewport.height}px`;
  wrapper.style.setProperty('--scale-factor', viewport.scale);

  // Create canvas
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  wrapper.appendChild(canvas);

  // Create text layer
  const textLayerDiv = document.createElement('div');
  textLayerDiv.className = 'textLayer';
  textLayerDiv.style.width = `${viewport.width}px`;
  textLayerDiv.style.height = `${viewport.height}px`;
  wrapper.appendChild(textLayerDiv);

  container.appendChild(wrapper);

  // Render canvas
  const renderContext = {
    canvasContext: context,
    viewport: viewport
  };
  await page.render(renderContext).promise;

  // Render text layer
  const textContent = await page.getTextContent();
  await pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayerDiv,
    viewport: viewport,
    textDivs: []
  }).promise;
}

// ═════════════════════════════════════════════════════════════════════════════
// DRAWER
// ═════════════════════════════════════════════════════════════════════════════
function openDrawer() {
  uploadDrawer.classList.remove('hidden');
  drawerOverlay.classList.remove('hidden');
}
function closeDrawer() {
  uploadDrawer.classList.add('hidden');
  drawerOverlay.classList.add('hidden');
}

btnAddDoc.addEventListener('click', openDrawer);
btnCloseDrawer.addEventListener('click', closeDrawer);
drawerOverlay.addEventListener('click', closeDrawer);

// ═════════════════════════════════════════════════════════════════════════════
// CLEAR SESSION
// ═════════════════════════════════════════════════════════════════════════════
clearSessionBtn.addEventListener('click', () => {
  if (!confirm('Clear all uploaded documents and chat history?')) return;

  // Tell backend to permanently delete vectors, files, and chat history
  if (currentSessionId) {
    fetch(`${API_BASE_URL}/session/${currentSessionId}`, { method: 'DELETE' }).catch(() => { });
  }

  // Reset state
  currentSessionId = null;
  isPdfUploaded = false;
  uploadedDocs = [];

  // Reset UI
  docPanelActive.classList.add('hidden');
  docPanelEmpty.classList.remove('hidden');
  docTabsEl.innerHTML = '';

  // Clear the inner containers instead of the parent viewer
  const pdfContainer = document.getElementById('pdf-container');
  const placeholderContainer = document.getElementById('placeholder-container');
  if (pdfContainer) pdfContainer.innerHTML = '';
  if (placeholderContainer) placeholderContainer.innerHTML = '';

  btnAddDoc.classList.add('hidden');
  questionInput.disabled = true;
  sendBtn.disabled = true;

  chatBox.innerHTML = `
    <div class="welcome-message">
      <i data-lucide="bot"></i>
      <h3>Session Cleared</h3>
      <p>Upload a new document to start a fresh conversation.</p>
    </div>`;
  lucide.createIcons();
});

// ═════════════════════════════════════════════════════════════════════════════
// ENABLE CHAT
// ═════════════════════════════════════════════════════════════════════════════
function enableChat() {
  isPdfUploaded = true;
  questionInput.disabled = false;
  sendBtn.disabled = false;
}

// ═════════════════════════════════════════════════════════════════════════════
// CHAT MESSAGING
// ═════════════════════════════════════════════════════════════════════════════
function appendMessage(role, content) {
  const welcome = chatBox.querySelector('.welcome-message');
  if (welcome) welcome.remove();

  const wrapper = document.createElement('div');
  wrapper.className = `msg-wrapper ${role}`;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'msg';
  msgDiv.dataset.rawContent = content; // Store raw text for copying
  if (role === 'assistant') {
    msgDiv.innerHTML = marked.parse(content);
  } else {
    msgDiv.textContent = content;
  }
  wrapper.appendChild(msgDiv);

  // Add Copy button
  const copyBtn = document.createElement('button');
  copyBtn.className = 'btn-copy-msg';
  copyBtn.innerHTML = '<i data-lucide="copy"></i>';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(msgDiv.dataset.rawContent || msgDiv.innerText);
    copyBtn.innerHTML = '<i data-lucide="check"></i>';
    setTimeout(() => {
      copyBtn.innerHTML = '<i data-lucide="copy"></i>';
      lucide.createIcons({ root: copyBtn });
    }, 2000);
    lucide.createIcons({ root: copyBtn });
  });

  // Append to wrapper so it sits completely outside the bubble
  wrapper.appendChild(copyBtn);

  chatBox.appendChild(wrapper);
  lucide.createIcons({ root: wrapper }); // Render the icon immediately
  scrollToBottom();
  return msgDiv;
}

function scrollToBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

// ═════════════════════════════════════════════════════════════════════════════
// PAGE JUMPING INTERCEPTOR
// ═════════════════════════════════════════════════════════════════════════════
chatBox.addEventListener('click', async (e) => {
  // Check if they clicked an <a> or something inside an <a>
  const anchor = e.target.closest('a');
  if (!anchor) return;

  const href = anchor.getAttribute('href');
  if (href && href.startsWith('#jump:')) {
    e.preventDefault();
    const parts = href.split(':');
    const safeTitle = parts[1];
    const pageNum = parts[2];
    const filename = decodeURIComponent(safeTitle);

    // Find the document in our uploaded list
    const doc = uploadedDocs.find(d => d.name === filename);
    if (!doc) {
      alert("This document is not in the current session anymore.");
      return;
    }

    if (!doc.isPdf) {
      alert("Page jumping is only supported for PDF files.");
      return;
    }

    // If changing docs, show the new doc first
    const isChangingDoc = !docTabsEl.querySelector(`.doc-tab[data-name="${filename}"]`).classList.contains('active');

    // Activate its tab
    [...docTabsEl.querySelectorAll('.doc-tab')].forEach(t => {
      if (t.dataset.name === filename) t.classList.add('active');
      else t.classList.remove('active');
    });

    // If we switched docs, render it first
    if (isChangingDoc) {
      await showDoc(doc);
    }

    // Scroll to the page wrapper
    const targetPage = document.getElementById(`pdf-page-${pageNum}`);
    if (targetPage) {
      targetPage.scrollIntoView({ behavior: 'smooth', block: 'start' });

      // Highlight the snippet if we have it
      if (window.currentSourcesData) {
        const snippetData = window.currentSourcesData.find(s => s.filename === filename && s.page === parseInt(pageNum));
        if (snippetData && snippetData.text) {
          highlightTextInLayer(targetPage.querySelector('.textLayer'), snippetData.text);
        }
      }
    }
  }
});

function highlightTextInLayer(textLayer, snippetText) {
  if (!textLayer || !snippetText) return;

  // Basic normalization for matching
  const normalize = (s) => s.replace(/\s+/g, ' ').toLowerCase().trim();
  const searchStr = normalize(snippetText);

  // We'll search by combining the text nodes sequentially
  const textNodes = Array.from(textLayer.querySelectorAll('span'));

  // Clear old highlights in this layer
  textNodes.forEach(node => {
    if (node.innerHTML.includes('<mark>')) {
      node.innerHTML = node.textContent; // reset
    }
  });

  // Since text is fragmented across many <span> elements in PDF.js, 
  // we do a fuzzy search to find which spans contain the snippet words.
  // For simplicity, we'll mark any span whose text is significantly present in the snippet.
  const snippetWords = searchStr.split(' ').filter(w => w.length > 3);

  if (snippetWords.length === 0) return;

  textNodes.forEach(node => {
    const nodeText = normalize(node.textContent);
    if (!nodeText) return;

    // If the node text contains at least two meaningful words from the snippet, highlight it
    let matches = 0;
    for (const word of snippetWords) {
      if (nodeText.includes(word)) matches++;
    }

    // Threshold to prevent random partial word highlighting
    if (matches >= Math.min(2, snippetWords.length)) {
      node.innerHTML = `<mark>${node.textContent}</mark>`;
    }
  });
}

// ── Initialize Lucide icons ───────────────────────────────────────────────────
lucide.createIcons();

// ═════════════════════════════════════════════════════════════════════════════
// CHAT SUBMIT
// ═════════════════════════════════════════════════════════════════════════════
chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isPdfUploaded) return;

  const question = questionInput.value.trim();
  if (!question) return;

  appendMessage('user', question);
  questionInput.value = '';
  questionInput.disabled = true;
  sendBtn.disabled = true;
  thinkingPopup.classList.remove('hidden');
  scrollToBottom();

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (currentSessionId) headers['x-session-id'] = currentSessionId;

    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ question })
    });

    thinkingPopup.classList.add('hidden');

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Unknown error' }));
      appendMessage('assistant', `**Error:** ${err.error || 'Something went wrong'}`);
    } else {
      // Create streaming bubble with inline typing dots
      const welcome = chatBox.querySelector('.welcome-message');
      if (welcome) welcome.remove();

      const wrapper = document.createElement('div');
      wrapper.className = 'msg-wrapper assistant';
      const msgDiv = document.createElement('div');
      msgDiv.className = 'msg';
      msgDiv.innerHTML = '<div class="inline-typing"><span></span><span></span><span></span></div>';
      wrapper.appendChild(msgDiv);

      // Add copy button specifically for the streaming bot message
      const copyBtn = document.createElement('button');
      copyBtn.className = 'btn-copy-msg';
      copyBtn.innerHTML = '<i data-lucide="copy"></i>';
      wrapper.appendChild(copyBtn);

      chatBox.appendChild(wrapper);
      lucide.createIcons({ root: wrapper });
      scrollToBottom();

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let fullText = '';
      let buffer = '';
      let firstToken = true;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep last (potentially incomplete) line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6).trim());
            if (data.content) {
              if (firstToken) { msgDiv.innerHTML = ''; firstToken = false; }
              fullText += data.content;
              msgDiv.dataset.rawContent = fullText;
              msgDiv.innerHTML = marked.parse(fullText);
              scrollToBottom();
            } else if (data.sources_data) {
              // Store snippet data globally so the PDF renderer can highlight it
              window.currentSourcesData = data.sources_data;
            }
          } catch (_) { /* ignore partial chunks */ }
        }
      }

      // Update copy button raw content after stream finishes
      const existingCopyBtn = wrapper.querySelector('.btn-copy-msg');
      if (existingCopyBtn) {
        existingCopyBtn.onclick = () => {
          navigator.clipboard.writeText(fullText);
          existingCopyBtn.innerHTML = '<i data-lucide="check"></i>';
          setTimeout(() => {
            existingCopyBtn.innerHTML = '<i data-lucide="copy"></i>';
            lucide.createIcons({ root: existingCopyBtn });
          }, 2000);
          lucide.createIcons({ root: existingCopyBtn });
        };
      }
    }

    questionInput.disabled = false;
    sendBtn.disabled = false;
    questionInput.focus();

  } catch (err) {
    thinkingPopup.classList.add('hidden');
    questionInput.disabled = false;
    sendBtn.disabled = false;
    appendMessage('assistant', `**Error:** Network error — ${err.message}`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// TAB CLOSE & REFRESH CLEANUP
// ═════════════════════════════════════════════════════════════════════════════
window.addEventListener('beforeunload', () => {
  if (currentSessionId) {
    // keepalive ensures the request finishes even as the browser kills the page
    fetch(`${API_BASE_URL}/session/${currentSessionId}`, {
      method: 'DELETE',
      keepalive: true
    }).catch(() => { });
  }
});
