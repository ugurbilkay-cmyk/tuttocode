'use strict';
const catalog = JSON.parse(document.getElementById('station-catalog').textContent);
const countries = new Map(catalog.countries.map(c => [c.id, c]));
const $ = id => document.getElementById(id);
const countryInput = $('country-id'), printer = $('printer'), printTemplate = $('print-template');
let selected = countries.get(countryInput.value);
let jobDirty = false;
function markDirty() {
  if (!window.stationPhotoId || !window.stationEditable) return;
  jobDirty = true;
  if ($('pending-changes')) $('pending-changes').hidden = false;
  document.querySelectorAll('form[action$="/issue"] button[type="submit"], form[action$="/ai/accept"] button[type="submit"], #ai-prepare-form button[type="submit"], #print-button, button[form="email-form"]').forEach(button => button.disabled = true);
  document.querySelectorAll('a[href$="/save.jpg"]').forEach(link => link.setAttribute('aria-disabled','true'));
  document.querySelectorAll('.photomatic-handoff').forEach(link=>link.setAttribute('aria-disabled','true'));
}
function updatePrints() {
  const previous = printTemplate.value;
  const options = catalog.prints.filter(p => p.filename.toLowerCase() === selected.default_print_name.toLowerCase() ||
    ([printer.value,'Installed templates','Generated layouts'].includes(p.printer) &&
    (p.format === selected.format || p.boxes.some(b => b.format === selected.format))));
  options.sort((a,b) => Number(a.filename.toLowerCase() !== selected.default_print_name.toLowerCase()) - Number(b.filename.toLowerCase() !== selected.default_print_name.toLowerCase()) ||
    Number(a.printer !== printer.value) - Number(b.printer !== printer.value) ||
    Number(a.printer !== 'Installed templates') - Number(b.printer !== 'Installed templates') || a.name.localeCompare(b.name));
  printTemplate.replaceChildren(...options.map(p => {
    const option = document.createElement('option');
    option.value = p.id; option.textContent = `${p.name} · ${p.boxes.length} photos · ${p.printer}`; return option;
  }));
  if (options.some(p => p.id === previous)) printTemplate.value = previous;
  updateDimensions();
}
function updateDimensions() {
  const p = catalog.prints.find(p => p.id === printTemplate.value);
  $('print-dimensions').textContent = p ? `${p.width_px} × ${p.height_px} px · ${p.dpi} DPI` : 'No matching print template';
}
function selectCountry(id) {
  if (id !== countryInput.value) markDirty();
  selected = countries.get(id); countryInput.value = id;
  try { sessionStorage.setItem('photomatic-country',id); } catch (_) {}
  $('country-label').textContent = selected.name;
  const flag = $('country-flag'); flag.hidden = !selected.flag; if (selected.flag) flag.src = selected.flag;
  $('photo-size').textContent = `${selected.width_mm} × ${selected.height_mm} mm`;
  $('photo-stage').style.setProperty('--photo-ratio', `${selected.width_mm}/${selected.height_mm}`);
  const overlay = $('crop-overlay'); overlay.hidden = !selected.overlay || !$('show-overlay').checked;
  if (selected.overlay) overlay.src = selected.overlay;
  printTemplate.value = ''; updatePrints(); updateJobMode(); $('country-dialog').close();
}
$('choose-country').addEventListener('click', () => { $('country-dialog').showModal(); $('country-search').focus(); });
$('close-countries').addEventListener('click', () => $('country-dialog').close());
document.querySelectorAll('.country-choice').forEach(button => button.addEventListener('click', () => selectCountry(button.dataset.country)));
$('country-search').addEventListener('input', e => {
  const query = e.target.value.trim().toLowerCase(); let visible = 0;
  document.querySelectorAll('.country-choice').forEach(button => { button.hidden = !button.dataset.search.includes(query); if (!button.hidden) visible++; });
  $('no-countries').hidden = visible > 0;
});
printer.addEventListener('change', () => { updatePrints();try { sessionStorage.setItem('photomatic-printer',printer.value); } catch (_) {} }); printTemplate.addEventListener('change', updateDimensions);
$('show-overlay').addEventListener('change', () => updateJobMode());
let beforeShown = false;
$('before-toggle')?.addEventListener('click', () => { beforeShown = !beforeShown; $('before-photo').hidden = !beforeShown; $('stage-photo').hidden = beforeShown; });
for (const id of ['zoom','x','y','angle']) $(id)?.addEventListener('input', e => $(id + '-value').textContent = e.target.value + (id === 'zoom' ? '' : id === 'angle' ? '°' : '%'));
$('reset-crop')?.addEventListener('click', () => { for (const [id, value] of [['zoom',1],['x',0],['y',0],['rotation',0],['angle',0]]) { $(id).value=value; $(id).dispatchEvent(new Event('input',{bubbles:true})); } });
document.querySelectorAll('[data-rotate]').forEach(button => button.addEventListener('click', () => {
  $('angle').value = Math.max(-15, Math.min(15, Number($('angle').value) + Number(button.dataset.rotate)));
  $('angle').dispatchEvent(new Event('input',{bubbles:true}));
}));
document.querySelectorAll('[data-measurements]').forEach(button => button.addEventListener('click', () => $('measurements-dialog').showModal()));
$('close-measurements')?.addEventListener('click', () => $('measurements-dialog').close());
$('open-ai-measurements')?.addEventListener('click', () => $('ai-measurements-dialog').showModal());
$('close-ai-measurements')?.addEventListener('click', () => $('ai-measurements-dialog').close());
document.querySelectorAll('.local-slider').forEach(input => input.addEventListener('input', () => {
  input.closest('label').querySelector('output').textContent = `${input.value} ${input.dataset.unit}`;
}));
$('reset-local-tools')?.addEventListener('click', () => {
  document.querySelectorAll('#local-tools .local-slider').forEach(input => { input.value=input.name==='enhancer_upscale_strength' ? 70 : 0; input.dispatchEvent(new Event('input',{bubbles:true})); });
  document.querySelectorAll('#local-tools input[type=checkbox]').forEach(input => { input.checked=false; input.dispatchEvent(new Event('input',{bubbles:true})); });
  if ($('enhancer-scale')) { $('enhancer-scale').value='1'; $('enhancer-scale').dispatchEvent(new Event('input',{bubbles:true})); }
  if ($('enhancer-engine')) { $('enhancer-engine').value='plksr'; $('enhancer-engine').dispatchEvent(new Event('input',{bubbles:true})); }
  if ($('enhancer-preset')) $('enhancer-preset').value='';
  if ($('blemish-sensitivity')) $('blemish-sensitivity').value='gentle';
  if ($('blemish-size')) $('blemish-size').value='medium';
  if ($('blemish-keep')) $('blemish-keep').value='[]';
});
$('enhancer-preset')?.addEventListener('change', event => {
  const preset = JSON.parse($('enhancer-presets').textContent)[event.target.value];
  if (!preset) return;
  const form = $('photo-form');
  document.querySelectorAll('#local-tools .local-slider:not(.enhancer-slider)').forEach(input => {
    input.value=preset.adjustments[input.name] ?? 0;
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  for (const [key,value] of Object.entries({lighting:0,denoise:0,detail:0,skin:0,blemish:0,scale:1,upscale_strength:70,upscale_engine:'plksr',...preset.enhancement})) {
    const input=form.elements.namedItem('enhancer_'+key);
    if (input) { input.value=value; input.dispatchEvent(new Event('input',{bubbles:true})); }
  }
  for (const key of ['auto_adjust','fix_shadows']) {
    const input=form.elements.namedItem(key);
    if (input) { input.checked=preset[key];input.dispatchEvent(new Event('input',{bubbles:true})); }
  }
});
function updateJobMode(reset=false) {
  const fullFrame = $('print-only')?.checked ?? Boolean(window.stationFullFrame);
  if ($('crop-controls')) $('crop-controls').hidden = Boolean(fullFrame);
  if (fullFrame && reset) {
    for (const [id,value] of [['zoom',1],['x',0],['y',0],['rotation',0],['angle',0]]) {
      if ($(id)) { $(id).value=value; $(id).dispatchEvent(new Event('input',{bubbles:true})); }
    }
  }
  $('crop-overlay').hidden = Boolean(fullFrame) || !$('show-overlay').checked || !selected.overlay;
}
$('print-only')?.addEventListener('change', () => updateJobMode(true)); updateJobMode();
let hotspotBusy = false;
let cleanerKeeps=[],cleanerImage=null,cleanerOverlay=null,cleanerDrawing=false;
function renderCleaner() {
  const canvas=$('cleaner-canvas'); if (!canvas || !cleanerImage) return;
  const context=canvas.getContext('2d');context.clearRect(0,0,canvas.width,canvas.height);
  context.drawImage(cleanerImage,0,0,canvas.width,canvas.height);
  if ($('cleaner-show-mask').checked && cleanerOverlay) context.drawImage(cleanerOverlay,0,0);
  context.strokeStyle='#16a34a';context.fillStyle='rgba(22,163,74,0.12)';context.lineWidth=2;
  for (const [x,y,r] of cleanerKeeps) { context.beginPath();context.arc(x*canvas.width,y*canvas.height,r*Math.min(canvas.width,canvas.height),0,2*Math.PI);context.fill();context.stroke(); }
  $('cleaner-progress').textContent=`${cleanerKeeps.length} keep areas.${window.stationEditable ? ' Apply changes to recalculate the repairs.' : ' Read-only review.'}`;
}
function loadCleanerImage(url) { return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('Repair preview unavailable. Refresh the photo.'));image.src=url;}); }
$('open-cleaner')?.addEventListener('click',async()=>{
  if (jobDirty) { alert('Apply changes before reviewing skin repairs.');return; }
  $('cleaner-dialog').showModal();$('cleaner-progress').textContent='Loading repairs…';if ($('cleaner-use')) $('cleaner-use').disabled=true;
  cleanerImage=null;cleanerOverlay=null;cleanerDrawing=false;cleanerKeeps=JSON.parse($('blemish-keep').value);
  try {
    const images=await Promise.all([loadCleanerImage(`/admin/p/${window.stationPhotoId}/cleaner/before.png?revision=${window.stationRevision}`),loadCleanerImage(`/admin/p/${window.stationPhotoId}/cleaner/mask.png?revision=${window.stationRevision}`)]);
    const canvas=$('cleaner-canvas'),ratio=Math.min(1,1280/Math.max(images[0].width,images[0].height));
    canvas.width=Math.round(images[0].width*ratio);canvas.height=Math.round(images[0].height*ratio);cleanerImage=images[0];
    cleanerOverlay=document.createElement('canvas');cleanerOverlay.width=canvas.width;cleanerOverlay.height=canvas.height;
    const context=cleanerOverlay.getContext('2d');context.drawImage(images[1],0,0,canvas.width,canvas.height);
    const pixels=context.getImageData(0,0,canvas.width,canvas.height);
    for (let i=0;i<pixels.data.length;i+=4) { const alpha=pixels.data[i];pixels.data[i]=30;pixels.data[i+1]=144;pixels.data[i+2]=255;pixels.data[i+3]=Math.round(alpha*.65); }
    context.putImageData(pixels,0,0);renderCleaner();if ($('cleaner-use')) $('cleaner-use').disabled=false;
  } catch(error) {$('cleaner-progress').textContent=error.message;}
});
function cleanerMark(event) {
  if (!window.stationEditable || !cleanerImage || cleanerKeeps.length>=256) return;
  const bounds=$('cleaner-canvas').getBoundingClientRect(),x=Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width)),y=Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height)),r=Number($('cleaner-radius').value);
  const previous=cleanerKeeps.at(-1);
  if (previous && cleanerDrawing && Math.hypot(x-previous[0],y-previous[1])<r/2) return;
  cleanerKeeps.push([x,y,r]);renderCleaner();
}
$('cleaner-canvas')?.addEventListener('pointerdown',event=>{cleanerDrawing=true;event.currentTarget.setPointerCapture(event.pointerId);cleanerMark(event);});
$('cleaner-canvas')?.addEventListener('pointermove',event=>{if (cleanerDrawing) cleanerMark(event);});
for (const name of ['pointerup','pointercancel']) $('cleaner-canvas')?.addEventListener(name,()=>cleanerDrawing=false);
$('close-cleaner')?.addEventListener('click',()=>$('cleaner-dialog').close());
$('cleaner-show-mask')?.addEventListener('change',renderCleaner);
$('cleaner-undo')?.addEventListener('click',()=>{cleanerKeeps.pop();renderCleaner();});
$('cleaner-clear')?.addEventListener('click',()=>{cleanerKeeps=[];renderCleaner();});
$('cleaner-use')?.addEventListener('click',()=>{$('blemish-keep').value=JSON.stringify(cleanerKeeps);markDirty();$('cleaner-dialog').close();});
function hotspotElement(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function showHotspotStage(stage) {
  const panel = hotspotElement('section', undefined, 'hotspot-stage');
  panel.append(hotspotElement('h3', stage.label));
  if (stage.preview) {
    const view = hotspotElement('div', undefined, 'hotspot-view');
    const image = hotspotElement('img'); image.src = stage.preview; image.alt = stage.label;
    view.append(image);
    if (stage.outlines) {
      const ns = 'http://www.w3.org/2000/svg';
      const overlay = document.createElementNS(ns, 'svg');
      overlay.setAttribute('viewBox', '0 0 1000 1000'); overlay.setAttribute('preserveAspectRatio', 'none');
      overlay.classList.add('hotspot-regions'); overlay.toggleAttribute('hidden', !$('hotspot-overlay').checked);
      for (const region of stage.outlines) {
        const polygon = document.createElementNS(ns, 'polygon');
        polygon.setAttribute('points', region.points.map(p => `${p[0]*1000},${p[1]*1000}`).join(' '));
        const title = document.createElementNS(ns, 'title'); title.textContent = region.label;
        polygon.append(title); overlay.append(polygon);
      }
      for (const patch of stage.patches) {
        const rect = document.createElementNS(ns, 'rect');
        ['x','y','width','height'].forEach((name, index) => rect.setAttribute(name, patch.box[index]*1000));
        rect.classList.add('hotspot-patch'); overlay.append(rect);
      }
      view.append(overlay);
    }
    panel.append(view);
  }
  if (stage.status !== 'diagnostic') {
    panel.append(hotspotElement('p', stage.message || 'Measurements unavailable. Staff review needed.', 'notice'));
    return panel;
  }
  panel.append(hotspotElement('p', `${stage.image_size.join(' × ')} px · ${stage.patch_count} candidate patches · diagnostic only`));
  const table = hotspotElement('table', undefined, 'measurements hotspot-table');
  const head = hotspotElement('tr');
  ['Region','Bright area','Near clip · any channel','Near clip · all channels'].forEach(label => head.append(hotspotElement('th',label)));
  const thead = hotspotElement('thead'); thead.append(head); table.append(thead);
  const tbody = hotspotElement('tbody');
  for (const region of stage.regions) {
    const tr = hotspotElement('tr'); tr.append(hotspotElement('td',region.label));
    for (const key of ['bright_percent','near_clip_any_percent','near_clip_all_percent'])
      tr.append(hotspotElement('td',region.status === 'measured' ? `${region[key]}%` : 'Unavailable'));
    tbody.append(tr);
  }
  table.append(tbody); panel.append(table);
  if (stage.overlay_truncated) panel.append(hotspotElement('p','Only the 100 largest patches are outlined.'));
  panel.append(hotspotElement('p',`Image reference: ${stage.image_sha256.slice(0,12)} · ${stage.engine}`, 'subtle'));
  return panel;
}
async function inspectHotspots() {
  if (hotspotBusy) return;
  if (jobDirty) { $('hotspot-progress').textContent = 'Apply changes and refresh before inspecting the photo.'; return; }
  hotspotBusy = true; $('refresh-hotspots').disabled = true;
  $('hotspot-results').replaceChildren(); $('hotspot-progress').textContent = 'Measuring facial regions…';
  try {
    const response = await fetch(`/admin/p/${window.stationPhotoId}/hotspots`, {cache:'no-store'});
    if (!response.ok) throw new Error(response.status === 409 ? 'The photo changed or is being processed. Refresh and inspect again.' : 'Inspection unavailable. Check your staff login and refresh.');
    const result = await response.json();
    $('hotspot-results').replaceChildren(...result.stages.map(showHotspotStage));
    $('hotspot-progress').textContent = 'Measurements complete. Compare the regions and review the original detail.';
  } catch (error) { $('hotspot-progress').textContent = error.message; }
  finally { hotspotBusy = false; $('refresh-hotspots').disabled = false; }
}
$('open-hotspots')?.addEventListener('click', () => { $('hotspots-dialog').showModal(); inspectHotspots(); });
$('close-hotspots')?.addEventListener('click', () => $('hotspots-dialog').close());
$('refresh-hotspots')?.addEventListener('click', inspectHotspots);
$('hotspot-overlay')?.addEventListener('change', () => document.querySelectorAll('.hotspot-regions').forEach(overlay => overlay.toggleAttribute('hidden', !$('hotspot-overlay').checked)));
function updateAiConsent() { if ($('upload-ai-consent')) $('upload-ai-consent').required = $('use-ai').checked; }
$('use-ai')?.addEventListener('change', updateAiConsent); updateAiConsent();
$('ai-prepare-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector('button[type=submit]'), progress = $('ai-progress');
  const data = new FormData(form);
  button.disabled = true; progress.hidden = false; progress.textContent = 'Preparing lighting and colour… This may take a few minutes.';
  try {
    const response = await fetch(form.action, {method:'POST', body:data});
    const type = response.headers.get('content-type') || '';
    const result = type.includes('application/json') ? await response.json() : {message:await response.text()};
    if (response.ok) { window.location.reload(); return; }
    progress.textContent = result.message || 'Preparation failed. Your current photo is unchanged.';
  } catch (_) { progress.textContent = 'Connection interrupted. Refresh to check the result before preparing again.'; }
  button.disabled = false;
});
$('print-button')?.addEventListener('click', () => {
  const query = new URLSearchParams({page:'1',template:printTemplate.value,printer:printer.value});
  window.open(`/admin/p/${window.stationPhotoId}/sheet.jpg?${query}`, '_blank', 'noopener');
});
let objectUrl = null;
function previewFile(file) {
  if (!file) return;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file); $('stage-photo').src = objectUrl; $('stage-photo').hidden = false; $('empty-photo').hidden = true;
}
$('file-input')?.addEventListener('change', e => previewFile(e.target.files[0]));
let stream = null;
function stopCamera() { stream?.getTracks().forEach(track => track.stop()); stream = null; }
$('camera-button')?.addEventListener('click', async () => {
  $('camera-dialog').showModal(); $('camera-error').hidden = true;
  try { stream = await navigator.mediaDevices.getUserMedia({video:{width:{ideal:2400},height:{ideal:3200},facingMode:'user'},audio:false}); $('camera-video').srcObject=stream; }
  catch (_) { $('camera-error').textContent='Camera unavailable. Allow browser camera access or use Open file for your camera photos.'; $('camera-error').hidden=false; }
});
$('close-camera').addEventListener('click', () => $('camera-dialog').close());
$('camera-dialog').addEventListener('close', stopCamera);
$('capture-photo').addEventListener('click', () => {
  const video = $('camera-video'); if (!video.videoWidth) return;
  const canvas = document.createElement('canvas'); canvas.width=video.videoWidth;canvas.height=video.videoHeight;
  canvas.getContext('2d').drawImage(video,0,0);
  canvas.toBlob(blob => {
    const file = new File([blob],'camera-photo.jpg',{type:'image/jpeg'});
    const transfer = new DataTransfer(); transfer.items.add(file); $('file-input').files=transfer.files;
    previewFile(file); $('camera-dialog').close();
  },'image/jpeg',.95);
});
$('photo-form').addEventListener('submit', () => {
  const button = $('process-button'); if (button) {
    button.disabled=true;
    const detailBackground = document.querySelector('input[name=replace_bg]')?.checked && $('background-engine')?.value === 'hr';
    const enhancerActive = ['lighting','denoise','blemish'].some(key => Number(document.querySelector(`[name=enhancer_${key}]`)?.value)>0) || Number($('enhancer-scale')?.value)>1;
    button.textContent=$('use-ai')?.checked ? 'Preparing with OpenAI…' : enhancerActive ? 'Enhancing locally… This can take several minutes.' : detailBackground ? 'Removing background… This can take a minute.' : 'Processing…';
  }
});
$('photo-form').addEventListener('input', event => {
  if (event.isTrusted && event.target.matches('#local-tools .local-slider, #enhancer-scale, #enhancer-engine, #blemish-sensitivity, #blemish-size')) $('enhancer-preset').value='';
  if (!['printer','print-template','show-overlay'].includes(event.target.id)) markDirty();
  if (['zoom','x','y','rotation','angle','print-only','file-input'].includes(event.target.id) && $('blemish-keep')) $('blemish-keep').value='[]';
});
document.querySelectorAll('a[href$="/save.jpg"]').forEach(link => link.addEventListener('click', event => { if (jobDirty) event.preventDefault(); }));
document.querySelectorAll('.photomatic-handoff').forEach(link=>link.addEventListener('click',event=>{if(jobDirty)event.preventDefault();}));

// Keep country/printer choices when opening the next shop photo.
if (!window.stationPhotoId) {
  try {
    const lastPrinter = sessionStorage.getItem('photomatic-printer');
    if ([...printer.options].some(p => p.value === lastPrinter)) printer.value = lastPrinter;
    const lastCountry = sessionStorage.getItem('photomatic-country');
    if (countries.has(lastCountry)) selectCountry(lastCountry); else updatePrints();
  } catch (_) {}
}
