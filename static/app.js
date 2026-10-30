
const el=id=>document.getElementById(id);
let selected=null,preview=null,currentHash=null,pollTimer=null;
let workspaceGeneration=0;

let activeRescan = null;

const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v===null||v===undefined?'—':Number(v).toFixed(2);

function formatReportDate(isoDate) {
  if (typeof isoDate !== 'string') return '—';

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return '—';

  const [, year, month, day] = match;

  const date = new Date(Date.UTC(
    Number(year), Number(month) - 1, Number(day)
  ));

  if (
    date.getUTCFullYear() !== Number(year) ||
    date.getUTCMonth() + 1 !== Number(month) ||
    date.getUTCDate() !== Number(day)
  ) {
    return '—';
  }

  return `${month}/${day}/${year}`;
}

function fullClassName(row) {
  const fund = String(row.fund_name || '').trim();
  const className = String(row.class_name || '').trim();

  if (!fund) return className || '—';
  if (!className) return fund;

  if (className.toLowerCase() === fund.toLowerCase()) {
    return fund;
  }

  return className.toLowerCase().startsWith(fund.toLowerCase() + ' ') ? className : `${fund} ${className}`;
}

function getLatestReportDate(rows) {
  const dates = rows
    .map(row => row.report_date)
    .filter(date => formatReportDate(date) !== '—');

  if (!dates.length) return '—';

  return formatReportDate(dates.sort().at(-1));
}

function showError(m){el('overview').className='notice';el('overview').textContent=m;el('result').innerHTML='';el('status').textContent='Error';}
function render(data){closeRescanPanel();const rows=data.results||[];currentHash=data.hash;el('overview').className='hidden';el('download').classList.remove('hidden');el('download').href='/api/documents/'+data.hash+'/xlsx';el('actions').classList.remove('hidden');el('verify').textContent=data.verified?'✓ Verified':'Mark results as verified';


  const latestDate = getLatestReportDate(rows);

  const fundNames = [
    ...new Set(
      rows
        .map(r => String(r.fund_name || '').trim())
        .filter(Boolean)
    )
  ];

const fmcs = [
  ...new Set(
    rows
      .map(r => String(
        r.fmc || r.fmc_name || data.fmc || data.fmc_name || ''
      ).trim())
      .filter(Boolean)
  )
];

  const fundDisplay = fundNames.length
    ? `<div class="fund-info">
         <strong>FMC:</strong> ${escapeHtml(fmcs.join(', ') || 'Not detected')} &nbsp; <strong>Fund Name:</strong>
         <span>${fundNames.map(escapeHtml).join(', ')}</span>
       </div>`
    : '';

  const reviewCount = rows.filter(r => r.needs_review === true).length;

  const reviewDisplay = reviewCount
    ? `<div class="notice">
         <strong>Needs Review:</strong>
         ${reviewCount} class(es) have uncertain reporting-period evidence.
       </div>`
    : '';

  const statsHtml = `
    <div class="stats">
      <div class="stat">
        <small>Latest Date</small>
        <b>${escapeHtml(latestDate)}</b>
      </div>
      <div class="stat">
        <small>Classes / Funds</small>
        <b>${rows.length}</b>
      </div>
      <div class="stat">
        <small>Results</small>
        <b>${rows.reduce(
          (count, r) => count +
            ['MER', 'TER', 'PTR']
              .filter(m => r[m] !== null && r[m] !== undefined).length,
          0
        )}</b>
      </div>
    </div>
  `;

  const tableHtml = rows.length
    ? `
      <div class="scroller">
        <table>
          <thead>
            <tr>
              <th>Class / Fund</th>
              <th>Date</th>
              <th>MER</th>
              <th>TER</th>
              <th>PTR</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${escapeHtml(fullClassName(r))}</td>
                <td>${escapeHtml(formatReportDate(r.report_date))}</td>
                <td class="number">${fmt(r.MER)}</td>
                <td class="number">${fmt(r.TER)}</td>
                <td class="number">${fmt(r.PTR)}</td>
                <td>
                  <button class="ghost edit"
                    data-class="${escapeHtml(r.class_name)}" data-rowid="${escapeHtml(r.row_id || '')}">
                    Edit
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `
    : `<div class="notice">
         No reliable metric table was extracted.
         This document needs review; missing values are not assumed zero.
       </div>`;

  el('result').innerHTML =
    fundDisplay + statsHtml + reviewDisplay + tableHtml;

el('result').querySelectorAll('.edit').forEach(b=>{
  b.onclick=()=>editRow(b);
});
el('details').innerHTML='<details><summary>Evidence and source pages</summary><div class="scroller"><table><thead><tr><th>Class</th><th>Ratio</th><th>Page</th><th>Source</th></tr></thead><tbody>'+rows.flatMap(r=>['MER','TER','PTR'].filter(m=>r.evidence?.[m]).map(m=>`<tr><td>${escapeHtml(r.class_name)}</td><td>${m}</td><td>${escapeHtml(r.evidence[m].page||'Manual')}</td><td class="small">${escapeHtml(r.evidence[m].source)}</td></tr>`)).join('')+'</tbody></table></div></details>';
}
async function json(url,opts){const res=await fetch(url,opts);let data=await res.json();if(!res.ok)throw Error(data.error||`HTTP ${res.status}`);return data;}
function setBusy(isBusy){el('extract').disabled=isBusy;el('pdf').disabled=isBusy;}
el('pdf').onchange=()=>{const f=el('pdf').files[0];selected=f||null;el('filename').textContent=f?f.name:'No PDF selected';if(preview)URL.revokeObjectURL(preview);preview=f?URL.createObjectURL(f):null;el('viewer').src=preview||'about:blank';};
el('extract').onclick=async()=>{const generation = workspaceGeneration;if(!selected)return alert('Choose a PDF file first.');if(pollTimer)clearTimeout(pollTimer);setBusy(true);el('status').textContent='Uploading PDF...';el('overview').className='empty';el('overview').textContent='Analyzing fund report...';el('result').innerHTML='';el('result').querySelectorAll('.edit').forEach(b=>b.onclick=()=>editRow(b.dataset.class));
el('details').innerHTML='';el('actions').classList.add('hidden');el('download').classList.add('hidden');el('progressBar').style.width='2%';try{const f=new FormData();f.append('pdf',selected);let j=await json('/api/extract',{method:'POST',body:f});if (generation !== workspaceGeneration) return;await poll(j.job)}catch(e){showError(e.message);setBusy(false);}};

async function poll(job, generation = workspaceGeneration) {
  if (generation !== workspaceGeneration) return;

  try {
    const d = await json('/api/jobs/' + job);

    if (generation !== workspaceGeneration) return;

    el('status').textContent =
      d.message + (d.total ? ` · Page ${d.page}/${d.total}` : '');

    el('progressBar').style.width =
      (d.total
        ? Math.min(98, d.page / d.total * 100)
        : (d.status === 'complete' ? 100 : 4)) + '%';

    if (d.status === 'failed') {
      throw Error(d.error || 'Scan failed');
    }

    if (d.status === 'complete') {
      const documentData = await json(
        '/api/documents/' + encodeURIComponent(d.hash)
      );

      if (generation !== workspaceGeneration) return;

      render(documentData);
      setBusy(false);
      el('progressBar').style.width = '100%';

      await refreshHistory();
      return;
    }

    pollTimer = setTimeout(() => poll(job, generation), 750);

  } catch (e) {
    if (generation !== workspaceGeneration) return;

    showError(e.message);
    setBusy(false);
  }
}

el('verify').onclick=async()=>{if(!currentHash)return;try{await json(`/api/documents/${currentHash}/verify`,{method:'POST'});el('verify').textContent='✓ Verified';refreshHistory();}catch(e){alert(e.message);}};

async function refreshHistory() {
  try {
    const data = await json('/api/history');

    el('exportListed').classList.toggle('hidden', data.length === 0);

    el('history').innerHTML = data.map(r => `
      <button class="item" data-hash="${r.hash}">
        ${escapeHtml(r.filename)}
        <span class="meta">
          ${new Date(r.listed_at * 1000).toLocaleString()}
          · ${r.verified ? 'Verified' : 'Unverified'}
        </span>
      </button>
    `).join('') || '<small class="muted">No scans yet</small>';

    el('history').querySelectorAll('.item').forEach(b => {
      b.onclick = async () => {
        try {
          // Load previously saved extraction results.
          const documentData = await json(
            '/api/documents/' + b.dataset.hash
          );

          render(documentData);

          // Restore the original PDF in the right-side viewer.
          const pdfUrl =
            '/api/documents/' +
            encodeURIComponent(b.dataset.hash) +
            '/pdf';

          const response = await fetch(pdfUrl, {
            method: 'GET',
            cache: 'no-store'
          });

          if (response.ok) {
            // Release the previous temporary browser PDF URL.
            if (preview) {
              URL.revokeObjectURL(preview);
              preview = null;
            }

            const pdfBlob = await response.blob();
            preview = URL.createObjectURL(pdfBlob);

            el('viewer').src = preview;
            el('status').textContent = 'Loaded from history';
          } else {
            el('viewer').src = 'about:blank';
            el('status').textContent =
              'History loaded — original PDF not available';
          }

          el('filename').textContent = documentData.filename
            || 'Saved PDF';

        } catch (e) {
          showError(e.message);
        }
      };
    });

  } catch (e) {
    console.warn('History loading failed:', e);
  }
}

el('reloadHistory').onclick=refreshHistory;refreshHistory();

async function refreshSavedHistory() {
  try {
    const data = await json('/api/history/all');

    el('savedHistoryList').innerHTML = data.map(r => `
      <div class="item">
        <div>
          ${escapeHtml(r.filename)}
          <span class="meta">
            ${new Date(r.created * 1000).toLocaleString()}
            · ${r.verified ? 'Verified' : 'Unverified'}
          </span>
        </div>
        <button class="ghost restoreSaved"
                data-hash="${escapeHtml(r.hash)}">
          Restore
        </button>
      </div>
    `).join('') || '<small class="muted">No saved documents yet</small>';

    el('savedHistoryList')
      .querySelectorAll('.restoreSaved')
      .forEach(button => {
        button.onclick = async () => {
          try {
            await json(
              '/api/workspace/restore/' +
              encodeURIComponent(button.dataset.hash),
              { method: 'POST' }
            );

            await refreshHistory();
            await refreshSavedHistory();

            el('status').textContent =
              'Document restored to Recent Documents';
          } catch (e) {
            alert(e.message);
          }
        };
      });

  } catch (e) {
    console.error('Saved History failed:', e);
    alert('Could not load Saved History: ' + e.message);
  }
}

el('viewAllHistory').onclick = async () => {
  el('savedHistory').classList.remove('hidden');
  await refreshSavedHistory();
};

el('closeSavedHistory').onclick = () => {
  el('savedHistory').classList.add('hidden');
};

function editRow(button) {
  if (!currentHash) return;

  const row = button.closest('tr');
  if (!row || row.dataset.editing === 'true') return;

  const name = button.dataset.class;
  const documentHash = currentHash;
  const cells = row.querySelectorAll('td');

  if (cells.length < 6) return;

  const metrics = ['MER', 'TER', 'PTR'];
  const original = {};
  const inputs = {};

  row.dataset.editing = 'true';

  metrics.forEach((metric, index) => {
    const cell = cells[index + 2];
    const text = cell.textContent.trim();

    original[metric] = text === '—' ? null : Number(text);

    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.min = '0';
    input.max = metric === 'PTR' ? '1000' : '100';
    input.className = 'inline-ratio-input';
    input.value = original[metric] === null
      ? ''
      : String(original[metric]);

    cell.textContent = '';
    cell.appendChild(input);
    inputs[metric] = input;
  });

  const actionCell = cells[5];
  actionCell.textContent = '';

  const saveButton = document.createElement('button');
  saveButton.className = 'ghost';
  saveButton.textContent = 'Save';

  const cancelButton = document.createElement('button');
  cancelButton.className = 'ghost';
  cancelButton.textContent = 'Cancel';

  actionCell.append(saveButton, cancelButton);

  function discardChanges() {
    metrics.forEach((metric, index) => {
      cells[index + 2].textContent = fmt(original[metric]);
    });

    actionCell.textContent = '';
    actionCell.appendChild(button);
    row.dataset.editing = 'false';
  }

  async function saveChanges() {
    const changes = {};

    for (const metric of metrics) {
      const text = inputs[metric].value.trim();
      const value = text === '' ? null : Number(text);
      const maximum = metric === 'PTR' ? 1000 : 100;

      if (
        value !== null &&
        (!Number.isFinite(value) || value < 0 || value > maximum)
      ) {
        alert(`Enter a valid ${metric} value between 0 and ${maximum}.`);
        inputs[metric].focus();
        return;
      }

      if (value !== original[metric]) {
        changes[metric] = value;
      }
    }

    if (!Object.keys(changes).length) {
      discardChanges();
      return;
    }

    const confirmed = confirm(
      `Save corrections for ${name}?\n\n` +
      Object.entries(changes)
        .map(([metric, value]) =>
          `${metric}: ${fmt(original[metric])} → ${fmt(value)}`
        )
        .join('\n') +
      '\n\nYes = Save changes\nNo = Discard changes'
    );

    if (!confirmed) {
      discardChanges();
      return;
    }

    saveButton.disabled = true;
    cancelButton.disabled = true;

    try {
      await json(
        `/api/documents/${encodeURIComponent(documentHash)}/correct-row`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            class_name: name,
            values: changes
          })
        }
      );

      if (currentHash === documentHash) {
        render(await json(
          `/api/documents/${encodeURIComponent(documentHash)}`
        ));

        el('status').textContent =
          'Corrections saved. Please verify the results.';
      }

      await refreshHistory();

    } catch (error) {
      alert('Could not save correction: ' + error.message);
      saveButton.disabled = false;
      cancelButton.disabled = false;
    }
  }

  saveButton.onclick = saveChanges;
  cancelButton.onclick = discardChanges;

  Object.values(inputs).forEach(input => {
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveChanges();
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        discardChanges();
      }
    });
  });

  inputs.MER.focus();
  inputs.MER.select();
}

function resetWorkspaceUI() {
  closeRescanPanel();
  // Invalidate previous extraction polling.
  workspaceGeneration++;

  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  selected = null;
  currentHash = null;

  if (preview) {
    URL.revokeObjectURL(preview);
    preview = null;
  }

  el('pdf').value = '';
  el('filename').textContent = 'No PDF selected';
  el('viewer').src = 'about:blank';

  el('overview').className = 'empty';
  el('overview').innerHTML =
    '<div class="emptyIcon">▤</div>' +
    'Upload a fund report and click <b>Extract ratios</b>.' +
    '<br><small>MER, TER and portfolio turnover ' +
    'are detected automatically.</small>';

  el('result').innerHTML = '';
  el('details').innerHTML = '';

  el('actions').classList.add('hidden');
  el('download').classList.add('hidden');
  el('download').removeAttribute('href');

  el('progressBar').style.width = '0%';
  el('status').textContent = 'Workspace cleared';

  setBusy(false);
}

el('clearList').onclick = async () => {
  const approved = confirm(
    'Clear current workspace?\n\n' +
    'This will clear Recent Documents, results, and PDF preview.\n' +
    'Saved History, PDFs, corrections, and verification will remain.\n\n' +
    'Click OK to clear or Cancel to keep everything.'
  );

  if (!approved) return;

  el('clearList').disabled = true;

  try {
    await json('/api/workspace/clear', {
      method: 'POST'
    });

    resetWorkspaceUI();
    await refreshHistory();

    if (!el('savedHistory').classList.contains('hidden')) {
      await refreshSavedHistory();
    }

  } catch (e) {
    alert('Clear List failed: ' + e.message);
  } finally {
    el('clearList').disabled = false;
  }
};


function updateExportButtons() {
  const listedButton = el('exportListed');

  // Export All is independent of the active workspace.
  // Export Listed follows the visible Recent Documents list.
  const hasListedDocuments =
    el('history').querySelector('.item') !== null;

  listedButton.classList.toggle(
    'hidden',
    !hasListedDocuments
  );
}

async function refreshExportButtons() {
  try {
    const documents = await json('/api/history');
    el('exportListed').classList.toggle(
      'hidden',
      documents.length === 0
    );
  } catch (error) {
    console.warn('Could not update export controls:', error);
  }
}

// Initial export control state
refreshExportButtons();


function closeRescanPanel() {
  activeRescan = null;
  el('rescanPanel').classList.add('hidden');
  el('rescanComparison').innerHTML = '';
  el('rescanMessage').textContent = '';
  el('rescanConfirm').disabled = false;
  el('rescanCancel').disabled = false;
}


function rescanRowsHtml(rows) {
  if (!rows.length) {
    return '<tr><td colspan="5">No results</td></tr>';
  }

  return rows.map(row => `
    <tr>
      <td>${escapeHtml(fullClassName(row))}</td>
      <td>${escapeHtml(formatReportDate(row.report_date))}</td>
      <td class="number">${fmt(row.MER)}</td>
      <td class="number">${fmt(row.TER)}</td>
      <td class="number">${fmt(row.PTR)}</td>
    </tr>
  `).join('');
}


el('rescan').onclick = async () => {
  if (!currentHash) return;

  closeRescanPanel();

  const hash = currentHash;
  el('rescan').disabled = true;
  el('status').textContent = 'Re-scanning saved PDF...';

  try {
    const oldDocument = await json(
      '/api/documents/' + encodeURIComponent(hash)
    );

    const previewData = await json(
      '/api/documents/' + encodeURIComponent(hash) +
      '/rescan/preview',
      { method: 'POST' }
    );

    // Do not open an obsolete preview if another document
    // was selected or Clear List was used meanwhile.
    if (currentHash !== hash) return;

    activeRescan = {
      hash,
      previewId: previewData.preview_id
    };

    el('rescanComparison').innerHTML = `
      <h3>Currently Saved Results</h3>
      <div class="scroller">
        <table>
          <thead>
            <tr><th>Class / Fund</th><th>Date</th>
            <th>MER</th><th>TER</th><th>PTR</th></tr>

          </thead>
          <tbody>${rescanRowsHtml(oldDocument.results || [])}</tbody>
        </table>
      </div>

      <h3>Proposed New Extraction</h3>
      <div class="scroller">
        <table>
          <thead>
            <tr><th>Class / Fund</th><th>Date</th>
            <th>MER</th><th>TER</th><th>PTR</th></tr>
          </thead>
          <tbody>${rescanRowsHtml(previewData.results || [])}</tbody>
        </table>
      </div>
    `;

    el('rescanMessage').textContent =
      'Review the proposed results carefully. ' +
      'Replacing will preserve a snapshot of the old extraction ' +
      'and reset verification to Unverified.';

    el('rescanPanel').classList.remove('hidden');
    el('status').textContent = 'Re-scan preview ready';

  } catch (error) {
    if (currentHash === hash) {
      alert('Re-scan failed: ' + error.message);
      el('status').textContent = 'Re-scan failed';
    }
  } finally {
    el('rescan').disabled = false;
  }
};

el('rescanCancel').onclick = () => {
  closeRescanPanel();
  el('status').textContent = 'Re-scan canceled; saved results unchanged';
};

el('rescanConfirm').onclick = async () => {
  if (!activeRescan) return;

  const { hash, previewId } = activeRescan;

  if (currentHash !== hash) {
    closeRescanPanel();
    return;
  }

  el('rescanConfirm').disabled = true;
  el('rescanCancel').disabled = true;

  try {
    const response = await json(
      '/api/documents/' + encodeURIComponent(hash) +
      '/rescan/confirm',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_id: previewId })
      }
    );

    closeRescanPanel();

    if (currentHash === hash) {
      render(response.document);
      el('status').textContent =
        'Re-scan saved. Please verify the new results.';
    }

    await refreshHistory();

    if (!el('savedHistory').classList.contains('hidden')) {
      await refreshSavedHistory();
    }

  } catch (error) {
    alert('Could not replace results: ' + error.message);
    el('rescanConfirm').disabled = false;
    el('rescanCancel').disabled = false;
  }
};


