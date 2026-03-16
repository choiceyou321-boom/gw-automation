/**
 * 자금관리 프론트엔드 (fund.js)
 * - 프로젝트 자금관리표 & 거래처현황
 */

// ===== 전역 상태 =====
let currentUser = null;
let currentProjectId = null;
let currentTab = 'dashboard';
let projectsCache = [];
let tradesCache = [];

// ===== 초기화 =====
document.addEventListener('DOMContentLoaded', async () => {
  await checkAuth();
  await loadProjects();
  bindEvents();
});

// ===== 인증 확인 =====
async function checkAuth() {
  try {
    const res = await fetch('/auth/me');
    if (!res.ok) throw new Error('인증 실패');
    const data = await res.json();
    currentUser = data.user || data;
    // 사용자 정보 표시
    const name = currentUser.name || currentUser.gw_id || '--';
    document.getElementById('headerUserName').textContent = name;
    document.getElementById('sidebarUserName').textContent = name;
    document.getElementById('userBadge').textContent = name.charAt(0);
  } catch (e) {
    // 인증 실패 시 챗봇 로그인으로 리다이렉트
    window.location.href = '/';
  }
}

// ===== 이벤트 바인딩 =====
function bindEvents() {
  // 새 프로젝트
  document.getElementById('newProjectBtn').addEventListener('click', createProject);

  // 로그아웃
  document.getElementById('logoutBtn').addEventListener('click', async () => {
    await fetch('/auth/logout', { method: 'POST' });
    window.location.href = '/';
  });

  // 탭 전환
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  // 사이드바 토글 (모바일)
  document.getElementById('sidebarToggle').addEventListener('click', () => {
    document.querySelector('.fund-sidebar').classList.toggle('open');
  });

  // 하도급 행 추가
  document.getElementById('addSubcontractBtn').addEventListener('click', addSubcontractRow);
  document.getElementById('saveSubcontractsBtn').addEventListener('click', saveSubcontracts);

  // 개요 저장/인원추가
  document.getElementById('saveOverviewBtn').addEventListener('click', saveOverview);
  document.getElementById('addMemberBtn').addEventListener('click', addMemberRow);

  // 수금현황 저장
  document.getElementById('saveCollectionsBtn').addEventListener('click', saveCollections);

  // 연락처 추가
  document.getElementById('addContactBtn').addEventListener('click', () => openContactModal());

  // 이체내역/예실 새로고침
  document.getElementById('refreshPaymentsBtn').addEventListener('click', () => loadPayments(currentProjectId));
  document.getElementById('refreshBudgetBtn').addEventListener('click', () => loadBudget(currentProjectId));

  // 모달 닫기
  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalCancelBtn').addEventListener('click', closeModal);
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
}

// ===== 프로젝트 목록 =====
async function loadProjects() {
  try {
    const res = await fetch('/api/fund/projects');
    if (!res.ok) throw new Error('프로젝트 목록 조회 실패');
    const data = await res.json();
    projectsCache = data.projects || [];
    renderProjectList();
  } catch (e) {
    showToast(e.message, 'error');
    projectsCache = [];
    renderProjectList();
  }
}

// 등급별 색상 매핑
const GRADE_COLORS = {
  '1등급': { bg: '#ef444422', color: '#ef4444', label: '1' },
  '2등급': { bg: '#f59e0b22', color: '#f59e0b', label: '2' },
  '3등급': { bg: '#3b82f622', color: '#3b82f6', label: '3' },
  '4등급': { bg: '#6b728022', color: '#6b7280', label: '4' },
};

function renderProjectList() {
  const list = document.getElementById('projectList');
  const empty = document.getElementById('emptyProjects');

  if (projectsCache.length === 0) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }

  empty.style.display = 'none';
  list.innerHTML = projectsCache.map(p => {
    const gc = GRADE_COLORS[p.grade] || null;
    const gradeBadge = gc
      ? `<span class="grade-badge" style="background:${gc.bg};color:${gc.color};" title="${p.grade}">${gc.label}</span>`
      : '';
    return `
    <li class="project-item ${p.id === currentProjectId ? 'active' : ''}"
        data-id="${p.id}" draggable="true"
        ondragstart="onProjectDragStart(event)" ondragover="onProjectDragOver(event)"
        ondrop="onProjectDrop(event)" ondragend="onProjectDragEnd(event)"
        onclick="selectProject(${p.id})">
      ${gradeBadge}
      <span class="project-name">${escapeHtml(p.name)}</span>
      <button class="project-delete" onclick="event.stopPropagation(); deleteProject(${p.id})"
              title="프로젝트 삭제">&times;</button>
    </li>`;
  }).join('');
}

// ===== 프로젝트 드래그 정렬 =====
let dragProjectId = null;

function onProjectDragStart(e) {
  dragProjectId = parseInt(e.currentTarget.dataset.id);
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onProjectDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const target = e.currentTarget;
  if (!target.classList.contains('drag-over')) {
    document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
    target.classList.add('drag-over');
  }
}

function onProjectDrop(e) {
  e.preventDefault();
  const targetId = parseInt(e.currentTarget.dataset.id);
  document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
  if (dragProjectId === targetId) return;

  // 순서 변경
  const fromIdx = projectsCache.findIndex(p => p.id === dragProjectId);
  const toIdx = projectsCache.findIndex(p => p.id === targetId);
  if (fromIdx < 0 || toIdx < 0) return;
  const [moved] = projectsCache.splice(fromIdx, 1);
  projectsCache.splice(toIdx, 0, moved);
  renderProjectList();
  saveProjectOrder();
}

function onProjectDragEnd(e) {
  e.currentTarget.classList.remove('dragging');
  document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
  dragProjectId = null;
}

async function saveProjectOrder() {
  const order = projectsCache.map(p => ({ id: p.id }));
  try {
    await fetch('/api/fund/projects/reorder', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order })
    });
  } catch (e) {
    // 순서 저장 실패 시 무시
  }
}

// ===== 프로젝트 선택 =====
async function selectProject(id) {
  currentProjectId = id;
  renderProjectList();

  const project = projectsCache.find(p => p.id === id);
  if (project) {
    document.getElementById('pageTitle').textContent = project.name;
  }

  // 탭 바 표시
  document.getElementById('tabBar').style.display = 'flex';
  document.getElementById('emptyState').style.display = 'none';

  // 공종 캐시 로드
  await loadTradesCache(id);

  // 현재 탭 로드
  switchTab(currentTab);
}

// ===== 프로젝트 생성 =====
function createProject() {
  openModal('새 프로젝트', `
    <div class="form-group">
      <label>프로젝트명</label>
      <input type="text" id="modalProjectName" placeholder="예: OO아파트 신축공사" />
    </div>
    <div class="form-group">
      <label>등급</label>
      <select id="modalProjectGrade">
        <option value="">-- 선택 --</option>
        <option value="1등급">1등급 (당사 직영/ETF, 확장 가능성)</option>
        <option value="2등급">2등급 (KOM, 2~3차 보고, 결과 보고)</option>
        <option value="3등급">3등급 (KOM, 2차 보고, 결과 보고)</option>
        <option value="4등급">4등급</option>
      </select>
    </div>
    <div class="form-group">
      <label>수주액 (원)</label>
      <input type="number" id="modalContractAmt" placeholder="0" />
    </div>
    <div class="form-group">
      <label>실행예산 (원)</label>
      <input type="number" id="modalBudgetAmt" placeholder="0" />
    </div>
  `, async () => {
    const name = document.getElementById('modalProjectName').value.trim();
    if (!name) {
      showToast('프로젝트명을 입력하세요.', 'error');
      return;
    }
    const grade = document.getElementById('modalProjectGrade').value;
    const constructionAmount = parseInt(document.getElementById('modalContractAmt').value) || 0;
    const executionBudget = parseInt(document.getElementById('modalBudgetAmt').value) || 0;

    try {
      const res = await fetch('/api/fund/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, grade, construction_amount: constructionAmount, execution_budget: executionBudget })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || '프로젝트 생성 실패');
      }
      const data = await res.json();
      closeModal();
      showToast('프로젝트가 생성되었습니다.', 'success');
      await loadProjects();
      if (data.id) selectProject(data.id);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  // 포커스
  setTimeout(() => document.getElementById('modalProjectName')?.focus(), 100);
}

// ===== 프로젝트 삭제 =====
async function deleteProject(id) {
  const project = projectsCache.find(p => p.id === id);
  const name = project ? project.name : '이 프로젝트';
  if (!confirm(`"${name}" 프로젝트를 삭제하시겠습니까?\n\n관련 데이터가 모두 삭제됩니다.`)) return;

  try {
    const res = await fetch(`/api/fund/projects/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('프로젝트 삭제 실패');

    showToast('프로젝트가 삭제되었습니다.', 'success');
    if (currentProjectId === id) {
      currentProjectId = null;
      document.getElementById('pageTitle').textContent = '프로젝트를 선택하세요';
      document.getElementById('tabBar').style.display = 'none';
      hideAllPanels();
      document.getElementById('emptyState').style.display = 'flex';
    }
    await loadProjects();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 탭 전환 =====
function switchTab(tabName) {
  currentTab = tabName;

  // 탭 UI 업데이트
  document.querySelectorAll('.tab-item').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tabName);
  });

  // 패널 표시/숨김
  hideAllPanels();
  const panel = document.getElementById(`panel-${tabName}`);
  if (panel) panel.style.display = 'block';

  // 탭별 데이터 로드
  if (!currentProjectId) return;
  switch (tabName) {
    case 'dashboard':    loadDashboard(currentProjectId); break;
    case 'overview':     loadOverview(currentProjectId); break;
    case 'collections':  loadCollections(currentProjectId); break;
    case 'subcontracts': loadSubcontracts(currentProjectId); break;
    case 'contacts':     loadContacts(currentProjectId); break;
    case 'payments':     loadPayments(currentProjectId); break;
    case 'budget':       loadBudget(currentProjectId); break;
  }
}

function hideAllPanels() {
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
}

// ===== 공종 캐시 =====
async function loadTradesCache(projectId) {
  try {
    const res = await fetch(`/api/fund/projects/${projectId}/trades`);
    if (!res.ok) throw new Error('공종 조회 실패');
    const data = await res.json();
    tradesCache = data.trades || [];
  } catch (e) {
    tradesCache = [];
  }
}

// ===== 대시보드 탭 =====
async function loadDashboard(projectId) {
  try {
    // 요약 API 호출
    const res = await fetch(`/api/fund/projects/${projectId}/summary`);
    if (!res.ok) throw new Error('대시보드 조회 실패');
    const data = await res.json();
    const s = data.summary || data;

    // 요약 카드
    const totalOrder = (s.design_amount || 0) + (s.construction_amount || 0);
    document.getElementById('valContract').textContent = formatWon(s.total_order || totalOrder);
    document.getElementById('valBudget').textContent = formatWon(s.execution_budget || 0);
    document.getElementById('valProfit').textContent = formatWon(s.profit_amount || 0);
    document.getElementById('valMargin').textContent = (s.profit_rate || 0).toFixed(1) + '%';

    // 수금현황 요약
    const collRes = await fetch(`/api/fund/projects/${projectId}/collections`);
    const collData = collRes.ok ? await collRes.json() : { collections: [] };
    const colls = collData.collections || [];
    let collTotal = 0, collCollected = 0;
    colls.forEach(c => {
      collTotal += (c.amount || 0);
      if (c.collected) collCollected += (c.amount || 0);
    });
    document.getElementById('valDashCollected').textContent = formatWon(collCollected);
    const collRate = collTotal ? (collCollected / collTotal * 100) : 0;
    document.getElementById('valDashCollectionRate').textContent = collRate.toFixed(1) + '%';

    // 공종별 지급현황 — 하도급 데이터에서 공종별 집계
    const subRes = await fetch(`/api/fund/projects/${projectId}/subcontracts`);
    const subData = subRes.ok ? await subRes.json() : { subcontracts: [] };
    const subs = subData.subcontracts || [];

    // 업체별 개별 행 표시 (공종 포함)
    const tbody = document.getElementById('dashTradeBody');
    if (subs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="no-data">등록된 하도급 업체가 없습니다.</td></tr>';
    } else {
      tbody.innerHTML = subs.map(sc => {
        const contract = sc.contract_amount || 0;
        let paid = 0;
        if (sc.payment_1_confirmed) paid += (sc.payment_1 || 0);
        if (sc.payment_2_confirmed) paid += (sc.payment_2 || 0);
        if (sc.payment_3_confirmed) paid += (sc.payment_3 || 0);
        if (sc.payment_4_confirmed) paid += (sc.payment_4 || 0);
        const remaining = contract - paid;
        const pct = contract ? (paid / contract * 100) : 0;
        return `<tr>
          <td>${escapeHtml(sc.trade_name || '미분류')}</td>
          <td>${escapeHtml(sc.company_name || '-')}</td>
          <td class="num">${formatWon(contract)}</td>
          <td class="num">${formatWon(paid)}</td>
          <td class="num">${formatWon(remaining)}</td>
          <td class="num">${renderPctBar(pct)}</td>
        </tr>`;
      }).join('');
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 개요 탭 =====
async function loadOverview(projectId) {
  try {
    const res = await fetch(`/api/fund/projects/${projectId}/overview`);
    if (!res.ok) throw new Error('개요 조회 실패');
    const data = await res.json();
    const ov = data.overview || {};

    // 필드 채우기
    document.querySelectorAll('.ov-field').forEach(el => {
      const field = el.dataset.field;
      if (!field || ov[field] === undefined) return;
      if (el.type === 'checkbox') {
        el.checked = !!ov[field];
      } else if (el.tagName === 'SELECT') {
        el.value = ov[field] || '';
      } else {
        el.value = ov[field] || '';
      }
    });

    // 진행상황 체크리스트
    renderMilestones(ov.milestones || []);

    // 배정인원
    renderMembers(ov.members || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderMembers(members) {
  const tbody = document.getElementById('memberBody');
  if (members.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="no-data">배정인원 없음</td></tr>';
    return;
  }
  tbody.innerHTML = members.map(m => `
    <tr>
      <td><input type="text" class="member-field" data-field="role" value="${escapeHtml(m.role || '')}" placeholder="역할" /></td>
      <td><input type="text" class="member-field" data-field="name" value="${escapeHtml(m.name || '')}" placeholder="담당자" /></td>
      <td><button class="btn-icon" onclick="this.closest('tr').remove()" title="삭제">&times;</button></td>
    </tr>
  `).join('');
}

function addMemberRow() {
  const tbody = document.getElementById('memberBody');
  const noData = tbody.querySelector('.no-data');
  if (noData) noData.parentElement.remove();
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="member-field" data-field="role" value="" placeholder="역할" /></td>
    <td><input type="text" class="member-field" data-field="name" value="" placeholder="담당자" /></td>
    <td><button class="btn-icon" onclick="this.closest('tr').remove()" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
}

function renderMilestones(milestones) {
  const container = document.getElementById('milestoneBody');
  if (!container) return;
  if (milestones.length === 0) {
    container.innerHTML = '<tr><td colspan="3" class="no-data">진행 단계 없음</td></tr>';
    return;
  }
  container.innerHTML = milestones.map(ms => `
    <tr data-id="${ms.id || ''}">
      <td>${escapeHtml(ms.name)}</td>
      <td class="chk"><input type="checkbox" class="ms-field" data-field="completed" ${ms.completed ? 'checked' : ''} /></td>
      <td>${escapeHtml(ms.date || '-')}</td>
    </tr>
  `).join('');
}

async function saveOverview() {
  if (!currentProjectId) return;

  const payload = {};

  // 필드 수집
  document.querySelectorAll('.ov-field').forEach(el => {
    const field = el.dataset.field;
    if (el.type === 'checkbox') {
      payload[field] = el.checked ? 1 : 0;
    } else if (el.type === 'number') {
      payload[field] = parseFloat(el.value) || 0;
    } else if (el.tagName === 'SELECT') {
      payload[field] = el.value;
    } else {
      payload[field] = el.value.trim();
    }
  });

  // 배정인원
  const members = [];
  document.querySelectorAll('#memberBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const role = tr.querySelector('[data-field="role"]')?.value?.trim() || '';
    const name = tr.querySelector('[data-field="name"]')?.value?.trim() || '';
    if (role || name) members.push({ role, name });
  });
  payload.members = members;

  // 진행상황 체크리스트
  const milestones = [];
  document.querySelectorAll('#milestoneBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const id = tr.dataset.id ? parseInt(tr.dataset.id) : null;
    const completed = tr.querySelector('[data-field="completed"]')?.checked ? 1 : 0;
    milestones.push({ id, completed });
  });
  payload.milestones = milestones;

  try {
    const res = await fetch(`/api/fund/projects/${currentProjectId}/overview`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('프로젝트 개요가 저장되었습니다.', 'success');
    await loadOverview(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 하도급상세 탭 =====
async function loadSubcontracts(projectId) {
  try {
    const res = await fetch(`/api/fund/projects/${projectId}/subcontracts`);
    if (!res.ok) throw new Error('하도급 조회 실패');
    const data = await res.json();
    renderSubcontractTable(data.subcontracts || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderSubcontractTable(rows) {
  const tbody = document.getElementById('subcontractBody');
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="15" class="no-data">데이터 없음 - "행 추가" 버튼으로 추가하세요.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((r, i) => {
    const p1 = r.payment_1 || 0, p2 = r.payment_2 || 0, p3 = r.payment_3 || 0, p4 = r.payment_4 || 0;
    const c1 = r.payment_1_confirmed, c2 = r.payment_2_confirmed, c3 = r.payment_3_confirmed, c4 = r.payment_4_confirmed;
    // 체크된(확인된) 지급만 기지급액에 합산
    const totalPaid = (c1 ? p1 : 0) + (c2 ? p2 : 0) + (c3 ? p3 : 0) + (c4 ? p4 : 0);
    const remaining = (r.contract_amount || 0) - totalPaid;
    const pct = r.contract_amount ? (totalPaid / r.contract_amount * 100).toFixed(1) : '0.0';

    return `<tr data-id="${r.id}">
      <td>${i + 1}</td>
      <td><select class="sc-trade" data-field="trade_id">
        <option value="">-- 선택 --</option>
        ${tradesCache.map(t => `<option value="${t.id}" ${t.id === r.trade_id ? 'selected' : ''}>${escapeHtml(t.name)}</option>`).join('')}
      </select></td>
      <td><input type="text" class="sc-field" data-field="company_name" value="${escapeHtml(r.company_name || '')}" placeholder="업체명" /></td>
      <td class="num"><input type="number" class="sc-field" data-field="contract_amount" value="${r.contract_amount || 0}" /></td>
      <td class="num"><input type="number" class="sc-field" data-field="payment_1" value="${p1}" /></td>
      <td class="num"><input type="number" class="sc-field" data-field="payment_2" value="${p2}" /></td>
      <td class="num"><input type="number" class="sc-field" data-field="payment_3" value="${p3}" /></td>
      <td class="num"><input type="number" class="sc-field" data-field="payment_4" value="${p4}" /></td>
      <td class="num sc-remaining">${formatNum(remaining)}</td>
      <td class="num sc-pct">${pct}%</td>
      <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_1_confirmed" ${c1 ? 'checked' : ''} onchange="recalcSubcontractRow(this)" /></td>
      <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_2_confirmed" ${c2 ? 'checked' : ''} onchange="recalcSubcontractRow(this)" /></td>
      <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_3_confirmed" ${c3 ? 'checked' : ''} onchange="recalcSubcontractRow(this)" /></td>
      <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_4_confirmed" ${c4 ? 'checked' : ''} onchange="recalcSubcontractRow(this)" /></td>
      <td><button class="btn-icon" onclick="removeSubcontractRow(this)" title="삭제">&times;</button></td>
    </tr>`;
  }).join('');

  // 금액 변경 시에도 재계산
  tbody.querySelectorAll('input[data-field^="payment_"][type="number"]').forEach(el => {
    el.addEventListener('change', () => recalcSubcontractRow(el));
  });
}

// 행별 잔여금액/지급율 실시간 재계산 (체크박스 or 금액 변경 시)
function recalcSubcontractRow(el) {
  const tr = el.closest('tr');
  if (!tr) return;
  const contract = parseInt(tr.querySelector('[data-field="contract_amount"]')?.value) || 0;
  let totalPaid = 0;
  for (let n = 1; n <= 4; n++) {
    const chk = tr.querySelector(`[data-field="payment_${n}_confirmed"]`);
    const amt = parseInt(tr.querySelector(`[data-field="payment_${n}"]`)?.value) || 0;
    if (chk && chk.checked) totalPaid += amt;
  }
  const remaining = contract - totalPaid;
  const pct = contract ? (totalPaid / contract * 100).toFixed(1) : '0.0';
  tr.querySelector('.sc-remaining').textContent = formatNum(remaining);
  tr.querySelector('.sc-pct').textContent = pct + '%';
}

function addSubcontractRow() {
  const tbody = document.getElementById('subcontractBody');
  // "데이터 없음" 행 제거
  const noData = tbody.querySelector('.no-data');
  if (noData) noData.parentElement.remove();

  const rowCount = tbody.querySelectorAll('tr').length;
  const tr = document.createElement('tr');
  tr.dataset.id = 'new';
  tr.innerHTML = `
    <td>${rowCount + 1}</td>
    <td><select class="sc-trade" data-field="trade_id">
      <option value="">-- 선택 --</option>
      ${tradesCache.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('')}
    </select></td>
    <td><input type="text" class="sc-field" data-field="company_name" value="" placeholder="업체명" /></td>
    <td class="num"><input type="number" class="sc-field" data-field="contract_amount" value="0" /></td>
    <td class="num"><input type="number" class="sc-field" data-field="payment_1" value="0" /></td>
    <td class="num"><input type="number" class="sc-field" data-field="payment_2" value="0" /></td>
    <td class="num"><input type="number" class="sc-field" data-field="payment_3" value="0" /></td>
    <td class="num"><input type="number" class="sc-field" data-field="payment_4" value="0" /></td>
    <td class="num sc-remaining">0</td>
    <td class="num sc-pct">0.0%</td>
    <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_1_confirmed" onchange="recalcSubcontractRow(this)" /></td>
    <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_2_confirmed" onchange="recalcSubcontractRow(this)" /></td>
    <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_3_confirmed" onchange="recalcSubcontractRow(this)" /></td>
    <td class="chk"><input type="checkbox" class="sc-field" data-field="payment_4_confirmed" onchange="recalcSubcontractRow(this)" /></td>
    <td><button class="btn-icon" onclick="removeSubcontractRow(this)" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
}

function removeSubcontractRow(btn) {
  const tr = btn.closest('tr');
  if (tr) tr.remove();
  // 번호 다시 매기기
  const rows = document.querySelectorAll('#subcontractBody tr');
  rows.forEach((row, i) => {
    const firstTd = row.querySelector('td');
    if (firstTd && !firstTd.classList.contains('no-data')) {
      firstTd.textContent = i + 1;
    }
  });
}

async function saveSubcontracts() {
  if (!currentProjectId) return;

  const rows = [];
  document.querySelectorAll('#subcontractBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const row = { id: tr.dataset.id === 'new' ? null : parseInt(tr.dataset.id) };

    tr.querySelectorAll('.sc-field, .sc-trade').forEach(el => {
      const field = el.dataset.field;
      if (el.type === 'checkbox') {
        row[field] = el.checked;
      } else if (el.type === 'number') {
        row[field] = parseInt(el.value) || 0;
      } else if (el.tagName === 'SELECT') {
        row[field] = el.value ? parseInt(el.value) : null;
      } else {
        row[field] = el.value.trim();
      }
    });
    rows.push(row);
  });

  try {
    const res = await fetch(`/api/fund/projects/${currentProjectId}/subcontracts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subcontracts: rows })
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('하도급 상세가 저장되었습니다.', 'success');
    await loadSubcontracts(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 공종관리 탭 =====
async function loadTrades(projectId) {
  await loadTradesCache(projectId);
  const tbody = document.getElementById('tradeBody');
  if (tradesCache.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="no-data">등록된 공종이 없습니다.</td></tr>';
    return;
  }

  tbody.innerHTML = tradesCache.map((t, i) => `
    <tr data-id="${t.id}">
      <td>${i + 1}</td>
      <td>${escapeHtml(t.name)}</td>
      <td>${escapeHtml(t.description || '-')}</td>
      <td>${t.created_at ? formatDate(t.created_at) : '-'}</td>
      <td>
        <button class="btn btn-sm btn-outlined" onclick="openTradeModal(${t.id})">수정</button>
        <button class="btn-icon" onclick="deleteTrade(${t.id})" title="삭제">&times;</button>
      </td>
    </tr>
  `).join('');
}

function openTradeModal(tradeId) {
  const isEdit = !!tradeId;
  const trade = isEdit ? tradesCache.find(t => t.id === tradeId) : {};

  openModal(isEdit ? '공종 수정' : '공종 추가', `
    <div class="form-group">
      <label>공종명</label>
      <input type="text" id="modalTradeName" value="${escapeHtml(trade.name || '')}" placeholder="예: 철근콘크리트" />
    </div>
    <div class="form-group">
      <label>설명</label>
      <textarea id="modalTradeDesc" placeholder="공종에 대한 설명 (선택)">${escapeHtml(trade.description || '')}</textarea>
    </div>
  `, async () => {
    const name = document.getElementById('modalTradeName').value.trim();
    if (!name) {
      showToast('공종명을 입력하세요.', 'error');
      return;
    }
    const description = document.getElementById('modalTradeDesc').value.trim();
    const url = isEdit
      ? `/api/fund/projects/${currentProjectId}/trades/${tradeId}`
      : `/api/fund/projects/${currentProjectId}/trades`;
    const method = isEdit ? 'PUT' : 'POST';

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description })
      });
      if (!res.ok) throw new Error(isEdit ? '수정 실패' : '추가 실패');
      closeModal();
      showToast(isEdit ? '공종이 수정되었습니다.' : '공종이 추가되었습니다.', 'success');
      await loadTrades(currentProjectId);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  setTimeout(() => document.getElementById('modalTradeName')?.focus(), 100);
}

async function deleteTrade(tradeId) {
  const trade = tradesCache.find(t => t.id === tradeId);
  if (!confirm(`"${trade ? trade.name : '이 공종'}"을 삭제하시겠습니까?`)) return;

  try {
    const res = await fetch(`/api/fund/projects/${currentProjectId}/trades/${tradeId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('공종 삭제 실패');
    showToast('공종이 삭제되었습니다.', 'success');
    await loadTrades(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 연락처 탭 =====
async function loadContacts(projectId) {
  try {
    const res = await fetch(`/api/fund/projects/${projectId}/contacts`);
    if (!res.ok) throw new Error('연락처 조회 실패');
    const data = await res.json();
    renderContactTable(data.contacts || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderContactTable(contacts) {
  const tbody = document.getElementById('contactBody');
  if (contacts.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">등록된 연락처가 없습니다.</td></tr>';
    return;
  }

  tbody.innerHTML = contacts.map((c, i) => `
    <tr data-id="${c.id}">
      <td>${i + 1}</td>
      <td>${escapeHtml(c.vendor_name || '-')}</td>
      <td>${escapeHtml(c.contact_person || '-')}</td>
      <td>${escapeHtml(c.phone || '-')}</td>
      <td>${escapeHtml(c.email || '-')}</td>
      <td>${escapeHtml(c.trade_name || '-')}</td>
      <td>${escapeHtml(c.note || '-')}</td>
      <td>
        <button class="btn btn-sm btn-outlined" onclick="openContactModal(${c.id})">수정</button>
        <button class="btn-icon" onclick="deleteContact(${c.id})" title="삭제">&times;</button>
      </td>
    </tr>
  `).join('');
}

function openContactModal(contactId) {
  const isEdit = !!contactId;

  // 편집 시 기존 데이터를 행에서 추출
  let contact = {};
  if (isEdit) {
    const tr = document.querySelector(`#contactBody tr[data-id="${contactId}"]`);
    if (tr) {
      const tds = tr.querySelectorAll('td');
      contact = {
        vendor_name: tds[1]?.textContent === '-' ? '' : tds[1]?.textContent,
        contact_person: tds[2]?.textContent === '-' ? '' : tds[2]?.textContent,
        phone: tds[3]?.textContent === '-' ? '' : tds[3]?.textContent,
        email: tds[4]?.textContent === '-' ? '' : tds[4]?.textContent,
        trade_name: tds[5]?.textContent === '-' ? '' : tds[5]?.textContent,
        note: tds[6]?.textContent === '-' ? '' : tds[6]?.textContent,
      };
    }
  }

  openModal(isEdit ? '연락처 수정' : '연락처 추가', `
    <div class="form-group">
      <label>업체명</label>
      <input type="text" id="modalVendorName" value="${escapeHtml(contact.vendor_name || '')}" placeholder="업체명" />
    </div>
    <div class="form-group">
      <label>담당자</label>
      <input type="text" id="modalContactPerson" value="${escapeHtml(contact.contact_person || '')}" placeholder="담당자 이름" />
    </div>
    <div class="form-group">
      <label>연락처</label>
      <input type="text" id="modalPhone" value="${escapeHtml(contact.phone || '')}" placeholder="010-0000-0000" />
    </div>
    <div class="form-group">
      <label>이메일</label>
      <input type="text" id="modalEmail" value="${escapeHtml(contact.email || '')}" placeholder="email@example.com" />
    </div>
    <div class="form-group">
      <label>공종</label>
      <select id="modalContactTrade">
        <option value="">-- 선택 --</option>
        ${tradesCache.map(t => `<option value="${t.id}" ${t.name === contact.trade_name ? 'selected' : ''}>${escapeHtml(t.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label>비고</label>
      <textarea id="modalNote" placeholder="비고 (선택)">${escapeHtml(contact.note || '')}</textarea>
    </div>
  `, async () => {
    const payload = {
      vendor_name: document.getElementById('modalVendorName').value.trim(),
      contact_person: document.getElementById('modalContactPerson').value.trim(),
      phone: document.getElementById('modalPhone').value.trim(),
      email: document.getElementById('modalEmail').value.trim(),
      trade_id: document.getElementById('modalContactTrade').value || null,
      note: document.getElementById('modalNote').value.trim(),
    };

    if (!payload.vendor_name) {
      showToast('업체명을 입력하세요.', 'error');
      return;
    }

    const url = isEdit
      ? `/api/fund/projects/${currentProjectId}/contacts/${contactId}`
      : `/api/fund/projects/${currentProjectId}/contacts`;
    const method = isEdit ? 'PUT' : 'POST';

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(isEdit ? '수정 실패' : '추가 실패');
      closeModal();
      showToast(isEdit ? '연락처가 수정되었습니다.' : '연락처가 추가되었습니다.', 'success');
      await loadContacts(currentProjectId);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  setTimeout(() => document.getElementById('modalVendorName')?.focus(), 100);
}

async function deleteContact(contactId) {
  if (!confirm('이 연락처를 삭제하시겠습니까?')) return;

  try {
    const res = await fetch(`/api/fund/projects/${currentProjectId}/contacts/${contactId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('연락처 삭제 실패');
    showToast('연락처가 삭제되었습니다.', 'success');
    await loadContacts(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 수금현황 탭 =====
async function loadCollections(projectId) {
  try {
    const res = await fetch(`/api/fund/projects/${projectId}/collections`);
    if (!res.ok) throw new Error('수금현황 조회 실패');
    const data = await res.json();
    renderCollections(data.collections || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderCollections(items) {
  const designBody = document.getElementById('collectionDesignBody');
  const constructionBody = document.getElementById('collectionConstructionBody');

  const designItems = items.filter(c => c.category === '설계');
  const constructionItems = items.filter(c => c.category === '시공');

  // 설계 테이블
  if (designItems.length === 0) {
    designBody.innerHTML = '<tr><td colspan="3" class="no-data">데이터 없음</td></tr>';
  } else {
    designBody.innerHTML = designItems.map(c => `
      <tr data-id="${c.id}">
        <td>${escapeHtml(c.stage)}</td>
        <td class="num"><input type="number" class="coll-field" data-field="amount" value="${c.amount || 0}" onchange="recalcCollectionSummary()" /></td>
        <td class="chk"><input type="checkbox" class="coll-field" data-field="collected" ${c.collected ? 'checked' : ''} onchange="recalcCollectionSummary()" /></td>
      </tr>
    `).join('');
  }

  // 시공 테이블
  if (constructionItems.length === 0) {
    constructionBody.innerHTML = '<tr><td colspan="3" class="no-data">데이터 없음</td></tr>';
  } else {
    constructionBody.innerHTML = constructionItems.map(c => `
      <tr data-id="${c.id}">
        <td>${escapeHtml(c.stage)}</td>
        <td class="num"><input type="number" class="coll-field" data-field="amount" value="${c.amount || 0}" onchange="recalcCollectionSummary()" /></td>
        <td class="chk"><input type="checkbox" class="coll-field" data-field="collected" ${c.collected ? 'checked' : ''} onchange="recalcCollectionSummary()" /></td>
      </tr>
    `).join('');
  }

  // 합계 계산
  updateCollectionSummary(items);
}

function updateCollectionSummary(items) {
  let totalAmount = 0, totalCollected = 0;
  items.forEach(c => {
    totalAmount += (c.amount || 0);
    if (c.collected) totalCollected += (c.amount || 0);
  });
  const uncollected = totalAmount - totalCollected;
  const rate = totalAmount ? (totalCollected / totalAmount * 100) : 0;

  document.getElementById('valTotalCollected').textContent = formatWon(totalCollected);
  document.getElementById('valTotalUncollected').textContent = formatWon(uncollected);
  document.getElementById('valCollectionRate').textContent = rate.toFixed(1) + '%';
}

// 체크박스/금액 변경 시 실시간 합계 재계산
function recalcCollectionSummary() {
  let totalAmount = 0, totalCollected = 0;
  document.querySelectorAll('#collectionDesignBody tr, #collectionConstructionBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const amtInput = tr.querySelector('[data-field="amount"]');
    const chkInput = tr.querySelector('[data-field="collected"]');
    const amt = parseInt(amtInput?.value) || 0;
    totalAmount += amt;
    if (chkInput?.checked) totalCollected += amt;
  });
  const uncollected = totalAmount - totalCollected;
  const rate = totalAmount ? (totalCollected / totalAmount * 100) : 0;
  document.getElementById('valTotalCollected').textContent = formatWon(totalCollected);
  document.getElementById('valTotalUncollected').textContent = formatWon(uncollected);
  document.getElementById('valCollectionRate').textContent = rate.toFixed(1) + '%';
}

async function saveCollections() {
  if (!currentProjectId) return;

  const items = [];
  document.querySelectorAll('#collectionDesignBody tr, #collectionConstructionBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const item = { id: parseInt(tr.dataset.id) || null };
    tr.querySelectorAll('.coll-field').forEach(el => {
      const field = el.dataset.field;
      if (el.type === 'checkbox') {
        item[field] = el.checked ? 1 : 0;
      } else if (el.type === 'number') {
        item[field] = parseInt(el.value) || 0;
      }
    });
    items.push(item);
  });

  try {
    const res = await fetch(`/api/fund/projects/${currentProjectId}/collections`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ collections: items })
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('수금현황이 저장되었습니다.', 'success');
    await loadCollections(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 이체내역 탭 (읽기 전용) =====
async function loadPayments(projectId) {
  const tbody = document.getElementById('paymentBody');
  tbody.innerHTML = '<tr><td colspan="7" class="no-data"><span class="loading-spinner"></span> 데이터 불러오는 중...</td></tr>';

  try {
    const res = await fetch(`/api/fund/projects/${projectId}/payments`);
    if (!res.ok) throw new Error('이체내역 조회 실패');
    const data = await res.json();
    const payments = data.payments || [];

    if (payments.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="no-data">이체내역이 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = payments.map((p, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(p.confirmed_date || p.scheduled_date || '-')}</td>
        <td>${escapeHtml(p.vendor_name || '-')}</td>
        <td class="num">${formatWon(p.amount || 0)}</td>
        <td>${escapeHtml(p.description || '-')}</td>
        <td>${escapeHtml((p.bank_name || '') + ' ' + (p.account_number || ''))}</td>
        <td>${escapeHtml(p.fund_category || '-')}</td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="no-data">${escapeHtml(e.message)}</td></tr>`;
  }
}

// ===== 예실대비 탭 (읽기 전용) =====
async function loadBudget(projectId) {
  const tbody = document.getElementById('budgetBody');
  tbody.innerHTML = '<tr><td colspan="6" class="no-data"><span class="loading-spinner"></span> 데이터 불러오는 중...</td></tr>';

  try {
    const res = await fetch(`/api/fund/projects/${projectId}/budget`);
    if (!res.ok) throw new Error('예실대비 조회 실패');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="no-data">예실대비 데이터가 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(item => {
      const remaining = (item.budget || 0) - (item.actual || 0);
      const pct = item.budget ? ((item.actual || 0) / item.budget * 100) : 0;
      return `<tr>
        <td>${escapeHtml(item.category || '-')}</td>
        <td class="num">${formatWon(item.budget || 0)}</td>
        <td class="num">${formatWon(item.actual || 0)}</td>
        <td class="num">${formatWon(remaining)}</td>
        <td class="num">${renderPctBar(pct)}</td>
        <td>${escapeHtml(item.note || '-')}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="no-data">${escapeHtml(e.message)}</td></tr>`;
  }
}

// ===== 모달 유틸 =====
let modalConfirmCallback = null;

function openModal(title, bodyHtml, onConfirm) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = bodyHtml;
  document.getElementById('modalOverlay').style.display = 'flex';
  modalConfirmCallback = onConfirm;
  document.getElementById('modalConfirmBtn').onclick = () => {
    if (modalConfirmCallback) modalConfirmCallback();
  };
}

function closeModal() {
  document.getElementById('modalOverlay').style.display = 'none';
  modalConfirmCallback = null;
}

// ===== 토스트 알림 =====
function showToast(message, type) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type || 'info'}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ===== 포맷 유틸 =====
function formatWon(value) {
  if (value === null || value === undefined) return '0 원';
  const num = typeof value === 'string' ? parseInt(value) : value;
  return num.toLocaleString('ko-KR') + ' 원';
}

function formatNum(value) {
  if (value === null || value === undefined) return '0';
  const num = typeof value === 'string' ? parseInt(value) : value;
  return num.toLocaleString('ko-KR');
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function escapeHtml(str) {
  if (!str) return '';
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(str).replace(/[&<>"']/g, c => map[c]);
}

function renderPctBar(pct) {
  const val = Math.min(100, Math.max(0, pct));
  let cls = 'low';
  if (val >= 80) cls = 'high';
  else if (val >= 40) cls = 'mid';

  return `<div class="pct-bar">
    <div class="pct-bar-track"><div class="pct-bar-fill ${cls}" style="width:${val}%"></div></div>
    <span class="pct-bar-label">${val.toFixed(1)}%</span>
  </div>`;
}

function renderStatusBadge(status) {
  if (!status) return '<span class="badge badge-muted">-</span>';
  const map = {
    '완료': 'success',
    '처리중': 'warning',
    '실패': 'danger',
    '대기': 'info',
  };
  const type = map[status] || 'muted';
  return `<span class="badge badge-${type}">${escapeHtml(status)}</span>`;
}
