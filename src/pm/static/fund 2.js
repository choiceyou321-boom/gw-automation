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
let _subcontractUnsaved = false; // [개선] 하도급 미저장 변경사항 추적
let _allBudgetData = [];          // 예실대비 전체 데이터 (연도 탭 전환용)
let _currentBudgetYear = null;    // 현재 선택된 연도 (null = 전체)

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
    case 'schedule':        loadSchedule(projectId); break;
    case 'collections':     loadCollections(projectId); break;
    case 'budget-payment':  loadSubcontracts(projectId); loadBudget(projectId); break;
    case 'vendors':         loadVendors(projectId); break;
    case 'payments':        loadPayments(projectId); break;
    case 'contracts':       loadGwContracts(projectId); break;
    case 'risks':           loadRisks(projectId); break;
  }
}

// ===== 초기화 =====
document.addEventListener('DOMContentLoaded', async () => {
  await checkAuth();
  await loadProjects();
  // [C1] TODO 데이터를 미리 로드해야 사이드바 뱃지 표시 가능
  await loadTodos();
  // TODO 로드 후 사이드바 뱃지 갱신
  renderProjectList();
  // 이전 프로젝트 드롭존 이벤트 설정 (최초 1회)
  setupArchivedDropZone();
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

  // [C5] 수금 빈 상태 — 기본 단계 추가 버튼
  document.getElementById('collAddDefaultBtn')?.addEventListener('click', () => {
    // 빈 상태 안내 숨기고 설계 테이블 첫 번째 행으로 포커스 이동
    const emptyState = document.getElementById('collectionsEmptyState');
    if (emptyState) emptyState.style.display = 'none';
    // 설계 테이블 tbody의 빈행 제거 후 포커스
    const designBody = document.getElementById('collectionDesignBody');
    if (designBody) {
      designBody.innerHTML = '';
      // 빈 행 추가 후 첫 번째 input 포커스
      const stages = ['계약금', '중도금', '잔금'];
      designBody.innerHTML = stages.map(stage => `
        <tr>
          <td>${escapeHtml(stage)}</td>
          <td class="num"><input type="text" class="coll-field coll-recalc-trigger num-input" data-field="amount" value="0" /></td>
          <td><input type="date" class="coll-field" data-field="collection_date" value="" /></td>
          <td class="chk"><input type="checkbox" class="coll-field coll-recalc-trigger" data-field="collected" /></td>
        </tr>`).join('');
      designBody.querySelector('input')?.focus();
    }
    showToast('기본 단계가 추가되었습니다. 금액을 입력하고 저장하세요.', 'info');
  });

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

  // 이체내역 엑셀 업로드
  document.getElementById('uploadPaymentsBtn')?.addEventListener('click', () => {
    document.getElementById('paymentFileInput').click();
  });
  document.getElementById('paymentFileInput')?.addEventListener('change', uploadPaymentExcel);

  // 대시보드 인쇄
  document.getElementById('printDashboardBtn')?.addEventListener('click', printDashboard);

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

  // 신규 데이터 동기화 버튼 (세금계산서 등)
  document.getElementById('pfSyncNewDataBtn')?.addEventListener('click', syncNewCrawlers);

  // 확장 크롤링 버튼
  document.getElementById('crawlAllExtendedBtn')?.addEventListener('click', runExtendedCrawl);

  // 리스크 추가 버튼 (이벤트 위임: panel-risks 내)
  document.getElementById('panel-risks')?.addEventListener('click', (e) => {
    if (e.target.closest('#addRiskBtn')) addRisk();
    const resolveBtn = e.target.closest('[data-resolve-risk]');
    if (resolveBtn) toggleRiskResolved(+resolveBtn.dataset.resolveRisk, resolveBtn.dataset.resolved !== 'true');
  });

  // 포트폴리오 AI 분석 버튼
  document.getElementById('pfAnalyzeBtn').addEventListener('click', generatePortfolioAnalysis);

  // 모달 닫기
  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalCancelBtn').addEventListener('click', closeModal);
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  // 마일스톤 추가/저장 버튼
  document.getElementById('btnAddMilestone')?.addEventListener('click', addMilestoneRow);
  document.getElementById('btnSaveMilestones')?.addEventListener('click', saveMilestonesFromSchedule);

  // 일정표 추가/저장 버튼
  document.getElementById('btnAddScheduleItem')?.addEventListener('click', addScheduleRow);
  document.getElementById('btnSaveSchedule')?.addEventListener('click', saveSchedule);

  // 일정표 뷰 전환 버튼 (CSP: inline onclick= 대신 addEventListener 사용)
  document.getElementById('btnTimelineView')?.addEventListener('click', () => setScheduleView('timeline'));
  document.getElementById('btnListView')?.addEventListener('click', () => setScheduleView('list'));
  document.getElementById('btnAddScheduleTimeline')?.addEventListener('click', addScheduleRowAndSwitch);

  // 타임라인 날짜 범위 피커
  document.getElementById('tlRangeStart')?.addEventListener('change', (e) => {
    _tlRangeStart = e.target.value ? new Date(e.target.value + '-01') : null;
    _saveTlRange(e.target.value, document.getElementById('tlRangeEnd')?.value || '');
    if (_scheduleView === 'timeline') renderTimeline(_scheduleItems);
  });
  document.getElementById('tlRangeEnd')?.addEventListener('change', (e) => {
    if (e.target.value) {
      // 다음 달 1일 - 1ms = 해당 월 말일
      const [y, m] = e.target.value.split('-').map(Number);
      _tlRangeEnd = new Date(y, m, 1); // setDate(0)을 renderTimeline에서 처리
    } else {
      _tlRangeEnd = null;
    }
    _saveTlRange(document.getElementById('tlRangeStart')?.value || '', e.target.value);
    if (_scheduleView === 'timeline') renderTimeline(_scheduleItems);
  });
  document.getElementById('btnTlRangeReset')?.addEventListener('click', () => {
    _tlRangeStart = null; _tlRangeEnd = null;
    document.getElementById('tlRangeStart').value = '';
    document.getElementById('tlRangeEnd').value = '';
    _saveTlRange('', '');
    if (_scheduleView === 'timeline') renderTimeline(_scheduleItems);
  });

  // 이전 프로젝트 폴더 헤더 (CSP로 인해 HTML onclick 대신 addEventListener 사용)
  document.getElementById('archivedFolderHeader')?.addEventListener('click', toggleArchivedFolder);

  // 이전 프로젝트 목록: 클릭 이벤트 위임 (복원 버튼, 프로젝트 선택)
  const archivedList = document.getElementById('archivedProjectList');
  if (archivedList) {
    archivedList.addEventListener('click', (e) => {
      const restoreBtn = e.target.closest('[data-restore-project]');
      if (restoreBtn) { e.stopPropagation(); archiveProject(+restoreBtn.dataset.restoreProject, false); return; }
      const li = e.target.closest('.project-item');
      if (li && li.dataset.id) selectProject(+li.dataset.id);
    });
  }

  // 일정표 팝오버 버튼
  document.getElementById('btnPopoverClose')?.addEventListener('click', closeSchedulePopover);
  document.getElementById('btnPopoverDelete')?.addEventListener('click', deleteScheduleItemFromPopover);
  document.getElementById('btnPopoverSave')?.addEventListener('click', saveScheduleItemFromPopover);

  // 타임라인 드래그 이벤트 위임 (동적 요소)
  const tlContainer = document.getElementById('timelineContainer');
  if (tlContainer) {
    tlContainer.addEventListener('mousedown', (e) => {
      // 바 왼쪽 핸들 (시작일 변경)
      const lh = e.target.closest('.tl-bar-lh');
      if (lh) {
        const bar = lh.closest('.tl-bar[data-idx]');
        if (bar) _onBarDragStart(e, 'left', parseInt(bar.dataset.idx, 10));
        return;
      }
      // 바 오른쪽 핸들 (종료일 변경)
      const rh = e.target.closest('.tl-bar-rh');
      if (rh) {
        const bar = rh.closest('.tl-bar[data-idx]');
        if (bar) _onBarDragStart(e, 'right', parseInt(bar.dataset.idx, 10));
        return;
      }
      // 마일스톤 드래그
      const msLine = e.target.closest('.tl-milestone-line[data-ms-idx]');
      if (msLine) {
        _onMsDragStart(e, parseInt(msLine.dataset.msIdx, 10));
      }
    });
    tlContainer.addEventListener('click', (e) => {
      // 핸들 클릭은 팝오버 제외
      if (e.target.closest('.tl-bar-lh') || e.target.closest('.tl-bar-rh')) return;
      const bar = e.target.closest('.tl-bar[data-idx]');
      if (bar) openSchedulePopover(parseInt(bar.dataset.idx, 10), e);
    });
  }

  // ===== 이벤트 위임 (동적 요소) =====

  // 프로젝트 리스트: 클릭, 드래그
  const projectList = document.getElementById('projectList');
  if (projectList) {
    projectList.addEventListener('click', (e) => {
      const delBtn = e.target.closest('[data-delete-project]');
      if (delBtn) { e.stopPropagation(); deleteProject(+delBtn.dataset.deleteProject); return; }
      const archBtn = e.target.closest('[data-archive-project]');
      if (archBtn) { e.stopPropagation(); archiveProject(+archBtn.dataset.archiveProject, true); return; }
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
      let visibleCount = 0;
      document.querySelectorAll('.project-item').forEach(li => {
        const name = li.querySelector('.project-name')?.textContent?.toLowerCase() || '';
        const visible = name.includes(q);
        li.style.display = visible ? '' : 'none';
        if (visible) visibleCount++;
      });
      // 검색 결과 없음 처리
      let emptyEl = document.getElementById('projectSearchEmpty');
      if (!emptyEl) {
        emptyEl = document.createElement('li');
        emptyEl.id = 'projectSearchEmpty';
        emptyEl.style.cssText = 'padding:12px 16px;color:#64748b;font-size:12px;text-align:center;list-style:none;';
        emptyEl.textContent = '검색 결과가 없습니다.';
        document.getElementById('projectList').appendChild(emptyEl);
      }
      emptyEl.style.display = (q && visibleCount === 0) ? 'block' : 'none';
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
    // 공정 일정: 삭제
    if (e.target.closest('.btn-del-sch')) {
      e.target.closest('tr').remove(); return;
    }
  });

  // 공정 일정 상태 변경 → 색상 클래스 실시간 갱신
  document.addEventListener('change', (e) => {
    if (e.target.classList.contains('sch-status-select')) {
      const sel = e.target;
      sel.className = `sch-status-select sch-${sel.value}`;
    }
  });

  // 마일스톤 날짜 변경 → D-Day 실시간 갱신
  document.addEventListener('change', (e) => {
    if (e.target.classList.contains('ms-date-field')) {
      const tr = e.target.closest('tr');
      if (!tr) return;
      const completed = tr.querySelector('.ms-toggle-completed')?.checked || false;
      const ddayCell = tr.querySelector('.dday-cell');
      if (ddayCell) ddayCell.innerHTML = ddayHtml(e.target.value, completed);
    }
  });

  // 하도급: 체크박스 및 금액 변경 시 recalc (이벤트 위임) + [개선] 미저장 플래그 설정
  document.addEventListener('change', (e) => {
    if (e.target.closest('.sc-recalc-trigger')) {
      _subcontractUnsaved = true; // 미저장 변경사항 표시
      recalcSubcontractRow(e.target); return;
    }
    // 금액 input 변경 시에도 재계산
    if (e.target.matches('#subcontractBody input[data-field^="payment_"], #subcontractBody input[data-field="contract_amount"], #subcontractBody input[data-field="changed_contract_amount"]')) {
      _subcontractUnsaved = true; // 미저장 변경사항 표시
      recalcSubcontractRow(e.target); return;
    }
  });

  // 하도급: 텍스트 필드 변경 시 미저장 플래그 설정
  document.addEventListener('input', (e) => {
    if (e.target.matches('#subcontractBody input.sc-field, #subcontractBody select.sc-trade')) {
      _subcontractUnsaved = true;
    }
  });

  // 하도급: 행 삭제
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn-remove-sc-row')) {
      _subcontractUnsaved = true; // 행 삭제도 미저장 변경
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

  // num-input: 타이핑 중 실시간 천단위 포맷
  document.addEventListener('input', (e) => {
    if (!e.target.classList.contains('num-input')) return;
    const el = e.target;
    const raw = el.value.replace(/[^0-9]/g, '');
    const formatted = raw ? parseInt(raw).toLocaleString('ko-KR') : '';
    // 커서 위치 보정
    const prevLen = el.value.length;
    el.value = formatted;
    const diff = formatted.length - prevLen;
    if (el.selectionStart !== undefined) {
      const pos = Math.max(0, (el.selectionStart || 0) + diff);
      el.setSelectionRange(pos, pos);
    }
  });

  // 일정표 팝오버: 외부 클릭 시 닫기
  document.addEventListener('click', (e) => {
    const pop = document.getElementById('scheduleItemPopover');
    if (!pop || pop.style.display === 'none') return;
    if (!pop.contains(e.target) && !e.target.closest('.tl-bar') && !e.target.closest('.tl-no-date')) {
      closeSchedulePopover();
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

    // 수익성 분석 그래프 렌더링
    _renderProfitChart(projects);

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

// ===== 포트폴리오 수익성 분석 그래프 =====
/**
 * 프로젝트별 이익률 막대 그래프 렌더링
 * - 수주액 0인 프로젝트 제외
 * - 이익률에 따라 색상 분기: 20% 이상=초록, 10~20%=파랑, 10% 미만=주황, 음수=빨강
 */
function _renderProfitChart(projects) {
  const section = document.getElementById('pfProfitChartSection');
  const body = document.getElementById('pfProfitChartBody');
  if (!section || !body) return;

  // 수주액이 있는 프로젝트만 필터링
  const filtered = projects.filter(p => {
    const totalOrder = (p.design_amount || 0) + (p.construction_amount || 0) + (p.total_order || 0);
    return totalOrder > 0;
  });

  if (filtered.length === 0) {
    section.style.display = 'none';
    return;
  }

  // 이익률 계산
  const withRate = filtered.map(p => {
    const totalOrder = p.total_order || ((p.design_amount || 0) + (p.construction_amount || 0));
    let rate = p.profit_rate || 0;
    if (!rate && totalOrder > 0 && p.profit_amount) {
      rate = p.profit_amount / totalOrder * 100;
    }
    return { name: p.name, rate };
  });

  // 절댓값 기준 최대값 (바 너비 계산용)
  const maxAbs = Math.max(...withRate.map(p => Math.abs(p.rate)), 1);

  // 색상 결정
  function barColor(rate) {
    if (rate >= 20) return '#10b981';  // 초록
    if (rate >= 10) return '#3b82f6';  // 파랑
    if (rate >= 0)  return '#f97316';  // 주황
    return '#ef4444';                   // 빨강 (음수)
  }

  body.innerHTML = withRate.map(p => {
    const pct = Math.min(Math.abs(p.rate) / maxAbs * 100, 100);
    const color = barColor(p.rate);
    const rateStr = p.rate.toFixed(1) + '%';
    return `<div class="pf-profit-row">
      <span class="pf-profit-label" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</span>
      <div class="pf-profit-bar-wrap">
        <div class="pf-profit-bar" style="width:${pct}%;background:${color};"></div>
      </div>
      <span class="pf-profit-value" style="color:${color};">${rateStr}</span>
    </div>`;
  }).join('');

  section.style.display = 'block';
}

// ===== 포트폴리오 AI 분석 =====

/** 간이 마크다운→HTML: 헤더, 볼드, 불릿, 줄바꿈 처리 */
function simpleMarkdown(text) {
  if (!text) return '';
  let s = escapeHtml(text);
  // ## 헤더 → 볼드 블록
  s = s.replace(/^#{1,3}\s+(.+)$/gm, '<strong class="ai-heading">$1</strong>');
  // **볼드**
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // • 불릿 (줄 시작)
  s = s.replace(/^[•\-]\s+/gm, '<span class="ai-bullet">•</span> ');
  // ⚠ 경고 아이콘 강조
  s = s.replace(/⚠/g, '<span style="color:#f59e0b">⚠</span>');
  // 빈 줄 → 단락 구분
  s = s.replace(/\n{2,}/g, '</p><p>');
  // 단일 줄바꿈
  s = s.replace(/\n/g, '<br>');
  return '<p>' + s + '</p>';
}

/** 인사이트 타입별 아이콘+라벨 */
const INSIGHT_META = {
  strategy:      { icon: '📊', label: '현황 점검', color: '#6366f1' },
  risk:          { icon: '⚠️', label: '리스크',   color: '#ef4444' },
  profitability: { icon: '💰', label: '자금 흐름', color: '#10b981' },
  action:        { icon: '🎯', label: '실행 권고', color: '#f59e0b' },
};

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

    // 분석 시각 표시 (포트폴리오 또는 프로젝트 인사이트 중 최신)
    const pfInsight = portfolio.find(i => i.insight_type === 'portfolio');
    const anyItem = pfInsight || Object.values(projects)[0]?.items?.[0];
    if (anyItem) {
      const dt = new Date(anyItem.generated_at);
      timeEl.textContent = `${dt.getMonth()+1}/${dt.getDate()} ${dt.getHours()}:${String(dt.getMinutes()).padStart(2,'0')} 분석`;
    }

    let html = '';

    // 프로젝트별 인사이트 카드
    const pidList = Object.keys(projects);
    if (pidList.length > 0) {
      html += '<div class="analysis-projects-grid">';
      for (const pid of pidList) {
        const pdata = projects[pid];
        const items = pdata.items || [];
        // 데이터 부족 프로젝트는 건너뛰기
        const hasReal = items.some(i => i.content && !i.content.includes('데이터 부족으로 분석 불가'));
        if (!hasReal) continue;

        html += `<div class="analysis-project-card">`;
        html += `<div class="analysis-project-name">${escapeHtml(pdata.project_name)}</div>`;
        html += '<div class="analysis-project-items">';
        for (const itype of ['strategy', 'risk', 'profitability', 'action']) {
          const item = items.find(i => i.type === itype);
          if (!item || !item.content || item.content.includes('데이터 부족')) continue;
          const meta = INSIGHT_META[itype] || { icon: 'ℹ️', label: itype, color: '#888' };
          html += `<div class="analysis-item">
            <div class="analysis-item-label" style="color:${meta.color}">${meta.icon} ${meta.label}</div>
            <div class="analysis-item-text">${simpleMarkdown(item.content)}</div>
          </div>`;
        }
        html += '</div></div>';
      }
      html += '</div>';
    }

    body.innerHTML = html || '<p class="pf-analysis-empty">분석할 데이터가 충분한 프로젝트가 없습니다.</p>';
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

  // 보관된 프로젝트와 활성 프로젝트 분리
  const activeProjects = projectsCache.filter(p => !p.is_archived);
  const archivedProjects = projectsCache.filter(p => p.is_archived);

  // 이전 프로젝트 폴더 렌더링
  renderArchivedProjects(archivedProjects);

  if (countEl) countEl.textContent = activeProjects.length;

  if (activeProjects.length === 0) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }

  empty.style.display = 'none';

  // [개선] 상태별 그룹핑: status 컬럼 기반 (active/completed/hold)
  // status가 없는 경우 등급별로 그룹핑
  const hasStatusInfo = activeProjects.some(p => p.status && p.status !== 'active');

  // 프로젝트 항목 HTML 생성 헬퍼
  const renderItem = (p) => {
    const gc = GRADE_COLORS[p.grade] || null;
    const gradeBadge = gc
      ? `<span class="grade-badge" style="background:${gc.bg};color:${gc.color};" title="${p.grade}">${gc.label}</span>`
      : '';

    // [C1] 미완료 TODO 수 뱃지
    const pendingTodos = todosCache.filter(t => !t.completed && t.project_id === p.id).length;
    const todoBadge = pendingTodos > 0
      ? `<span class="sidebar-todo-badge" title="미완료 TODO ${pendingTodos}건">${pendingTodos}</span>`
      : '';

    return `
    <li class="project-item ${p.id === currentProjectId ? 'active' : ''}"
        data-id="${p.id}" draggable="true">
      ${gradeBadge}
      <span class="project-name">${escapeHtml(p.name)}</span>
      ${todoBadge}
      <button class="project-archive" data-archive-project="${p.id}"
              title="이전 프로젝트로 이동">↓</button>
      <button class="project-delete" data-delete-project="${p.id}"
              title="프로젝트 삭제">&times;</button>
    </li>`;
  };

  if (hasStatusInfo) {
    // 상태별 3개 그룹: 진행중 / 완료 / 보류
    const STATUS_GROUPS = [
      { key: 'active',    label: '진행중',  keys: ['active', '', null, undefined] },
      { key: 'completed', label: '완료',    keys: ['completed'] },
      { key: 'hold',      label: '보류',    keys: ['hold', 'paused', 'suspended'] },
    ];
    let html = '';
    STATUS_GROUPS.forEach(group => {
      const members = activeProjects.filter(p =>
        group.keys.includes(p.status) || group.keys.includes(p.status || '')
      );
      if (members.length === 0) return;
      html += `<li class="sidebar-group-header">${group.label} <span class="sidebar-group-count">${members.length}</span></li>`;
      html += members.map(renderItem).join('');
    });
    list.innerHTML = html;
  } else {
    // 상태 정보 없음 → 등급별 그룹핑 (1등급 > 2등급 > 3등급 > 4등급 > 미분류)
    const GRADE_ORDER = ['1등급', '2등급', '3등급', '4등급'];
    const gradeMap = {};
    const noGrade = [];
    activeProjects.forEach(p => {
      if (p.grade && GRADE_ORDER.includes(p.grade)) {
        (gradeMap[p.grade] = gradeMap[p.grade] || []).push(p);
      } else {
        noGrade.push(p);
      }
    });

    // 등급이 모두 동일하거나 미분류만 있으면 단순 목록
    const gradedKeys = GRADE_ORDER.filter(g => gradeMap[g]?.length > 0);
    if (gradedKeys.length <= 1 && noGrade.length > 0) {
      list.innerHTML = activeProjects.map(renderItem).join('');
      return;
    }

    let html = '';
    gradedKeys.forEach(grade => {
      const members = gradeMap[grade];
      const gc = GRADE_COLORS[grade];
      html += `<li class="sidebar-group-header"><span style="color:${gc?.color || '#888'}">${grade}</span> <span class="sidebar-group-count">${members.length}</span></li>`;
      html += members.map(renderItem).join('');
    });
    if (noGrade.length > 0) {
      html += `<li class="sidebar-group-header">미분류 <span class="sidebar-group-count">${noGrade.length}</span></li>`;
      html += noGrade.map(renderItem).join('');
    }
    list.innerHTML = html;
  }
}

// ===== 프로젝트 드래그 정렬 =====
let dragProjectId = null;

function onProjectDragStart(e, li) {
  dragProjectId = parseInt(li.dataset.id);
  li.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  // 보관 드롭존에서도 project ID를 읽을 수 있도록 저장
  e.dataTransfer.setData('text/plain', String(dragProjectId));
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

// ===== 이전 프로젝트 폴더 =====
let archivedFolderOpen = false;

function toggleArchivedFolder() {
  archivedFolderOpen = !archivedFolderOpen;
  const folder = document.getElementById('archivedFolder');
  const list = document.getElementById('archivedProjectList');
  if (archivedFolderOpen) {
    folder.classList.add('expanded');
    list.style.display = '';
  } else {
    folder.classList.remove('expanded');
    list.style.display = 'none';
  }
}

function setupArchivedDropZone() {
  const zone = document.getElementById('archivedDropZone');
  if (!zone) return;
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });
  zone.addEventListener('dragleave', () => {
    zone.classList.remove('drag-over');
  });
  zone.addEventListener('drop', async (e) => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const projectId = parseInt(e.dataTransfer.getData('text/plain'));
    if (!projectId) return;
    await archiveProject(projectId, true);
  });
}

async function archiveProject(projectId, archive) {
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_archived: archive })
    });
    if (!res.ok) throw new Error('요청 실패');
    showToast(archive ? '이전 프로젝트로 이동했습니다.' : '프로젝트를 복원했습니다.');
    // 현재 선택된 프로젝트를 보관하면 선택 해제 (삭제 시 처리 패턴과 동일)
    if (archive && currentProjectId === projectId) {
      currentProjectId = null;
      document.getElementById('pageTitle').textContent = '프로젝트를 선택하세요';
      document.getElementById('tabBar').style.display = 'none';
      hideAllPanels();
      document.getElementById('emptyState').style.display = 'block';
      loadPortfolioView();
    }
    await loadProjects();
  } catch (e) {
    showToast('오류: ' + e.message, 'error');
  }
}

function renderArchivedProjects(archivedProjects) {
  const list = document.getElementById('archivedProjectList');
  const countEl = document.getElementById('archivedFolderCount');
  const folder = document.getElementById('archivedFolder');
  if (!list || !folder) return;

  if (countEl) countEl.textContent = archivedProjects.length;

  // 드롭존이 항상 보여야 드래그로 보관 가능 → 폴더는 항상 표시
  folder.style.display = '';

  if (archivedProjects.length === 0) {
    list.innerHTML = '';
    // 항목 없으면 목록 닫기
    archivedFolderOpen = false;
    folder.classList.remove('expanded');
    list.style.display = 'none';
    return;
  }

  // 열림 상태 유지
  list.style.display = archivedFolderOpen ? '' : 'none';

  list.innerHTML = archivedProjects.map(p => {
    const grade = p.grade || '';
    const gc = GRADE_COLORS[grade] || null;
    const gradeBadge = gc
      ? `<span class="grade-badge" style="background:${gc.bg};color:${gc.color};" title="${p.grade}">${gc.label}</span>`
      : '';
    return `<li class="project-item" data-id="${p.id}">
      ${gradeBadge}
      <span class="project-name" style="cursor:pointer;">${escapeHtml(p.name)}</span>
      <button class="restore-btn" data-restore-project="${p.id}" title="복원">↩</button>
    </li>`;
  }).join('');
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
  // [개선] 하도급 상세에 미저장 변경사항이 있으면 경고
  if (_subcontractUnsaved && currentProjectId !== id) {
    const ok = confirm('하도급 상세에 저장하지 않은 변경사항이 있습니다.\n다른 프로젝트를 선택하면 변경사항이 사라집니다. 계속하시겠습니까?');
    if (!ok) return;
    _subcontractUnsaved = false;
  }

  currentProjectId = id;
  renderProjectList();

  const project = projectsCache.find(p => p.id === id);
  if (project) {
    document.getElementById('pageTitle').textContent = project.name;
  }

  // GW 동기화 배지 업데이트
  _updateGwSyncBadge(id);

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
  // [개선] 하도급 탭에서 다른 탭으로 이동 시 미저장 경고
  if (_subcontractUnsaved && currentTab !== tabName) {
    const ok = confirm('하도급 상세에 저장하지 않은 변경사항이 있습니다.\n탭을 이동하면 변경사항이 사라집니다. 계속하시겠습니까?');
    if (!ok) {
      // 탭 이동 취소 — 하도급 탭 버튼을 다시 active로 표시
      document.querySelectorAll('.tab-item').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === currentTab);
      });
      return;
    }
    _subcontractUnsaved = false; // 경고 무시하고 이동 시 플래그 초기화
  }

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
  showLoading('대시보드 불러오는 중...');
  try {
    // 모든 데이터를 병렬로 조회
    const [summaryRes, collRes, subRes, overviewRes, schedRes] = await Promise.all([
      safeFetch(`/api/fund/projects/${projectId}/summary`),
      safeFetch(`/api/fund/projects/${projectId}/collections`),
      safeFetch(`/api/fund/projects/${projectId}/subcontracts`),
      safeFetch(`/api/fund/projects/${projectId}/overview`),
      safeFetch(`/api/fund/projects/${projectId}/schedule`),
    ]);

    const summaryData = summaryRes.ok ? await summaryRes.json() : {};
    const collData = collRes.ok ? await collRes.json() : { collections: [] };
    const subData = subRes.ok ? await subRes.json() : { subcontracts: [] };
    const ovData = overviewRes.ok ? await overviewRes.json() : { overview: {} };
    const schedData = schedRes.ok ? await schedRes.json() : { items: [] };

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

    // ─── [개선] 대시보드 상단 미니 요약 카드 4개 업데이트 ───
    const dtcCollected = document.getElementById('dtcCollected');
    const dtcUncollected = document.getElementById('dtcUncollected');
    const dtcBudgetRate = document.getElementById('dtcBudgetRate');
    const dtcTodoPending = document.getElementById('dtcTodoPending');
    if (dtcCollected)   dtcCollected.textContent   = formatWon(collCollected) + '원';
    if (dtcUncollected) dtcUncollected.textContent = formatWon(collTotal - collCollected) + '원';
    if (dtcBudgetRate)  dtcBudgetRate.textContent  = budgetPct.toFixed(1) + '%';
    if (dtcTodoPending) {
      // todosCache가 아직 로드 안됐을 수 있으므로 새로 로드 후 계산
      if (todosCache.length === 0) {
        await loadTodos();
      }
      const pendingCount = todosCache.filter(t => !t.completed && t.project_id === parseInt(projectId)).length;
      dtcTodoPending.textContent = pendingCount + '건';
      // [C1] 사이드바 뱃지도 갱신
      renderProjectList();
    }

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

    // ─── 8) 공정 일정 미니 타임라인 ───
    renderDashTimeline(schedData.items || []);

    // ─── 9) 대시보드 경고 카드 (미수금 D-Day + 예산 초과 임박) ───
    // 미수금 D-7 이내 경고 카드 — collections 데이터 재사용
    renderDashCollectionAlert(colls);
    // 예산 집행률 95% 초과 경보 카드 — 비동기로 별도 조회
    renderDashBudgetAlert(projectId);

    // 인사이트 필터링 갱신 (현재 프로젝트만)
    renderInsights();

  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    hideLoading(); // [개선] 대시보드 로딩 완료
  }
}

// ===== 대시보드 경고 카드 =====

/**
 * [1] 미수금 D-7 이내 경고 카드
 * - is_collected=0 이고 collection_date 있는 항목 필터링
 * - D-7 이내(미래) 또는 기한 초과(D+N) 항목이 있으면 카드 표시
 */
function renderDashCollectionAlert(colls) {
  const alertEl = document.getElementById('dashCollectionAlert');
  if (!alertEl) return; // HTML에 컨테이너 없으면 무시

  // 미수금 + 예정일 있는 항목만 필터
  const urgentItems = (colls || []).filter(c => {
    if (c.collected) return false;
    if (!c.collection_date) return false;
    const diff = calcDday(c.collection_date);
    if (diff === null) return false;
    return diff <= 7; // 7일 이내(과거 포함)
  });

  if (urgentItems.length === 0) {
    alertEl.style.display = 'none';
    return;
  }

  // 총 미수금 금액 합산
  const totalAmt = urgentItems.reduce((s, c) => s + (c.amount || 0), 0);

  // D-Day 요약 텍스트 생성 (최대 3개까지 표시)
  const ddays = urgentItems.slice(0, 3).map(c => {
    const diff = calcDday(c.collection_date);
    if (diff < 0) return `D+${Math.abs(diff)}`;
    if (diff === 0) return 'D-Day';
    return `D-${diff}`;
  });
  const moreText = urgentItems.length > 3 ? ` 외 ${urgentItems.length - 3}건` : '';

  // 기한 초과 항목이 있으면 빨강, 아니면 주황
  const hasOverdue = urgentItems.some(c => calcDday(c.collection_date) < 0);
  const colorClass = hasOverdue ? 'dash-alert-danger' : 'dash-alert-warning';

  alertEl.className = `dash-alert-card ${colorClass}`;
  alertEl.style.display = 'flex';
  alertEl.innerHTML = `
    <span class="dash-alert-icon">${hasOverdue ? '🔴' : '⚠️'}</span>
    <div class="dash-alert-body">
      <div class="dash-alert-title">수금 예정 ${urgentItems.length}건 (${ddays.join(', ')}${moreText})</div>
      <div class="dash-alert-sub">총 미수금 ${formatWon(totalAmt)}원</div>
    </div>
  `;
}

/**
 * [2] 예산 집행률 95% 초과 경보 카드
 * - /api/fund/projects/{id}/budget/detail?leaf_only=true 조회
 * - 집행률 = unit_am / abgt_sum_am * 100 ≥ 95인 항목 필터링
 * - 실패 시 카드 숨김 (graceful)
 */
async function renderDashBudgetAlert(projectId) {
  const alertEl = document.getElementById('dashBudgetAlert');
  if (!alertEl) return;

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/budget/detail?leaf_only=true`);
    if (!res.ok) { alertEl.style.display = 'none'; return; }
    const data = await res.json();
    const rows = data.rows || data.items || data.data || [];

    // 집행률 95% 이상인 항목 필터링
    const overItems = rows.filter(r => {
      const budget = r.abgt_sum_am || r.abgtSumAm || 0;
      const actual = r.unit_am || r.unitAm || 0;
      if (!budget || budget <= 0) return false;
      return (actual / budget * 100) >= 95;
    });

    if (overItems.length === 0) {
      alertEl.style.display = 'none';
      return;
    }

    // 이름 + 집행률 텍스트 (최대 3개)
    const labels = overItems.slice(0, 3).map(r => {
      const name = r.def_nm || r.defNm || r.bgt_nm || r.bgtNm || '항목';
      const budget = r.abgt_sum_am || r.abgtSumAm || 1;
      const actual = r.unit_am || r.unitAm || 0;
      const pct = Math.round(actual / budget * 100);
      return `${escapeHtml(name)} ${pct}%`;
    });
    const moreText = overItems.length > 3 ? ` 외 ${overItems.length - 3}건` : '';

    alertEl.className = 'dash-alert-card dash-alert-warning';
    alertEl.style.display = 'flex';
    alertEl.innerHTML = `
      <span class="dash-alert-icon">🔥</span>
      <div class="dash-alert-body">
        <div class="dash-alert-title">예산 초과 임박: ${labels.join(' · ')}${moreText}</div>
        <div class="dash-alert-sub">집행률 95% 이상 항목이 있습니다</div>
      </div>
    `;
  } catch (_) {
    // 에러 시 카드 숨김 (graceful degradation)
    alertEl.style.display = 'none';
  }
}

// 대시보드용 미니 타임라인 (읽기 전용, 드래그 없음)
function renderDashTimeline(items) {
  const container = document.getElementById('dashTimelineContainer');
  if (!container) return;

  const barItems = (items || []).filter(it => (it.item_type || 'bar') === 'bar');
  const milestones = (items || []).filter(it => it.item_type === 'milestone');

  if (barItems.length === 0 && milestones.length === 0) {
    container.innerHTML = '<p class="no-data-text">일정 없음</p>';
    return;
  }

  const today = new Date(); today.setHours(0, 0, 0, 0);

  // 날짜 범위
  let minD = new Date(today), maxD = new Date(today);
  minD.setDate(1); maxD.setMonth(maxD.getMonth() + 2); maxD.setDate(1);
  items.forEach(it => {
    if (it.start_date) { const d = new Date(it.start_date); if (d < minD) { minD = new Date(d); minD.setDate(1); } }
    if (it.end_date)   { const d = new Date(it.end_date);   if (d > maxD) maxD = new Date(d); }
  });
  minD.setDate(1); minD.setMonth(minD.getMonth() - 1);
  maxD.setMonth(maxD.getMonth() + 2); maxD.setDate(0);

  // 주차 배열
  const weeks = [];
  let wStart = new Date(minD);
  const dow = wStart.getDay();
  wStart.setDate(wStart.getDate() - (dow === 0 ? 6 : dow - 1));
  let wNo = 1;
  while (wStart <= maxD) {
    const wEnd = new Date(wStart); wEnd.setDate(wEnd.getDate() + 6);
    weeks.push({ start: new Date(wStart), end: new Date(wEnd), no: wNo++ });
    wStart.setDate(wStart.getDate() + 7);
  }
  if (weeks.length === 0) { container.innerHTML = '<p class="no-data-text">날짜 범위 오류</p>'; return; }

  const totalMs = (weeks[weeks.length - 1].end - weeks[0].start) || 1;
  const pct = d => Math.max(0, Math.min(100, (d - weeks[0].start) / totalMs * 100));
  const curWeekIdx = weeks.findIndex(w => today >= w.start && today <= w.end);
  const todayPct = pct(today);
  const fmtDate = d => `${d.getMonth() + 1}-${d.getDate()}`;

  // 월 그룹
  const monthGroups = [];
  weeks.forEach(w => {
    const key = w.start.getFullYear() * 100 + w.start.getMonth();
    if (!monthGroups.length || monthGroups[monthGroups.length - 1].key !== key)
      monthGroups.push({ key, label: `${w.start.getMonth() + 1}월`, count: 1 });
    else monthGroups[monthGroups.length - 1].count++;
  });

  // 그룹 색상
  const GROUP_COLORS = ['c0','c1','c2','c3','c4','c5','c6','c7'];
  const groupColorMap = {};
  const seenG = new Set();
  barItems.forEach(it => {
    const g = it.group_name || '';
    if (g && !seenG.has(g)) { seenG.add(g); groupColorMap[g] = GROUP_COLORS[seenG.size % GROUP_COLORS.length]; }
  });

  const nowMonKey = today.getFullYear() * 100 + today.getMonth();

  let html = `<div class="tl-scroll-wrap"><table class="tl-table">`;
  // 헤더: 월
  html += `<thead><tr class="tl-head-month"><td class="tl-left" rowspan="2" style="text-align:center;font-size:10px;color:#6b7280;">항목</td>`;
  monthGroups.forEach(mg => {
    html += `<td colspan="${mg.count}" class="${mg.key === nowMonKey ? 'cur-month' : ''}">${escapeHtml(mg.label)}</td>`;
  });
  html += `</tr>`;
  // 헤더: 날짜
  html += `<tr class="tl-head-day">`;
  weeks.forEach((w, i) => {
    html += `<td class="${i === curWeekIdx ? 'cur-week' : ''}">${fmtDate(w.start)}</td>`;
  });
  html += `</tr></thead><tbody>`;

  // 바 항목 행 (읽기 전용 — 핸들 없음)
  barItems.forEach((it, rowNum) => {
    const isLast = rowNum === barItems.length - 1;
    const colorClass = it.group_name ? (groupColorMap[it.group_name] || 'c5') : (it.status || 'planned');

    html += `<tr class="tl-data-row"><td class="tl-left"><div class="tl-left-inner">
      <div class="tl-group-name" style="font-size:11px;">${escapeHtml(it.item_name || '')}</div>
      ${it.group_name ? `<div class="tl-group-subtitle">${escapeHtml(it.group_name)}</div>` : ''}
    </div></td>`;
    html += `<td colspan="${weeks.length}" class="tl-cell dash-mini-tl-cell">`;

    // 주차 세로선
    html += `<div style="position:absolute;inset:0;display:flex;pointer-events:none;">`;
    weeks.forEach((w, i) => {
      html += `<div style="flex:1;border-right:1px solid rgba(255,255,255,0.04);${i === curWeekIdx ? 'background:rgba(59,130,246,0.04);' : ''}"></div>`;
    });
    html += `</div>`;

    // 오늘 마커
    html += `<div class="tl-today-line" style="left:${todayPct.toFixed(2)}%">${isLast ? '<span class="tl-today-chip">오늘</span>' : ''}</div>`;

    // 마일스톤 선 (레이블은 마지막 행에만)
    milestones.forEach(ms => {
      if (!ms.start_date) return;
      const msPct = pct(new Date(ms.start_date));
      const lineColor = ms.bar_color || '#a855f7';
      html += `<div class="tl-milestone-line" style="left:${msPct.toFixed(2)}%;border-color:${escapeHtml(lineColor)};pointer-events:none;cursor:default;">
        ${isLast ? `<span class="tl-milestone-label" style="color:${escapeHtml(lineColor)};">${escapeHtml(ms.item_name || '')}</span>` : ''}
      </div>`;
    });

    // 바 (핸들 없이 심플)
    if (it.start_date && it.end_date) {
      const left = pct(new Date(it.start_date));
      const right = pct(new Date(new Date(it.end_date).getTime() + 86400000));
      const width = Math.max(0.8, right - left);
      const barColor = it.bar_color || '';
      const styleExtra = barColor ? `background:${escapeHtml(barColor)};` : '';
      html += `<div class="tl-bar ${barColor ? '' : colorClass}"
        style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;${styleExtra}cursor:default;"
        title="${escapeHtml(it.item_name || '')} (${escapeHtml(it.start_date)}~${escapeHtml(it.end_date)})">
        <span class="tl-bar-text">${escapeHtml(it.item_name || '')}</span>
      </div>`;
    }
    html += `</td></tr>`;
  });

  html += `</tbody></table></div>`;
  container.innerHTML = html;
}

// ===== 개요 탭 =====
async function loadOverview(projectId) {
  showLoading('개요 불러오는 중...');
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
      } else if (el.classList.contains('num-input')) {
        el.value = formatNum(ov[field] || 0);
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
  } finally {
    hideLoading();
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
    container.innerHTML = '<tr><td colspan="6" class="no-data">진행 단계 없음</td></tr>';
    updateMilestoneProgress([]);
    updateOvMilestoneSummary([]);
    return;
  }
  container.innerHTML = milestones.map((ms, idx) => `
    <tr data-id="${ms.id || ''}" class="${ms.completed ? 'ms-done' : ''}">
      <td class="ms-num">${idx + 1}</td>
      <td><input type="text" class="ms-name-field" data-field="name" value="${escapeHtml(ms.name)}" placeholder="단계명" /></td>
      <td class="chk"><input type="checkbox" class="ms-field ms-toggle-completed" data-field="completed" ${ms.completed ? 'checked' : ''} /></td>
      <td><input type="date" class="ms-date-field" data-field="date" value="${escapeHtml(ms.date || '')}" /></td>
      <td class="dday-cell">${ddayHtml(ms.date, ms.completed)}</td>
      <td><button class="btn-icon btn-del-ms btn-del-ms-action" title="삭제">&times;</button></td>
    </tr>
  `).join('');
  updateMilestoneProgress(milestones);
  updateOvMilestoneSummary(milestones);
}

function toggleMilestoneRow(checkbox) {
  const tr = checkbox.closest('tr');
  if (checkbox.checked) {
    tr.classList.add('ms-done');
  } else {
    tr.classList.remove('ms-done');
  }
  // D-Day 셀 갱신 (완료 상태에 따라 표시 변경)
  const dateVal = tr.querySelector('.ms-date-field')?.value || '';
  const ddayCell = tr.querySelector('.dday-cell');
  if (ddayCell) ddayCell.innerHTML = ddayHtml(dateVal, checkbox.checked);
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
    <td><input type="date" class="ms-date-field" data-field="date" value="" /></td>
    <td class="dday-cell"><span class="dday-none">-</span></td>
    <td><button class="btn-icon btn-del-ms btn-del-ms-action" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
  tr.querySelector('.ms-name-field').focus();
  updateMilestoneProgress();
}

// ===== D-Day 계산 헬퍼 =====
function calcDday(dateStr) {
  if (!dateStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  target.setHours(0, 0, 0, 0);
  if (isNaN(target.getTime())) return null;
  return Math.round((target - today) / 86400000);
}

function ddayHtml(dateStr, completed) {
  if (!dateStr) return '<span class="dday-none">-</span>';
  const diff = calcDday(dateStr);
  if (diff === null) return '<span class="dday-none">-</span>';
  if (completed) return '<span class="dday-done">완료</span>';
  if (diff > 0) {
    const cls = diff <= 7 ? 'dday-soon' : 'dday-future';
    return `<span class="dday-badge ${cls}">D-${diff}</span>`;
  } else if (diff === 0) {
    return '<span class="dday-badge dday-today">D-Day</span>';
  } else {
    return `<span class="dday-badge dday-over">D+${Math.abs(diff)}</span>`;
  }
}

// ===== 개요 탭 마일스톤 요약 =====
function updateOvMilestoneSummary(milestones) {
  const el = document.getElementById('ovMilestoneText');
  if (!el) return;
  if (!milestones || milestones.length === 0) {
    el.textContent = '등록된 마일스톤 없음';
    return;
  }
  const total = milestones.length;
  const done = milestones.filter(m => m.completed).length;
  const pct = total > 0 ? Math.round(done / total * 100) : 0;

  // 다음 미완료 마일스톤 (날짜 있는 것 중 가장 가까운 미래 또는 가장 적게 지난 것)
  const upcoming = milestones
    .filter(m => !m.completed && m.date)
    .sort((a, b) => a.date.localeCompare(b.date))[0];

  let text = `완료 ${done}/${total} (${pct}%)`;
  if (upcoming) {
    const diff = calcDday(upcoming.date);
    let ddayStr = '';
    if (diff !== null) {
      ddayStr = diff > 0 ? ` D-${diff}` : diff === 0 ? ' D-Day' : ` D+${Math.abs(diff)}`;
    }
    text += ` · 다음: ${upcoming.name}${ddayStr}`;
  }
  el.textContent = text;
}

// ===== 일정표 탭 =====
let _scheduleView = 'timeline';   // 'list' | 'timeline'
let _scheduleItems = [];          // 현재 로드된 일정 항목 (단일 소스)
let _popoverItemIndex = -1;       // 팝오버로 편집 중인 항목 인덱스
let _scheduleLoadedProject = null; // 마지막으로 일정을 로드한 프로젝트 ID (뷰 초기화 판단용)
// 타임라인 드래그용 상태
let _tlWeeks = [];                // 현재 렌더링된 주차 배열
let _tlTotalMs = 1;               // 타임라인 전체 밀리초 (좌표 변환용)
let _tlMinStart = 0;              // 타임라인 시작 타임스탬프
let _barDrag = null;              // 바 드래그 상태 (null | {idx, dragType, startX, origLeft, origWidth, cellRect, _curLeft, _curWidth})
let _msDrag = null;               // 마일스톤 드래그 상태 (null | {msIdx, startX, origLeft, cellRect, _curLeft})
let _tlRangeStart = null;         // 사용자 지정 타임라인 시작월 (Date | null)
let _tlRangeEnd = null;           // 사용자 지정 타임라인 종료월 (Date | null)

/** 타임라인 시작/종료월을 프로젝트 DB에 저장 (YYYY-MM 문자열, 빈 문자열=초기화) */
async function _saveTlRange(startMonth, endMonth) {
  if (!currentProjectId) return;
  try {
    await gwFetch(`/api/fund/projects/${currentProjectId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        timeline_start_month: startMonth || '',
        timeline_end_month:   endMonth   || '',
      }),
    });
    // projectsCache 동기화
    const proj = projectsCache.find(p => p.id === currentProjectId);
    if (proj) {
      proj.timeline_start_month = startMonth || '';
      proj.timeline_end_month   = endMonth   || '';
    }
  } catch (_) { /* silent — UI 차단 불필요 */ }
}

async function loadSchedule(projectId) {
  showLoading('일정표 불러오는 중...');
  try {
    const [schedRes, ovRes] = await Promise.all([
      safeFetch(`/api/fund/projects/${projectId}/schedule`),
      safeFetch(`/api/fund/projects/${projectId}/overview`),
    ]);
    const schedData = schedRes.ok ? await schedRes.json() : { items: [] };
    const ovData = ovRes.ok ? await ovRes.json() : { overview: {} };

    const items = schedData.items || [];
    _scheduleItems = items;

    // 프로젝트가 바뀐 경우에만 뷰를 초기화: 항목이 없으면 목록 뷰, 있으면 타임라인 뷰
    // 같은 프로젝트 재로드 시 사용자가 선택한 뷰 유지
    if (_scheduleLoadedProject !== projectId) {
      _scheduleView = items.length === 0 ? 'list' : 'timeline';
      _scheduleLoadedProject = projectId;

      // 저장된 타임라인 시작/종료월 복원
      const proj = projectsCache.find(p => p.id === projectId);
      const startMon = proj?.timeline_start_month || '';
      const endMon   = proj?.timeline_end_month   || '';
      const startEl  = document.getElementById('tlRangeStart');
      const endEl    = document.getElementById('tlRangeEnd');
      if (startEl) startEl.value = startMon;
      if (endEl)   endEl.value   = endMon;
      _tlRangeStart = startMon ? new Date(startMon + '-01') : null;
      if (endMon) {
        const [y, m] = endMon.split('-').map(Number);
        _tlRangeEnd = new Date(y, m, 1);
      } else {
        _tlRangeEnd = null;
      }
    }

    renderScheduleItems(items);
    setScheduleView(_scheduleView);  // 뷰 토글 버튼 상태 반영
    renderMilestones(ovData.overview?.milestones || []);
  } catch (e) {
    showToast('일정 불러오기 실패: ' + e.message, 'error');
  } finally {
    hideLoading();
  }
}

function setScheduleView(view) {
  _scheduleView = view;
  const listEl = document.getElementById('scheduleListView');
  const tlEl = document.getElementById('scheduleTimeline');
  const btnList = document.getElementById('btnListView');
  const btnTl = document.getElementById('btnTimelineView');
  if (listEl) listEl.style.display = view === 'list' ? '' : 'none';
  if (tlEl) tlEl.style.display = view === 'timeline' ? '' : 'none';
  if (btnList) btnList.classList.toggle('active', view === 'list');
  if (btnTl) btnTl.classList.toggle('active', view === 'timeline');
  if (view === 'timeline') renderTimeline(_scheduleItems);
}

// 목록 뷰로 전환 후 새 행 추가
function addScheduleRowAndSwitch() {
  setScheduleView('list');
  addScheduleRow();
}

function renderTimeline(items) {
  const container = document.getElementById('timelineContainer');
  if (!container) return;

  const allItems = items || [];
  const barItems = allItems.filter(it => (it.item_type || 'bar') === 'bar');
  const milestones = allItems.filter(it => it.item_type === 'milestone');

  if (barItems.length === 0 && milestones.length === 0) {
    container.innerHTML = `<div class="tl-empty-msg" style="padding:40px;text-align:center;color:#6b7280;font-size:13px;">
      일정 항목이 없습니다. 아래 [+ 항목 추가] 버튼으로 추가하세요.</div>`;
    return;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // 날짜 범위 계산 (사용자 지정 우선)
  let minD, maxD;
  if (_tlRangeStart) {
    minD = new Date(_tlRangeStart);
  } else {
    minD = new Date(today); minD.setDate(1);
    allItems.forEach(it => {
      if (it.start_date) { const d = new Date(it.start_date); if (d < minD) { minD = new Date(d); minD.setDate(1); } }
    });
    minD.setDate(1); minD.setMonth(minD.getMonth() - 1);
  }
  if (_tlRangeEnd) {
    maxD = new Date(_tlRangeEnd); maxD.setDate(0); // 해당 월 마지막 날
  } else {
    maxD = new Date(today); maxD.setMonth(maxD.getMonth() + 2); maxD.setDate(1);
    allItems.forEach(it => {
      if (it.end_date) { const d = new Date(it.end_date); if (d > maxD) maxD = new Date(d); }
    });
    maxD.setMonth(maxD.getMonth() + 2); maxD.setDate(0);
  }

  // 주차 배열 생성 (월요일 시작)
  const weeks = [];
  let wStart = new Date(minD);
  const dow = wStart.getDay();
  wStart.setDate(wStart.getDate() - (dow === 0 ? 6 : dow - 1));
  let weekNo = 1;
  while (wStart <= maxD) {
    const wEnd = new Date(wStart); wEnd.setDate(wEnd.getDate() + 6);
    weeks.push({ start: new Date(wStart), end: new Date(wEnd), no: weekNo++ });
    wStart.setDate(wStart.getDate() + 7);
  }

  if (weeks.length === 0) {
    container.innerHTML = `<div style="padding:40px;text-align:center;color:#6b7280;">날짜 범위를 계산할 수 없습니다.</div>`;
    return;
  }

  const totalMs = (weeks[weeks.length - 1].end - weeks[0].start) || 1;
  const pct = (d) => Math.max(0, Math.min(100, (d - weeks[0].start) / totalMs * 100));

  // 드래그 좌표 변환용 모듈 변수 저장
  _tlWeeks = weeks;
  _tlTotalMs = totalMs;
  _tlMinStart = weeks[0].start.getTime();

  // 현재 주 인덱스
  const curWeekIdx = weeks.findIndex(w => today >= w.start && today <= w.end);

  // 월 그룹 (헤더 colspan)
  const monthGroups = [];
  weeks.forEach(w => {
    const key = w.start.getFullYear() * 100 + w.start.getMonth();
    if (!monthGroups.length || monthGroups[monthGroups.length - 1].key !== key) {
      monthGroups.push({ key, label: `${w.start.getMonth() + 1}월`, count: 1 });
    } else {
      monthGroups[monthGroups.length - 1].count++;
    }
  });

  // 그룹 색상 팔레트 (group_name 기준)
  const GROUP_COLORS = ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7'];
  const groupColorMap = {};
  const seenG = new Set();
  barItems.forEach(it => {
    const g = it.group_name || '';
    if (g && !seenG.has(g)) { seenG.add(g); groupColorMap[g] = GROUP_COLORS[seenG.size % GROUP_COLORS.length]; }
  });

  const nowMonKey = today.getFullYear() * 100 + today.getMonth();
  const fmtDate = d => `${d.getMonth() + 1}-${d.getDate()}`;
  const todayPct = pct(today);

  // HTML 빌드
  let html = `<div class="tl-scroll-wrap"><table class="tl-table">`;

  // 헤더 행 1: 월
  html += `<thead><tr class="tl-head-month"><td class="tl-left" rowspan="3" style="text-align:center;font-size:11px;color:#6b7280;">항목</td>`;
  monthGroups.forEach(mg => {
    html += `<td colspan="${mg.count}" class="${mg.key === nowMonKey ? 'cur-month' : ''}">${escapeHtml(mg.label)}</td>`;
  });
  html += `</tr>`;

  // 헤더 행 2: 주차
  html += `<tr class="tl-head-week">`;
  weeks.forEach((w, i) => {
    html += `<td class="${i === curWeekIdx ? 'cur-week' : ''}">${w.no}W</td>`;
  });
  html += `</tr>`;

  // 헤더 행 3: 날짜
  html += `<tr class="tl-head-day">`;
  weeks.forEach((w, i) => {
    html += `<td class="${i === curWeekIdx ? 'cur-week' : ''}">${fmtDate(w.start)}</td>`;
  });
  html += `</tr></thead><tbody>`;

  // 데이터 행: 바 항목별 1행 (마일스톤은 세로 선으로 전 행에 표시)
  const rowCount = barItems.length;
  if (rowCount === 0) {
    // 바 없이 마일스톤만 있는 경우: 더미 행 1개
    html += _buildItemRow(null, -1, true, weeks, pct, curWeekIdx, {}, milestones, todayPct, totalMs);
  } else {
    barItems.forEach((it, rowNum) => {
      const isLast = rowNum === rowCount - 1;
      const idx = _scheduleItems.indexOf(it);
      const colorClass = it.group_name ? (groupColorMap[it.group_name] || 'c5') : (it.status || 'planned');
      html += _buildItemRow(it, idx, isLast, weeks, pct, curWeekIdx, colorClass, milestones, todayPct, totalMs);
    });
  }

  html += `</tbody></table></div>`;
  container.innerHTML = html;
}

// 바 항목 1행 렌더링 (it=null이면 마일스톤 전용 더미 행)
function _buildItemRow(it, idx, isLast, weeks, pct, curWeekIdx, colorClass, milestones, todayPct, totalMs) {
  const isMilestoneOnly = (it === null);
  const itemName = it ? (it.item_name || '') : '';
  const groupName = it ? (it.group_name || '') : '';

  let html = `<tr class="tl-data-row">`;
  html += `<td class="tl-left"><div class="tl-left-inner">
    <div class="tl-group-name">${escapeHtml(itemName)}</div>
    ${groupName ? `<div class="tl-group-subtitle">${escapeHtml(groupName)}</div>` : ''}
  </div></td>`;

  // 전체 주차 단일 td (colspan)
  html += `<td colspan="${weeks.length}" class="tl-cell" style="height:40px;">`;

  // 주차 구분 세로선
  html += `<div style="position:absolute;inset:0;display:flex;pointer-events:none;">`;
  weeks.forEach((w, i) => {
    html += `<div style="flex:1;border-right:1px solid rgba(255,255,255,0.04);${i === curWeekIdx ? 'background:rgba(59,130,246,0.04);' : ''}"></div>`;
  });
  html += `</div>`;

  // 오늘 마커 (선은 전 행, 칩 레이블은 마지막 행에만)
  html += `<div class="tl-today-line" style="left:${todayPct.toFixed(2)}%">
    ${isLast ? '<span class="tl-today-chip">오늘</span>' : ''}
  </div>`;

  // 마일스톤 라인 (전 행에 선 표시; 레이블은 마지막 행에만)
  milestones.forEach(ms => {
    if (!ms.start_date) return;
    const msIdx = _scheduleItems.indexOf(ms);
    const msPct = pct(new Date(ms.start_date));
    const lineColor = ms.bar_color || '#a855f7';
    html += `<div class="tl-milestone-line" data-ms-idx="${msIdx}" style="left:${msPct.toFixed(2)}%;border-color:${escapeHtml(lineColor)};">
      ${isLast ? `<span class="tl-milestone-label" style="color:${escapeHtml(lineColor)};">${escapeHtml(ms.item_name || '')}</span>` : ''}
    </div>`;
  });

  // 바 렌더링
  if (!isMilestoneOnly && it.start_date && it.end_date) {
    const s = new Date(it.start_date), e = new Date(it.end_date);
    const left = pct(s);
    const right = pct(new Date(e.getTime() + 86400000));
    const width = Math.max(0.8, right - left);
    const barColor = it.bar_color || '';
    const styleExtra = barColor ? `background:${escapeHtml(barColor)};` : '';
    const isCritical = it.is_critical || false;
    const cpStyle = isCritical ? 'border:2px solid #dc2626;box-shadow:0 0 4px rgba(220,38,38,0.4);' : '';
    const cls = barColor ? '' : colorClass;
    const floatInfo = it.total_float > 0 ? ` | 여유:${it.total_float}일` : '';
    const cpMark = isCritical ? '★ ' : '';
    html += `<div class="tl-bar ${cls}" data-idx="${idx}"
      style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;${styleExtra}${cpStyle}"
      title="${cpMark}${escapeHtml(itemName)} (${escapeHtml(it.start_date)}~${escapeHtml(it.end_date)})${floatInfo}">
      <div class="tl-bar-lh"></div>
      <span class="tl-bar-text">${cpMark}${escapeHtml(itemName)}</span>
      <div class="tl-bar-rh"></div>
    </div>`;
  }

  html += `</td></tr>`;
  return html;
}

function openSchedulePopover(idx, event) {
  _popoverItemIndex = idx;
  const item = _scheduleItems[idx];
  if (!item) return;

  document.getElementById('popItemName').value = item.item_name || '';
  document.getElementById('popStartDate').value = item.start_date || '';
  document.getElementById('popEndDate').value = item.end_date || '';
  document.getElementById('popStatus').value = item.status || 'planned';
  document.getElementById('popNotes').value = item.notes || '';
  const gpEl = document.getElementById('popGroupName');
  if (gpEl) gpEl.value = item.group_name || '';
  const itEl = document.getElementById('popItemType');
  if (itEl) itEl.value = item.item_type || 'bar';

  const popover = document.getElementById('scheduleItemPopover');
  popover.style.display = '';

  // 팝오버 위치 계산 (화면 넘침 방지)
  const rect = event.target.getBoundingClientRect();
  let top = rect.bottom + 8;
  let left = rect.left;
  const pw = 310;
  const ph = 340;
  if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
  if (left < 8) left = 8;
  if (top + ph > window.innerHeight - 8) top = rect.top - ph - 8;
  if (top < 8) top = 8;
  popover.style.top = top + 'px';
  popover.style.left = left + 'px';
}

function closeSchedulePopover() {
  const pop = document.getElementById('scheduleItemPopover');
  if (pop) pop.style.display = 'none';
  _popoverItemIndex = -1;
}

// ───── 타임라인 드래그 헬퍼 ─────

function _msToDateStr(ms) {
  const d = new Date(ms);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function _snapToDay(d) {
  const s = new Date(d);
  s.setHours(0, 0, 0, 0);
  return s;
}

// 바 드래그 시작 (dragType: 'left' | 'right')
function _onBarDragStart(e, dragType, idx) {
  e.preventDefault();
  e.stopPropagation();
  const cell = e.target.closest('.tl-cell');
  if (!cell) return;
  const barEl = cell.querySelector(`.tl-bar[data-idx="${idx}"]`);
  if (!barEl) return;
  const cellRect = cell.getBoundingClientRect();
  const origLeft = parseFloat(barEl.style.left) || 0;
  const origWidth = parseFloat(barEl.style.width) || 0;
  _barDrag = { idx, dragType, startX: e.clientX, origLeft, origWidth, cellRect, _curLeft: origLeft, _curWidth: origWidth };
  document.addEventListener('mousemove', _onBarDragMove);
  document.addEventListener('mouseup', _onBarDragEnd, { once: true });
}

function _onBarDragMove(e) {
  if (!_barDrag) return;
  const { dragType, startX, origLeft, origWidth, cellRect, idx } = _barDrag;
  const deltaPct = (e.clientX - startX) / cellRect.width * 100;
  let newLeft = origLeft, newWidth = origWidth;
  if (dragType === 'left') {
    newLeft = Math.max(0, origLeft + deltaPct);
    newWidth = Math.max(0.8, origWidth - deltaPct);
  } else { // 'right'
    newWidth = Math.max(0.8, origWidth + deltaPct);
  }
  // 시각적 즉시 반영 (재렌더링 없음)
  const container = document.getElementById('timelineContainer');
  container?.querySelectorAll(`.tl-bar[data-idx="${idx}"]`).forEach(el => {
    el.style.left = `${newLeft.toFixed(2)}%`;
    el.style.width = `${newWidth.toFixed(2)}%`;
  });
  _barDrag._curLeft = newLeft;
  _barDrag._curWidth = newWidth;
}

function _onBarDragEnd() {
  if (!_barDrag) return;
  document.removeEventListener('mousemove', _onBarDragMove);
  const { idx } = _barDrag;
  const newLeft = _barDrag._curLeft;
  const newWidth = _barDrag._curWidth;
  _barDrag = null;
  // 퍼센트 → 날짜 변환
  const startMs = _tlMinStart + newLeft / 100 * _tlTotalMs;
  const endMs = _tlMinStart + (newLeft + newWidth) / 100 * _tlTotalMs - 86400000;
  const item = _scheduleItems[idx];
  if (!item) return;
  item.start_date = _msToDateStr(_snapToDay(new Date(startMs)).getTime());
  item.end_date = _msToDateStr(_snapToDay(new Date(Math.max(startMs, endMs))).getTime());
  _saveScheduleItems(_scheduleItems);
  renderTimeline(_scheduleItems);
}

// 마일스톤 드래그 시작
function _onMsDragStart(e, msIdx) {
  e.preventDefault();
  e.stopPropagation();
  const cell = e.target.closest('.tl-cell');
  if (!cell) return;
  const msEl = cell.querySelector(`.tl-milestone-line[data-ms-idx="${msIdx}"]`);
  if (!msEl) return;
  const cellRect = cell.getBoundingClientRect();
  const origLeft = parseFloat(msEl.style.left) || 0;
  _msDrag = { msIdx, startX: e.clientX, origLeft, cellRect, _curLeft: origLeft };
  document.addEventListener('mousemove', _onMsDragMove);
  document.addEventListener('mouseup', _onMsDragEnd, { once: true });
}

function _onMsDragMove(e) {
  if (!_msDrag) return;
  const { msIdx, startX, origLeft, cellRect } = _msDrag;
  const deltaPct = (e.clientX - startX) / cellRect.width * 100;
  const newLeft = Math.max(0, Math.min(99, origLeft + deltaPct));
  // 모든 행의 같은 마일스톤 라인 동시 이동
  document.querySelectorAll(`.tl-milestone-line[data-ms-idx="${msIdx}"]`).forEach(el => {
    el.style.left = `${newLeft.toFixed(2)}%`;
  });
  _msDrag._curLeft = newLeft;
}

function _onMsDragEnd() {
  if (!_msDrag) return;
  document.removeEventListener('mousemove', _onMsDragMove);
  const { msIdx } = _msDrag;
  const newLeft = _msDrag._curLeft;
  _msDrag = null;
  const newMs = _tlMinStart + newLeft / 100 * _tlTotalMs;
  const newDateStr = _msToDateStr(_snapToDay(new Date(newMs)).getTime());
  const item = _scheduleItems[msIdx];
  if (!item) return;
  item.start_date = newDateStr;
  item.end_date = newDateStr; // 마일스톤은 단일 날짜
  _saveScheduleItems(_scheduleItems);
  renderTimeline(_scheduleItems);
}

function saveScheduleItemFromPopover() {
  if (_popoverItemIndex < 0 || _popoverItemIndex >= _scheduleItems.length) return;
  const item = _scheduleItems[_popoverItemIndex];
  const newName = document.getElementById('popItemName').value.trim();
  item.item_name  = newName || item.item_name;
  item.start_date = document.getElementById('popStartDate').value;
  item.end_date   = document.getElementById('popEndDate').value;
  item.status     = document.getElementById('popStatus').value;
  item.notes      = document.getElementById('popNotes').value.trim();
  const gpEl = document.getElementById('popGroupName');
  if (gpEl) item.group_name = gpEl.value.trim();
  const itEl = document.getElementById('popItemType');
  if (itEl) item.item_type = itEl.value;

  closeSchedulePopover();
  renderTimeline(_scheduleItems);
  renderScheduleItems(_scheduleItems);  // 목록 뷰도 동기화
  _saveScheduleItems(_scheduleItems);
}

function deleteScheduleItemFromPopover() {
  if (_popoverItemIndex < 0) return;
  if (!confirm('이 항목을 삭제할까요?')) return;
  _scheduleItems.splice(_popoverItemIndex, 1);
  closeSchedulePopover();
  renderTimeline(_scheduleItems);
  renderScheduleItems(_scheduleItems);
  _saveScheduleItems(_scheduleItems);
}

async function _saveScheduleItems(items) {
  if (!currentProjectId) return;
  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('일정 저장 완료', 'success');
  } catch (e) {
    showToast('저장 실패: ' + e.message, 'error');
  }
}

function renderScheduleItems(items) {
  const tbody = document.getElementById('scheduleBody');
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">항목 없음 — 아래 버튼으로 추가하세요</td></tr>';
    return;
  }
  const statusMap = {
    planned: { label: '준비중', cls: 'sch-planned' },
    ongoing: { label: '진행중', cls: 'sch-ongoing' },
    done:    { label: '완료',   cls: 'sch-done' },
    hold:    { label: '보류',   cls: 'sch-hold' },
  };
  tbody.innerHTML = items.map((item, idx) => {
    const st = statusMap[item.status] || statusMap.planned;
    return `
    <tr data-id="${Number(item.id) || ''}">
      <td class="ms-num">${idx + 1}</td>
      <td><input type="text" class="sch-name-field" value="${escapeHtml(item.item_name || '')}" placeholder="항목명" /></td>
      <td><input type="text" class="sch-group-field" value="${escapeHtml(item.group_name || '')}" placeholder="그룹명" /></td>
      <td>
        <select class="sch-type-select">
          <option value="bar"       ${(item.item_type || 'bar') === 'bar'       ? 'selected' : ''}>바</option>
          <option value="milestone" ${item.item_type === 'milestone' ? 'selected' : ''}>마일스톤</option>
        </select>
      </td>
      <td><input type="date" class="sch-start-field" value="${escapeHtml(item.start_date || '')}" /></td>
      <td><input type="date" class="sch-end-field"   value="${escapeHtml(item.end_date || '')}" /></td>
      <td>
        <select class="sch-status-select ${st.cls}">
          <option value="planned" ${item.status === 'planned' ? 'selected' : ''}>준비중</option>
          <option value="ongoing" ${item.status === 'ongoing' ? 'selected' : ''}>진행중</option>
          <option value="done"    ${item.status === 'done'    ? 'selected' : ''}>완료</option>
          <option value="hold"    ${item.status === 'hold'    ? 'selected' : ''}>보류</option>
        </select>
      </td>
      <td><button class="btn-icon btn-del-sch" title="삭제">&times;</button></td>
    </tr>`;
  }).join('');
}

function addScheduleRow() {
  const tbody = document.getElementById('scheduleBody');
  const noData = tbody.querySelector('.no-data');
  if (noData) noData.parentElement?.remove();
  const num = tbody.querySelectorAll('tr').length + 1;
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="ms-num">${num}</td>
    <td><input type="text" class="sch-name-field" value="" placeholder="항목명" /></td>
    <td><input type="text" class="sch-group-field" value="" placeholder="그룹명" /></td>
    <td>
      <select class="sch-type-select">
        <option value="bar" selected>바</option>
        <option value="milestone">마일스톤</option>
      </select>
    </td>
    <td><input type="date" class="sch-start-field" value="" /></td>
    <td><input type="date" class="sch-end-field"   value="" /></td>
    <td>
      <select class="sch-status-select sch-planned">
        <option value="planned" selected>준비중</option>
        <option value="ongoing">진행중</option>
        <option value="done">완료</option>
        <option value="hold">보류</option>
      </select>
    </td>
    <td><button class="btn-icon btn-del-sch" title="삭제">&times;</button></td>
  `;
  tbody.appendChild(tr);
  tr.querySelector('.sch-name-field').focus();
  // _scheduleItems에도 빈 항목 추가 (타임라인 뷰 전환 시 반영)
  _scheduleItems.push({ item_name: '', group_name: '', item_type: 'bar', start_date: '', end_date: '', status: 'planned', notes: '' });
}

function _collectScheduleItems() {
  const rows = document.querySelectorAll('#scheduleBody tr:not(.no-data)');
  const items = [];
  rows.forEach(tr => {
    const name = tr.querySelector('.sch-name-field')?.value?.trim() || '';
    if (!name) return;
    items.push({
      item_name:  name,
      group_name: tr.querySelector('.sch-group-field')?.value?.trim() || '',
      item_type:  tr.querySelector('.sch-type-select')?.value || 'bar',
      start_date: tr.querySelector('.sch-start-field')?.value || '',
      end_date:   tr.querySelector('.sch-end-field')?.value || '',
      notes:      tr.querySelector('.sch-notes-field')?.value?.trim() || '',
      status:     tr.querySelector('.sch-status-select')?.value || 'planned',
    });
  });
  return items;
}

async function saveSchedule() {
  if (!currentProjectId) return;
  try {
    const items = _collectScheduleItems();
    _scheduleItems = items;  // 목록 뷰 저장 후 단일 소스 동기화
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('공정 일정이 저장되었습니다.', 'success');
    // 타임라인이 보이는 경우 재렌더링
    if (_scheduleView === 'timeline') renderTimeline(_scheduleItems);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function saveMilestonesFromSchedule() {
  if (!currentProjectId) return;
  const milestones = [];
  document.querySelectorAll('#milestoneBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const id = tr.dataset.id ? parseInt(tr.dataset.id) : null;
    const name = tr.querySelector('[data-field="name"]')?.value?.trim() || '';
    const completed = tr.querySelector('[data-field="completed"]')?.checked ? 1 : 0;
    const date = tr.querySelector('[data-field="date"]')?.value?.trim() || '';
    if (name) milestones.push({ id, name, completed, date });
  });
  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/overview`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ milestones }),
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast('마일스톤이 저장되었습니다.', 'success');
    updateOvMilestoneSummary(milestones);
    markRelatedTabsDirty('dashboard');
  } catch (e) {
    showToast(e.message, 'error');
  }
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
      const cacheUpdated = escapeHtml(String(data.cache_updated || '').slice(0, 16));
      cacheInfoEl.innerHTML = `
        <span>총 ${Number(data.cache_count) || 0}개 중 ${Number(data.total) || 0}개 표시 · 동기화: ${cacheUpdated}</span>
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
      loadProjects();
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

async function importScheduleFromPm() {
  const overwrite = confirm('이미 일정 데이터가 있는 프로젝트도 덮어쓸까요?\n[확인] = 덮어쓰기, [취소] = 신규 프로젝트만');
  const btn = document.getElementById('btnImportSchedulePm');
  if (btn) { btn.disabled = true; btn.textContent = '가져오는 중...'; }
  try {
    const res = await gwFetch('/api/fund/import-schedule-from-pm-sheet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overwrite })
    });
    const data = await res.json();
    if (data.success !== false) {
      showToast(`일정 데이터 가져오기 완료: ${data.imported_count ?? 0}개 프로젝트 반영`);
      if (currentProjectId) markRelatedTabsDirty('schedule');
    } else {
      showToast('일정 가져오기 실패: ' + (data.message || '알 수 없는 오류'), 'error');
    }
  } catch (e) {
    showToast('일정 가져오기 오류: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '일정 가져오기'; }
  }
}

async function importCollectionsFromPm() {
  const overwrite = confirm('이미 수금현황 데이터가 있는 프로젝트도 덮어쓸까요?\n[확인] = 덮어쓰기, [취소] = 신규 프로젝트만');
  const btn = document.getElementById('btnImportCollectionsPm');
  if (btn) { btn.disabled = true; btn.textContent = '가져오는 중...'; }
  try {
    const res = await gwFetch('/api/fund/import-collections-from-pm-sheet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overwrite })
    });
    const data = await res.json();
    if (data.success !== false) {
      showToast(`수금일정 가져오기 완료: ${data.imported_count ?? 0}개 프로젝트 반영`);
      if (currentProjectId) markRelatedTabsDirty('collections');
    } else {
      showToast('수금일정 가져오기 실패: ' + (data.message || data.error || '알 수 없는 오류'), 'error');
    }
  } catch (e) {
    showToast('수금일정 가져오기 오류: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '수금일정 가져오기'; }
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
    } else if (el.classList.contains('num-input')) {
      payload[field] = parseAmountInput(el);
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
    markRelatedTabsDirty('schedule');
    await loadOverview(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ===== 하도급상세 탭 =====
async function loadSubcontracts(projectId) {
  showLoading('하도급 상세 불러오는 중...');
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/subcontracts`);
    if (!res.ok) throw new Error('하도급 조회 실패');
    const data = await res.json();
    renderSubcontractTable(data.subcontracts || []);
    _subcontractUnsaved = false; // 새로 로드됐으므로 미저장 플래그 초기화
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    hideLoading();
  }
}

function renderSubcontractTable(rows) {
  const tbody = document.getElementById('subcontractBody');
  const table = document.getElementById('subcontractTable');
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="16" class="no-data">데이터 없음 - "행 추가" 버튼으로 추가하세요.</td></tr>';
    // 손익 카드도 초기화
    _updateSubcontractSummaryCards(0, 0, 0);
    // tfoot 제거
    const oldTfoot = table.querySelector('tfoot');
    if (oldTfoot) oldTfoot.remove();
    return;
  }

  // 공종명 조회 헬퍼 (tradesCache에서 id→name)
  const _tradeName = (tradeId) => {
    const t = tradesCache.find(tc => tc.id === tradeId);
    return t ? t.name : '';
  };

  // 공종별 그룹핑 (소계 계산용)
  const groups = {};
  rows.forEach(r => {
    const tname = _tradeName(r.trade_id) || '미지정';
    if (!groups[tname]) groups[tname] = { rows: [], contractSum: 0, paidSum: 0 };
    groups[tname].rows.push(r);
    const eff = (r.changed_contract_amount > 0) ? r.changed_contract_amount : (r.contract_amount || 0);
    groups[tname].contractSum += eff;
    let paid = 0;
    for (let n = 1; n <= 4; n++) {
      if (r[`payment_${n}_confirmed`]) paid += (r[`payment_${n}`] || 0);
    }
    groups[tname].paidSum += paid;
  });
  const groupKeys = Object.keys(groups);
  const showGroupHeaders = groupKeys.length > 1;

  // 행 렌더링 (공종별 그룹 헤더 포함)
  let html = '';
  let rowIdx = 0;
  groupKeys.forEach(gname => {
    const g = groups[gname];
    // 그룹 헤더 (2개 이상 그룹일 때만)
    if (showGroupHeaders) {
      html += `<tr class="subcontract-group-header">
        <td colspan="16">${escapeHtml(gname)} (${g.rows.length}개 업체) — 소계: ${formatNum(g.contractSum)}원</td>
      </tr>`;
    }
    g.rows.forEach(r => {
      const p1 = r.payment_1 || 0, p2 = r.payment_2 || 0, p3 = r.payment_3 || 0, p4 = r.payment_4 || 0;
      const c1 = r.payment_1_confirmed, c2 = r.payment_2_confirmed, c3 = r.payment_3_confirmed, c4 = r.payment_4_confirmed;
      const totalPaid = (c1 ? p1 : 0) + (c2 ? p2 : 0) + (c3 ? p3 : 0) + (c4 ? p4 : 0);
      const effectiveContract = (r.changed_contract_amount > 0) ? r.changed_contract_amount : (r.contract_amount || 0);
      const remaining = effectiveContract - totalPaid;
      const pct = effectiveContract ? (totalPaid / effectiveContract * 100).toFixed(1) : '0.0';
      rowIdx++;

      html += `<tr data-id="${r.id}">
        <td>${rowIdx}</td>
        <td><select class="sc-trade" data-field="trade_id">
          <option value="">-- 선택 --</option>
          ${tradesCache.map(t => `<option value="${t.id}" ${t.id === r.trade_id ? 'selected' : ''}>${escapeHtml(t.name)}</option>`).join('')}
        </select></td>
        <td><input type="text" class="sc-field" data-field="company_name" value="${escapeHtml(r.company_name || '')}" placeholder="업체명" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="contract_amount" value="${formatNum(r.contract_amount || 0)}" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="changed_contract_amount" value="${formatNum(r.changed_contract_amount || 0)}" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="payment_1" value="${formatNum(p1)}" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="payment_2" value="${formatNum(p2)}" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="payment_3" value="${formatNum(p3)}" /></td>
        <td class="num"><input type="text" class="sc-field num-input" data-field="payment_4" value="${formatNum(p4)}" /></td>
        <td class="num sc-remaining">${formatNum(remaining)}</td>
        <td class="num sc-pct">${pct}%</td>
        <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_1_confirmed" ${c1 ? 'checked' : ''} /></td>
        <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_2_confirmed" ${c2 ? 'checked' : ''} /></td>
        <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_3_confirmed" ${c3 ? 'checked' : ''} /></td>
        <td class="chk"><input type="checkbox" class="sc-field sc-recalc-trigger" data-field="payment_4_confirmed" ${c4 ? 'checked' : ''} /></td>
        <td><button class="btn-icon btn-remove-sc-row" title="삭제">&times;</button></td>
      </tr>`;
    });
  });
  tbody.innerHTML = html;

  // 금액 변경 재계산은 이벤트 위임으로 처리 (DOMContentLoaded 내 document change 리스너)

  // [개선] 손익 요약 카드 업데이트
  let totalContract = 0, totalPaidSum = 0;
  rows.forEach(r => {
    // 변경계약금액 우선
    totalContract += (r.changed_contract_amount > 0) ? r.changed_contract_amount : (r.contract_amount || 0);
    const p1 = r.payment_1_confirmed ? (r.payment_1 || 0) : 0;
    const p2 = r.payment_2_confirmed ? (r.payment_2 || 0) : 0;
    const p3 = r.payment_3_confirmed ? (r.payment_3 || 0) : 0;
    const p4 = r.payment_4_confirmed ? (r.payment_4 || 0) : 0;
    totalPaidSum += p1 + p2 + p3 + p4;
  });
  _updateSubcontractSummaryCards(totalContract, totalPaidSum, totalContract - totalPaidSum);

  // [개선] tfoot sticky 합계 행 렌더링
  _renderSubcontractTfoot(totalContract, totalPaidSum);
}

// 행별 잔여금액/지급율 실시간 재계산 (체크박스 or 금액 변경 시)
function recalcSubcontractRow(el) {
  const tr = el.closest('tr');
  if (!tr) return;
  const contractRaw = parseAmountInput(tr.querySelector('[data-field="contract_amount"]'));
  const changedRaw = parseAmountInput(tr.querySelector('[data-field="changed_contract_amount"]'));
  const contract = changedRaw > 0 ? changedRaw : contractRaw;
  let totalPaid = 0;
  for (let n = 1; n <= 4; n++) {
    const chk = tr.querySelector(`[data-field="payment_${n}_confirmed"]`);
    const amt = parseAmountInput(tr.querySelector(`[data-field="payment_${n}"]`));
    if (chk && chk.checked) totalPaid += amt;
  }
  const remaining = contract - totalPaid;
  const pct = contract ? (totalPaid / contract * 100).toFixed(1) : '0.0';
  tr.querySelector('.sc-remaining').textContent = formatNum(remaining);
  tr.querySelector('.sc-pct').textContent = pct + '%';

  // [개선] 전체 합계 카드도 실시간 재계산
  _recalcSubcontractSummaryFromDOM();
}

/** 하도급 손익 카드 DOM에서 직접 재계산 */
function _recalcSubcontractSummaryFromDOM() {
  let totalContract = 0, totalPaidSum = 0;
  document.querySelectorAll('#subcontractBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const contractRaw = parseAmountInput(tr.querySelector('[data-field="contract_amount"]'));
    const changedRaw = parseAmountInput(tr.querySelector('[data-field="changed_contract_amount"]'));
    const contract = changedRaw > 0 ? changedRaw : contractRaw;
    totalContract += contract;
    let paid = 0;
    for (let n = 1; n <= 4; n++) {
      const chk = tr.querySelector(`[data-field="payment_${n}_confirmed"]`);
      const amt = parseAmountInput(tr.querySelector(`[data-field="payment_${n}"]`));
      if (chk && chk.checked) paid += amt;
    }
    totalPaidSum += paid;
  });
  _updateSubcontractSummaryCards(totalContract, totalPaidSum, totalContract - totalPaidSum);
  _renderSubcontractTfoot(totalContract, totalPaidSum);
}

/** 하도급 손익 요약 카드 3개 업데이트 헬퍼 */
function _updateSubcontractSummaryCards(totalContract, totalPaid, totalRemain) {
  const elContract = document.getElementById('scTotalContract');
  const elPaid     = document.getElementById('scTotalPaid');
  const elRemain   = document.getElementById('scTotalRemain');
  if (elContract) elContract.textContent = formatWon(totalContract) + '원';
  if (elPaid)     elPaid.textContent     = formatWon(totalPaid) + '원';
  if (elRemain)   elRemain.textContent   = formatWon(totalRemain) + '원';
}

/** 하도급 테이블 tfoot sticky 합계 행 렌더링 */
function _renderSubcontractTfoot(totalContract, totalPaid) {
  const table = document.getElementById('subcontractTable');
  if (!table) return;
  // 기존 tfoot 제거
  const oldTfoot = table.querySelector('tfoot');
  if (oldTfoot) oldTfoot.remove();

  const totalRemain = totalContract - totalPaid;
  const pct = totalContract ? (totalPaid / totalContract * 100).toFixed(1) : '0.0';
  const tfoot = document.createElement('tfoot');
  tfoot.innerHTML = `<tr>
    <td colspan="3" style="text-align:center;">합계</td>
    <td class="num">${formatNum(totalContract)}</td>
    <td class="num"></td>
    <td colspan="4"></td>
    <td class="num">${formatNum(totalRemain)}</td>
    <td class="num">${pct}%</td>
    <td colspan="5"></td>
  </tr>`;
  table.appendChild(tfoot);
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
    <td class="num"><input type="text" class="sc-field num-input" data-field="contract_amount" value="0" /></td>
    <td class="num"><input type="text" class="sc-field num-input" data-field="payment_1" value="0" /></td>
    <td class="num"><input type="text" class="sc-field num-input" data-field="payment_2" value="0" /></td>
    <td class="num"><input type="text" class="sc-field num-input" data-field="payment_3" value="0" /></td>
    <td class="num"><input type="text" class="sc-field num-input" data-field="payment_4" value="0" /></td>
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
      } else if (el.classList.contains('num-input')) {
        row[field] = parseAmountInput(el);
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
    _subcontractUnsaved = false; // [개선] 저장 성공 시 미저장 플래그 초기화
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
  showLoading('수금현황 불러오는 중...');
  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/collections`);
    if (!res.ok) throw new Error('수금현황 조회 실패');
    const data = await res.json();
    renderCollections(data.collections || []);
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    hideLoading();
  }
}

// 수금 예정일 D-day 긴급도 계산 (미수금 항목만)
function _collDateClass(dateStr, collected) {
  if (!dateStr || collected) return '';
  const date = new Date(dateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.ceil((date - today) / (1000 * 60 * 60 * 24));
  if (diff < 0) return 'coll-overdue';    // 기한 초과
  if (diff <= 3) return 'coll-urgent';    // D-3 이내
  return '';
}

/**
 * [4] 수금 예정일 D-Day 인라인 배지 HTML 반환
 * - 수금 완료: 빈 문자열 (배지 없음)
 * - 예정일 없음: 빈 문자열
 * - 기한 초과(D+N): 빨강 배지
 * - D-Day: 빨강 배지
 * - D-3 이내: 주황 점멸 배지
 * - D-4~D-7: 파랑 배지
 * - D-8 이상: 배지 없음
 */
function _collDdayBadge(dateStr, collected) {
  if (!dateStr || collected) return '';
  const diff = calcDday(dateStr);
  if (diff === null) return '';
  if (diff < 0) {
    return `<span class="coll-dday-badge coll-dday-over">D+${Math.abs(diff)}</span>`;
  }
  if (diff === 0) {
    return '<span class="coll-dday-badge coll-dday-today">D-Day</span>';
  }
  if (diff <= 3) {
    return `<span class="coll-dday-badge coll-dday-urgent">D-${diff}</span>`;
  }
  if (diff <= 7) {
    return `<span class="coll-dday-badge coll-dday-soon">D-${diff}</span>`;
  }
  return ''; // D-8 이상: 배지 없음
}

function renderCollections(items) {
  const designBody = document.getElementById('collectionDesignBody');
  const constructionBody = document.getElementById('collectionConstructionBody');

  const designItems = items.filter(c => c.category === '설계');
  const constructionItems = items.filter(c => c.category === '시공');

  // [개선] 전체 빈 상태 처리 — 수금 데이터가 전혀 없을 때 안내 메시지 표시
  const emptyState = document.getElementById('collectionsEmptyState');
  if (emptyState) {
    emptyState.style.display = items.length === 0 ? 'block' : 'none';
  }

  // [4] 수금 행 렌더 헬퍼: D-Day 배지 포함
  const renderCollRow = (c, amtType = 'text') => {
    const urgency = _collDateClass(c.collection_date, c.collected);
    // D-Day 배지: 미수금 + 예정일 있을 때만
    const ddayBadge = _collDdayBadge(c.collection_date, c.collected);
    const amtInput = amtType === 'text'
      ? `<input type="text" class="coll-field coll-recalc-trigger num-input" data-field="amount" value="${formatNum(c.amount || 0)}" />`
      : `<input type="number" class="coll-field coll-recalc-trigger" data-field="amount" value="${c.amount || 0}" />`;
    return `
    <tr data-id="${c.id}" class="${urgency}">
      <td>${escapeHtml(c.stage)}</td>
      <td class="num">${amtInput}</td>
      <td class="coll-date-cell">
        <input type="date" class="coll-field" data-field="collection_date" value="${escapeHtml(c.collection_date || '')}" />
        ${ddayBadge}
      </td>
      <td class="chk"><input type="checkbox" class="coll-field coll-recalc-trigger" data-field="collected" ${c.collected ? 'checked' : ''} /></td>
    </tr>`;
  };

  // 설계 테이블
  if (designItems.length === 0) {
    designBody.innerHTML = '<tr><td colspan="4" class="no-data">데이터 없음</td></tr>';
  } else {
    designBody.innerHTML = designItems.map(c => renderCollRow(c, 'text')).join('');
  }

  // 시공 테이블
  if (constructionItems.length === 0) {
    constructionBody.innerHTML = '<tr><td colspan="4" class="no-data">데이터 없음</td></tr>';
  } else {
    constructionBody.innerHTML = constructionItems.map(c => renderCollRow(c, 'number')).join('');
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

  // [3] 수금률 진행바 업데이트
  _updateCollectionProgressBar(rate, totalCollected, uncollected);

  // [개선] 미수금 합계 배너 업데이트
  _updateUncollectedBanner(uncollected, rate);
}

/**
 * [3] 수금률 진행바 업데이트 (내부 헬퍼)
 * - #collectionProgressWrap 컨테이너에 진행바 렌더링
 * - 컨테이너 없으면 무시 (graceful)
 */
function _updateCollectionProgressBar(rate, collected, uncollected) {
  const wrap = document.getElementById('collectionProgressWrap');
  if (!wrap) return;
  const pct = Math.min(Math.max(rate, 0), 100);
  // 수금률에 따라 색상 결정
  let fillColor = 'var(--success)';
  if (pct < 30) fillColor = 'var(--danger)';
  else if (pct < 70) fillColor = 'var(--warning)';

  wrap.innerHTML = `
    <div class="coll-progress-wrap">
      <div class="coll-progress-header">
        <span class="coll-progress-label">수금 진행률</span>
        <span class="coll-progress-pct" style="color:${fillColor};">${pct.toFixed(1)}%</span>
      </div>
      <div class="coll-progress-bar-bg">
        <div class="coll-progress-bar-fill" style="width:${pct}%; background:${fillColor};"></div>
      </div>
      <div class="coll-progress-detail">
        <span>수금 ${formatWon(collected)}원</span>
        <span>미수금 ${formatWon(uncollected)}원</span>
      </div>
    </div>
  `;
}

/** 미수금 배너 업데이트 (내부 헬퍼) */
function _updateUncollectedBanner(uncollected, rate) {
  const banner = document.getElementById('uncollectedBanner');
  const bannerAmt = document.getElementById('bannerUncollected');
  const bannerRate = document.getElementById('bannerCollectionRate');
  if (!banner) return;
  // 미수금이 있을 때만 배너 표시
  if (uncollected > 0) {
    banner.style.display = 'flex';
    if (bannerAmt)  bannerAmt.textContent  = formatWon(uncollected) + '원';
    if (bannerRate) bannerRate.textContent = '수금율 ' + rate.toFixed(1) + '%';
  } else {
    banner.style.display = 'none';
  }
}

// 체크박스/금액 변경 시 실시간 합계 재계산
function recalcCollectionSummary() {
  let totalAmount = 0, totalCollected = 0;
  document.querySelectorAll('#collectionDesignBody tr, #collectionConstructionBody tr').forEach(tr => {
    if (tr.querySelector('.no-data')) return;
    const amtInput = tr.querySelector('[data-field="amount"]');
    const chkInput = tr.querySelector('[data-field="collected"]');
    const amt = parseAmountInput(amtInput);
    totalAmount += amt;
    if (chkInput?.checked) totalCollected += amt;
  });
  const uncollected = totalAmount - totalCollected;
  const rate = totalAmount ? (totalCollected / totalAmount * 100) : 0;
  document.getElementById('valTotalCollected').textContent = formatWon(totalCollected);
  document.getElementById('valTotalUncollected').textContent = formatWon(uncollected);
  document.getElementById('valCollectionRate').textContent = rate.toFixed(1) + '%';

  // [3] 수금률 진행바 실시간 업데이트
  _updateCollectionProgressBar(rate, totalCollected, uncollected);
  // [개선] 미수금 배너도 실시간 업데이트
  _updateUncollectedBanner(uncollected, rate);
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
        } else if (el.classList.contains('num-input')) {
          item[field] = parseAmountInput(el);
        } else {
          item[field] = el.value;
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

// ===== 대시보드 인쇄 (보고서 레이아웃) =====
async function printDashboard() {
  if (!currentProjectId) { showToast('프로젝트를 선택해주세요.', 'error'); return; }

  showToast('보고서 생성 중...', 'info');

  // 데이터 수집
  const [sumR, colR, subR, ovR] = await Promise.all([
    safeFetch(`/api/fund/projects/${currentProjectId}/summary`),
    safeFetch(`/api/fund/projects/${currentProjectId}/collections`),
    safeFetch(`/api/fund/projects/${currentProjectId}/subcontracts`),
    safeFetch(`/api/fund/projects/${currentProjectId}/overview`),
  ]);
  const s = (sumR.ok ? await sumR.json() : {}).summary || {};
  const colls = (colR.ok ? await colR.json() : {}).collections || [];
  const subs  = (subR.ok ? await subR.json() : {}).subcontracts || [];
  const ov    = (ovR.ok  ? await ovR.json() : {}).overview || {};

  // 계산
  const totalOrder = s.total_order || ((s.design_amount||0) + (s.construction_amount||0));
  const execBudget = s.execution_budget || 0;
  const profit = s.profit_amount || 0;
  const profitRate = s.profit_rate || 0;

  let payLimit = 0, totalPaid = 0;
  subs.forEach(sc => {
    payLimit += (sc.contract_amount || 0);
    [1,2,3,4].forEach(n => { if (sc[`payment_${n}_confirmed`]) totalPaid += (sc[`payment_${n}`] || 0); });
  });

  let collTotal = 0, collDone = 0;
  colls.forEach(c => { collTotal += (c.amount||0); if (c.collected) collDone += (c.amount||0); });
  const collRate = collTotal ? (collDone/collTotal*100) : 0;
  const payRate = payLimit ? (totalPaid/payLimit*100) : 0;
  const budgetRate = execBudget ? (totalPaid/execBudget*100) : 0;

  const ms = ov.milestones || [];
  const msDone = ms.filter(m => m.completed).length;
  const msRate = ms.length ? (msDone/ms.length*100) : 0;
  const members = ov.members || [];

  const fD = d => d ? d.replace(/-/g,'.') : '-';
  const fW = n => (n||0).toLocaleString('ko-KR');
  const pName = document.querySelector('.project-item.active .project-name')?.textContent || '';
  const now = new Date();
  const dateStr = `${now.getFullYear()}.${String(now.getMonth()+1).padStart(2,'0')}.${String(now.getDate()).padStart(2,'0')}`;

  // 이슈
  const issueFields = [
    {key:'issue_design',label:'디자인/인허가'},{key:'issue_schedule',label:'일정'},
    {key:'issue_budget',label:'예산'},{key:'issue_operation',label:'운영'},
    {key:'issue_defect',label:'하자'},{key:'issue_other',label:'기타'}
  ];
  const issues = issueFields.filter(f => ov[f.key]);

  // 진행 바 HTML
  const bar = (pct, color) => `
    <div style="display:flex;align-items:center;gap:8px;">
      <div style="flex:1;height:14px;background:#e5e7eb;border-radius:7px;overflow:hidden;">
        <div style="width:${Math.min(pct,100)}%;height:100%;background:${color};border-radius:7px;"></div>
      </div>
      <span style="font-weight:700;font-size:14px;min-width:50px;text-align:right;">${pct.toFixed(1)}%</span>
    </div>`;

  // 보고서 HTML
  const html = `<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>${pName} - 프로젝트 현황 보고서</title>
<style>
  @page { size: A4 landscape; margin: 12mm 15mm; }
  * { margin:0; padding:0; box-sizing:border-box; font-family: 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif; }
  body { color:#1e293b; font-size:11px; line-height:1.5; }

  .header { text-align:center; border-bottom:3px solid #4f46e5; padding-bottom:10px; margin-bottom:14px; }
  .header h1 { font-size:22px; font-weight:800; color:#1e293b; }
  .header .date { font-size:11px; color:#64748b; margin-top:2px; }
  .header .company { font-size:12px; color:#4f46e5; font-weight:600; }

  .section { margin-bottom:12px; page-break-inside:avoid; }
  .section-title { font-size:13px; font-weight:700; color:#4f46e5; border-bottom:2px solid #e5e7eb; padding-bottom:4px; margin-bottom:8px; }

  /* 요약 카드 */
  .cards { display:grid; gap:8px; margin-bottom:12px; }
  .cards-6 { grid-template-columns:repeat(6,1fr); }
  .cards-4 { grid-template-columns:repeat(4,1fr); }
  .cards-3 { grid-template-columns:repeat(3,1fr); }
  .card { border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; text-align:center; }
  .card-label { font-size:10px; color:#64748b; margin-bottom:2px; }
  .card-value { font-size:15px; font-weight:800; color:#1e293b; }
  .card-accent { border-left:3px solid #4f46e5; }
  .card-blue { border-left:3px solid #3b82f6; }
  .card-green { border-left:3px solid #22c55e; }
  .card-red { border-left:3px solid #ef4444; }
  .card-violet { border-left:3px solid #8b5cf6; }
  .text-red { color:#ef4444; }
  .text-green { color:#22c55e; }
  .text-blue { color:#3b82f6; }

  /* 진행률 */
  .progress-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:12px; }
  .progress-item { border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; }
  .progress-label { font-size:10px; color:#64748b; margin-bottom:4px; }
  .progress-detail { font-size:9px; color:#94a3b8; margin-top:4px; display:flex; justify-content:space-between; }

  /* 정보 그리드 */
  .info-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:12px; }
  .info-box { border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; }
  .info-box h3 { font-size:11px; font-weight:700; color:#334155; margin-bottom:6px; border-bottom:1px solid #f1f5f9; padding-bottom:3px; }
  table.kv { width:100%; border-collapse:collapse; }
  table.kv th { text-align:left; color:#64748b; font-weight:500; padding:2px 6px 2px 0; width:35%; font-size:10px; }
  table.kv td { color:#1e293b; padding:2px 0; font-size:10px; }

  /* 체크리스트 */
  .check-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:2px 12px; }
  .check-item { display:flex; align-items:center; gap:4px; font-size:10px; padding:1px 0; }
  .check-done { color:#22c55e; }
  .check-pending { color:#94a3b8; }

  /* 수금 테이블 */
  table.data { width:100%; border-collapse:collapse; font-size:10px; }
  table.data th { background:#f8fafc; color:#475569; font-weight:600; padding:4px 8px; border:1px solid #e2e8f0; text-align:left; }
  table.data td { padding:4px 8px; border:1px solid #e2e8f0; }
  table.data .num { text-align:right; }
  .badge { display:inline-block; padding:1px 6px; border-radius:3px; font-size:9px; font-weight:600; }
  .badge-done { background:#dcfce7; color:#16a34a; }
  .badge-pending { background:#fee2e2; color:#dc2626; }

  /* 하단 2열 */
  .bottom-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }

  /* 멤버 태그 */
  .member-tags { display:flex; flex-wrap:wrap; gap:4px; }
  .member-tag { background:#f1f5f9; border:1px solid #e2e8f0; border-radius:4px; padding:2px 6px; font-size:10px; }
  .member-role { color:#4f46e5; font-weight:600; margin-right:2px; }

  /* 이슈 */
  .issue-item { display:flex; gap:6px; padding:3px 0; border-bottom:1px solid #f1f5f9; }
  .issue-label { color:#64748b; font-weight:600; min-width:80px; font-size:10px; }
  .issue-value { color:#1e293b; font-size:10px; }

  .footer { text-align:center; color:#94a3b8; font-size:9px; margin-top:10px; border-top:1px solid #e5e7eb; padding-top:6px; }
</style></head><body>

<!-- 헤더 -->
<div class="header">
  <div class="company">GLOW SEOUL</div>
  <h1>${pName}</h1>
  <div class="date">프로젝트 현황 보고서 | ${dateStr}</div>
</div>

<!-- 1. 금액 요약 -->
<div class="section">
  <div class="section-title">금액 요약</div>
  <div class="cards cards-6">
    <div class="card card-blue"><div class="card-label">수주액</div><div class="card-value">${fW(totalOrder)}</div></div>
    <div class="card card-violet"><div class="card-label">실행예산</div><div class="card-value">${fW(execBudget)}</div></div>
    <div class="card card-green"><div class="card-label">수익금</div><div class="card-value">${fW(profit)}</div></div>
    <div class="card card-green"><div class="card-label">수금액</div><div class="card-value">${fW(collDone)}</div></div>
    <div class="card card-accent"><div class="card-label">수금률</div><div class="card-value text-blue">${collRate.toFixed(1)}%</div></div>
    <div class="card card-accent"><div class="card-label">이익률</div><div class="card-value ${profitRate >= 0 ? 'text-green' : 'text-red'}">${profitRate.toFixed(1)}%</div></div>
  </div>
  <div class="cards cards-3">
    <div class="card"><div class="card-label">지급총한도 (하도급 계약합계)</div><div class="card-value">${fW(payLimit)}</div></div>
    <div class="card"><div class="card-label">기지급액</div><div class="card-value">${fW(totalPaid)}</div></div>
    <div class="card card-red"><div class="card-label">잔여지급한도</div><div class="card-value">${fW(payLimit - totalPaid)}</div></div>
  </div>
</div>

<!-- 2. 진행률 -->
<div class="section">
  <div class="section-title">진행률 현황</div>
  <div class="progress-grid">
    <div class="progress-item">
      <div class="progress-label">수금 진행률</div>
      ${bar(collRate, '#3b82f6')}
      <div class="progress-detail"><span>수금 ${fW(collDone)}</span><span>미수금 ${fW(collTotal-collDone)}</span></div>
    </div>
    <div class="progress-item">
      <div class="progress-label">지급 진행률</div>
      ${bar(payRate, '#8b5cf6')}
      <div class="progress-detail"><span>지급 ${fW(totalPaid)}</span><span>잔여 ${fW(payLimit-totalPaid)}</span></div>
    </div>
    <div class="progress-item">
      <div class="progress-label">예산 집행률</div>
      ${bar(budgetRate, '#22c55e')}
      <div class="progress-detail"><span>집행 ${fW(totalPaid)}</span><span>잔여 ${fW(Math.max(execBudget-totalPaid,0))}</span></div>
    </div>
    <div class="progress-item">
      <div class="progress-label">공정 진행률</div>
      ${bar(msRate, '#6366f1')}
      <div class="progress-detail"><span>완료 ${msDone}건</span><span>잔여 ${ms.length-msDone}건</span></div>
    </div>
  </div>
</div>

<!-- 3. 프로젝트 정보 + 일정 + 배정인원 -->
<div class="info-grid">
  <div class="info-box">
    <h3>프로젝트 정보</h3>
    <table class="kv">
      <tr><th>카테고리</th><td>${escapeHtml(ov.project_category||'-')}</td></tr>
      <tr><th>위치</th><td>${escapeHtml(ov.location||'-')}</td></tr>
      <tr><th>용도</th><td>${escapeHtml(ov.usage||'-')}</td></tr>
      <tr><th>규모</th><td>${escapeHtml(ov.scale||'-')}</td></tr>
      <tr><th>연면적</th><td>${ov.area_pyeong ? escapeHtml(ov.area_pyeong)+'평' : '-'}</td></tr>
      <tr><th>현황</th><td>${escapeHtml(ov.current_status||'-')}</td></tr>
    </table>
  </div>
  <div class="info-box">
    <h3>일정 / 계약</h3>
    <table class="kv">
      <tr><th>설계기간</th><td>${fD(ov.design_start)} ~ ${fD(ov.design_end)}</td></tr>
      <tr><th>시공기간</th><td>${fD(ov.construction_start)} ~ ${fD(ov.construction_end)}</td></tr>
      <tr><th>오픈예정</th><td>${fD(ov.open_date)}</td></tr>
      <tr><th>설계계약</th><td>${ov.design_contract_amount ? fW(ov.design_contract_amount)+'원' : '-'}</td></tr>
      <tr><th>시공계약</th><td>${ov.construction_contract_amount ? fW(ov.construction_contract_amount)+'원' : '-'}</td></tr>
    </table>
  </div>
  <div class="info-box">
    <h3>배정인원 (${members.length}명)</h3>
    <div class="member-tags">
      ${members.length ? members.map(m => `<span class="member-tag"><span class="member-role">${escapeHtml(m.role||'')}</span>${escapeHtml(m.name||'')}</span>`).join('') : '<span style="color:#94a3b8">배정인원 없음</span>'}
    </div>
  </div>
</div>

<!-- 4. 진행상황 + 이슈 -->
<div class="bottom-grid">
  <div class="info-box">
    <h3>진행상황 (${msDone}/${ms.length} 완료)</h3>
    ${ms.length ? `<div class="check-grid">${ms.map(m => `
      <div class="check-item ${m.completed?'check-done':'check-pending'}">
        ${m.completed?'☑':'☐'} ${escapeHtml(m.name||'')}${m.date?' <small>('+escapeHtml(m.date)+')</small>':''}
      </div>`).join('')}</div>` : '<span style="color:#94a3b8">진행 단계 없음</span>'}
  </div>
  <div class="info-box">
    <h3>이슈사항</h3>
    ${issues.length ? issues.map(f => `<div class="issue-item"><span class="issue-label">${escapeHtml(f.label)}</span><span class="issue-value">${escapeHtml(ov[f.key]||'')}</span></div>`).join('') : '<span style="color:#94a3b8">이슈 없음</span>'}
  </div>
</div>

<!-- 5. 수금현황 -->
<div class="section" style="margin-top:10px;">
  <div class="section-title">수금현황 (수금률 ${collRate.toFixed(1)}%)</div>
  <table class="data">
    <thead><tr><th>구분</th><th>단계</th><th class="num">금액(원)</th><th>수금 예정일</th><th>상태</th></tr></thead>
    <tbody>
      ${colls.length ? colls.map(c => `<tr>
        <td>${escapeHtml(c.category||'-')}</td>
        <td>${escapeHtml(c.stage||'-')}</td>
        <td class="num">${fW(c.amount||0)}</td>
        <td>${c.collection_date||'-'}</td>
        <td>${c.collected ? '<span class="badge badge-done">수금완료</span>' : '<span class="badge badge-pending">미수금</span>'}</td>
      </tr>`).join('') : '<tr><td colspan="5" style="text-align:center;color:#94a3b8;">수금 데이터 없음</td></tr>'}
    </tbody>
  </table>
</div>

<div class="footer">GLOW SEOUL | 프로젝트 관리 시스템 | ${dateStr} 출력</div>

</body></html>`;

  // 새 창에서 인쇄
  const w = window.open('', '_blank', 'width=1200,height=800');
  if (!w) { showToast('팝업이 차단되었습니다. 팝업 허용 후 다시 시도해주세요.', 'error'); return; }
  w.document.write(html);
  w.document.close();
  w.onload = () => { w.print(); };
}

// ===== 이체내역 탭 =====

async function uploadPaymentExcel(e) {
  const file = e.target.files[0];
  if (!file || !currentProjectId) return;

  const btn = document.getElementById('uploadPaymentsBtn');
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> 업로드 중...';

  try {
    const fd = new FormData();
    fd.append('file', file);

    // CSRF 토큰 첨부
    const csrfToken = document.cookie.split(';').map(c => c.trim())
      .find(c => c.startsWith('csrf_token='))?.split('=')[1] || '';

    const res = await fetch(`/api/fund/projects/${currentProjectId}/payments/import`, {
      method: 'POST',
      body: fd,
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || '업로드 실패');

    showToast(data.message || `이체내역 ${data.count}건 임포트 완료`, 'success');
    loadPayments(currentProjectId);
  } catch (err) {
    showToast(err.message || '엑셀 업로드에 실패했습니다.', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
    e.target.value = '';  // 같은 파일 재선택 허용
  }
}

async function loadPayments(projectId) {
  const tbody = document.getElementById('paymentBody');
  tbody.innerHTML = '<tr><td colspan="7" class="no-data"><span class="loading-spinner"></span> 데이터 불러오는 중...</td></tr>';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/payments`);
    if (!res.ok) throw new Error('이체내역 조회 실패');
    const data = await res.json();
    const payments = data.payments || [];

    // 지급 총액 표시
    const totalAmount = payments.reduce((sum, p) => sum + (p.amount || 0), 0);
    const totalEl = document.getElementById('paymentTotalAmount');
    const countEl = document.getElementById('paymentTotalCount');
    if (totalEl) totalEl.textContent = formatWon(totalAmount);
    if (countEl) countEl.textContent = payments.length + '건';

    if (payments.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="no-data">이체내역이 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = payments.map((p, i) => {
      const supplyAmt = p.supply_amount != null && p.supply_amount !== 0
        ? formatWon(p.supply_amount) : '-';
      const taxAmt = p.tax_amount != null && p.tax_amount !== 0
        ? formatWon(p.tax_amount) : '-';
      return `<tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(p.confirmed_date || p.scheduled_date || '-')}</td>
        <td>${escapeHtml(p.vendor_name || '-')}</td>
        <td class="num">${formatWon(p.amount || 0)}</td>
        <td class="num">${supplyAmt}</td>
        <td class="num">${taxAmt}</td>
        <td>${escapeHtml(p.description || '-')}</td>
        <td>${escapeHtml((p.bank_name || '') + ' ' + (p.account_number || ''))}</td>
        <td>${escapeHtml(p.fund_category || '-')}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="no-data">${escapeHtml(e.message)}</td></tr>`;
  }
}

// ===== 예실대비 탭 (GW 크롤링 연동) =====

// 예산 집행률 Top5 미니 수평 바 차트
function _renderBudgetTopChart(items) {
  const containerId = 'budgetTopChart';
  let container = document.getElementById(containerId);
  if (!container) return; // HTML에 컨테이너 없으면 무시

  if (!items || items.length === 0) {
    container.style.display = 'none';
    return;
  }

  // 집행액 기준 상위 5개 항목
  const top5 = [...items]
    .filter(i => (i.actual_amount || 0) > 0)
    .sort((a, b) => (b.actual_amount || 0) - (a.actual_amount || 0))
    .slice(0, 5);

  if (top5.length === 0) { container.style.display = 'none'; return; }

  const maxActual = Math.max(...top5.map(i => i.actual_amount || 0));
  container.style.display = 'block';
  container.innerHTML = '<h4 class="chart-mini-title">집행액 상위 과목</h4>' +
    top5.map(item => {
      const pct = maxActual ? ((item.actual_amount || 0) / maxActual * 100) : 0;
      const rate = item.execution_rate || 0;
      const barColor = rate >= 95 ? '#ef4444' : rate >= 80 ? '#f97316' : '#3b82f6';
      return `<div class="chart-mini-row">
        <div class="chart-mini-label" title="${escapeHtml(item.budget_sub_category || item.budget_category || '')}">${escapeHtml((item.budget_sub_category || item.budget_category || '-').substring(0, 8))}</div>
        <div class="chart-mini-bar-wrap">
          <div class="chart-mini-bar" style="width:${pct.toFixed(1)}%;background:${barColor}"></div>
        </div>
        <div class="chart-mini-value">${formatWon(item.actual_amount || 0)}</div>
      </div>`;
    }).join('');
}

// ── 예실대비 테이블 렌더링 (연도 필터 적용 후 호출) ──
function _renderBudgetTable(items) {
  const tbody = document.getElementById('budgetBody');

  // ── 필터: 수입 과목(코드 '1'로 시작) 및 장(XX00000) 그룹 행 숨김 ──
  const isJangCode = (code) => code && /^\d{2}00000$/.test(code);
  const filtered = items.filter(item => {
    const code = item.budget_code || '';
    if (code.startsWith('1')) return false;  // 수입 과목 숨김
    if (isJangCode(code) || code === '0000000') {
      return code === '0000000';
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">해당 연도의 예실대비 데이터가 없습니다.</td></tr>';
    document.getElementById('budgetSummaryCards').style.display = 'none';
    return;
  }

  // 수입/지출 분류 (과목코드가 '1'로 시작 → 수입, 나머지 → 지출)
  const _isIncomeItem = (item) => (item.budget_code || '').startsWith('1');

  // 요약 카드 업데이트 — 지출 항목만 합산 (수입 혼입 방지)
  let totalExpenseBudget = 0, totalExpenseActual = 0;
  filtered.forEach(item => {
    if (!_isIncomeItem(item)) {
      totalExpenseBudget += (item.budget_amount || 0);
      totalExpenseActual += (item.actual_amount || 0);
    }
  });
  const totalRemain = totalExpenseBudget - totalExpenseActual;
  const avgRate = totalExpenseBudget ? (totalExpenseActual / totalExpenseBudget * 100) : 0;

  document.getElementById('budgetTotalAmount').textContent = formatWon(totalExpenseBudget);
  document.getElementById('budgetTotalActual').textContent = formatWon(totalExpenseActual);
  document.getElementById('budgetTotalRemain').textContent = formatWon(totalRemain);

  // 집행률 색상 분기: 95%+ 빨강, 80~95% 주황, 미만 파랑
  const avgRateEl = document.getElementById('budgetAvgRate');
  avgRateEl.textContent = avgRate.toFixed(1) + '%';
  if (avgRate >= 95) {
    avgRateEl.style.color = '#ef4444';
  } else if (avgRate >= 80) {
    avgRateEl.style.color = '#f97316';
  } else {
    avgRateEl.style.color = '#3b82f6';
  }

  document.getElementById('budgetSummaryCards').style.display = 'grid';

  // 테이블 렌더링 — 집행율에 따라 색상 차등 + 계층 구조 (장/관/항/목)
  const LEVEL_INDENT = { 1: 0, 2: 12, 3: 24, 4: 36 };
  const DIV_BADGES   = {
    '장': '<span class="budget-level-badge lv1">장</span>',
    '관': '<span class="budget-level-badge lv2">관</span>',
    '항': '<span class="budget-level-badge lv3">항</span>',
    '목': '<span class="budget-level-badge lv4">목</span>',
  };

  tbody.innerHTML = filtered.map(item => {
    const budget   = item.budget_amount || 0;
    const actual   = item.actual_amount || 0;
    const remain   = item.difference || (budget - actual);
    const rate     = item.execution_rate || (budget ? (actual / budget * 100) : 0);
    const defNm    = item.def_nm || item.budget_category || '';
    const bgtNm    = item.budget_sub_category || item.budget_category || '-';
    const bgtCd    = item.budget_code || '-';
    const divFg    = parseInt(item.div_fg || 0);
    const isLeaf   = item.is_leaf;
    const isIncome = _isIncomeItem(item);
    const indent   = LEVEL_INDENT[divFg] || 0;
    const badge    = DIV_BADGES[defNm] || '';
    let rowClass = (divFg === 1 || divFg === 2) && !isLeaf ? 'budget-row-parent' : '';
    if (isIncome) rowClass += ' budget-row-income';

    // 수입 항목은 수금률이 높을수록 좋음 → 위험 색상 적용 안 함
    let barClass = isIncome ? 'pct-income' : 'pct-normal';
    if (!isIncome) {
      if (rate >= 95) barClass = 'pct-danger';
      else if (rate >= 80) barClass = 'pct-warning';
    }

    const incomeLabel = isIncome
      ? '<span class="budget-income-badge">수입</span>'
      : '';

    return `<tr class="${rowClass}">
      <td style="padding-left:${indent + 12}px">${badge}${incomeLabel}${escapeHtml(bgtNm)}</td>
      <td class="code-cell">${escapeHtml(bgtCd)}</td>
      <td class="def-nm-cell">${escapeHtml(defNm)}</td>
      <td class="num">${formatWon(budget)}</td>
      <td class="num">${formatWon(actual)}</td>
      <td class="num ${remain < 0 ? 'text-danger' : ''}">${formatWon(remain)}</td>
      <td class="num">
        <div class="pct-bar-wrap">
          <div class="exec-bar ${barClass}" style="width:${Math.min(rate, 100)}%"></div>
          <span class="pct-label">${rate.toFixed(1)}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');

  // 집행액 상위 과목 차트 — 숨김 처리
  const topChartEl = document.getElementById('budgetTopChart');
  if (topChartEl) topChartEl.innerHTML = '';
}

// ── 연도별 탭 렌더링 ──
function _renderBudgetYearTabs(years) {
  const container = document.getElementById('budgetYearTabs');
  if (!container) return;

  if (years.length <= 1) {
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }

  container.style.display = 'flex';
  container.innerHTML = years.map((y, i) =>
    `<button class="year-tab-btn${i === 0 ? ' active' : ''}" data-year="${y}">${y}년</button>`
  ).join('');

  container.querySelectorAll('.year-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.year-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _currentBudgetYear = btn.dataset.year ? parseInt(btn.dataset.year) : null;
      const filtered = _currentBudgetYear
        ? _allBudgetData.filter(row => (row.year || 0) === _currentBudgetYear)
        : _allBudgetData;
      _renderBudgetTable(filtered);
    });
  });
}

async function loadBudget(projectId) {
  const tbody = document.getElementById('budgetBody');
  tbody.innerHTML = '<tr><td colspan="7" class="no-data"><span class="loading-spinner"></span> 데이터 불러오는 중...</td></tr>';

  // 연도 탭 초기화
  const yearTabsEl = document.getElementById('budgetYearTabs');
  if (yearTabsEl) { yearTabsEl.style.display = 'none'; yearTabsEl.innerHTML = ''; }
  _allBudgetData = [];
  _currentBudgetYear = null;

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/budget`);
    if (!res.ok) throw new Error('예실대비 조회 실패');
    const data = await res.json();
    const items = data.budget || [];

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="no-data">예실대비 데이터가 없습니다. "GW에서 가져오기"를 클릭하세요.</td></tr>';
      document.getElementById('budgetSummaryCards').style.display = 'none';
      document.getElementById('budgetMeta').style.display = 'none';
      const summaryTotals = document.getElementById('budgetSummaryTotals');
      if (summaryTotals) summaryTotals.style.display = 'none';
      return;
    }

    // 전체 데이터 저장 (탭 전환용)
    _allBudgetData = items;

    // 합계 데이터 (projects.budget_summary) 표시
    _loadBudgetSummaryTotals(projectId);

    // 예산 변경 이력 로드
    _loadBudgetChanges(projectId);

    // 마지막 동기화 시각
    const latestSync = items.reduce((latest, item) => {
      const t = item.scraped_at || '';
      return t > latest ? t : latest;
    }, '');
    if (latestSync) {
      document.getElementById('budgetLastSync').textContent = formatDateTime(latestSync);
      document.getElementById('budgetMeta').style.display = 'block';
    }

    // 연도 목록 추출 (내림차순: 최신 연도 먼저)
    const years = [...new Set(items.map(i => i.year).filter(y => y))].sort((a, b) => b - a);

    // 연도 정보 뱃지 (기존 budgetYearInfo)
    if (years.length > 1) {
      const sortedAsc = [...years].sort((a, b) => a - b);
      const yearInfo = document.getElementById('budgetYearInfo');
      if (yearInfo) {
        yearInfo.textContent = `조회 기간: ${sortedAsc[0]}~${sortedAsc[sortedAsc.length - 1]}`;
        yearInfo.style.display = 'inline-block';
      }
    }

    // 연도별 탭 렌더링 (2개 이상일 때)
    _renderBudgetYearTabs(years);

    // 초기 표시: 최신 연도 데이터
    if (years.length > 1) {
      _currentBudgetYear = years[0];  // 가장 최신 연도
      const initialItems = items.filter(row => (row.year || 0) === _currentBudgetYear);
      _renderBudgetTable(initialItems);
    } else {
      // 연도가 1개이하면 전체 표시
      _renderBudgetTable(items);
    }
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
      `<button class="btn ${escapeHtml(b.className || '')}" ${b.id ? `id="${escapeHtml(b.id)}"` : ''}>${escapeHtml(b.label || '')}</button>`
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

// ===== 토스트 알림 (개선: 우측 하단 고정, 에러/경고는 상세 형태) =====
function showToast(message, type = 'info') {
  // 에러/경고: 하단 우측 상세 토스트
  if (type === 'error' || type === 'warning') {
    _showBottomToast(message, type);
  } else {
    // 성공/정보: 기존 상단 우측 토스트
    _showTopToast(message, type);
  }
}

/** 상단 우측 토스트 (성공/정보용) */
function _showTopToast(message, type) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/** 하단 우측 상세 토스트 (에러/경고용) — 3초 후 자동 사라짐 */
function _showBottomToast(message, type) {
  let container = document.querySelector('.toast-container-bottom');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container-bottom';
    document.body.appendChild(container);
  }

  // 아이콘 SVG
  const icons = {
    error:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  };
  const titles = { error: '오류', warning: '경고' };

  const toast = document.createElement('div');
  toast.className = `toast-bottom toast-bottom-${type}`;
  toast.innerHTML = `
    <span class="toast-bottom-icon">${icons[type] || ''}</span>
    <div class="toast-bottom-body">
      <div class="toast-bottom-title">${titles[type] || type}</div>
      <div class="toast-bottom-msg">${escapeHtml(message)}</div>
    </div>
    <button class="toast-bottom-close" title="닫기">&times;</button>
  `;

  // 닫기 버튼
  toast.querySelector('.toast-bottom-close').addEventListener('click', () => _dismissBottomToast(toast));
  container.appendChild(toast);

  // 3초 후 자동 사라짐
  setTimeout(() => _dismissBottomToast(toast), 4000);
}

function _dismissBottomToast(toast) {
  if (!toast.parentNode) return;
  toast.style.opacity = '0';
  toast.style.transform = 'translateY(10px)';
  toast.style.transition = 'all 0.3s ease';
  setTimeout(() => toast.remove(), 300);
}

// ===== 전역 로딩 오버레이 (모든 비동기 fetch에 공통 적용) =====
let _loadingCount = 0;

function showLoading(text = '불러오는 중...') {
  _loadingCount++;
  let overlay = document.getElementById('globalLoadingOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'globalLoadingOverlay';
    overlay.className = 'global-loading-overlay';
    overlay.innerHTML = `
      <div class="global-loading-spinner"></div>
      <div class="global-loading-text" id="globalLoadingText">${escapeHtml(text)}</div>
    `;
    document.body.appendChild(overlay);
  } else {
    const textEl = overlay.querySelector('#globalLoadingText');
    if (textEl) textEl.textContent = text;
    overlay.style.display = 'flex';
  }
}

function hideLoading() {
  _loadingCount = Math.max(0, _loadingCount - 1);
  if (_loadingCount === 0) {
    const overlay = document.getElementById('globalLoadingOverlay');
    if (overlay) overlay.style.display = 'none';
  }
}

// ===== 포맷 유틸 =====
function formatWon(value) {
  if (value === null || value === undefined) return '0';
  const num = typeof value === 'string' ? parseInt(value) : value;
  return num.toLocaleString('ko-KR');
}

const formatNum = formatWon;

// 쉼표 제거 후 정수 파싱 (num-input 저장 시 공통 사용)
function parseAmountInput(el) {
  if (!el) return 0;
  return parseInt((el.value || '').replace(/,/g, '')) || 0;
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
  if (filter === 'current') filtered = todosCache.filter(t => t.project_id === currentProjectId);
  if (filter === 'pending') filtered = todosCache.filter(t => !t.completed);
  if (filter === 'completed') filtered = todosCache.filter(t => t.completed);

  if (filtered.length === 0) {
    container.innerHTML = '<p class="no-data-text">TODO 항목이 없습니다.</p>';
    return;
  }

  container.innerHTML = filtered.map(t => {
    const priorityLabel = { high: '높음', medium: '보통', low: '낮음' }[t.priority] || '보통';
    const projectName = t.project_name || projectsCache.find(p => p.id === t.project_id)?.name || '';

    // [개선] 마감 임박 강조 — due_date가 있으면 D-Day 계산, D-3 이내이면 긴급 배지 표시
    let dueBadge = '';
    let urgentClass = '';
    if (t.due_date && !t.completed) {
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const due   = new Date(t.due_date); due.setHours(0, 0, 0, 0);
      const diffDays = Math.ceil((due - today) / 86400000); // ms → 일
      if (diffDays <= 3) {
        urgentClass = 'has-due-urgent';
        const label = diffDays < 0 ? `D+${Math.abs(diffDays)}` : (diffDays === 0 ? 'D-Day' : `D-${diffDays}`);
        dueBadge = `<span class="due-badge due-badge-urgent">${label}</span>`;
      } else {
        dueBadge = `<span class="due-badge">D-${diffDays}</span>`;
      }
    }

    // [개선] AI 권고 TODO 판별 — content에 '[AI 권고]' 태그 포함 여부 확인
    const isAiTodo = t.content && t.content.includes('[AI 권고]');
    // AI 권고는 보라색 배지 표시, 표시용 텍스트에서 태그 제거
    const displayText = isAiTodo ? t.content.replace('[AI 권고]', '').trim() : t.content;
    const aiBadge = isAiTodo
      ? '<span class="todo-ai-badge">AI 권고</span>'
      : '';

    return `
      <div class="todo-item ${t.completed ? 'completed' : ''} ${urgentClass} ${isAiTodo ? 'todo-ai' : ''}" data-todo-id="${t.id}">
        <input type="checkbox" class="todo-checkbox" data-id="${t.id}" ${t.completed ? 'checked' : ''} />
        <span class="todo-text">${escapeHtml(displayText)}</span>
        <div class="todo-meta">
          ${aiBadge}
          ${dueBadge}
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

    // [개선] 완료 처리 시 취소선 + 페이드아웃 애니메이션 (0.4초)
    if (completed) {
      const todoItem = checkbox.closest('.todo-item');
      if (todoItem) {
        todoItem.classList.add('fade-out-done');
        // 애니메이션 완료 후 목록 갱신
        setTimeout(() => renderTodos(), 420);
        return; // 애니메이션 중 바로 renderTodos 호출 방지
      }
    }
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
  if (!wrap || !count) return;
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

// ─────────────────────────────────────────
// 신규 데이터 동기화 (D6)
// 선택된 프로젝트의 세금계산서 등 신규 크롤러 데이터를 GW에서 동기화한다.
// ─────────────────────────────────────────

async function syncNewCrawlers() {
  // 프로젝트가 선택되어 있어야 함
  if (!currentProjectId) {
    showToast('프로젝트를 먼저 선택하세요', 'error');
    return;
  }

  const btn = document.getElementById('pfSyncNewDataBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '동기화 중...';
  }

  showToast('신규 데이터 동기화를 시작합니다...', 'info');

  let successCount = 0;
  let failCount = 0;
  const messages = [];

  // 세금계산서 동기화
  try {
    const result = await gwFetch(`/api/fund/projects/${currentProjectId}/tax-invoices/sync`, { method: 'POST' });
    if (result.success) {
      successCount++;
      messages.push(`세금계산서 ${result.count}건`);
    } else {
      failCount++;
      messages.push(`세금계산서 실패: ${result.error || '오류'}`);
    }
  } catch (e) {
    failCount++;
    messages.push(`세금계산서 실패: ${e.message}`);
  }

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><polyline points="23 20 23 14 17 14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> 신규 데이터 동기화`;
  }

  const summaryMsg = messages.join(' / ');
  if (failCount === 0) {
    showToast(`동기화 완료: ${summaryMsg}`, 'success');
  } else if (successCount > 0) {
    showToast(`일부 동기화 완료: ${summaryMsg}`, 'warning');
  } else {
    showToast(`동기화 실패: ${summaryMsg}`, 'error');
  }
}

// ─────────────────────────────────────────
// GW 계약 내역 탭 (9-23)
// ─────────────────────────────────────────

async function loadGwContracts(projectId) {
  const wrap = document.getElementById('contractsTableWrap');
  if (!wrap) return;
  wrap.innerHTML = '<p class="no-data-text"><span class="loading-spinner"></span> 불러오는 중...</p>';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/gw-contracts`);
    if (!res.ok) throw new Error('계약 조회 실패');
    const data = await res.json();
    const contracts = data.gw_contracts || [];

    if (contracts.length === 0) {
      wrap.innerHTML = `<div class="gw-empty-hint">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color:var(--content-text-muted)"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <p>계약 데이터가 없습니다.<br>GW 동기화 후 표시됩니다.</p>
      </div>`;
      return;
    }

    const rows = contracts.map((c, i) => {
      const supplyAmt = c.supply_amount != null && c.supply_amount !== 0
        ? formatWon(c.supply_amount) : '-';
      const taxAmt = c.tax_amount != null && c.tax_amount !== 0
        ? formatWon(c.tax_amount) : '-';
      const contractAmt = c.contract_amount != null ? formatWon(c.contract_amount) : '-';
      const statusBadge = c.status
        ? `<span class="contract-status-badge contract-status-${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>`
        : '-';
      return `<tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(c.contract_date || '-')}</td>
        <td>${escapeHtml(c.contract_type || '-')}</td>
        <td class="num">${contractAmt}</td>
        <td class="num">${supplyAmt}</td>
        <td class="num">${taxAmt}</td>
        <td>${escapeHtml(c.vendor_name || '-')}</td>
        <td>${statusBadge}</td>
      </tr>`;
    }).join('');

    wrap.innerHTML = `<div class="table-wrapper">
      <table class="data-table" id="contractsTable">
        <thead>
          <tr>
            <th style="width:40px;">No</th>
            <th>계약일</th>
            <th>계약유형</th>
            <th class="num">계약금액(원)</th>
            <th class="num">공급가액(원)</th>
            <th class="num">세액(원)</th>
            <th>거래처명</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  } catch (e) {
    wrap.innerHTML = `<p class="no-data-text" style="color:var(--danger)">${escapeHtml(e.message)}</p>`;
  }
}

// ─────────────────────────────────────────
// 리스크 관리 탭 (9-24)
// ─────────────────────────────────────────

async function loadRisks(projectId) {
  const wrap = document.getElementById('risksListWrap');
  if (!wrap) return;
  wrap.innerHTML = '<p class="no-data-text"><span class="loading-spinner"></span> 불러오는 중...</p>';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/risks`);
    if (!res.ok) throw new Error('리스크 조회 실패');
    const data = await res.json();
    const risks = data.risks || [];

    if (risks.length === 0) {
      wrap.innerHTML = `<div class="gw-empty-hint">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color:var(--content-text-muted)"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <p>리스크 항목이 없습니다.<br>"리스크 추가" 버튼으로 추가하세요.</p>
      </div>`;
      return;
    }

    const severityLabel = { high: '높음', medium: '중간', low: '낮음' };
    const cards = risks.map(r => {
      const sev = r.severity || 'medium';
      const isResolved = r.status === 'resolved';
      const date = r.created_at ? r.created_at.substring(0, 10) : '';
      return `<div class="risk-card risk-sev-${escapeHtml(sev)} ${isResolved ? 'risk-resolved' : ''}">
        <div class="risk-card-header">
          <span class="risk-type">${escapeHtml(r.risk_type || '미분류')}</span>
          <span class="risk-severity-badge risk-sev-badge-${escapeHtml(sev)}">${escapeHtml(severityLabel[sev] || sev)}</span>
          <span class="risk-status-badge ${isResolved ? 'risk-badge-resolved' : 'risk-badge-open'}">
            ${isResolved ? '✓ 해결됨' : '진행 중'}
          </span>
          <button class="btn btn-sm risk-resolve-btn"
            data-resolve-risk="${r.id}"
            data-resolved="${isResolved}"
            title="${isResolved ? '미해결로 변경' : '해결됨으로 표시'}">
            ${isResolved ? '↺ 재오픈' : '✓ 해결'}
          </button>
        </div>
        <div class="risk-description">${escapeHtml(r.description || '-')}</div>
        ${r.mitigation ? `<div class="risk-mitigation">조치: ${escapeHtml(r.mitigation)}</div>` : ''}
        <div class="risk-meta">${date ? `등록일: ${date}` : ''}${r.created_by ? ` · ${escapeHtml(r.created_by)}` : ''}</div>
      </div>`;
    }).join('');

    wrap.innerHTML = `<div class="risk-cards-grid">${cards}</div>`;
  } catch (e) {
    wrap.innerHTML = `<p class="no-data-text" style="color:var(--danger)">${escapeHtml(e.message)}</p>`;
  }
}

async function addRisk() {
  if (!currentProjectId) { showToast('프로젝트를 먼저 선택하세요', 'error'); return; }

  openModal('리스크 추가', `
    <div class="form-group">
      <label>리스크 유형</label>
      <input type="text" id="riskTypeInput" placeholder="예: 일정 지연, 예산 초과, 인허가" />
    </div>
    <div class="form-group">
      <label>심각도</label>
      <select id="riskSeveritySelect">
        <option value="high">높음</option>
        <option value="medium" selected>중간</option>
        <option value="low">낮음</option>
      </select>
    </div>
    <div class="form-group">
      <label>설명</label>
      <textarea id="riskDescInput" rows="3" placeholder="리스크 내용을 입력하세요"></textarea>
    </div>
  `, async () => {
    const risk_type = document.getElementById('riskTypeInput').value.trim();
    const severity  = document.getElementById('riskSeveritySelect').value;
    const description = document.getElementById('riskDescInput').value.trim();
    if (!description) { showToast('설명을 입력하세요', 'error'); return; }

    try {
      const res = await safeFetch(`/api/fund/projects/${currentProjectId}/risks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ risk_type: risk_type || '미분류', severity, description, source: 'manual' }),
      });
      if (!res.ok) throw new Error('리스크 추가 실패');
      showToast('리스크가 추가되었습니다.', 'success');
      closeModal();
      loadRisks(currentProjectId);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });
}

async function toggleRiskResolved(riskId, isResolved) {
  try {
    const res = await safeFetch(`/api/fund/risks/${riskId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_resolved: isResolved }),
    });
    if (!res.ok) throw new Error('리스크 수정 실패');
    showToast(isResolved ? '리스크가 해결됨으로 표시되었습니다.' : '리스크가 재오픈되었습니다.', 'success');
    loadRisks(currentProjectId);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// ─────────────────────────────────────────
// 예산 변경 이력 (9-19)
// ─────────────────────────────────────────

async function _loadBudgetChanges(projectId) {
  const section  = document.getElementById('budgetChangesSection');
  const countEl  = document.getElementById('budgetChangesCount');
  const listEl   = document.getElementById('budgetChangesList');
  if (!section || !listEl) return;

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/budget-changes`);
    if (!res.ok) { section.style.display = 'none'; return; }
    const data = await res.json();
    const changes = data.budget_changes || [];

    if (changes.length === 0) { section.style.display = 'none'; return; }

    if (countEl) countEl.textContent = changes.length;
    section.style.display = 'block';
    listEl.innerHTML = changes.map(c => `
      <div class="budget-change-item">
        <span class="bc-date">${escapeHtml(c.change_date || c.created_at || '-').substring(0, 10)}</span>
        <span class="bc-type">${escapeHtml(c.change_type || '-')}</span>
        <span class="bc-amount">${c.amount != null ? formatWon(c.amount) + '원' : '-'}</span>
        ${c.notes ? `<span class="bc-notes">${escapeHtml(c.notes)}</span>` : ''}
      </div>
    `).join('');
  } catch (e) {
    section.style.display = 'none';
  }
}

// ─────────────────────────────────────────
// 크롤링 일괄 실행 (9-29)
// ─────────────────────────────────────────

async function runExtendedCrawl() {
  const btn = document.getElementById('crawlAllExtendedBtn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span> 크롤링 중...';
  }
  showToast('전체 GW 동기화를 시작합니다. 시간이 걸릴 수 있습니다...', 'info');

  try {
    const { data } = await gwFetch('/api/fund/crawl-gw-all', { method: 'POST' });
    const succeeded = data.succeeded || 0;
    const failed    = data.failed    || 0;
    const msg = `GW 동기화 완료: 성공 ${succeeded}건, 실패 ${failed}건`;
    showToast(msg, failed === 0 ? 'success' : 'warning');
    // 포트폴리오 데이터 갱신
    loadPortfolioView();
  } catch (e) {
    showToast('동기화 실패: ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><polyline points="23 20 23 14 17 14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> 확장 크롤링`;
    }
  }
}

// ─────────────────────────────────────────
// GW 데이터 신선도 배지 (9-25)
// ─────────────────────────────────────────

async function _updateGwSyncBadge(projectId) {
  const badge = document.getElementById('gwSyncBadge');
  if (!badge) return;
  badge.style.display = 'none';

  try {
    const res = await safeFetch(`/api/fund/projects/${projectId}/overview`);
    if (!res.ok) return;
    const data = await res.json();
    const synced = data.overview && data.overview.gw_last_synced;
    if (!synced) {
      badge.textContent = 'GW 미동기화';
      badge.style.display = 'inline-block';
      badge.classList.add('gw-sync-badge-none');
      badge.classList.remove('gw-sync-badge-ok');
      return;
    }

    // 몇 일 전인지 계산
    const syncDate = new Date(synced);
    const now = new Date();
    const diffMs = now - syncDate;
    const diffDays = Math.floor(diffMs / 86400000);
    let label;
    if (diffDays === 0) {
      const diffHours = Math.floor(diffMs / 3600000);
      label = diffHours === 0 ? '방금 동기화' : `${diffHours}시간 전 동기화`;
    } else {
      label = `${diffDays}일 전 동기화`;
    }

    badge.textContent = 'GW ' + label;
    badge.style.display = 'inline-block';
    badge.classList.toggle('gw-sync-badge-ok', diffDays < 3);
    badge.classList.toggle('gw-sync-badge-stale', diffDays >= 3);
    badge.classList.remove('gw-sync-badge-none');
  } catch (e) {
    badge.style.display = 'none';
  }
}

// ===== 유틸 =====
function formatDateTime(str) {
  if (!str) return '-';
  const d = new Date(str);
  return `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// ═══════════════════════════════════════════════
// 공정표 자동생성 모달 + 내보내���
// ═══════════════════════════════════════════════

let _genTradeData = null; // 마스터 데이터 캐시

// ��달 열기/닫기
document.getElementById('btnGenerateSchedule')?.addEventListener('click', openGenScheduleModal);
document.getElementById('genScheduleClose')?.addEventListener('click', closeGenScheduleModal);
document.getElementById('genScheduleCancel')?.addEventListener('click', closeGenScheduleModal);
document.getElementById('genScheduleSubmit')?.addEventListener('click', submitGenSchedule);
document.getElementById('genProjectType')?.addEventListener('change', onGenTypeChange);
document.getElementById('btnParseEstimate')?.addEventListener('click', parseEstimateFile);
document.getElementById('btnToggleTradeEdit')?.addEventListener('click', toggleTradeEditPanel);
document.getElementById('btnAddCustomTrade')?.addEventListener('click', addCustomTrade);
document.getElementById('btnSavePreset')?.addEventListener('click', saveCustomPreset);

// 내보내기 드롭다운
document.getElementById('btnExportSchedule')?.addEventListener('click', (e) => {
  e.stopPropagation();
  const dd = document.getElementById('exportDropdown');
  if (dd) dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
});
document.getElementById('exportDropdown')?.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-export-fmt]');
  if (!btn) return;
  const fmt = btn.dataset.exportFmt;
  document.getElementById('exportDropdown').style.display = 'none';
  await exportSchedule(fmt);
});
document.addEventListener('click', () => {
  const dd = document.getElementById('exportDropdown');
  if (dd) dd.style.display = 'none';
});

function openGenScheduleModal() {
  if (!currentProjectId) { showToast('프로젝트를 먼저 선택하세요.', 'error'); return; }
  const modal = document.getElementById('genScheduleModal');
  if (modal) modal.style.display = 'flex';
  // 개요에서 착공일/준공일 가져오기
  const proj = projectsCache?.find(p => p.id === currentProjectId);
  if (proj) {
    const startEl = document.getElementById('genStartDate');
    const endEl = document.getElementById('genEndDate');
    if (startEl && proj.timeline_start_month) startEl.value = proj.timeline_start_month + '-01';
    if (endEl && proj.timeline_end_month) {
      const [y, m] = proj.timeline_end_month.split('-');
      const lastDay = new Date(+y, +m, 0).getDate();
      endEl.value = `${proj.timeline_end_month}-${String(lastDay).padStart(2, '0')}`;
    }
  }
  onGenTypeChange();
}

function closeGenScheduleModal() {
  const modal = document.getElementById('genScheduleModal');
  if (modal) modal.style.display = 'none';
}

async function onGenTypeChange() {
  const type = document.getElementById('genProjectType')?.value || '오피스';
  try {
    const res = await safeFetch(`/api/fund/process-map/trades?type=${encodeURIComponent(type)}`);
    if (!res.ok) throw new Error('공종 데이터 로드 실패');
    const data = await res.json();
    _genTradeData = data;
    renderTradeChecklist(data.groups, new Set(data.preset_trades || []));
    // 그룹 select 채우기
    const groupSel = document.getElementById('newTradeGroup');
    if (groupSel && data.groups) {
      groupSel.innerHTML = '<option value="">그룹 선택</option>';
      const seen = new Set();
      for (const g of data.groups) {
        if (!seen.has(g.group)) {
          seen.add(g.group);
          groupSel.innerHTML += `<option value="${escapeHtml(g.group)}">${escapeHtml(g.group)}</option>`;
        }
      }
    }
    // 프리셋 select (genProjectType)에 커스텀 프리셋 추가
    const typeSel = document.getElementById('genProjectType');
    if (typeSel && data.presets) {
      const existing = new Set([...typeSel.options].map(o => o.value));
      for (const p of data.presets) {
        if (p.is_custom && !existing.has(p.name)) {
          const opt = document.createElement('option');
          opt.value = p.name;
          opt.textContent = p.name + ' (커스텀)';
          typeSel.appendChild(opt);
        }
      }
    }
  } catch (e) {
    showToast('공종 데이터 로드 실패: ' + e.message, 'error');
  }
}

function renderTradeChecklist(groups, presetSet) {
  const container = document.getElementById('genTradeChecklist');
  if (!container) return;
  let html = '';
  for (const grp of groups) {
    const grpId = 'gen_grp_' + grp.group.replace(/[^a-zA-Z0-9가-힣]/g, '_');
    const allChecked = grp.items.every(it => presetSet.has(it.name));
    html += `<div class="gen-trade-group">
      <label class="gen-trade-group-header" style="border-left:3px solid ${escapeHtml(grp.color)};padding-left:8px;">
        <input type="checkbox" class="gen-grp-chk" data-grp="${escapeHtml(grpId)}" ${allChecked ? 'checked' : ''}>
        <strong>${escapeHtml(grp.group)}</strong>
      </label>
      <div class="gen-trade-items">`;
    for (const it of grp.items) {
      const checked = presetSet.has(it.name) ? 'checked' : '';
      const delBtn = it.is_custom ? `<button class="gen-trade-del" data-trade-id="${it.id}" title="삭제">&times;</button>` : '';
      html += `<label class="gen-trade-item"><input type="checkbox" class="gen-trade-chk" data-grp="${escapeHtml(grpId)}" value="${escapeHtml(it.name)}" ${checked}> ${escapeHtml(it.name)}${delBtn}</label>`;
    }
    html += `</div></div>`;
  }
  container.innerHTML = html;

  // 그룹 체크박스 → 하위 전체 토글
  container.querySelectorAll('.gen-grp-chk').forEach(gc => {
    gc.addEventListener('change', () => {
      const grp = gc.dataset.grp;
      container.querySelectorAll(`.gen-trade-chk[data-grp="${grp}"]`).forEach(c => { c.checked = gc.checked; });
    });
  });
  // 개별 체크박스 → 그룹 상태 반영
  container.querySelectorAll('.gen-trade-chk').forEach(tc => {
    tc.addEventListener('change', () => {
      const grp = tc.dataset.grp;
      const all = container.querySelectorAll(`.gen-trade-chk[data-grp="${grp}"]`);
      const checked = [...all].filter(c => c.checked).length;
      const gc = container.querySelector(`.gen-grp-chk[data-grp="${grp}"]`);
      if (gc) { gc.checked = checked === all.length; gc.indeterminate = checked > 0 && checked < all.length; }
    });
  });
  // 커스텀 공종 삭제 버튼 이벤트 위임
  container.addEventListener('click', async (e) => {
    const delBtn = e.target.closest('.gen-trade-del');
    if (!delBtn) return;
    e.preventDefault();
    const tradeId = delBtn.dataset.tradeId;
    if (!tradeId || !confirm('이 공종을 삭제하시겠습니까?')) return;
    try {
      const res = await safeFetch(`/api/fund/process-map/trades/${tradeId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('삭제 실패');
      showToast('공종 삭제 완료', 'success');
      onGenTypeChange();
    } catch (err) {
      showToast('공종 삭제 실패: ' + err.message, 'error');
    }
  });
}

function getSelectedTrades() {
  const container = document.getElementById('genTradeChecklist');
  if (!container) return [];
  return [...container.querySelectorAll('.gen-trade-chk:checked')].map(c => c.value);
}

async function parseEstimateFile() {
  const fileEl = document.getElementById('genEstimateFile');
  const resultEl = document.getElementById('genEstimateResult');
  if (!fileEl?.files?.length) { showToast('내역서 파일을 선택하세요.', 'error'); return; }

  const formData = new FormData();
  formData.append('file', fileEl.files[0]);

  try {
    resultEl.textContent = '분석 중...';
    const res = await safeFetch('/api/fund/process-map/parse-estimate', { method: 'POST', body: formData });
    if (!res.ok) throw new Error('파싱 실패');
    const data = await res.json();

    // 매칭된 공종 자동 체크
    const container = document.getElementById('genTradeChecklist');
    if (container && data.matched_trades) {
      const matchedSet = new Set(data.matched_trades);
      container.querySelectorAll('.gen-trade-chk').forEach(c => {
        if (matchedSet.has(c.value)) c.checked = true;
      });
      // 그룹 체크 상태 갱신
      container.querySelectorAll('.gen-grp-chk').forEach(gc => {
        const grp = gc.dataset.grp;
        const all = container.querySelectorAll(`.gen-trade-chk[data-grp="${grp}"]`);
        const checked = [...all].filter(c => c.checked).length;
        gc.checked = checked === all.length;
        gc.indeterminate = checked > 0 && checked < all.length;
      });
    }

    const matched = data.matched_trades?.length || 0;
    const unmatched = data.unmatched?.length || 0;
    resultEl.innerHTML = `<span style="color:#22c55e;">${matched}개 공종 매칭</span>` +
      (unmatched > 0 ? ` | <span style="color:#f97316;">${unmatched}개 미매칭 (${escapeHtml(data.unmatched.slice(0, 3).join(', '))}...)</span>` : '');
  } catch (e) {
    resultEl.textContent = '내역서 파싱 실패: ' + e.message;
  }
}

async function submitGenSchedule() {
  const startDate = document.getElementById('genStartDate')?.value;
  const endDate = document.getElementById('genEndDate')?.value;
  const area = parseFloat(document.getElementById('genArea')?.value) || 100;
  const projectType = document.getElementById('genProjectType')?.value || '오피스';
  const hasImport = document.getElementById('genImportMat')?.checked || false;
  const selectedTrades = getSelectedTrades();

  if (!startDate || !endDate) { showToast('착공일과 준공일을 입력하세요.', 'error'); return; }
  if (selectedTrades.length === 0) { showToast('최소 1개 이상 공종을 선택하세요.', 'error'); return; }

  showLoading('공정표 생성 중...');
  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/generate-schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start_date: startDate,
        end_date: endDate,
        area_pyeong: area,
        project_type: projectType,
        selected_trades: selectedTrades,
        has_import_materials: hasImport,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '생성 실패');
    }
    const data = await res.json();

    closeGenScheduleModal();
    showToast(`공정표 생성 완료! (${data.summary?.total_trades || 0}개 공종, ${data.summary?.total_calendar_days || 0}일)`, 'success');

    // 타임라인 갱신
    await loadSchedule(currentProjectId);

    // 다운로드 링크
    if (data.xlsx_url) {
      const a = document.createElement('a');
      a.href = data.xlsx_url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    if (data.pdf_url) {
      setTimeout(() => {
        const a2 = document.createElement('a');
        a2.href = data.pdf_url;
        a2.download = '';
        document.body.appendChild(a2);
        a2.click();
        a2.remove();
      }, 500);
    }
  } catch (e) {
    showToast('공정표 생성 실패: ' + e.message, 'error');
  } finally {
    hideLoading();
  }
}

async function exportSchedule(fmt) {
  if (!currentProjectId) { showToast('프로젝트를 먼저 선택하세요.', 'error'); return; }
  showLoading('내보내기 중...');
  try {
    const res = await safeFetch(`/api/fund/projects/${currentProjectId}/export-schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: fmt }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '내보내기 실패');
    }
    const data = await res.json();

    if (data.xlsx_url && (fmt === 'xlsx' || fmt === 'both')) {
      const a = document.createElement('a');
      a.href = data.xlsx_url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    if (data.pdf_url && (fmt === 'pdf' || fmt === 'both')) {
      setTimeout(() => {
        const a2 = document.createElement('a');
        a2.href = data.pdf_url;
        a2.download = '';
        document.body.appendChild(a2);
        a2.click();
        a2.remove();
      }, 500);
    }
    showToast('내보내기 완료!', 'success');
  } catch (e) {
    showToast('내보내기 실패: ' + e.message, 'error');
  } finally {
    hideLoading();
  }
}

// ────────────────────────────────────────────
// 공종 편집 (Phase B)
// ────────────────────────────────────────────

function toggleTradeEditPanel() {
  const panel = document.getElementById('tradeEditPanel');
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

async function addCustomTrade() {
  const groupName = document.getElementById('newTradeGroup')?.value;
  const name = document.getElementById('newTradeName')?.value?.trim();
  const days = parseInt(document.getElementById('newTradeDays')?.value) || 0;
  if (!groupName || !name) {
    showToast('그룹과 공종명을 입력하세요.', 'error');
    return;
  }
  // 그룹 색상 찾기
  let groupColor = '#6b7280';
  if (_genTradeData?.groups) {
    const g = _genTradeData.groups.find(g => g.group === groupName);
    if (g) groupColor = g.color;
  }
  try {
    const res = await safeFetch('/api/fund/process-map/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        group_name: groupName,
        group_color: groupColor,
        name: name,
        default_days: days,
        is_custom: 1,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '추가 실패');
    }
    showToast(`공종 "${name}" 추가 완료`, 'success');
    document.getElementById('newTradeName').value = '';
    onGenTypeChange();
  } catch (e) {
    showToast('공종 추가 실패: ' + e.message, 'error');
  }
}

async function saveCustomPreset() {
  const name = document.getElementById('newPresetName')?.value?.trim();
  if (!name) {
    showToast('프리셋명을 입력하세요.', 'error');
    return;
  }
  const selected = getSelectedTrades();
  if (selected.length === 0) {
    showToast('최소 1개 이상 공종을 선택하세요.', 'error');
    return;
  }
  try {
    const res = await safeFetch('/api/fund/process-map/presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        preset_name: name,
        trade_names: selected,
        is_custom: 1,
      }),
    });
    if (!res.ok) throw new Error('저장 실패');
    showToast(`프리셋 "${name}" 저장 완료 (${selected.length}개 공종)`, 'success');
    document.getElementById('newPresetName').value = '';
    // genProjectType에 커스텀 프리셋 추가
    const typeSel = document.getElementById('genProjectType');
    if (typeSel) {
      const exists = [...typeSel.options].some(o => o.value === name);
      if (!exists) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name + ' (커스텀)';
        typeSel.appendChild(opt);
      }
    }
  } catch (e) {
    showToast('프리셋 저장 실패: ' + e.message, 'error');
  }
}
