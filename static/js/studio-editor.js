(() => {
  const root = document.getElementById('studio-editor');
  if (!root) return;

  const projectId = root.dataset.projectId;
  const readonly = root.dataset.readonly === 'true';
  const language = root.dataset.language || 'en';
  const csrf = document.querySelector('#studio-csrf input[name="csrfmiddlewaretoken"]')?.value || '';
  const workspace = document.getElementById('zone-workspace');
  const zoneSelect = document.getElementById('active-zone');
  const saveState = document.getElementById('studio-save-state');
  const validationPanel = document.getElementById('studio-validation');
  const validationTitle = document.getElementById('validation-title');
  const validationList = document.getElementById('validation-list');
  const deleteButton = document.getElementById('delete-selected-element');
  const methodControl = document.getElementById('element-production-method');
  const controls = {
    x: document.getElementById('transform-x'),
    y: document.getElementById('transform-y'),
    scale: document.getElementById('transform-scale'),
    rotation: document.getElementById('transform-rotation'),
  };
  let selected = null;
  let dirty = false;
  let selectedArtworkMethods = [];

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;

  function transformFor(el) {
    return {
      x: number(el.dataset.x, .5),
      y: number(el.dataset.y, .5),
      scale: number(el.dataset.scale, .35),
      rotation: number(el.dataset.rotation, 0),
    };
  }

  function applyElement(el) {
    const t = transformFor(el);
    el.style.left = `${t.x * 100}%`;
    el.style.top = `${t.y * 100}%`;
    el.style.width = `${t.scale * 100}%`;
    el.style.aspectRatio = '1 / 1';
    el.style.transform = `translate(-50%, -50%) rotate(${t.rotation}deg)`;
  }

  function updateControls() {
    const enabled = !!selected && !readonly;
    Object.values(controls).forEach(input => { if (input) input.disabled = !enabled; });
    if (methodControl) methodControl.disabled = !enabled;
    if (deleteButton) deleteButton.disabled = !enabled;
    document.getElementById('no-element-selected')?.toggleAttribute('hidden', !!selected);
    if (!selected) return;
    const t = transformFor(selected);
    controls.x.value = t.x.toFixed(2);
    controls.y.value = t.y.toFixed(2);
    controls.scale.value = t.scale.toFixed(2);
    controls.rotation.value = Math.round(t.rotation);
    if (methodControl) methodControl.value = selected.dataset.method || 'print';
  }

  function setSelected(el) {
    document.querySelectorAll('[data-studio-element].is-selected').forEach(node => node.classList.remove('is-selected'));
    selected = el || null;
    if (selected) {
      selected.classList.add('is-selected');
      if (zoneSelect && zoneSelect.value !== selected.dataset.zoneId) setActiveZone(selected.dataset.zoneId, false);
    }
    updateControls();
  }

  function setSaveState(state) {
    if (!saveState) return;
    saveState.dataset.state = state;
    saveState.textContent = state === 'saving' ? root.dataset.saving : state === 'error' ? root.dataset.saveError : root.dataset.saved;
  }

  function savedTransform(el) {
    try { return JSON.parse(el.dataset.saved || '{}'); } catch (_) { return transformFor(el); }
  }

  function restoreSaved(el) {
    const t = savedTransform(el);
    Object.entries(t).forEach(([key, value]) => { el.dataset[key] = value; });
    applyElement(el);
    if (selected === el) updateControls();
  }

  async function saveElement(el, extra = {}) {
    if (!el || readonly) return false;
    dirty = true;
    setSaveState('saving');
    const payload = { transform: transformFor(el), ...extra };
    try {
      const response = await fetch(`/api/v1/studio-projects/${projectId}/elements/${el.dataset.elementId}/`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('validation');
      const body = await response.json();
      const t = body.transform || payload.transform;
      Object.entries(t).forEach(([key, value]) => { el.dataset[key] = value; });
      if (body.production_method) el.dataset.method = body.production_method;
      el.dataset.saved = JSON.stringify(t);
      applyElement(el);
      dirty = false;
      setSaveState('saved');
      updateControls();
      await refreshValidation();
      return true;
    } catch (_) {
      restoreSaved(el);
      dirty = false;
      setSaveState('error');
      await refreshValidation();
      return false;
    }
  }

  async function refreshValidation() {
    if (!validationPanel) return;
    try {
      const response = await fetch(`/api/v1/studio-projects/${projectId}/validation/`, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      validationPanel.classList.toggle('is-valid', !!data.valid);
      validationPanel.classList.toggle('is-invalid', !data.valid);
      if (validationTitle) validationTitle.textContent = data.valid ? (language === 'ar' ? 'جاهز للطلب' : 'Ready to order') : (language === 'ar' ? 'يحتاج إلى انتباه' : 'Needs attention');
      if (validationList) {
        validationList.replaceChildren();
        const messages = data.valid ? [language === 'ar' ? 'المنتج والخيار والعناصر والمواضع صالحة حالياً.' : 'Product, variant, elements and placements are currently valid.'] : (language === 'ar' ? ['راجع موضع العنصر وطريقة الإنتاج وأهلية المصدر.'] : (data.errors || ['Review the customization before ordering.']));
        messages.forEach(message => { const li = document.createElement('li'); li.textContent = message; validationList.appendChild(li); });
      }
      const readyAction = document.querySelector('input[name="action"][value="ready"]');
      const readyButton = readyAction?.closest('form')?.querySelector('button[type="submit"]');
      if (readyButton) readyButton.disabled = !data.valid;
    } catch (_) {}
  }

  function zoneOption(id) {
    return zoneSelect ? Array.from(zoneSelect.options).find(option => option.value === String(id)) : null;
  }

  function setActiveZone(id, syncSources = true) {
    if (!zoneSelect || !workspace) return;
    const option = zoneOption(id) || zoneSelect.options[0];
    if (!option) return;
    zoneSelect.value = option.value;
    document.getElementById('active-zone-title').textContent = option.dataset.zoneName || option.textContent;
    const ratio = clamp(number(option.dataset.zoneRatio, 1), .35, 2.85);
    workspace.style.aspectRatio = `${ratio} / 1`;
    document.querySelectorAll('[data-zone-anchor]').forEach(marker => marker.setAttribute('aria-current', marker.dataset.zoneAnchor === option.value ? 'true' : 'false'));
    document.querySelectorAll('[data-studio-element]').forEach(el => { el.hidden = el.dataset.zoneId !== option.value; });
    const width = option.dataset.zoneWidth;
    const height = option.dataset.zoneHeight;
    const dimensions = document.getElementById('zone-dimensions');
    if (dimensions) dimensions.textContent = width && height ? (language === 'ar' ? `الحد الأقصى الحقيقي للمنطقة: ${width} × ${height} مم. الإحداثيات محفوظة normalized ولا تتأثر باتجاه RTL.` : `Real zone maximum: ${width} × ${height} mm. Coordinates are normalized and never mirrored by RTL.`) : (language === 'ar' ? 'الإحداثيات محفوظة normalized داخل المنطقة ولا تتأثر باتجاه RTL.' : 'Coordinates are normalized inside the zone and never mirrored by RTL.');
    if (selected && selected.dataset.zoneId !== option.value) setSelected(null);
    if (syncSources) document.querySelectorAll('[data-zone-select]').forEach(select => { if (Array.from(select.options).some(item => item.value === option.value)) { select.value = option.value; updateMethodSelect(select); } });
  }

  function zoneMethods(select) {
    const option = select.options[select.selectedIndex];
    const method = option?.dataset.zoneMethod || 'both';
    return method === 'both' ? ['print', 'embroidery'] : [method];
  }

  function updateMethodSelect(zoneControl) {
    const form = zoneControl.closest('form');
    const methodSelect = form?.querySelector('[data-method-select]');
    if (!methodSelect) return;
    let methods = zoneMethods(zoneControl);
    if (form?.dataset.sourceForm === 'artwork' && selectedArtworkMethods.length) methods = methods.filter(method => selectedArtworkMethods.includes(method));
    Array.from(methodSelect.options).forEach(option => { option.hidden = !methods.includes(option.value); option.disabled = !methods.includes(option.value); });
    if (!methods.includes(methodSelect.value)) methodSelect.value = methods[0] || '';
    const submit = form.querySelector('button[type="submit"]');
    if (submit && form.dataset.sourceForm === 'artwork') submit.disabled = !document.getElementById('selected-artwork-version')?.value || methods.length === 0;
    else if (submit) submit.disabled = methods.length === 0;
  }

  document.querySelectorAll('[data-studio-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-studio-tab]').forEach(tab => tab.setAttribute('aria-selected', tab === button ? 'true' : 'false'));
    document.querySelectorAll('[data-studio-pane]').forEach(pane => { pane.hidden = pane.dataset.studioPane !== button.dataset.studioTab; });
  }));

  document.querySelectorAll('[data-artwork-choice]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-artwork-choice]').forEach(choice => choice.setAttribute('aria-pressed', choice === button ? 'true' : 'false'));
    document.getElementById('selected-artwork-version').value = button.dataset.artworkVersion;
    selectedArtworkMethods = (button.dataset.methods || '').split(',').filter(Boolean);
    const zone = document.querySelector('#add-artwork-form [data-zone-select]');
    if (zone) updateMethodSelect(zone);
  }));

  const initiallySelectedArtwork = document.querySelector('[data-artwork-choice][aria-pressed="true"]');
  if (initiallySelectedArtwork) selectedArtworkMethods = (initiallySelectedArtwork.dataset.methods || '').split(',').filter(Boolean);

  document.querySelectorAll('[data-zone-select]').forEach(select => {
    select.addEventListener('change', () => updateMethodSelect(select));
    updateMethodSelect(select);
  });

  zoneSelect?.addEventListener('change', () => setActiveZone(zoneSelect.value));
  document.querySelectorAll('[data-zone-anchor]').forEach(marker => marker.addEventListener('click', () => setActiveZone(marker.dataset.zoneAnchor)));

  document.querySelectorAll('[data-studio-element]').forEach(el => {
    applyElement(el);
    el.addEventListener('click', event => { event.stopPropagation(); setSelected(el); });
    el.addEventListener('focus', () => setSelected(el));
    if (readonly || !workspace) return;
    el.addEventListener('pointerdown', event => {
      if (event.button !== undefined && event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      setSelected(el);
      const rect = workspace.getBoundingClientRect();
      const start = transformFor(el);
      const mode = event.target.dataset.handle || 'move';
      const centerX = rect.left + start.x * rect.width;
      const centerY = rect.top + start.y * rect.height;
      el.setPointerCapture?.(event.pointerId);
      const move = e => {
        if (mode === 'move') {
          el.dataset.x = (e.clientX - rect.left) / rect.width;
          el.dataset.y = (e.clientY - rect.top) / rect.height;
        } else if (mode === 'scale') {
          const distance = Math.hypot(e.clientX - centerX, e.clientY - centerY);
          el.dataset.scale = clamp((distance * 2) / rect.width, .05, 1.15);
        } else if (mode === 'rotate') {
          el.dataset.rotation = Math.atan2(e.clientY - centerY, e.clientX - centerX) * 180 / Math.PI + 90;
        }
        applyElement(el);
        updateControls();
      };
      const up = async e => {
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        el.removeEventListener('pointercancel', up);
        el.releasePointerCapture?.(e.pointerId);
        await saveElement(el);
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointercancel', up);
    });
  });

  workspace?.addEventListener('click', () => setSelected(null));

  Object.entries(controls).forEach(([key, input]) => input?.addEventListener('change', async () => {
    if (!selected) return;
    selected.dataset[key] = input.value;
    applyElement(selected);
    await saveElement(selected);
  }));

  methodControl?.addEventListener('change', async () => {
    if (!selected) return;
    const previous = selected.dataset.method;
    selected.dataset.method = methodControl.value;
    const ok = await saveElement(selected, { production_method: methodControl.value });
    if (!ok) selected.dataset.method = previous;
  });

  deleteButton?.addEventListener('click', async () => {
    if (!selected || readonly) return;
    setSaveState('saving');
    try {
      const response = await fetch(`/api/v1/studio-projects/${projectId}/elements/${selected.dataset.elementId}/`, { method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf } });
      if (!response.ok) throw new Error('delete');
      const removed = selected;
      setSelected(null);
      removed.remove();
      setSaveState('saved');
      await refreshValidation();
    } catch (_) { setSaveState('error'); }
  });

  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });

  const initialZone = zoneSelect?.value;
  if (initialZone) setActiveZone(initialZone, true);
  if (initiallySelectedArtwork) {
    document.getElementById('selected-artwork-version').value = initiallySelectedArtwork.dataset.artworkVersion;
    const zone = document.querySelector('#add-artwork-form [data-zone-select]');
    if (zone) updateMethodSelect(zone);
  }
})();
