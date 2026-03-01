/**
 * GW 자동화 챗봇 - 프론트엔드 JS
 * 기능: 인증(로그인/회원가입), 채팅 UI, 파일 드래그앤드랍, 메시지 송수신
 */

// 상태 관리
const state = {
  sessionId: null,
  pendingFiles: [],   // [{name, type, data(base64), preview}]
  isLoading: false,
  currentUser: null,  // {gw_id, name, position, ...}
};

// DOM 요소 (채팅)
let dom = {};

// ===== 초기화 =====
async function init() {
  // 로그인 상태 확인
  await checkAuth();
}

// ===== 인증 관련 =====
async function checkAuth() {
  try {
    const res = await fetch('/auth/me', { credentials: 'same-origin' });
    if (res.ok) {
      const data = await res.json();
      state.currentUser = data.user;
      showMainApp();
    } else {
      showAuthScreen();
    }
  } catch (e) {
    showAuthScreen();
  }
}

function showAuthScreen() {
  document.getElementById('authContainer').style.display = 'flex';
  document.getElementById('mainApp').style.display = 'none';
  setupAuthEvents();
}

function showMainApp() {
  document.getElementById('authContainer').style.display = 'none';
  document.getElementById('mainApp').style.display = 'flex';
  setupChatDom();
  setupChatEvents();

  // 사용자 이름 표시
  if (state.currentUser) {
    document.getElementById('userName').textContent =
      `${state.currentUser.name}${state.currentUser.position ? ' ' + state.currentUser.position : ''}`;
    // 관리자면 관리 링크 표시
    if (state.currentUser.gw_id === 'tgjeon') {
      document.getElementById('adminLink').style.display = 'inline-block';
    }
  }

  // 세션 ID 생성
  if (!state.sessionId) {
    state.sessionId = generateId();
  }

  // 이전 대화 목록 로드
  loadSessions();
}

function setupAuthEvents() {
  // 탭 전환
  const loginTab = document.getElementById('loginTab');
  const registerTab = document.getElementById('registerTab');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');

  loginTab.addEventListener('click', () => {
    loginTab.classList.add('active');
    registerTab.classList.remove('active');
    loginForm.style.display = 'block';
    registerForm.style.display = 'none';
    clearAuthErrors();
  });

  registerTab.addEventListener('click', () => {
    registerTab.classList.add('active');
    loginTab.classList.remove('active');
    registerForm.style.display = 'block';
    loginForm.style.display = 'none';
    clearAuthErrors();
  });

  // 로그인 폼
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const gw_id = document.getElementById('loginId').value.trim();
    const gw_pw = document.getElementById('loginPw').value;
    const errorEl = document.getElementById('loginError');
    errorEl.textContent = '';

    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gw_id, gw_pw }),
        credentials: 'same-origin',
      });
      const data = await res.json();
      if (res.ok) {
        state.currentUser = data.user;
        showMainApp();
      } else {
        errorEl.textContent = data.detail || '로그인에 실패했습니다.';
      }
    } catch (err) {
      errorEl.textContent = '서버 연결에 실패했습니다.';
    }
  });

  // 회원가입 폼
  registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('regName').value.trim();
    const position = document.getElementById('regPosition').value.trim();
    const gw_id = document.getElementById('regId').value.trim();
    const gw_pw = document.getElementById('regPw').value;
    const errorEl = document.getElementById('registerError');
    errorEl.textContent = '';

    try {
      const res = await fetch('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gw_id, gw_pw, name, position }),
        credentials: 'same-origin',
      });
      const data = await res.json();
      if (res.ok) {
        // 회원가입 성공 → 자동 로그인
        const loginRes = await fetch('/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gw_id, gw_pw }),
          credentials: 'same-origin',
        });
        if (loginRes.ok) {
          const loginData = await loginRes.json();
          state.currentUser = loginData.user;
          showMainApp();
        } else {
          // 로그인 탭으로 전환
          document.getElementById('loginTab').click();
          document.getElementById('loginError').textContent = '가입 완료! 로그인해주세요.';
          document.getElementById('loginError').style.color = 'var(--accent)';
        }
      } else {
        errorEl.textContent = data.detail || '회원가입에 실패했습니다.';
      }
    } catch (err) {
      errorEl.textContent = '서버 연결에 실패했습니다.';
    }
  });
}

function clearAuthErrors() {
  document.getElementById('loginError').textContent = '';
  document.getElementById('registerError').textContent = '';
}

async function doLogout() {
  try {
    await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  } catch (e) { /* 무시 */ }
  state.currentUser = null;
  state.sessionId = null;
  showAuthScreen();
}

// ===== 채팅 DOM 초기화 =====
function setupChatDom() {
  dom = {
    messages: document.getElementById('messages'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    attachBtn: document.getElementById('attachBtn'),
    fileInput: document.getElementById('fileInput'),
    attachmentsPreview: document.getElementById('attachmentsPreview'),
    attachmentsList: document.getElementById('attachmentsList'),
    dropOverlay: document.getElementById('dropOverlay'),
    inputArea: document.getElementById('inputArea'),
    newChatBtn: document.getElementById('newChatBtn'),
    clearBtn: document.getElementById('clearBtn'),
    sidebarToggle: document.getElementById('sidebarToggle'),
    sidebar: document.querySelector('.sidebar'),
    logoutBtn: document.getElementById('logoutBtn'),
  };
}

function setupChatEvents() {
  dom.messageInput.addEventListener('input', onInputChange);
  dom.messageInput.addEventListener('keydown', onKeyDown);
  dom.sendBtn.addEventListener('click', sendMessage);
  dom.attachBtn.addEventListener('click', () => dom.fileInput.click());
  dom.fileInput.addEventListener('change', onFileSelect);
  dom.newChatBtn.addEventListener('click', newChat);
  dom.clearBtn.addEventListener('click', clearChat);
  dom.sidebarToggle.addEventListener('click', toggleSidebar);
  dom.logoutBtn.addEventListener('click', doLogout);

  // 빠른 실행 버튼
  document.querySelectorAll('.quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const msg = btn.dataset.msg;
      if (msg) {
        dom.messageInput.value = msg;
        onInputChange();
        sendMessage();
      }
      dom.sidebar.classList.remove('open');
    });
  });

  // 드래그앤드랍
  setupDragAndDrop();
}

// ===== 메시지 전송 =====
async function sendMessage() {
  if (state.isLoading) return;
  const text = dom.messageInput.value.trim();
  if (!text && state.pendingFiles.length === 0) return;

  // 입력 초기화
  const userMsg = text;
  const files = [...state.pendingFiles];
  dom.messageInput.value = '';
  dom.messageInput.style.height = 'auto';
  clearAttachments();
  updateSendBtn();

  // 사용자 메시지 표시
  appendMessage('user', userMsg, files);

  // 로딩 표시
  state.isLoading = true;
  const loadingEl = appendLoading();

  try {
    const payload = {
      message: userMsg,
      session_id: state.sessionId,
      files: files.map(f => ({ name: f.name, type: f.type, data: f.data })),
    };

    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'same-origin',
    });

    if (res.status === 401) {
      loadingEl.remove();
      appendMessage('error', '세션이 만료되었습니다. 다시 로그인해주세요.');
      setTimeout(() => doLogout(), 2000);
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `서버 오류 (${res.status})`);
    }

    const data = await res.json();

    // 세션 ID 업데이트
    if (data.session_id) state.sessionId = data.session_id;

    // 로딩 제거 후 응답 표시
    loadingEl.remove();
    appendMessage('bot', data.response, [], data.action, data.action_result);

    // 세션 목록 갱신
    loadSessions();

  } catch (err) {
    loadingEl.remove();
    appendMessage('error', `오류가 발생했습니다: ${err.message}`);
  } finally {
    state.isLoading = false;
    dom.messageInput.focus();
  }
}

// ===== 메시지 렌더링 =====
function appendMessage(role, text, files = [], action = null, actionResult = null) {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;

  const avatar = document.createElement('div');
  avatar.className = `avatar ${role === 'user' ? 'user-avatar' : 'bot-avatar'}`;
  avatar.textContent = role === 'user' ? (state.currentUser ? state.currentUser.name[0] : 'Me') : 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  // 첨부 이미지 (사용자 메시지)
  if (files && files.length > 0) {
    files.forEach(f => {
      if (f.type && f.type.startsWith('image/') && f.preview) {
        const img = document.createElement('img');
        img.src = f.preview;
        img.className = 'bubble-image';
        img.alt = f.name;
        bubble.appendChild(img);
      } else if (f.type === 'application/pdf') {
        const p = document.createElement('p');
        p.textContent = `\u{1F4CE} ${f.name}`;
        p.style.fontSize = '12px';
        p.style.color = 'rgba(255,255,255,0.7)';
        bubble.appendChild(p);
      }
    });
  }

  // 텍스트
  if (text) {
    const p = document.createElement('p');
    p.textContent = text;
    bubble.appendChild(p);
  }

  // 액션 카드 (봇 응답)
  if (action && actionResult) {
    const card = document.createElement('div');
    card.className = 'action-card';
    const label = document.createElement('div');
    label.className = 'action-label';
    label.textContent = getActionLabel(action);
    card.appendChild(label);
    const result = document.createElement('p');
    result.textContent = actionResult;
    card.appendChild(result);
    bubble.appendChild(card);
  }

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  dom.messages.appendChild(wrapper);

  scrollToBottom();
  return wrapper;
}

function appendLoading() {
  const wrapper = document.createElement('div');
  wrapper.className = 'message bot';

  const avatar = document.createElement('div');
  avatar.className = 'avatar bot-avatar';
  avatar.textContent = 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const dots = document.createElement('div');
  dots.className = 'loading-dots';
  for (let i = 0; i < 3; i++) {
    const s = document.createElement('span');
    dots.appendChild(s);
  }
  bubble.appendChild(dots);

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  dom.messages.appendChild(wrapper);
  scrollToBottom();
  return wrapper;
}

function getActionLabel(action) {
  const labels = {
    reserve_meeting_room: '회의실 예약',
    submit_expense_approval: '경비 결재',
    summarize_mail: '메일 요약',
    check_reservation_status: '예약 현황',
    check_available_rooms: '빈 회의실',
    cancel_meeting_reservation: '예약 취소',
  };
  return labels[action] || action;
}

// ===== 입력 처리 =====
function onInputChange() {
  dom.messageInput.style.height = 'auto';
  dom.messageInput.style.height = Math.min(dom.messageInput.scrollHeight, 160) + 'px';
  updateSendBtn();
}

function onKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!state.isLoading) sendMessage();
  }
}

function updateSendBtn() {
  const hasText = dom.messageInput.value.trim().length > 0;
  const hasFiles = state.pendingFiles.length > 0;
  dom.sendBtn.disabled = (!hasText && !hasFiles) || state.isLoading;
}

// ===== 파일 처리 =====
function onFileSelect(e) {
  const files = Array.from(e.target.files || []);
  processFiles(files);
  e.target.value = '';
}

async function processFiles(files) {
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'];
  const MAX_SIZE = 10 * 1024 * 1024;

  for (const file of files) {
    if (!allowed.includes(file.type)) {
      alert(`'${file.name}'은(는) 지원하지 않는 파일 형식입니다.\n(JPG, PNG, GIF, WebP, PDF 지원)`);
      continue;
    }
    if (file.size > MAX_SIZE) {
      alert(`'${file.name}'의 크기가 10MB를 초과합니다.`);
      continue;
    }

    try {
      const { data, preview } = await readFileAsBase64(file);
      state.pendingFiles.push({
        name: file.name,
        type: file.type,
        data,
        preview,
      });
    } catch (err) {
      console.error('파일 읽기 오류:', err);
    }
  }

  renderAttachments();
  updateSendBtn();
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target.result;
      const base64 = dataUrl.split(',')[1];
      const preview = file.type.startsWith('image/') ? dataUrl : null;
      resolve({ data: base64, preview });
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function renderAttachments() {
  dom.attachmentsList.innerHTML = '';

  if (state.pendingFiles.length === 0) {
    dom.attachmentsPreview.style.display = 'none';
    return;
  }

  dom.attachmentsPreview.style.display = 'block';

  state.pendingFiles.forEach((f, idx) => {
    const item = document.createElement('div');
    item.className = 'attachment-item';

    if (f.preview) {
      const img = document.createElement('img');
      img.src = f.preview;
      img.className = 'attachment-thumb';
      img.alt = f.name;
      item.appendChild(img);
    } else {
      const icon = document.createElement('div');
      icon.className = 'attachment-icon';
      icon.textContent = '\u{1F4C4}';
      item.appendChild(icon);
    }

    const name = document.createElement('span');
    name.className = 'attachment-name';
    name.textContent = f.name;
    item.appendChild(name);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'attachment-remove';
    removeBtn.textContent = '\u00D7';
    removeBtn.title = '제거';
    removeBtn.addEventListener('click', () => {
      state.pendingFiles.splice(idx, 1);
      renderAttachments();
      updateSendBtn();
    });
    item.appendChild(removeBtn);

    dom.attachmentsList.appendChild(item);
  });
}

function clearAttachments() {
  state.pendingFiles = [];
  if (dom.attachmentsList) dom.attachmentsList.innerHTML = '';
  if (dom.attachmentsPreview) dom.attachmentsPreview.style.display = 'none';
}

// ===== 드래그앤드랍 =====
function setupDragAndDrop() {
  let dragCounter = 0;

  document.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragCounter++;
    if (dragCounter === 1) {
      dom.dropOverlay.classList.add('active');
    }
  });

  document.addEventListener('dragleave', (e) => {
    dragCounter--;
    if (dragCounter === 0) {
      dom.dropOverlay.classList.remove('active');
    }
  });

  document.addEventListener('dragover', (e) => {
    e.preventDefault();
  });

  document.addEventListener('drop', (e) => {
    e.preventDefault();
    dragCounter = 0;
    dom.dropOverlay.classList.remove('active');

    const files = Array.from(e.dataTransfer.files || []);
    if (files.length > 0) {
      processFiles(files);
    }
  });
}

// ===== 유틸 =====
function scrollToBottom() {
  requestAnimationFrame(() => {
    dom.messages.scrollTop = dom.messages.scrollHeight;
  });
}

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// ===== 새 대화 / 초기화 =====
function newChat() {
  clearSession();
  dom.messages.innerHTML = '';
  const userName = state.currentUser ? state.currentUser.name : '';
  appendMessage('bot',
    `${userName}님, 새 대화가 시작되었습니다.\n회의실 예약, 경비 결재, 메일 요약 등을 도와드릴게요.`
  );
  loadSessions();
}

async function clearChat() {
  if (!confirm('대화를 초기화하시겠습니까?')) return;

  try {
    if (state.sessionId) {
      await fetch(`/history/${state.sessionId}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
    }
  } catch (e) { /* 무시 */ }

  clearSession();
  dom.messages.innerHTML = '';
  appendMessage('bot',
    '대화가 초기화되었습니다.\n무엇을 도와드릴까요?'
  );
}

function clearSession() {
  state.sessionId = generateId();
  clearAttachments();
  if (dom.messageInput) {
    dom.messageInput.value = '';
    dom.messageInput.style.height = 'auto';
  }
  updateSendBtn();
}

// ===== 사이드바 토글 (모바일) =====
function toggleSidebar() {
  dom.sidebar.classList.toggle('open');
}

// 사이드바 외부 클릭 시 닫기
document.addEventListener('click', (e) => {
  const sidebar = document.querySelector('.sidebar');
  const toggle = document.getElementById('sidebarToggle');
  if (
    sidebar &&
    sidebar.classList.contains('open') &&
    !sidebar.contains(e.target) &&
    e.target !== toggle
  ) {
    sidebar.classList.remove('open');
  }
});

// ===== 세션 목록 관리 =====

/** 서버에서 세션 목록을 가져와 사이드바에 표시 */
async function loadSessions() {
  const listEl = document.getElementById('historyList');
  if (!listEl) return;

  try {
    const res = await fetch('/sessions', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    const sessions = data.sessions || [];

    listEl.innerHTML = '';

    sessions.forEach(s => {
      const item = document.createElement('div');
      item.className = 'history-item' + (s.session_id === state.sessionId ? ' active' : '');
      item.dataset.session = s.session_id;

      // 제목: 세션 title 또는 마지막 메시지 미리보기
      const titleEl = document.createElement('div');
      titleEl.className = 'history-title';
      const displayTitle = s.title || (s.last_message ? s.last_message.substring(0, 40) : '새 대화');
      titleEl.textContent = displayTitle;
      item.appendChild(titleEl);

      // 시간 표시
      const timeEl = document.createElement('div');
      timeEl.className = 'history-time';
      timeEl.textContent = formatSessionTime(s.updated_at || s.created_at);
      item.appendChild(timeEl);

      // 삭제 버튼
      const delBtn = document.createElement('button');
      delBtn.className = 'history-delete';
      delBtn.title = '삭제';
      delBtn.innerHTML = '&times;';
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(s.session_id);
      });
      item.appendChild(delBtn);

      // 세션 클릭 시 로드
      item.addEventListener('click', () => {
        loadSession(s.session_id);
      });

      listEl.appendChild(item);
    });
  } catch (e) {
    console.error('세션 목록 로드 오류:', e);
  }
}

/** 특정 세션의 히스토리를 로드하여 채팅 영역에 표시 */
async function loadSession(sessionId) {
  try {
    const res = await fetch(`/history/${sessionId}`, { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    const history = data.history || [];

    // 세션 전환
    state.sessionId = sessionId;
    clearAttachments();

    // 채팅 영역 초기화 후 히스토리 표시
    dom.messages.innerHTML = '';

    if (history.length === 0) {
      const userName = state.currentUser ? state.currentUser.name : '';
      appendMessage('bot', `${userName}님, 무엇을 도와드릴까요?`);
    } else {
      history.forEach(msg => {
        if (msg.role === 'user') {
          appendMessage('user', msg.content);
        } else if (msg.role === 'assistant') {
          appendMessage('bot', msg.content, [], msg.action || null, msg.action_result || null);
        }
      });
    }

    // 사이드바 활성 표시 갱신
    loadSessions();

    // 모바일에서 사이드바 닫기
    if (dom.sidebar) dom.sidebar.classList.remove('open');
  } catch (e) {
    console.error('세션 로드 오류:', e);
  }
}

/** 세션 삭제 */
async function deleteSession(sessionId) {
  if (!confirm('이 대화를 삭제하시겠습니까?')) return;

  try {
    await fetch(`/history/${sessionId}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });

    // 현재 세션이 삭제되면 새 대화 시작
    if (state.sessionId === sessionId) {
      newChat();
    } else {
      loadSessions();
    }
  } catch (e) {
    console.error('세션 삭제 오류:', e);
  }
}

/** 세션 시간을 사람이 읽기 좋은 형식으로 변환 */
function formatSessionTime(dateStr) {
  if (!dateStr) return '';
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHour = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return '방금';
    if (diffMin < 60) return `${diffMin}분 전`;
    if (diffHour < 24) return `${diffHour}시간 전`;
    if (diffDay < 7) return `${diffDay}일 전`;

    // 날짜 표시
    const month = date.getMonth() + 1;
    const day = date.getDate();
    return `${month}월 ${day}일`;
  } catch (e) {
    return '';
  }
}

// ===== 시작 =====
init();
