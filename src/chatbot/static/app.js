/**
 * GW 자동화 챗봇 - 프론트엔드 JS
 * 기능: 인증(로그인/회원가입), 채팅 UI, 파일 드래그앤드랍, 메시지 송수신
 */

// ===== CSRF 토큰 유틸리티 =====
function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}
async function safeFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    options.headers = options.headers || {};
    if (options.headers instanceof Headers) {
      options.headers.set('X-CSRF-Token', getCsrfToken());
    } else {
      options.headers['X-CSRF-Token'] = getCsrfToken();
    }
  }
  return fetch(url, options);
}

// 상태 관리
const state = {
  sessionId: null,
  pendingFiles: [],        // [{name, type, data(base64), preview}]  이미지/PDF
  pendingAttachPath: null, // XLSX 등 /upload 후 받은 attachment_token
  pendingAttachName: null, // 표시용 파일명
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
    const res = await safeFetch('/auth/me', { credentials: 'same-origin' });
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
    // 관리자면 관리 링크 표시 (서버 is_admin 필드 기준)
    if (state.currentUser.is_admin) {
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
      const res = await safeFetch('/auth/login', {
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
      const res = await safeFetch('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gw_id, gw_pw, name, position }),
        credentials: 'same-origin',
      });
      const data = await res.json();
      if (res.ok) {
        // 회원가입 성공 → 자동 로그인
        const loginRes = await safeFetch('/auth/login', {
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
    await safeFetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
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
  const attachPath = state.pendingAttachPath;
  const attachName = state.pendingAttachName;
  dom.messageInput.value = '';
  dom.messageInput.style.height = 'auto';
  clearAttachments();
  updateSendBtn();

  // 사용자 메시지 표시 (XLSX 첨부 포함)
  const displayFiles = attachName
    ? [...files, { name: attachName, type: 'application/xlsx', preview: null }]
    : files;
  appendMessage('user', userMsg, displayFiles);

  // 로딩 표시
  state.isLoading = true;
  const loadingEl = appendLoading();

  try {
    const payload = {
      message: userMsg,
      session_id: state.sessionId,
      files: files.map(f => ({ name: f.name, type: f.type, data: f.data })),
    };
    if (attachPath) {
      payload.attachment_token = attachPath;
    }
    // 오디오 파일의 토큰도 attachment_token으로 전달
    const audioFile = files.find(f => f.isAudio && f.audioToken);
    if (audioFile && !payload.attachment_token) {
      payload.attachment_token = audioFile.audioToken;
    }

    const res = await safeFetch('/chat', {
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

    // CSRF 토큰 만료 시 자동 복구: /auth/me 호출로 쿠키 재설정 후 재시도
    if (res.status === 403) {
      const errData = await res.json().catch(() => ({}));
      if (errData.detail && errData.detail.includes('CSRF')) {
        await fetch('/auth/me', { credentials: 'same-origin' });
        const retryRes = await safeFetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          credentials: 'same-origin',
        });
        if (retryRes.ok) {
          const retryData = await retryRes.json();
          if (retryData.session_id) state.sessionId = retryData.session_id;
          loadingEl.remove();
          appendMessage('bot', retryData.response, [], retryData.action, retryData.action_result);
          loadSessions();
          return;
        }
      }
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

  // 첨부 파일 (사용자 메시지)
  if (files && files.length > 0) {
    files.forEach(f => {
      if (f.type && f.type.startsWith('image/') && f.preview) {
        const img = document.createElement('img');
        img.src = f.preview;
        img.className = 'bubble-image';
        img.alt = f.name;
        bubble.appendChild(img);
      } else if (f.name) {
        const icon = f.type === 'application/pdf' ? '📎' : '📊';
        const p = document.createElement('p');
        p.textContent = `${icon} ${f.name}`;
        p.style.fontSize = '12px';
        p.style.color = 'rgba(255,255,255,0.7)';
        bubble.appendChild(p);
      }
    });
  }

  // 텍스트 (봇 메시지: /download/ 링크를 클릭 가능한 다운로드 버튼으로 변환)
  if (text) {
    if (role === 'bot') {
      renderBotText(bubble, text);
    } else {
      const p = document.createElement('p');
      p.textContent = text;
      bubble.appendChild(p);
    }
  }

  // 액션 카드 (봇 응답) — response가 이미 도구 결과를 포함하면 숨김
  if (action && actionResult && text) {
    // Gemini가 도구 결과를 자연어로 재가공하여 response에 포함하므로
    // action_result를 접을 수 있는 상세 영역으로만 표시
    const details = document.createElement('details');
    details.className = 'action-card';
    const summary = document.createElement('summary');
    summary.className = 'action-label';
    summary.textContent = getActionLabel(action);
    summary.style.cursor = 'pointer';
    details.appendChild(summary);
    const result = document.createElement('p');
    result.textContent = actionResult;
    details.appendChild(result);
    bubble.appendChild(details);
  } else if (action && actionResult) {
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

/**
 * 봇 메시지 텍스트 렌더링
 * - [텍스트](/download/파일명) 형식 → <a download> 버튼으로 변환
 * - 나머지 텍스트는 줄 단위로 <p> 렌더링
 */
function renderBotText(container, text) {
  // markdown 링크 패턴: [label](url)
  const linkPattern = /\[([^\]]+)\]\((\/download\/[^)]+)\)/g;
  const lines = text.split('\n');

  lines.forEach(line => {
    if (!line.trim()) {
      // 빈 줄 → 약간의 여백
      const br = document.createElement('div');
      br.style.height = '4px';
      container.appendChild(br);
      return;
    }

    // 줄 안에 /download/ 링크가 있는지 확인
    if (linkPattern.test(line)) {
      linkPattern.lastIndex = 0;
      const wrap = document.createElement('div');
      wrap.style.margin = '4px 0';

      let lastIdx = 0;
      let match;
      linkPattern.lastIndex = 0;
      while ((match = linkPattern.exec(line)) !== null) {
        // 링크 앞 텍스트
        if (match.index > lastIdx) {
          const span = document.createElement('span');
          span.textContent = line.slice(lastIdx, match.index);
          wrap.appendChild(span);
        }
        // 다운로드 버튼
        const a = document.createElement('a');
        a.href = match[2];
        a.download = match[2].split('/').pop();
        a.textContent = match[1];
        a.className = 'download-btn';
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        wrap.appendChild(a);
        lastIdx = match.index + match[0].length;
      }
      // 링크 뒤 텍스트
      if (lastIdx < line.length) {
        const span = document.createElement('span');
        span.textContent = line.slice(lastIdx);
        wrap.appendChild(span);
      }
      container.appendChild(wrap);
    } else {
      const p = document.createElement('p');
      p.textContent = line;
      container.appendChild(p);
    }
  });
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
    // 회의실
    reserve_meeting_room: '회의실 예약',
    cancel_meeting_reservation: '예약 취소',
    check_reservation_status: '예약 현황',
    check_available_rooms: '빈 회의실',
    list_my_reservations: '내 예약 목록',
    cleanup_test_reservations: '테스트 예약 정리',
    // 전자결재
    submit_expense_approval: '지출결의서 작성',
    submit_draft_approval: '임시보관 상신',
    submit_approval_form: '전자결재 작성',
    start_approval_wizard: '전자결재 위저드',
    search_project_code: '프로젝트 코드 검색',
    add_cc_to_approval_doc: '수신참조 추가',
    // 계약서
    start_contract_wizard: '계약서 작성 위저드',
    generate_contracts_from_file: '계약서 일괄 생성',
    // 메일
    get_mail_summary: '메일 요약',
    summarize_mail: '메일 요약',
    // 음성
    transcribe_audio: '음성 변환',
    // 프로젝트 관리
    get_fund_summary: '프로젝트 자금현황',
    get_project_detail: '프로젝트 상세',
    compare_projects: '포트폴리오 비교',
    generate_project_report: '프로젝트 보고서',
    update_project_info: '프로젝트 정보 수정',
    add_project_note: '프로젝트 메모 추가',
    add_project_subcontract: '하도급 업체 추가',
    update_collection_status: '수금 상태 변경',
    add_project_todo: 'TODO 추가',
    add_project_contact: '연락처 추가',
    get_overdue_items: '미결 항목 조회',
    update_project_milestone: '마일스톤 업데이트',
    // 위저드 (내부)
    contract_wizard: '계약서 위저드',
    approval_wizard: '전자결재 위저드',
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
  const allowedBase64 = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'];
  const allowedUpload = [
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
  ];
  const audioTypes = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/mp4', 'audio/x-m4a', 'audio/m4a',
    'audio/ogg', 'audio/flac', 'audio/x-flac', 'audio/webm',
  ];
  const audioExts = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.webm'];
  const MAX_SIZE_BASE64 = 10 * 1024 * 1024;
  const MAX_SIZE_UPLOAD = 20 * 1024 * 1024;

  for (const file of files) {
    const isXlsx = file.name.toLowerCase().endsWith('.xlsx') || allowedUpload.includes(file.type);
    const fileExt = '.' + file.name.split('.').pop().toLowerCase();
    const isAudio = audioTypes.includes(file.type) || audioExts.includes(fileExt);

    if (isAudio) {
      // 오디오 → /upload 엔드포인트로 전송, STT 처리
      if (file.size > MAX_SIZE_UPLOAD) {
        alert(`'${file.name}'의 크기가 20MB를 초과합니다.`);
        continue;
      }
      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await safeFetch('/upload', {
          method: 'POST',
          body: formData,
          credentials: 'same-origin',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(`파일 업로드 실패: ${err.detail || res.status}`);
          continue;
        }
        const data = await res.json();
        // 오디오 파일 정보를 pendingFiles에 추가 (미리보기는 아이콘)
        state.pendingFiles.push({
          name: file.name,
          type: file.type || 'audio/mpeg',
          data: null,
          preview: null,
          isAudio: true,
          audioToken: data.audio_token || data.attachment_token,
        });
      } catch (err) {
        console.error('오디오 업로드 오류:', err);
        alert('오디오 파일 업로드 중 오류가 발생했습니다.');
      }
    } else if (isXlsx) {
      // XLSX → /upload 엔드포인트로 전송, attachment_token 저장
      if (file.size > MAX_SIZE_UPLOAD) {
        alert(`'${file.name}'의 크기가 20MB를 초과합니다.`);
        continue;
      }
      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await safeFetch('/upload', {
          method: 'POST',
          body: formData,
          credentials: 'same-origin',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(`파일 업로드 실패: ${err.detail || res.status}`);
          continue;
        }
        const data = await res.json();
        state.pendingAttachPath = data.attachment_token;
        state.pendingAttachName = file.name;
      } catch (err) {
        console.error('XLSX 업로드 오류:', err);
        alert('파일 업로드 중 오류가 발생했습니다.');
      }
    } else if (allowedBase64.includes(file.type)) {
      if (file.size > MAX_SIZE_BASE64) {
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
    } else {
      alert(`'${file.name}'은(는) 지원하지 않는 파일 형식입니다.\n(JPG, PNG, GIF, WebP, PDF, XLSX, MP3, WAV, M4A 지원)`);
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

  const hasFiles = state.pendingFiles.length > 0 || state.pendingAttachPath;
  if (!hasFiles) {
    dom.attachmentsPreview.style.display = 'none';
    return;
  }

  dom.attachmentsPreview.style.display = 'block';

  // 이미지/PDF 파일
  state.pendingFiles.forEach((f, idx) => {
    const item = document.createElement('div');
    item.className = 'attachment-item';

    if (f.isAudio) {
      const icon = document.createElement('div');
      icon.className = 'attachment-icon';
      icon.textContent = '\u{1F3A4}';
      item.appendChild(icon);
    } else if (f.preview) {
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

  // XLSX 파일 (attachment_token 방식)
  if (state.pendingAttachPath) {
    const item = document.createElement('div');
    item.className = 'attachment-item';

    const icon = document.createElement('div');
    icon.className = 'attachment-icon';
    icon.textContent = '\u{1F4CA}';  // 📊
    item.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'attachment-name';
    name.textContent = state.pendingAttachName || 'Excel 파일';
    item.appendChild(name);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'attachment-remove';
    removeBtn.textContent = '\u00D7';
    removeBtn.title = '제거';
    removeBtn.addEventListener('click', () => {
      state.pendingAttachPath = null;
      state.pendingAttachName = null;
      renderAttachments();
      updateSendBtn();
    });
    item.appendChild(removeBtn);

    dom.attachmentsList.appendChild(item);
  }
}

function clearAttachments() {
  state.pendingFiles = [];
  state.pendingAttachPath = null;
  state.pendingAttachName = null;
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
      await safeFetch(`/history/${state.sessionId}`, {
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
    const res = await safeFetch('/sessions', { credentials: 'same-origin' });
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
    const res = await safeFetch(`/history/${sessionId}`, { credentials: 'same-origin' });
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
    await safeFetch(`/history/${sessionId}`, {
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
