/**
 * 프로젝트 관리 프론트엔드 (fund.js)
 * - 프로젝트 프로젝트 관리표 & 거래처현황
 */

// ===== XSS 방어 유틸리티 =====
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ===== CSRF 토큰 유틸리티 =====
function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}

/**
 * fetch 래퍼: state-changing 요청에 자동으로 X-CSRF-Token 헤더 추가
 */
async function safeFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    options.headers = options.headers || {};
    options.headers['X-CSRF-Token'] = getCsrfToken();
  }
  return fetch(url, options);
}

/**
 * GW 크롤링 전용 fetch 래퍼
 * - 상태코드별 한국어 에러 메시지 처리
 * - 403 시 페이지 새로고침 안내 (CSRF 토큰 만료 대응)
 * - 응답이 ok이면 JSON 파싱까지 수행하여 반환
 */
async function gwFetch(url, options = {}) {
  const res = await safeFetch(url, options);

  if (res.ok) return { response: res, data: await res.json() };

  // 상태코드별 에러 처리
  switch (res.status) {
    case 401:
      throw new Error('GW 로그인이 만료되었습니다. 다시 로그인해주세요.');
    case 403: {
      // CSRF 토큰 만료 가능성 — 페이지 새로고침으로 토큰 재발급 안내
      throw new Error('인증 오류가 발생했습니다. 페이지를 새로고침해주세요.');
    }
    case 408:
    case 504:
      throw new Error('서버 응답 시간이 초과되었습니다. 프로젝트 수가 많으면 개별 동기화를 시도해주세요.');
    case 500:
      throw new Error('서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
    default: {
      // 그 외 HTTP 에러 — 서버 응답 메시지 활용
      const errData = await res.json().catch(() => null);
      const errMsg = errData?.detail || errData?.error || errData?.message || `서버 오류 (${res.status})`;
      throw new Error(errMsg);
    }
  }
}

// ===== 전역 상태 =====
let currentUser = null;
let currentProjectId = null;
let currentTab = 'dashboard';
let projectsCache = [];
let tradesCache = [];
let dirtyTabs = new Set();  // 저장 후 갱신이 필요한 탭 추적

// ===== 탭 간 데이터 동기화 =====
// 각 탭의 데이터가 어떤 탭에 영향을 주는지 정의
const TAB_DEPENDENCIES = {
  'budget-payment': ['dashboard'],       // 하도급/예산 변경 → 대시보드 갱신
  collections:      ['dashboard'],       // 수금 변경 → 대시보드 수금률 갱신
  overview:         ['dashboard'],       // 개요 변경 → 대시보드 프로젝트 정보 갱신
  vendors:          ['budget-payment', 'dashboard'], // 공종/연락처 변경 → 하도급 공종 드롭다운 + 대시보드
};

/**
 * 저장 후 호출: 변경된 탭과 연관된 탭을 dirty로 표시하고,
 * 현재 보고 있는 탭이 dirty면 즉시 갱신
 */
function markRelatedTabsDirty(savedTab) {
  const deps = TAB_DEPENDENCIES[savedTab] || [];
  deps.forEach(tab => dirtyTabs.add(tab));

  // 현재 보고 있는 탭이 dirty 목록에 있으면 즉시 갱신
  if (dirtyTabs.has(currentTab) && currentProjectId) {
    dirtyTabs.delete(currentTab);
    refreshTab(currentTab, currentProjectId);
  }
}

/** 특정 탭 데이터를 서버에서 다시 로드 */
function refreshTab(tabName, projectId) {
  switch (tabName) {
    case 'dashboard':       loadDashboard(projectId); break;
    case 'overview':        loadOverview(projectId); break;
    case 'collections':     loadCollections(projectId); break;
    case 'budget-payment':  loadSubcontracts(projectId); loadBudget(projectId); break;
    case 'vendors':         loadVendors(projectId); break;
    case 'payments':        loadPayments(projectId); break;
  }
}

// ===== 초기화 =====
document.addEventListener('DOMContentLoaded', async () => {
  await checkAuth();
  await loadProjects();
  bindEvents();
  initInsights();
});

// ===== 인증 확인 =====
async function checkAuth() {
  try {
    const res = await safeFetch('/auth/me');
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
    await safeFetch('/auth/logout', { method: 'POST' });
    window.location.href = '/';
  });

  // 탭 전환
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  // 서브탭 전환 (하도급/예실 패널에만 적용 — vendors 패널은 단일 뷰)
  document.querySelectorAll('#panel-budget-payment .sub-tab-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const parentPanel = btn.closest('.tab-panel');
      parentPanel.querySelectorAll('.sub-tab-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      parentPanel.querySelectorAll('.sub-tab-panel').forEach(p => p.style.display = 'none');
      const target = parentPanel.querySelector(`#subpanel-${btn.dataset.subtab}`);
      if (target) target.style.display = 'block';
    });
  });

  // 사이드바 토글 (모바일)
  document.getElementById('sidebarToggle').addEventListener('click', () => {
    const sidebar = document.querySelector('.fund-sidebar');
    sidebar.classList.toggle('open');
    // 오버레이 토글
    let overlay = document.getElementById('sidebarOverlay');
    if (sidebar.classList.contains('open')) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'sidebarOverlay';
        overlay.className = 'sidebar-overlay';
        overlay.addEventListener('click', () => {
          sidebar.classList.remove('open');
          overlay.remove();
        });
        document.body.appendChild(overlay);
      }
    } else if (overlay) {
      overlay.remove();
    }
  });

  // 하도급 행 추가
  document.getElementById('addSubcontractBtn').addEventListener('click', addSubcontractRow);
  document.getElementById('saveSubcontractsBtn').addEventListener('click', saveSubcontracts);

  // 개요 저장/인원추가/GW 크롤링
  document.getElementById('saveOverviewBtn').addEventListener('click', saveOverview);
  document.getElementById('addMemberBtn').addEventListener('click', addMemberRow);
  document.getElementById('crawlGwBtn').addEventListener('click', handleGwImport);

  // 수금현황 저장
  document.getElementById('saveCollectionsBtn').addEventListener('click', saveCollections);

  // 하도급 업체 추가 (통합 테이블)
  document.getElementById('addVendorBtn')?.addEventListener('click', () => openVendorModal());

  // 하도급 업체 테이블 이벤트 위임 (수정/삭제)
  document.getElementById('vendorBody')?.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.edit-vendor-btn');
    if (editBtn) {
      const row = editBtn.closest('tr');
      if (row) openVendorModal(+row.dataset.id);
      return;
    }
    const delBtn = e.target.closest('.delete-vendor-btn');
    if (delBtn) {
      const row = delBtn.closest('tr');
      if (row) deleteVendor(+row.dataset.id);
    }
  });

  // 이체내역/예실 새로고침
  document.getElementById('refreshPaymentsBtn').addEventListener('click', () => loadPayments(currentProjectId));
  document.getElementById('refreshBudgetBtn').addEventListener('click', () => loadBudget(currentProjectId));

  // 예실대비 GW 크롤링
  document.getElementById('crawlBudgetBtn')?.addEventListener('click', async () => {
    if (!currentProjectId) return;
    const btn = document.getElementById('crawlBudgetBtn');
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> 크롤링 중...';
    try {
      const { data } = await gwFetch(`/api/fund/projects/${currentProjectId}/crawl-gw`, { method: 'POST' });
      if (data.success) {
        const msg = data.message || 'GW 예실대비 데이터를 가져왔습니다.';
        showToast(msg, 'success');
        loadBudget(currentProjectId);
      } else {
        showToast(data.error || data.message || '크롤링 실패', 'error');
      }
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  });

  // 포트폴리오 버튼 (헤더)
  document.getElementById('portfolioBtn').addEventListener('click', goToPortfolio);

  // 포트폴리오 새로고침 버튼
  document.getElementById('pfRefreshBtn').addEventListener('click', () => {
    loadPortfolioView();
    showToast('포트폴리오 현황을 새로고침했습니다.', 'success');
  });

  // 포트폴리오 전체 GW 동기화 버튼
  document.getElementById('pfSyncGwBtn')?.addEventListener('click', syncAllGw);

  // PM 시트 가져오기 버튼
  document.getElementById('pfImportPmBtn')?.addEventListener('click', importPmSheet);

  // 포트폴리오 AI 분석 버튼
  document.getElementById('pfAnalyzeBtn').addEventListener('click', generatePortfolioAnalysis);

  // 모달 닫기
  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalCancelBtn').addEventListener('click', closeModal);
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  // 마일스톤 추가 버튼
  const btnAddMs = document.getElementById('btnAddMilestone');
  if (btnAddMs) btnAddMs.addEventListener('click', addMilestoneRow);

  // ===== 이벤트 위임 (동적 요소) =====

  // 프로젝트 리스트: 클릭, 드래그
  const projectList = document.getElementById('projectList');
  if (projectList) {
    projectList.addEventListener('click', (e) => {
      const delBtn = e.target.closest('[data-delete-project]');
      if (delBtn) { e.stopPropagation(); deleteProject(+delBtn.dataset.deleteProject); return; }
      const li = e.target.closest('.project-item');
      if (li) selectProject(+li.dataset.id);
    });
    projectList.addEventListener('dragstart', (e) => {
      const li = e.target.closest('.project-item');
      if (li) onProjectDragStart(e, li);
    });
    projectList.addEventListener('dragover', (e) => {
      const li = e.target.closest('.project-item');
      if (li) onProjectDragOver(e, li);
    });
    projectList.addEventListener('drop', (e) => {
      const li = e.target.closest('.project-item');
      if (li) onProjectDrop(e, li);
    });
    projectList.addEventListener('dragend', (e) => {
      const li = e.target.closest('.project-item');
      if (li) onProjectDragEnd(e, li);
    });
  }

  // 프로젝트 검색 필터
  const projectSearchInput = document.getElementById('projectSearch');
  if (projectSearchInput) {
    projectSearchInput.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase().trim();
      document.querySelectorAll('.project-item').forEach(li => {
        const name = li.querySelector('.project-name')?.textContent?.toLowerCase() || '';
        li.style.display = name.includes(q) ? '' : 'none';
      });
    });
  }

  // 대시보드/HTML: clickable-title → switchTab
  document.addEventListener('click', (e) => {
    const switchEl = e.target.closest('[data-switch-tab]');
    if (switchEl) { switchTab(switchEl.dataset.switchTab); return; }
  });

  // 행 삭제 (인원 테이블 등)
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn-remove-row')) {
      e.target.closest('tr').remove(); return;
    }
  });

  // 마일스톤: 완료 토글
  document.addEventListener('change', (e) => {
    if (e.target.closest('.ms-toggle-completed')) {
      toggleMilestoneRow(e.target); return;
    }
  });

  // 마일스톤: 삭제
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn-del-ms-action')) {
      e.target.closest('tr').remove(); updateMilestoneProgress(); return;
    }
  });

  // 하도급: 체크박스 및 금액 변경 시 recalc (이벤트 위임)
  document.addEventListener('change', (e) => {
    if (e.target.closest('.sc-recalc-trigger')) {
      recalcSubcontractRow(e.target); return;
    }
    // 금액 input 변경 시에도 재계산
    if (e.target.matches('#subcontractBody input[data-field^="payment_"][type="number"], #subcontractBody input[data-field="contract_amount"]')) {
      recalcSubcontractRow(e.target); return;
    }
  });

  // 하도급: 행 삭제
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn-remove-sc-row')) {
      removeSubcontractRow(e.target); return;
    }
  });

  // (공종/연락처 이벤트 위임은 vendorBody에서 통합 처리)

  // 수금현황: recalc
  document.addEventListener('change', (e) => {
    if (e.target.closest('.coll-recalc-trigger')) {
      recalcCollectionSummary(); return;
    }
  });
}

// ===== 프로젝트 목록 =====
async function loadProjects() {
  try {
    const res = await safeFetch('/api/fund/projects');
    if (!res.ok) throw new Error('프로젝트 목록 조회 실패');
    const data = await res.json();
    projectsCache = data.projects || [];
    renderProjectList();
    // 프로젝트 미선택 시 포트폴리오 뷰 로드
    if (!currentProjectId) loadPortfolioView();
  } catch (e) {
    showToast(e.message, 'error');
    projectsCache = [];
    renderProjectList();
  }
}

// ===== 포트폴리오 비교 뷰 =====
async function loadPortfolioView() {
  try {
    const res = await safeFetch('/api/fund/portfolio-summary');
    if (!res.ok) return;
    const data = await res.json();
    let projects = data.projects || [];

    // projectsCache 순서에 맞게 정렬 (드래그 정렬 반영)
    if (projectsCache.length > 0) {
      const orderMap = new Map(projectsCache.map((p, i) => [p.id, i]));
      projects.sort((a, b) => (orderMap.get(a.id) ?? 999) - (orderMap.get(b.id) ?? 999));
    }

    // 요약 카드
    const totalOrder = projects.reduce((s, p) => s + (p.total_order || 0), 0);
    const totalCollected = projects.reduce((s, p) => s + (p.coll_collected || 0), 0);
    const totalCollTotal = projects.reduce((s, p) => s + (p.coll_total || 0), 0);

    document.getElementById('pfTotalProjects').textContent = projects.length + '건';
    document.getElementById('pfTotalOrder').textContent = formatWon(totalOrder);
    document.getElementById('pfTotalCollected').textContent = formatWon(totalCollected);
    document.getElementById('pfTotalUncollected').textContent = formatWon(totalCollTotal - totalCollected);

    // 비교 테이블
    const tbody = document.getElementById('pfCompareBody');
    if (projects.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="no-data">프로젝트를 추가하세요.</td></tr>';
      return;
    }
    tbody.innerHTML = projects.map(p => {
      const collRate = p.coll_rate || 0;
      const payRate = p.payment_rate || 0;
      const profitRate = p.profit_rate || 0;
      return `<tr class="pf-row-clickable" data-id="${p.id}" draggable="true">
        <td class="pf-name-cell">${escapeHtml(p.name)}</td>
        <td><span class="pf-grade">${escapeHtml(p.grade)}</span></td>
        <td class="num">${formatWon(p.total_order)}</td>
        <td class="num">${formatWon(p.execution_budget)}</td>
        <td class="num">${collRate.toFixed(1)}%</td>
        <td class="num">${payRate.toFixed(1)}%</td>
        <td class="num ${profitRate >= 0 ? 'positive' : 'negative'}">${profitRate.toFixed(1)}%</td>
        <td>
          <div class="pf-inline-bar">
            <div class="pf-inline-fill" style="width:${Math.min(collRate, 100)}%"></div>
          </div>
        </td>
      </tr>`;
    }).join('');

    // 행 클릭 + 드래그 이벤트
    tbody.querySelectorAll('.pf-row-clickable').forEach(row => {
      row.addEventListener('click', () => {
        selectProject(parseInt(row.dataset.id));
      });
      row.addEventListener('dragstart', (e) => onPfRowDragStart(e, row));
      row.addEventListener('dragover', (e) => onPfRowDragOver(e, row));
      row.addEventListener('drop', (e) => onPfRowDrop(e, row));
      row.addEventListener('dragend', (e) => onPfRowDragEnd(e, row));
    });

    // 포트폴리오 AI 분석 로드
    loadPortfolioAnalysis();
  } catch (e) {
    console.error('포트폴리오 로드 실패:', e);
    document.getElementById('pfTotalProjects').textContent = '-';
    document.getElementById('pfTotalOrder').textContent = '-';
    document.getElementById('pfTotalCollected').textContent = '-';
    document.getElementById('pfTotalUncollected').textContent = '-';
  }
}

// ===== 포트폴리오 AI 분석 =====
async function loadPortfolioAnalysis() {
  const body = document.getElementById('pfAnalysisBody');
  const timeEl = document.getElementById('pfAnalysisTime');
  try {
    const res = await safeFetch('/api/fund/portfolio-analysis');
    if (!res.ok) return;
    const data = await res.json();

    const portfolio = data.portfolio || [];
    const projects = data.projects || {};

    if (portfolio.length === 0 && Object.keys(projects).length === 0) {
      body.innerHTML = '<p class="pf-analysis-empty">아직 분석 결과가 없습니다. \'새로 분석하기\'를 눌러 AI 분석을 시작하세요.</p>';
      timeEl.textContent = '';
      return;
    }

    let html = '';

    // 포트폴리오 전체 인사이트
    const pfInsight = portfolio.find(i => i.insight_type === 'portfolio');
    if (pfInsight) {
      html += `<div class="analysis-card">
        <div class="analysis-card-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
          전체 포트폴리오 분석
        </div>
        <div class="analysis-card-content">${escapeHtml(pfInsight.content)}</div>
      </div>`;
      const dt = new Date(pfInsight.generated_at);
      timeEl.textContent = `${dt.getMonth()+1}/${dt.getDate()} ${dt.getHours()}:${String(dt.getMinutes()).padStart(2,'0')} 분석`;
    }

    // 프로젝트별 주요 리스크/액션 요약
    const pidList = Object.keys(projects);
    if (pidList.length > 0) {
      html += '<div class="analysis-card"><div class="analysis-card-title">';
      html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
      html += '프로젝트별 핵심 리스크 & 실행 권고</div><div class="analysis-card-content">';
      for (const pid of pidList) {
        const pdata = projects[pid];
        const risk = pdata.items.find(i => i.type === 'risk');
        const action = pdata.items.find(i => i.type === 'action');
        html += `<strong>${escapeHtml(pdata.project_name)}</strong>\n`;
        if (risk) html += `  리스크: ${escapeHtml(risk.content)}\n`;
        if (action) html += `  권고: ${escapeHtml(action.content)}\n`;
        html += '\n';
      }
      html += '</div></div>';
    }

    body.innerHTML = html;
  } catch (e) {
    console.error('포트폴리오 분석 로드 실패:', e);
  }
}

async function generatePortfolioAnalysis() {
  const btn = document.getElementById('pfAnalyzeBtn');
  const body = document.getElementById('pfAnalysisBody');

  btn.disabled = true;
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 1 4 4c0 1.95-1.4 3.58-3.25 3.93L12 22l-.75-12.07A4.001 4.001 0 0 1 12 2z"/></svg> 분석 중...';
  body.innerHTML = '<div class="pf-analysis-loading"><div class="spinner"></div><span>AI가 전체 포트폴리오를 분석하고 있습니다...</span></div>';

  try {
    const res = await safeFetch('/api/fund/insights/generate', { method: 'POST' });
    if (!res.ok) throw new Error('분석 실패');
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '분석 실패');
    showToast('포트폴리오 분석이 완료되었습니다.', 'success');
    await loadPortfolioAnalysis();
  } catch (e) {
    body.innerHTML = `<p class="pf-analysis-empty">분석에 실패했습니다: ${escapeHtml(e.message)}</p>`;
    showToast('분석 실패: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 1 4 4c0 1.95-1.4 3.58-3.25 3.93L12 22l-.75-12.07A4.001 4.001 0 0 1 12 2z"/></svg> 새로 분석하기';
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
  const countEl = document.getElementById('projectCount');

  if (countEl) countEl.textContent = projectsCache.length;

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
        data-id="${p.id}" draggable="true">
      ${gradeBadge}
      <span class="project-name">${escapeHtml(p.name)}</span>
      <button class="project-delete" data-delete-project="${p.id}"
              title="프로젝트 삭제">&times;</button>
    </li>`;
  }).join('');
}

// ===== 프로젝트 드래그 정렬 =====
let dragProjectId = null;

function onProjectDragStart(e, li) {
  dragProjectId = parseInt(li.dataset.id);
  li.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onProjectDragOver(e, li) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if (!li.classList.contains('drag-over')) {
    document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
    li.classList.add('drag-over');
  }
}

async function onProjectDrop(e, li) {
  e.preventDefault();
  const targetId = parseInt(li.dataset.id);
  document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
  if (dragProjectId === targetId) return;

  // 순서 변경
  const fromIdx = projectsCache.findIndex(p => p.id === dragProjectId);
  const toIdx = projectsCache.findIndex(p => p.id === targetId);
  if (fromIdx < 0 || toIdx < 0) return;
  const [moved] = projectsCache.splice(fromIdx, 1);
  projectsCache.splice(toIdx, 0, moved);
  renderProjectList();
  await saveProjectOrder();
  // 포트폴리오 테이블도 같은 순서로 갱신
  loadPortfolioView();
}

function onProjectDragEnd(e, li) {
  li.classList.remove('dragging');
  document.querySelectorAll('.project-item.drag-over').forEach(el => el.classList.remove('drag-over'));
  dragProjectId = null;
}

async function saveProjectOrder() {
  const order = projectsCache.map(p => ({ id: p.id }));
  try {
    await safeFetch('/api/fund/projects/reorder', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order })
    });
  } catch (e) {
    // 순서 저장 실패 시 무시
  }
}

// ===== 포트폴리오 테이블 드래그 정렬 =====
let dragPfRowId = null;

function onPfRowDragStart(e, row) {
  dragPfRowId = parseInt(row.dataset.id);
  row.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onPfRowDragOver(e, row) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if (!row.classList.contains('pf-drag-over')) {
    document.querySelectorAll('.pf-row-clickable.pf-drag-over').forEach(el => el.classList.remove('pf-drag-over'));
    row.classList.add('pf-drag-over');
  }
}

async function onPfRowDrop(e, row) {
  e.preventDefault();
  const targetId = parseInt(row.dataset.id);
  document.querySelectorAll('.pf-row-clickable.pf-drag-over').forEach(el => el.classList.remove('pf-drag-over'));
  if (dragPfRowId === targetId) return;

  // projectsCache 순서 변경
  const fromIdx = projectsCache.findIndex(p => p.id === dragPfRowId);
  const toIdx = projectsCache.findIndex(p => p.id === targetId);
  if (fromIdx < 0 || toIdx < 0) return;
  const [moved] = projectsCache.splice(fromIdx, 1);
  projectsCache.splice(toIdx, 0, moved);

  // 사이드바 동기화 + 서버 저장 후 포트폴리오 갱신
  renderProjectList();
  await saveProjectOrder();
  loadPortfolioView();
}

function onPfRowDragEnd(e, row) {
  row.classList.remove('dragging');
  document.querySelectorAll('.pf-row-clickable.pf-drag-over').forEach(el => el.classList.remove('pf-drag-over'));
  dragPfRowId = null;
}

// ===== 프로젝트 선택 =====
async function selectProject(id) {
  currentProjectId = id;
  renderProjectList();

  const project = projectsCache.find(p => p.id === id);
  if (project) {
    document.getElementById('pageTitle').textContent = project.name;
  }

  // 모바일: 사이드바 닫기
  const sidebar = document.querySelector('.fund-sidebar');
  sidebar.classList.remove('open');
  const overlay = document.getElementById('sidebarOverlay');
  if (overlay) overlay.remove();

  // 탭 바 표시, 포트폴리오 버튼 표시
  document.getElementById('tabBar').style.display = 'flex';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('portfolioBtn').style.display = 'inline-flex';

  // 공종 캐시 로드
  await loadTradesCache(id);

  // 자료실 로드
  loadMaterials();

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
      <label>GW 사업코드 <small style="color:#888;">(입력 시 자동으로 GW 정보를 가져옵니다)</small></label>
      <input type="text" id="modalProjectCode" placeholder="예: GS-25-0088" />
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
    const projectCode = document.getElementById('modalProjectCode').value.trim();
    const constructionAmount = parseInt(document.getElementById('modalContractAmt').value) || 0;
    const executionBudget = parseInt(document.getElementById('modalBudgetAmt').value) || 0;

    const payload = { name, grade, construction_amount: constructionAmount, execution_budget: executionBudget };
    if (projectCode) payload.project_code = projectCode;

    try {
      const res = await safeFetch('/api/fund/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || '프로젝트 생성 실패');
      }
      const data = await res.json();
      closeModal();
      if (data.crawling) {
        showToast('프로젝트가 생성되었습니다. GW 정보를 백그라운드에서 가져오는 중입니다...', 'success');
      } else {
        showToast('프로젝트가 생성되었습니다.', 'success');
      }
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
    const res = await safeFetch(`/api/fund/projects/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('프로젝트 삭제 실패');

    showToast('프로젝트가 삭제되었습니다.', 'success');
    if (currentProjectId === id) {
      currentProjectId = null;
      document.getElementById('pageTitle').textContent = '프로젝트를 선택하세요';
      document.getElementById('tabBar').style.display = 'none';
      hideAllPanels();
      document.getElementById('emptyState').style.display = 'block';
      loadPortfolioView();
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

  // dirty 탭이면 항상 새로고침, 아니어도 로드
  dirtyTabs.delete(tabName);

  // 탭별 데이터 로드
  if (!currentProjectId) return;
  refreshTab(tabName, currentProjectId);
}

function hideAllPanels() {
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
}

// ===== 포트폴리오 화면으로 이동 =====
function goToPortfolio() {
  currentProjectId = null;
  document.getElementById('pageTitle').textContent = '포트폴리오 현황';
  document.getElementById('tabBar').style.display = 'none';
  document.getElementById('portfolioBtn').style.display = 'none';
  hideAllPanels();
  document.getElementById('emptyState').style.display = 'block';
  renderProjectList();
  loadPortfolioView();
}

// ===== 공종 캐시 =====
async function loadTradesCache(projectId) {
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/trades`);
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
    // 모든 데이터를 병렬로 조회
    const [summaryRes, collRes, subRes, overviewRes] = await Promise.all([
      safeFetch(`/api/fund/projects/${projectId}/summary`),
      safeFetch(`/api/fund/projects/${projectId}/collections`),
      safeFetch(`/api/fund/projects/${projectId}/subcontracts`),
      safeFetch(`/api/fund/projects/${projectId}/overview`),
    ]);

    const summaryData = summaryRes.ok ? await summaryRes.json() : {};
    const collData = collRes.ok ? await collRes.json() : { collections: [] };
    const subData = subRes.ok ? await subRes.json() : { subcontracts: [] };
    const ovData = overviewRes.ok ? await overviewRes.json() : { overview: {} };

    const s = summaryData.summary || summaryData;
    const ov = ovData.overview || {};
    const colls = collData.collections || [];
    const subs = subData.subcontracts || [];

    // ─── 1) 금액 요약 카드 (상단) ───
    const totalOrder = (s.design_amount || 0) + (s.construction_amount || 0);
    document.getElementById('valContract').textContent = formatWon(s.total_order || totalOrder);
    document.getElementById('valBudget').textContent = formatWon(s.execution_budget || 0);
    document.getElementById('valProfit').textContent = formatWon(s.profit_amount || 0);
    document.getElementById('valMargin').textContent = (s.profit_rate || 0).toFixed(1) + '%';

    // 하도급 기지급액 / 지급총한도 / 잔여지급한도 계산
    let paymentLimit = 0, totalPaid = 0;
    subs.forEach(sc => {
      paymentLimit += (sc.contract_amount || 0);
      if (sc.payment_1_confirmed) totalPaid += (sc.payment_1 || 0);
      if (sc.payment_2_confirmed) totalPaid += (sc.payment_2 || 0);
      if (sc.payment_3_confirmed) totalPaid += (sc.payment_3 || 0);
      if (sc.payment_4_confirmed) totalPaid += (sc.payment_4 || 0);
    });
    document.getElementById('valPaymentLimit').textContent = formatWon(paymentLimit);
    document.getElementById('valTotalPaid').textContent = formatWon(totalPaid);
    document.getElementById('valRemainingLimit').textContent = formatWon(paymentLimit - totalPaid);

    // 수금 요약
    let collTotal = 0, collCollected = 0;
    colls.forEach(c => {
      collTotal += (c.amount || 0);
      if (c.collected) collCollected += (c.amount || 0);
    });
    document.getElementById('valDashCollected').textContent = formatWon(collCollected);
    const collRate = collTotal ? (collCollected / collTotal * 100) : 0;
    document.getElementById('valDashCollectionRate').textContent = collRate.toFixed(1) + '%';

    // ─── 1.5) 진행률 차트 ───
    // 수금 진행률
    const collPct = collTotal ? (collCollected / collTotal * 100) : 0;
    document.getElementById('chartCollectionPct').textContent = collPct.toFixed(1) + '%';
    document.getElementById('chartCollectionFill').style.width = Math.min(collPct, 100) + '%';
    document.getElementById('chartCollected').textContent = formatWon(collCollected);
    document.getElementById('chartUncollected').textContent = formatWon(collTotal - collCollected);

    // 지급 진행률
    const payPct = paymentLimit ? (totalPaid / paymentLimit * 100) : 0;
    document.getElementById('chartPaymentPct').textContent = payPct.toFixed(1) + '%';
    document.getElementById('chartPaymentFill').style.width = Math.min(payPct, 100) + '%';
    document.getElementById('chartPaid').textContent = formatWon(totalPaid);
    document.getElementById('chartRemaining').textContent = formatWon(paymentLimit - totalPaid);

    // 예산 집행률 (기지급액 / 실행예산)
    const execBudget = s.execution_budget || 0;
    const budgetPct = execBudget ? (totalPaid / execBudget * 100) : 0;
    document.getElementById('chartBudgetPct').textContent = budgetPct.toFixed(1) + '%';
    document.getElementById('chartBudgetFill').style.width = Math.min(budgetPct, 100) + '%';
    document.getElementById('chartExecuted').textContent = formatWon(totalPaid);
    document.getElementById('chartBudgetRemain').textContent = formatWon(Math.max(execBudget - totalPaid, 0));

    // 공정 진행률 (마일스톤)
    const msAll = (ovData.overview || {}).milestones || [];
    const msDone = msAll.filter(m => m.completed).length;
    const msPct = msAll.length ? (msDone / msAll.length * 100) : 0;
    document.getElementById('chartMilestonePct').textContent = msPct.toFixed(0) + '%';
    document.getElementById('chartMilestoneFill').style.width = Math.min(msPct, 100) + '%';
    document.getElementById('chartMsDone').textContent = msDone + '건';
    document.getElementById('chartMsRemain').textContent = (msAll.length - msDone) + '건';

    // ─── 2) 프로젝트 정보 ───
    document.getElementById('dashCategory').textContent = ov.project_category || '-';
    document.getElementById('dashLocation').textContent = ov.location || '-';
    document.getElementById('dashUsage').textContent = ov.usage || '-';
    document.getElementById('dashScale').textContent = ov.scale || '-';
    document.getElementById('dashArea').textContent = ov.area_pyeong ? ov.area_pyeong + '평' : '-';
    document.getElementById('dashStatus').textContent = ov.current_status || '-';

    // ─── 3) 일정 / 계약 ───
    const fmtDate = (d) => d ? d.replace(/-/g, '.') : '-';
    const period = (start, end) => {
      if (!start && !end) return '-';
      return `${fmtDate(start)} ~ ${fmtDate(end)}`;
    };
    document.getElementById('dashDesignPeriod').textContent = period(ov.design_start, ov.design_end);
    document.getElementById('dashConstructionPeriod').textContent = period(ov.construction_start, ov.construction_end);
    document.getElementById('dashOpenDate').textContent = ov.open_date || '-';
    document.getElementById('dashDesignContract').textContent =
      ov.design_contract_amount ? `${fmtDate(ov.design_contract_date)} / ${formatWon(ov.design_contract_amount)}원` : '-';
    document.getElementById('dashConstructionContract').textContent =
      ov.construction_contract_amount ? `${fmtDate(ov.construction_contract_date)} / ${formatWon(ov.construction_contract_amount)}원` : '-';

    // ─── 4) 진행상황 ───
    const milestoneEl = document.getElementById('dashMilestones');
    const milestones = ov.milestones || [];
    if (milestones.length === 0) {
      milestoneEl.innerHTML = '<p class="no-data-text">진행 단계 없음</p>';
    } else {
      const completedCount = milestones.filter(m => m.completed).length;
      const pct = milestones.length ? (completedCount / milestones.length * 100) : 0;
      milestoneEl.innerHTML = `
        <div class="dash-progress-bar">
          <div class="dash-progress-fill" style="width:${pct}%"></div>
        </div>
        <p class="dash-progress-text">${completedCount} / ${milestones.length} 완료 (${pct.toFixed(0)}%)</p>
        <div class="dash-checklist">
          ${milestones.map((m, i) => `
            <div class="dash-check-item ${m.completed ? 'done' : ''}">
              <span class="dash-check-icon">${m.completed ? '☑' : '☐'}</span>
              <span class="dash-check-name">${escapeHtml(m.name || '단계')}</span>
              ${m.date ? `<span class="dash-check-date">${escapeHtml(m.date)}</span>` : ''}
            </div>
          `).join('')}
        </div>`;
    }

    // ─── 5) 이슈사항 ───
    const issueEl = document.getElementById('dashIssues');
    const issueFields = [
      { key: 'issue_design', label: '디자인/인허가' },
      { key: 'issue_schedule', label: '일정' },
      { key: 'issue_budget', label: '예산' },
      { key: 'issue_operation', label: '운영' },
      { key: 'issue_defect', label: '하자' },
      { key: 'issue_other', label: '기타' },
    ];
    const activeIssues = issueFields.filter(f => ov[f.key]);
    if (activeIssues.length === 0) {
      issueEl.innerHTML = '<p class="no-data-text">이슈 없음</p>';
    } else {
      issueEl.innerHTML = activeIssues.map(f => `
        <div class="dash-issue-item">
          <span class="dash-issue-label">${f.label}</span>
          <span class="dash-issue-value">${escapeHtml(ov[f.key])}</span>
        </div>
      `).join('');
    }

    // ─── 6) 수금현황 테이블 ───
    const collBody = document.getElementById('dashCollectionBody');
    if (colls.length === 0) {
      collBody.innerHTML = '<tr><td colspan="4" class="no-data">수금 데이터 없음</td></tr>';
    } else {
      collBody.innerHTML = colls.map(c => `<tr>
        <td>${escapeHtml(c.category || '-')}</td>
        <td>${escapeHtml(c.stage || '-')}</td>
        <td class="num">${formatWon(c.amount || 0)}</td>
        <td class="chk">${c.collected ? '<span class="badge-done">완료</span>' : '<span class="badge-pending">대기</span>'}</td>
      </tr>`).join('');
    }

    // ─── 7) 배정인원 ───
    const memberEl = document.getElementById('dashMembers');
    const members = ov.members || [];
    if (members.length === 0) {
      memberEl.innerHTML = '<p class="no-data-text">배정인원 없음</p>';
    } else {
      memberEl.innerHTML = members.map(m => `
        <div class="dash-member-item">
          <span class="dash-member-role">${escapeHtml(m.role || '-')}</span>
          <span class="dash-member-name">${escapeHtml(m.name || '-')}</span>
        </div>
      `).join('');
    }

    // 인사이트 필터링 갱신 (현재 프로젝트만)
    renderInsights();

  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 개요 탭 =====
async function loadOverview(projectId) {
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/overview`);
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

    // 등급 + 사업코드는 projects 테이블 → 캐시에서 로드
    const project = projectsCache.find(p => p.id === projectId);
    const gradeSelect = document.getElementById('ovGradeSelect');
    if (gradeSelect && project) {
      gradeSelect.value = project.grade || '';
    }
    const codeInput = document.getElementById('ovProjectCode');
    if (codeInput && project) {
      codeInput.value = project.project_code || '';
    }

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
      <td><button class="btn-icon btn-remove-row" title="삭제">&times;</button></td>
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
    <td><button class="btn-icon btn-remove-row" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
}

function renderMilestones(milestones) {
  const container = document.getElementById('milestoneBody');
  if (!container) return;
  if (milestones.length === 0) {
    container.innerHTML = '<tr><td colspan="5" class="no-data">진행 단계 없음</td></tr>';
    updateMilestoneProgress([]);
    return;
  }
  container.innerHTML = milestones.map((ms, idx) => `
    <tr data-id="${ms.id || ''}" class="${ms.completed ? 'ms-done' : ''}">
      <td class="ms-num">${idx + 1}</td>
      <td><input type="text" class="ms-name-field" data-field="name" value="${escapeHtml(ms.name)}" placeholder="단계명" /></td>
      <td class="chk"><input type="checkbox" class="ms-field ms-toggle-completed" data-field="completed" ${ms.completed ? 'checked' : ''} /></td>
      <td><input type="text" class="ms-date-field" data-field="date" value="${escapeHtml(ms.date || '')}" placeholder="날짜" /></td>
      <td><button class="btn-icon btn-del-ms btn-del-ms-action" title="삭제">&times;</button></td>
    </tr>
  `).join('');
  updateMilestoneProgress(milestones);
}

function toggleMilestoneRow(checkbox) {
  const tr = checkbox.closest('tr');
  if (checkbox.checked) {
    tr.classList.add('ms-done');
  } else {
    tr.classList.remove('ms-done');
  }
  updateMilestoneProgress();
}

function updateMilestoneProgress(milestones) {
  // DOM에서 직접 계산
  const rows = document.querySelectorAll('#milestoneBody tr:not(.no-data)');
  const total = rows.length;
  const completed = document.querySelectorAll('#milestoneBody tr .ms-field:checked').length;
  const pct = total > 0 ? (completed / total * 100) : 0;

  const fill = document.getElementById('msProgressFill');
  const text = document.getElementById('msProgressText');
  const badge = document.getElementById('msProgressBadge');

  if (fill) fill.style.width = pct + '%';
  if (text) text.textContent = total > 0 ? `${completed}/${total} (${pct.toFixed(0)}%)` : '';
  if (badge) {
    if (total === 0) {
      badge.textContent = '';
    } else if (completed === total) {
      badge.textContent = '완료';
      badge.className = 'ms-progress-badge badge-complete';
    } else {
      badge.textContent = '진행중';
      badge.className = 'ms-progress-badge badge-progress';
    }
  }
}

function addMilestoneRow() {
  const tbody = document.getElementById('milestoneBody');
  const noData = tbody.querySelector('.no-data');
  if (noData) noData.parentElement.remove();

  const rows = tbody.querySelectorAll('tr');
  const num = rows.length + 1;
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="ms-num">${num}</td>
    <td><input type="text" class="ms-name-field" data-field="name" value="" placeholder="단계명" /></td>
    <td class="chk"><input type="checkbox" class="ms-field ms-toggle-completed" data-field="completed" /></td>
    <td><input type="text" class="ms-date-field" data-field="date" value="" placeholder="날짜" /></td>
    <td><button class="btn-icon btn-del-ms btn-del-ms-action" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
  // 새 행의 이름 인풋에 포커스
  tr.querySelector('.ms-name-field').focus();
  updateMilestoneProgress();
}

// 상단 "그룹웨어에서 가져오기" 버튼 핸들러
async function handleGwImport() {
  if (!currentProjectId) {
    showToast('프로젝트를 먼저 선택해주세요.', 'error');
    return;
  }
  const project = projectsCache.find(p => p.id === currentProjectId);
  const projectCode = project?.project_code;

  if (projectCode) {
    // 사업코드 이미 있음 → 바로 동기화
    await syncGwAfterCodeSet();
  } else {
    // 사업코드 없음 → 검색 모달
    openGwProjectSearch();
  }
}

async function crawlFromGW() {
  if (!currentProjectId) {
    showToast('프로젝트를 먼저 선택해주세요.', 'error');
    return;
  }

  // 캐시에서 프로젝트 조회 — 캐시가 오래되었을 수 있으므로 개요 입력값도 확인
  const project = projectsCache.find(p => p.id === currentProjectId);
  const inputCode = document.getElementById('ovProjectCode')?.value?.trim();
  const projectCode = inputCode || project?.project_code;

  if (!projectCode) {
    showToast('GW 사업코드가 설정되지 않았습니다. 개요 탭에서 "그룹웨어에서 가져오기" 버튼을 이용해주세요.', 'error');
    return;
  }

  // 입력된 사업코드가 캐시와 다르면 먼저 저장
  if (inputCode && inputCode !== project?.project_code) {
    try {
      await safeFetch(`/api/fund/projects/${currentProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_code: inputCode })
      });
      // 캐시 업데이트
      if (project) project.project_code = inputCode;
    } catch (e) {
      showToast('사업코드 저장 실패: ' + e.message, 'error');
      return;
    }
  }

  const btn = document.getElementById('crawlGwBtn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> 크롤링 중... (최대 3분 소요)';

  try {
    const { data } = await gwFetch(`/api/fund/projects/${currentProjectId}/crawl-gw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (data.success) {
      // 상세 결과 메시지 구성
      let msg = data.message || 'GW에서 프로젝트 정보를 가져왔습니다.';
      if (data.details && data.details.length > 0) {
        const detailMsgs = data.details
          .map(d => `${d.item}: ${d.status === 'success' ? d.message : '실패'}`)
          .join(', ');
        msg += ` (${detailMsgs})`;
      }
      showToast(msg, 'success');
      // 개요 데이터 새로고침
      await loadOverview(currentProjectId);
      // 프로젝트 목록 갱신 (사업코드 등 반영)
      await loadProjects();
      // 예실대비 탭 갱신
      loadBudget(currentProjectId);
      // 대시보드도 갱신 (예산 데이터 반영)
      markRelatedTabsDirty('overview');
    } else {
      // 실패한 단계 상세 표시
      let errMsg = data.error || data.detail || data.message || '크롤링 실패';
      if (data.details && data.details.length > 0) {
        const failDetails = data.details
          .filter(d => d.status !== 'success')
          .map(d => `${d.item}: ${d.message}`)
          .join('\n');
        if (failDetails) errMsg += '\n\n실패 상세:\n' + failDetails;
      }
      showToast(errMsg, 'error');
      if (data.details) console.log('GW 크롤링 상세:', data.details);
    }
  } catch (e) {
    showToast('GW 크롤링 요청 실패: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
}

// 개요 탭에서 "그룹웨어에서 가져오기" 버튼 → GW 프로젝트 검색 모달
function openGwProjectSearch() {
  if (!currentProjectId) return;

  openModal('GW 프로젝트 검색', `
    <div class="form-group">
      <label>키워드 입력</label>
      <div style="display:flex;gap:6px;">
        <input type="text" id="gwSearchName" placeholder="프로젝트명, 사업코드 등 키워드 입력" style="flex:1;" />
        <button class="btn btn-primary btn-sm" id="gwSearchBtn" style="white-space:nowrap;">검색</button>
      </div>
      <small style="color:#888;margin-top:4px;display:block;">일부 키워드만 입력해도 검색됩니다. (예: 의림지, 카페, 오블리브)</small>
    </div>
    <div id="gwSearchResults" style="margin-top:12px;">
      <div id="gwCacheInfo" style="display:none;padding:4px 14px;font-size:11px;color:#94a3b8;justify-content:space-between;align-items:center;margin-bottom:4px;"></div>
      <div id="gwSearchList" style="max-height:300px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;"></div>
    </div>
    <div id="gwSearchLoading" style="display:none;text-align:center;padding:20px;">
      <span class="loading-spinner"></span> 그룹웨어에서 프로젝트 목록을 가져오는 중... (최대 3분 소요)
    </div>
    <div id="gwFetchPrompt" style="display:none;text-align:center;padding:16px;">
      <p style="color:#64748b;margin-bottom:12px;">GW 프로젝트 목록이 아직 없습니다.<br>최초 1회 그룹웨어에서 전체 목록을 가져와야 합니다.</p>
      <button class="btn btn-primary" id="gwFetchListBtn">GW에서 프로젝트 목록 가져오기</button>
    </div>
  `, null, [
    { label: '닫기', className: 'btn-outlined', id: 'gwCloseBtn', handler: closeModal }
  ]);

  setTimeout(() => {
    const input = document.getElementById('gwSearchName');
    if (input) {
      input.focus();
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doGwProjectSearch();
      });
      // 타이핑할 때 실시간 검색 (300ms 디바운스)
      let debounceTimer;
      input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => doGwProjectSearch(), 300);
      });
    }
    document.getElementById('gwSearchBtn')?.addEventListener('click', doGwProjectSearch);
    document.getElementById('gwFetchListBtn')?.addEventListener('click', fetchGwProjectList);

    // 초기 검색 (캐시 있으면 전체 목록 표시)
    doGwProjectSearch();
  }, 100);
}

async function doGwProjectSearch() {
  const nameInput = document.getElementById('gwSearchName');
  const searchName = nameInput?.value?.trim() || '';
  const resultsEl = document.getElementById('gwSearchResults');
  const listEl = document.getElementById('gwSearchList');
  const fetchPrompt = document.getElementById('gwFetchPrompt');

  try {
    const { data } = await gwFetch('/api/fund/gw/search-projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ search_name: searchName }),
    });

    // 캐시 없으면 가져오기 안내
    if (data.need_fetch) {
      resultsEl.style.display = 'none';
      fetchPrompt.style.display = 'block';
      return;
    }

    fetchPrompt.style.display = 'none';
    resultsEl.style.display = 'block';

    if (!data.success || !data.projects || data.projects.length === 0) {
      listEl.innerHTML = '<div style="padding:16px;text-align:center;color:#64748b;">검색 결과가 없습니다.</div>';
      return;
    }

    // 캐시 정보 + 다시 가져오기 버튼 (목록 밖에 표시)
    const cacheInfoEl = document.getElementById('gwCacheInfo');
    if (cacheInfoEl && data.cache_updated) {
      cacheInfoEl.style.display = 'flex';
      cacheInfoEl.innerHTML = `
        <span>총 ${data.cache_count}개 중 ${data.total}개 표시 · 동기화: ${data.cache_updated?.slice(0, 16)}</span>
        <button id="gwRefreshBtn" style="font-size:11px;padding:2px 8px;color:#3b82f6;border:1px solid #3b82f6;background:transparent;border-radius:4px;cursor:pointer;">🔄 다시 가져오기</button>
      `;
      document.getElementById('gwRefreshBtn')?.addEventListener('click', fetchGwProjectList);
    }

    listEl.innerHTML = data.projects.map(p => `
      <div class="gw-search-item" data-code="${escapeHtml(p.code)}" data-name="${escapeHtml(p.name)}"
           style="padding:10px 14px;cursor:pointer;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center;transition:background 0.15s;">
        <div>
          <div style="font-weight:600;color:#1e293b;">${escapeHtml(p.name)}</div>
          <div style="font-size:12px;color:#64748b;">사업코드: ${escapeHtml(p.code)}</div>
        </div>
        <button class="btn btn-xs btn-primary" style="white-space:nowrap;">선택</button>
      </div>
    `).join('');

    listEl.querySelectorAll('.gw-search-item').forEach(el => {
      el.addEventListener('mouseenter', () => el.style.background = '#f0f7ff');
      el.addEventListener('mouseleave', () => el.style.background = '');
      el.addEventListener('click', () => selectGwProject(el.dataset.code, el.dataset.name));
    });

  } catch (e) {
    resultsEl.style.display = 'block';
    listEl.innerHTML = `<div style="padding:16px;text-align:center;color:#e53e3e;">검색 실패: ${escapeHtml(e.message)}</div>`;
  }
}

async function fetchGwProjectList() {
  const fetchBtn = document.getElementById('gwFetchListBtn');
  const loadingEl = document.getElementById('gwSearchLoading');
  const fetchPrompt = document.getElementById('gwFetchPrompt');

  if (fetchBtn) fetchBtn.disabled = true;
  fetchPrompt.style.display = 'none';
  loadingEl.style.display = 'block';

  try {
    const { data } = await gwFetch('/api/fund/gw/fetch-project-list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    loadingEl.style.display = 'none';

    if (data.success) {
      showToast(data.message || 'GW 프로젝트 목록을 가져왔습니다.', 'success');
      doGwProjectSearch();  // 캐시된 결과로 재검색
    } else {
      fetchPrompt.style.display = 'block';
      showToast(data.error || 'GW 프로젝트 목록 가져오기 실패', 'error');
    }
  } catch (e) {
    loadingEl.style.display = 'none';
    fetchPrompt.style.display = 'block';
    showToast('GW 접속 실패: ' + e.message, 'error');
  } finally {
    if (fetchBtn) fetchBtn.disabled = false;
  }
}

async function selectGwProject(code, name) {
  if (!currentProjectId || !code) return;

  // 사업코드 저장
  try {
    await safeFetch(`/api/fund/projects/${currentProjectId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_code: code })
    });
    const cached = projectsCache.find(p => p.id === currentProjectId);
    if (cached) cached.project_code = code;

    // 사업코드 필드 업데이트
    const codeInput = document.getElementById('ovProjectCode');
    if (codeInput) codeInput.value = code;

    closeModal();
    showToast(`사업코드 '${code}' (${name})가 저장되었습니다.`, 'success');

    // GW 크롤링도 실행 (프로젝트정보 + 예실대비)
    const doSync = confirm(`사업코드가 저장되었습니다.\n그룹웨어에서 예산 데이터도 함께 가져올까요?\n(프로젝트 등록정보 + 예실대비현황)`);
    if (doSync) {
      await syncGwAfterCodeSet();
    }
  } catch (e) {
    showToast('사업코드 저장 실패: ' + e.message, 'error');
  }
}

// 사업코드 설정 후 GW 동기화
async function syncGwAfterCodeSet() {
  const btn = document.getElementById('crawlGwBtn');
  const origText = btn?.innerHTML;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> 동기화 중...';
  }

  try {
    const { data } = await gwFetch(`/api/fund/projects/${currentProjectId}/crawl-gw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (data.success) {
      let msg = data.message || 'GW에서 프로젝트 정보를 가져왔습니다.';
      if (data.details?.length > 0) {
        const detailMsgs = data.details
          .map(d => `${d.item}: ${d.status === 'success' ? d.message : '실패'}`)
          .join(', ');
        msg += ` (${detailMsgs})`;
      }
      showToast(msg, 'success');
      await loadOverview(currentProjectId);
      await loadProjects();
      loadBudget(currentProjectId);
      markRelatedTabsDirty('overview');
    } else {
      showToast(data.error || 'GW 동기화 실패', 'error');
    }
  } catch (e) {
    showToast('GW 동기화 실패: ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

// 포트폴리오 뷰 "전체 GW 동기화" 버튼 (프로젝트 등록정보 + 예실대비 일괄 크롤링)
async function syncAllGw() {
  if (!confirm('사업코드가 등록된 모든 프로젝트의 GW 정보를 일괄 동기화합니다.\n(프로젝트 등록정보 + 예실대비현황(사업별) + 합계)\n시간이 다소 걸릴 수 있습니다. 계속하시겠습니까?')) return;

  const btn = document.getElementById('pfSyncGwBtn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> 동기화 중...';

  try {
    const { data } = await gwFetch('/api/fund/crawl-gw-all', { method: 'POST' });
    if (data.success) {
      // 표준 응답: synced/failed/total 필드 활용
      let msg;
      if (data.total != null && data.failed > 0) {
        msg = `${data.total}개 중 ${data.synced || 0}개 동기화 완료, ${data.failed}개 실패`;
      } else {
        msg = data.message || `GW 동기화 완료 (${data.synced || 0}건)`;
      }
      showToast(msg, 'success');
      // 단계별 결과 콘솔 로깅
      if (data.stages) console.log('GW 동기화 단계별:', data.stages);
      if (data.details) console.log('GW 동기화 상세:', data.details);
      loadPortfolioView();  // 포트폴리오 새로고침
    } else {
      // 부분 실패 또는 전체 실패 — 단계 정보 포함
      let errMsg = data.error || '일괄 동기화 실패';
      if (data.total != null && data.synced > 0) {
        errMsg = `${data.total}개 중 ${data.synced}개 성공, ${data.failed}개 실패`;
      }
      // 실패한 단계 표시
      if (data.stages) {
        const failedStages = data.stages.filter(s => !s.success).map(s => s.stage);
        if (failedStages.length > 0) {
          errMsg += ` (실패 단계: ${failedStages.join(', ')})`;
        }
      }
      showToast(errMsg, 'error');
      if (data.stages) console.log('GW 동기화 단계별:', data.stages);
      if (data.details) console.log('GW 동기화 실패 상세:', data.details);
    }
  } catch (e) {
    showToast('GW 일괄 동기화 요청 실패: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
}

// PM팀 Official 시트에서 프로젝트 기본정보 가져오기
async function importPmSheet() {
  if (!confirm('PM팀 Official 시트에서 프로젝트 기본정보를 가져옵니다.\n(프로젝트 이름, 등급, 배정인원, 마일스톤, 개요 등)\n기존 프로젝트는 업데이트되고, 신규 프로젝트는 자동 생성됩니다.\n계속하시겠습니까?')) return;

  const btn = document.getElementById('pfImportPmBtn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> 가져오는 중...';

  try {
    const { data } = await gwFetch('/api/fund/import-pm-sheet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'upsert' }),
    });
    if (data.success) {
      const parts = [];
      if (data.created > 0) parts.push(`${data.created}개 생성`);
      if (data.updated > 0) parts.push(`${data.updated}개 업데이트`);
      if (data.skipped > 0) parts.push(`${data.skipped}개 스킵`);
      const msg = parts.length > 0
        ? `PM 시트 임포트 완료: ${parts.join(', ')}`
        : 'PM 시트에서 변경사항이 없습니다.';
      showToast(msg, 'success');
      if (data.errors && data.errors.length > 0) {
        console.warn('PM 시트 임포트 오류:', data.errors);
        showToast(`${data.errors.length}건의 오류가 발생했습니다. 콘솔을 확인하세요.`, 'warning');
      }
      loadSidebar();
      loadPortfolioView();
    } else {
      showToast(data.error || 'PM 시트 임포트 실패', 'error');
    }
  } catch (e) {
    showToast('PM 시트 임포트 요청 실패: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
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
    const name = tr.querySelector('[data-field="name"]')?.value?.trim() || '';
    const completed = tr.querySelector('[data-field="completed"]')?.checked ? 1 : 0;
    const date = tr.querySelector('[data-field="date"]')?.value?.trim() || '';
    if (name) milestones.push({ id, name, completed, date });
  });
  payload.milestones = milestones;

  // grade, project_code는 projects 테이블 필드 → 별도 API
  const grade = payload.grade;
  delete payload.grade;
  const projectCode = document.getElementById('ovProjectCode')?.value?.trim() || '';

  try {
    // 개요 저장
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/overview`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('저장 실패');

    // 등급 + 사업코드 변경 시 프로젝트 테이블 업데이트
    const projectUpdate = {};
    if (grade !== undefined) projectUpdate.grade = grade;
    projectUpdate.project_code = projectCode;  // 빈 문자열이면 사업코드 제거
    if (Object.keys(projectUpdate).length > 0) {
      await safeFetch(`/api/fund/projects/${currentProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(projectUpdate)
      });
      // 사이드바 프로젝트 목록 갱신 (등급 뱃지 반영)
      await loadProjects();
      if (currentProjectId) {
        document.querySelectorAll('.project-item').forEach(li => {
          li.classList.toggle('active', +li.dataset.id === currentProjectId);
        });
      }
    }

    showToast('프로젝트 개요가 저장되었습니다.', 'success');
    markRelatedTabsDirty('overview');
    await loadOverview(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 하도급상세 탭 =====
async function loadSubcontracts(projectId) {
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/subcontracts`);
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
      <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_1_confirmed" ${c1 ? 'checked' : ''} /></td>
      <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_2_confirmed" ${c2 ? 'checked' : ''} /></td>
      <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_3_confirmed" ${c3 ? 'checked' : ''} /></td>
      <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_4_confirmed" ${c4 ? 'checked' : ''} /></td>
      <td><button class="btn-icon btn-remove-sc-row" title="삭제">&times;</button></td>
    </tr>`;
  }).join('');

  // 금액 변경 재계산은 이벤트 위임으로 처리 (DOMContentLoaded 내 document change 리스너)
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
    <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_1_confirmed" /></td>
    <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_2_confirmed" /></td>
    <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_3_confirmed" /></td>
    <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_4_confirmed" /></td>
    <td><button class="btn-icon btn-remove-sc-row" title="삭제">&times;</button></td>
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
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/subcontracts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subcontracts: rows })
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('하도급 상세가 저장되었습니다.', 'success');
    markRelatedTabsDirty('budget-payment');
    await loadSubcontracts(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 하도급 업체 통합 테이블 =====
let vendorsCache = [];  // 현재 로드된 업체(contacts) 데이터

async function loadVendors(projectId) {
  // 공종 캐시도 함께 로드 (모달 드롭다운용)
  await loadTradesCache(projectId);

  const tbody = document.getElementById('vendorBody');
  tbody.innerHTML = '<tr><td colspan="7" class="no-data"><span class="loading-spinner"></span></td></tr>';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/contacts`);
    if (!res.ok) throw new Error('업체 조회 실패');
    const data = await res.json();
    vendorsCache = data.contacts || [];

    if (vendorsCache.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="no-data">등록된 하도급 업체가 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = vendorsCache.map((c, i) => `
      <tr data-id="${c.id}">
        <td>${i + 1}</td>
        <td>${escapeHtml(c.trade_name || '-')}</td>
        <td>${escapeHtml(c.vendor_name || c.company_name || '-')}</td>
        <td>${escapeHtml(c.contact_person || '-')}</td>
        <td>${escapeHtml(c.phone || '-')}</td>
        <td>${c.created_at ? formatDate(c.created_at) : '-'}</td>
        <td>
          <button class="btn btn-sm btn-outlined edit-vendor-btn" title="수정">수정</button>
          <button class="btn-icon delete-vendor-btn" title="삭제">&times;</button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="no-data">${escapeHtml(e.message)}</td></tr>`;
  }
}

/** 업체 추가/수정 모달 */
function openVendorModal(contactId) {
  const isEdit = !!contactId;

  // 편집 시 캐시에서 데이터 가져오기
  let contact = {};
  if (isEdit) {
    contact = vendorsCache.find(c => c.id === contactId) || {};
  }

  openModal(isEdit ? '업체 수정' : '업체 추가', `
    <div class="form-group">
      <label>공종</label>
      <select id="modalContactTrade">
        <option value="">-- 선택 --</option>
        ${tradesCache.map(t => `<option value="${t.id}" ${t.name === (contact.trade_name || '') ? 'selected' : ''}>${escapeHtml(t.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label>업체명 <span style="color:var(--danger)">*</span></label>
      <input type="text" id="modalVendorName" value="${escapeHtml(contact.vendor_name || contact.company_name || '')}" placeholder="업체명" />
    </div>
    <div class="form-group">
      <label>담당자</label>
      <input type="text" id="modalContactPerson" value="${escapeHtml(contact.contact_person || '')}" placeholder="담당자 이름" />
    </div>
    <div class="form-group">
      <label>담당자 연락처</label>
      <input type="text" id="modalPhone" value="${escapeHtml(contact.phone || '')}" placeholder="010-0000-0000" />
    </div>
    <div class="form-group">
      <label>이메일</label>
      <input type="text" id="modalEmail" value="${escapeHtml(contact.email || '')}" placeholder="email@example.com" />
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
      const res = await safeFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(isEdit ? '수정 실패' : '추가 실패');
      closeModal();
      showToast(isEdit ? '업체 정보가 수정되었습니다.' : '업체가 추가되었습니다.', 'success');
      markRelatedTabsDirty('vendors');
      await loadVendors(currentProjectId);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  setTimeout(() => document.getElementById('modalVendorName')?.focus(), 100);
}

/** 업체 삭제 */
async function deleteVendor(contactId) {
  const vendor = vendorsCache.find(c => c.id === contactId);
  const name = vendor ? (vendor.vendor_name || vendor.company_name || '이 업체') : '이 업체';
  if (!confirm(`"${name}"을(를) 삭제하시겠습니까?`)) return;

  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/contacts/${contactId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('업체 삭제 실패');
    showToast('업체가 삭제되었습니다.', 'success');
    markRelatedTabsDirty('vendors');
    await loadVendors(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 수금현황 탭 =====
async function loadCollections(projectId) {
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/collections`);
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
        <td class="num"><input type="number" class="coll-field coll-recalc-trigger" data-field="amount" value="${c.amount || 0}" /></td>
        <td class="chk"><input type="checkbox" class="coll-field coll-recalc-trigger" data-field="collected" ${c.collected ? 'checked' : ''} /></td>
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
        <td class="num"><input type="number" class="coll-field coll-recalc-trigger" data-field="amount" value="${c.amount || 0}" /></td>
        <td class="chk"><input type="checkbox" class="coll-field coll-recalc-trigger" data-field="collected" ${c.collected ? 'checked' : ''} /></td>
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
  // 설계/시공 테이블 각각에서 category 부여
  const collectFromTable = (tbody, category) => {
    tbody.querySelectorAll('tr').forEach(tr => {
      if (tr.querySelector('.no-data')) return;
      const item = { id: parseInt(tr.dataset.id) || null, category };
      // stage는 첫 번째 <td> 텍스트
      const firstTd = tr.querySelector('td');
      if (firstTd) item.stage = firstTd.textContent.trim();
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
  };
  collectFromTable(document.getElementById('collectionDesignBody'), '설계');
  collectFromTable(document.getElementById('collectionConstructionBody'), '시공');

  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/collections`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ collections: items })
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('수금현황이 저장되었습니다.', 'success');
    markRelatedTabsDirty('collections');
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
    const res = await safeFetch(`/api/fund/projects/${projectId}/payments`);
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

// ===== 예실대비 탭 (GW 크롤링 연동) =====
async function loadBudget(projectId) {
  const tbody = document.getElementById('budgetBody');
  tbody.innerHTML = '<tr><td colspan="7" class="no-data"><span class="loading-spinner"></span> 데이터 불러오는 중...</td></tr>';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/budget`);
    if (!res.ok) throw new Error('예실대비 조회 실패');
    const data = await res.json();
    const items = data.budget || [];

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="no-data">예실대비 데이터가 없습니다. "GW에서 가져오기"를 클릭하세요.</td></tr>';
      document.getElementById('budgetSummaryCards').style.display = 'none';
      document.getElementById('budgetMeta').style.display = 'none';
      // 합계 카드 숨기기
      const summaryTotals = document.getElementById('budgetSummaryTotals');
      if (summaryTotals) summaryTotals.style.display = 'none';
      return;
    }

    // 요약 카드 업데이트
    let totalBudget = 0, totalActual = 0;
    items.forEach(item => {
      totalBudget += (item.budget_amount || 0);
      totalActual += (item.actual_amount || 0);
    });
    const totalRemain = totalBudget - totalActual;
    const avgRate = totalBudget ? (totalActual / totalBudget * 100) : 0;

    document.getElementById('budgetTotalAmount').textContent = formatWon(totalBudget);
    document.getElementById('budgetTotalActual').textContent = formatWon(totalActual);
    document.getElementById('budgetTotalRemain').textContent = formatWon(totalRemain);
    document.getElementById('budgetAvgRate').textContent = avgRate.toFixed(1) + '%';
    document.getElementById('budgetSummaryCards').style.display = 'grid';

    // 합계 데이터 (projects.budget_summary) 표시
    _loadBudgetSummaryTotals(projectId);

    // 마지막 동기화 시각
    const latestSync = items.reduce((latest, item) => {
      const t = item.scraped_at || '';
      return t > latest ? t : latest;
    }, '');
    if (latestSync) {
      document.getElementById('budgetLastSync').textContent = formatDateTime(latestSync);
      document.getElementById('budgetMeta').style.display = 'block';
    }

    // 연도별 그룹 표시 (전기 데이터 구분)
    const years = [...new Set(items.map(i => i.year).filter(y => y))].sort();
    const hasMultiYear = years.length > 1;
    if (hasMultiYear) {
      const yearInfo = document.getElementById('budgetYearInfo');
      if (yearInfo) {
        yearInfo.textContent = `조회 기간: ${years[0]}~${years[years.length - 1]}`;
        yearInfo.style.display = 'inline-block';
      }
    }

    // 테이블 렌더링 — 집행율에 따라 색상 차등
    tbody.innerHTML = items.map(item => {
      const budget = item.budget_amount || 0;
      const actual = item.actual_amount || 0;
      const remain = item.difference || (budget - actual);
      const rate = item.execution_rate || (budget ? (actual / budget * 100) : 0);

      // 집행율 바 색상: 80% 이상 주의(orange), 95% 이상 위험(red)
      let barClass = 'pct-normal';
      if (rate >= 95) barClass = 'pct-danger';
      else if (rate >= 80) barClass = 'pct-warning';

      return `<tr>
        <td>${escapeHtml(item.budget_category || '-')}</td>
        <td class="code-cell">${escapeHtml(item.budget_code || '-')}</td>
        <td>${escapeHtml(item.budget_sub_category || '-')}</td>
        <td class="num">${formatWon(budget)}</td>
        <td class="num">${formatWon(actual)}</td>
        <td class="num ${remain < 0 ? 'text-danger' : ''}">${formatWon(remain)}</td>
        <td class="num">
          <div class="pct-bar-wrap">
            <div class="pct-bar ${barClass}" style="width:${Math.min(rate, 100)}%"></div>
            <span class="pct-label">${rate.toFixed(1)}%</span>
          </div>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="no-data">${escapeHtml(e.message)}</td></tr>`;
  }
}

// 예실대비 합계 데이터 (수입합계/지출합계/총잔액) 표시
async function _loadBudgetSummaryTotals(projectId) {
  const container = document.getElementById('budgetSummaryTotals');
  if (!container) return; // HTML에 컨테이너가 없으면 무시

  try {
    // 프로젝트 상세에서 budget_summary 가져오기
    const res = await safeFetch(`/api/fund/projects/${projectId}`);
    if (!res.ok) return;
    const project = await res.json();
    const summaryStr = project.budget_summary;
    if (!summaryStr) {
      container.style.display = 'none';
      return;
    }

    let summary;
    try {
      summary = typeof summaryStr === 'string' ? JSON.parse(summaryStr) : summaryStr;
    } catch (e) {
      container.style.display = 'none';
      return;
    }

    const income = summary.income_total || 0;
    const expense = summary.expense_total || 0;
    const balance = summary.total_balance || 0;

    if (income === 0 && expense === 0 && balance === 0) {
      container.style.display = 'none';
      return;
    }

    container.innerHTML = `
      <div class="summary-totals-row">
        <div class="summary-total-item">
          <span class="st-label">수입합계</span>
          <span class="st-value">${formatWon(income)}</span>
        </div>
        <div class="summary-total-item">
          <span class="st-label">지출합계</span>
          <span class="st-value">${formatWon(expense)}</span>
        </div>
        <div class="summary-total-item">
          <span class="st-label">총잔액</span>
          <span class="st-value ${balance < 0 ? 'text-danger' : ''}">${formatWon(balance)}</span>
        </div>
      </div>
    `;
    container.style.display = 'block';
  } catch (e) {
    console.log('합계 데이터 로드 실패:', e.message);
    container.style.display = 'none';
  }
}


// ===== 모달 유틸 =====
let modalConfirmCallback = null;

function openModal(title, bodyHtml, onConfirm, customFooter) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = bodyHtml;
  document.getElementById('modalOverlay').style.display = 'flex';
  modalConfirmCallback = onConfirm;

  const footer = document.getElementById('modalFooter');
  if (customFooter) {
    // 커스텀 버튼 배열: [{label, className, id?, handler?}]
    footer.innerHTML = customFooter.map(b =>
      `<button class="btn ${b.className || ''}" ${b.id ? `id="${b.id}"` : ''}>${b.label}</button>`
    ).join('');
    // CSP 호환: addEventListener로 핸들러 바인딩
    customFooter.forEach(b => {
      if (b.handler && b.id) {
        document.getElementById(b.id)?.addEventListener('click', b.handler);
      }
    });
  } else {
    footer.innerHTML = '';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-outlined';
    cancelBtn.id = 'modalCancelBtn';
    cancelBtn.textContent = '취소';
    cancelBtn.addEventListener('click', closeModal);
    footer.appendChild(cancelBtn);

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.id = 'modalConfirmBtn';
    confirmBtn.textContent = '확인';
    confirmBtn.addEventListener('click', () => {
      if (modalConfirmCallback) modalConfirmCallback();
    });
    footer.appendChild(confirmBtn);
  }
}

function closeModal() {
  document.getElementById('modalOverlay').style.display = 'none';
  modalConfirmCallback = null;
  // footer 복원 (커스텀 footer 사용 후 원래대로)
  const footer = document.getElementById('modalFooter');
  if (!footer.querySelector('#modalConfirmBtn')) {
    footer.innerHTML = '';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-outlined';
    cancelBtn.id = 'modalCancelBtn';
    cancelBtn.textContent = '취소';
    cancelBtn.addEventListener('click', closeModal);
    footer.appendChild(cancelBtn);

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.id = 'modalConfirmBtn';
    confirmBtn.textContent = '확인';
    footer.appendChild(confirmBtn);
  }
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
  if (value === null || value === undefined) return '0';
  const num = typeof value === 'string' ? parseInt(value) : value;
  return num.toLocaleString('ko-KR');
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

// escapeHtml은 파일 상단(line 7)에 정의됨 — 중복 제거 완료

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

// ===== AI 인사이트 =====
let insightsCache = [];
let todosCache = [];
let materialsCache = [];
let notificationsCache = [];

// 인사이트 초기화 (DOMContentLoaded에서 호출)
function initInsights() {
  // 인사이트 생성 버튼
  document.getElementById('generateInsightsBtn')?.addEventListener('click', generateInsights);

  // TODO 이벤트
  document.getElementById('addTodoBtn')?.addEventListener('click', openTodoModal);
  document.getElementById('todoFilter')?.addEventListener('change', renderTodos);
  document.getElementById('todoModalClose')?.addEventListener('click', closeTodoModal);
  document.getElementById('todoModalCancelBtn')?.addEventListener('click', closeTodoModal);
  document.getElementById('todoModalSaveBtn')?.addEventListener('click', saveTodo);
  document.getElementById('todoModalOverlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeTodoModal();
  });

  // TODO 이벤트 위임
  document.getElementById('todoList')?.addEventListener('change', (e) => {
    if (e.target.classList.contains('todo-checkbox')) toggleTodo(e.target);
  });
  document.getElementById('todoList')?.addEventListener('click', (e) => {
    const del = e.target.closest('.todo-delete');
    if (del) deleteTodo(+del.dataset.id);
  });

  // 인사이트 카드 토글/탭
  document.getElementById('projectInsightsList')?.addEventListener('click', (e) => {
    const header = e.target.closest('.pic-header');
    if (header) {
      const body = header.nextElementSibling;
      const toggle = header.querySelector('.pic-toggle');
      body.classList.toggle('open');
      toggle.classList.toggle('open');
    }
    const tab = e.target.closest('.insight-tab');
    if (tab) {
      const card = tab.closest('.project-insight-card');
      card.querySelectorAll('.insight-tab').forEach(t => t.classList.remove('active'));
      card.querySelectorAll('.insight-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      card.querySelector(`.insight-panel[data-type="${tab.dataset.type}"]`)?.classList.add('active');
    }
  });

  // 자료실 이벤트
  document.getElementById('addMaterialTextBtn')?.addEventListener('click', openMemoModal);
  document.getElementById('materialFileInput')?.addEventListener('change', handleMaterialUpload);
  document.getElementById('memoModalClose')?.addEventListener('click', closeMemoModal);
  document.getElementById('memoModalCancelBtn')?.addEventListener('click', closeMemoModal);
  document.getElementById('memoModalSaveBtn')?.addEventListener('click', saveMemo);
  document.getElementById('memoModalOverlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeMemoModal();
  });

  // 알림
  document.getElementById('notificationBtn')?.addEventListener('click', toggleNotificationPanel);
  document.getElementById('markAllReadBtn')?.addEventListener('click', markAllNotificationsRead);

  // 초기 데이터 로드
  loadTodos();
  loadInsights();
  loadNotifications();
}

// ===== 인사이트 로드/렌더 =====
async function loadInsights() {
  try {
    const res = await safeFetch('/api/fund/insights');
    if (res.ok) {
      const data = await res.json();
      insightsCache = data.insights || [];
      renderInsights();
    }
  } catch { /* ignore */ }
}

function renderInsights() {
  // 포트폴리오 인사이트 — 프로젝트 선택 시 숨김
  const portfolio = insightsCache.find(i => (!i.project_id || i.project_id === 0) && i.insight_type === 'portfolio');
  const box = document.getElementById('portfolioInsightBox');
  if (box) {
    if (portfolio && !currentProjectId) {
      box.style.display = 'block';
      document.getElementById('portfolioInsightContent').textContent = portfolio.content;
      const lastGen = document.getElementById('lastGeneratedText');
      if (lastGen) lastGen.textContent = `마지막 생성: ${formatDateTime(portfolio.generated_at)}`;
    } else {
      box.style.display = 'none';
    }
  }

  // 프로젝트별 인사이트 — 현재 선택된 프로젝트만 표시
  const filtered = currentProjectId
    ? insightsCache.filter(i => i.project_id === currentProjectId)
    : insightsCache.filter(i => i.project_id && i.project_id > 0);
  const projectIds = [...new Set(filtered.map(i => i.project_id))];
  const container = document.getElementById('projectInsightsList');
  if (!container) return;

  if (projectIds.length === 0) {
    const msg = currentProjectId
      ? '이 프로젝트의 인사이트가 없습니다. "인사이트 생성" 버튼을 눌러주세요.'
      : '"인사이트 생성" 버튼을 눌러 AI 분석을 시작하세요.';
    container.innerHTML = `<p class="no-data-text">${msg}</p>`;
    return;
  }

  const types = [
    { key: 'strategy', label: '현황 점검', cls: 'tab-strategy' },
    { key: 'risk', label: '놓치기 쉬운 리스크', cls: 'tab-risk' },
    { key: 'profitability', label: '자금 흐름', cls: 'tab-profitability' },
    { key: 'action', label: '지금 해야 할 일', cls: 'tab-action' },
  ];

  container.innerHTML = projectIds.map(pid => {
    const projectInsights = insightsCache.filter(i => i.project_id === pid);
    const projectName = projectInsights[0]?.project_name || `프로젝트 #${pid}`;
    const available = types.filter(t => projectInsights.find(i => i.insight_type === t.key));
    if (available.length === 0) return '';

    return `
      <div class="project-insight-card">
        <div class="pic-header">
          <span class="pic-title">${escapeHtml(projectName)}</span>
          <svg class="pic-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </div>
        <div class="pic-body">
          <div class="insight-tabs">
            ${available.map((t, i) => `<button class="insight-tab ${i === 0 ? 'active' : ''}" data-type="${t.key}">${t.label}</button>`).join('')}
          </div>
          ${available.map((t, i) => {
            const ins = projectInsights.find(i2 => i2.insight_type === t.key);
            return `<div class="insight-panel ${t.cls} ${i === 0 ? 'active' : ''}" data-type="${t.key}">${escapeHtml(ins?.content || '')}</div>`;
          }).join('')}
        </div>
      </div>`;
  }).join('');
}

async function generateInsights() {
  if (!confirm('전체 프로젝트 AI 인사이트를 생성합니다.\n진행하시겠습니까?')) return;

  const loading = document.getElementById('insightsLoading');
  const btn = document.getElementById('generateInsightsBtn');
  loading.style.display = 'flex';
  btn.disabled = true;

  try {
    const res = await safeFetch('/api/fund/insights/generate', { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || '인사이트 생성 실패');
    }
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '생성 실패');

    showToast('인사이트가 생성되었습니다!', 'success');
    await loadInsights();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    loading.style.display = 'none';
    btn.disabled = false;
  }
}

// ===== TODO =====
async function loadTodos() {
  try {
    const res = await safeFetch('/api/fund/todos');
    if (res.ok) {
      const data = await res.json();
      todosCache = data.todos || [];
      renderTodos();
    }
  } catch { /* ignore */ }
}

function renderTodos() {
  const container = document.getElementById('todoList');
  if (!container) return;
  const filter = document.getElementById('todoFilter')?.value || 'all';

  let filtered = todosCache;
  if (filter === 'pending') filtered = todosCache.filter(t => !t.completed);
  if (filter === 'completed') filtered = todosCache.filter(t => t.completed);

  if (filtered.length === 0) {
    container.innerHTML = '<p class="no-data-text">TODO 항목이 없습니다.</p>';
    return;
  }

  container.innerHTML = filtered.map(t => {
    const priorityLabel = { high: '높음', medium: '보통', low: '낮음' }[t.priority] || '보통';
    const projectName = t.project_name || projectsCache.find(p => p.id === t.project_id)?.name || '';

    return `
      <div class="todo-item ${t.completed ? 'completed' : ''}">
        <input type="checkbox" class="todo-checkbox" data-id="${t.id}" ${t.completed ? 'checked' : ''} />
        <span class="todo-text">${escapeHtml(t.content)}</span>
        <div class="todo-meta">
          ${projectName ? `<span class="badge-project-tag">${escapeHtml(projectName)}</span>` : ''}
          ${t.category ? `<span class="badge-category-tag">${escapeHtml(t.category)}</span>` : ''}
          <span class="todo-badge badge-${t.priority || 'medium'}">${priorityLabel}</span>
        </div>
        <button class="todo-delete" data-id="${t.id}" title="삭제">&times;</button>
      </div>`;
  }).join('');
}

async function toggleTodo(checkbox) {
  const id = +checkbox.dataset.id;
  const completed = checkbox.checked ? 1 : 0;
  try {
    const res = await safeFetch(`/api/fund/todos/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ completed }),
    });
    if (!res.ok) throw new Error('서버 오류');
    const todo = todosCache.find(t => t.id === id);
    if (todo) todo.completed = completed;
  } catch (e) {
    // 실패 시 체크박스 원복
    checkbox.checked = !checkbox.checked;
    showToast('TODO 상태 변경에 실패했습니다.', 'error');
  }
  renderTodos();
}

async function deleteTodo(id) {
  if (!confirm('이 TODO를 삭제하시겠습니까?')) return;
  try {
    const res = await safeFetch(`/api/fund/todos/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('서버 오류');
    todosCache = todosCache.filter(t => t.id !== id);
    renderTodos();
    showToast('TODO가 삭제되었습니다.', 'success');
  } catch (e) {
    showToast('TODO 삭제에 실패했습니다.', 'error');
  }
}

function openTodoModal() {
  const select = document.getElementById('todoProjectSelect');
  if (select) {
    select.innerHTML = '<option value="">-- 전체 --</option>' +
      projectsCache.map(p => `<option value="${p.id}" ${p.id === currentProjectId ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('');
  }
  document.getElementById('todoContentInput').value = '';
  document.getElementById('todoPrioritySelect').value = 'medium';
  document.getElementById('todoCategoryInput').value = '';
  document.getElementById('todoModalOverlay').style.display = 'flex';
  setTimeout(() => document.getElementById('todoContentInput')?.focus(), 100);
}

function closeTodoModal() {
  document.getElementById('todoModalOverlay').style.display = 'none';
}

async function saveTodo() {
  const content = document.getElementById('todoContentInput')?.value.trim();
  if (!content) { showToast('할 일을 입력하세요.', 'error'); return; }

  const project_id = document.getElementById('todoProjectSelect')?.value || null;
  const priority = document.getElementById('todoPrioritySelect')?.value || 'medium';
  const category = document.getElementById('todoCategoryInput')?.value.trim() || '';

  try {
    const res = await safeFetch('/api/fund/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, project_id: project_id ? +project_id : null, priority, category }),
    });
    if (!res.ok) throw new Error('저장 실패');
    closeTodoModal();
    showToast('TODO가 추가되었습니다.', 'success');
    await loadTodos();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 자료실 (Materials) =====
async function loadMaterials() {
  if (!currentProjectId) return;
  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/materials`);
    if (res.ok) {
      const data = await res.json();
      materialsCache = data.materials || [];
      renderMaterials();
    }
  } catch { /* ignore */ }
}

function renderMaterials() {
  const container = document.getElementById('materialsList');
  if (!container) return;

  if (materialsCache.length === 0) {
    container.innerHTML = '<p class="no-data-text">등록된 자료가 없습니다.</p>';
    return;
  }

  container.innerHTML = materialsCache.map(m => {
    const typeIcon = m.material_type === 'file' ? 'file' : m.material_type === 'text' ? 'text' : 'note';
    const typeLabel = m.material_type === 'file' ? (m.file_name?.split('.').pop()?.toUpperCase() || 'FILE') : (m.material_type === 'text' ? 'TXT' : 'MEMO');
    const displayName = m.file_name || m.description || '메모';
    return `
      <div class="material-item" data-id="${m.id}">
        <div class="material-icon ${typeIcon}">${typeLabel}</div>
        <div class="material-info">
          <div class="material-name">${escapeHtml(displayName)}</div>
          <div class="material-date">${formatDateTime(m.created_at)}</div>
        </div>
        <button class="material-delete" data-id="${m.id}" title="삭제">&times;</button>
      </div>`;
  }).join('');

  // 삭제 이벤트
  container.querySelectorAll('.material-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = +btn.dataset.id;
      if (!confirm('이 자료를 삭제하시겠습니까?')) return;
      try {
        await safeFetch(`/api/fund/materials/${id}`, { method: 'DELETE' });
        showToast('자료가 삭제되었습니다.', 'success');
        await loadMaterials();
      } catch { showToast('삭제 실패', 'error'); }
    });
  });
}

function openMemoModal() {
  document.getElementById('memoTitleInput').value = '';
  document.getElementById('memoContentInput').value = '';
  document.getElementById('memoModalOverlay').style.display = 'flex';
  setTimeout(() => document.getElementById('memoTitleInput')?.focus(), 100);
}

function closeMemoModal() {
  document.getElementById('memoModalOverlay').style.display = 'none';
}

async function saveMemo() {
  const title = document.getElementById('memoTitleInput')?.value.trim() || '메모';
  const content = document.getElementById('memoContentInput')?.value.trim();
  if (!content) { showToast('내용을 입력하세요.', 'error'); return; }
  if (!currentProjectId) { showToast('프로젝트를 선택하세요.', 'error'); return; }

  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/materials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ material_type: 'text', description: title, content_text: content }),
    });
    if (!res.ok) throw new Error('저장 실패');
    closeMemoModal();
    showToast('메모가 저장되었습니다.', 'success');
    await loadMaterials();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function handleMaterialUpload(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;
  if (!currentProjectId) { showToast('프로젝트를 선택하세요.', 'error'); return; }

  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('material_type', 'file');
    formData.append('description', file.name);

    try {
      const res = await safeFetch(`/api/fund/projects/${currentProjectId}/materials/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error(`${file.name} 업로드 실패`);
      showToast(`${file.name} 업로드 완료`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }
  e.target.value = '';
  await loadMaterials();
}

// ===== 알림 (Notifications) =====
async function loadNotifications() {
  try {
    const res = await safeFetch('/api/fund/notifications');
    if (res.ok) {
      const data = await res.json();
      notificationsCache = data.notifications || [];
      renderNotificationBadge();
    }
  } catch { /* ignore */ }
}

function renderNotificationBadge() {
  const unread = notificationsCache.filter(n => !n.read).length;
  const wrap = document.getElementById('notificationBadgeWrap');
  const count = document.getElementById('notificationCount');
  // 버튼은 항상 표시, 뱃지 숫자만 토글
  wrap.style.display = '';
  if (unread > 0) {
    count.style.display = '';
    count.textContent = unread > 99 ? '99+' : unread;
  } else {
    count.style.display = 'none';
  }
}

function toggleNotificationPanel() {
  const panel = document.getElementById('notificationPanel');
  const isOpen = panel.style.display !== 'none';
  if (isOpen) {
    panel.style.display = 'none';
  } else {
    renderNotificationList();
    panel.style.display = 'block';
  }
}

function renderNotificationList() {
  const container = document.getElementById('notificationList');
  if (!container) return;

  if (notificationsCache.length === 0) {
    container.innerHTML = '<p class="no-data-text">알림이 없습니다.</p>';
    return;
  }

  container.innerHTML = notificationsCache.slice(0, 20).map(n => `
    <div class="notification-item ${n.read ? '' : 'unread'} type-${n.notification_type || 'info'}">
      <div class="notif-message">${escapeHtml(n.message)}</div>
      <div class="notif-time">${formatDateTime(n.created_at)}</div>
    </div>
  `).join('');
}

async function markAllNotificationsRead() {
  try {
    await safeFetch('/api/fund/notifications/read-all', { method: 'POST' });
    notificationsCache.forEach(n => n.read = 1);
    renderNotificationBadge();
    renderNotificationList();
  } catch { /* ignore */ }
}

// ===== 유틸 =====
function formatDateTime(str) {
  if (!str) return '-';
  const d = new Date(str);
  return `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}
