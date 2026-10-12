'use strict';
const catalog = JSON.parse(document.getElementById('station-catalog').textContent);
const countries = new Map(catalog.countries.map(c => [c.id, c]));
const $ = id => document.getElementById(id);
const countryInput = $('country-id'), printer = $('printer'), printTemplate = $('print-template');
let selected = countries.get(countryInput.value);
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
  selected = countries.get(id); countryInput.value = id;
  try { sessionStorage.setItem('photomatic-country',id); } catch (_) {}
  $('country-label').textContent = selected.name;
  const flag = $('country-flag'); flag.hidden = !selected.flag; if (selected.flag) flag.src = selected.flag;
  $('photo-size').textContent = `${selected.width_mm} × ${selected.height_mm} mm`;
  $('photo-stage').style.setProperty('--photo-ratio', `${selected.width_mm}/${selected.height_mm}`);
  const overlay = $('crop-overlay'); overlay.hidden = !selected.overlay || !$('show-overlay').checked;
  if (selected.overlay) overlay.src = selected.overlay;
  printTemplate.value = ''; updatePrints(); $('country-dialog').close();
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
$('show-overlay').addEventListener('change', e => $('crop-overlay').hidden = !e.target.checked || !selected.overlay);
let beforeShown = false;
$('before-toggle')?.addEventListener('click', () => { beforeShown = !beforeShown; $('before-photo').hidden = !beforeShown; $('stage-photo').hidden = beforeShown; });
for (const id of ['zoom','x','y']) $(id)?.addEventListener('input', e => $(id + '-value').textContent = e.target.value + (id === 'zoom' ? '' : '%'));
$('reset-crop')?.addEventListener('click', () => { for (const [id, value] of [['zoom',1],['x',0],['y',0],['rotation',0]]) { $(id).value=value; $(id).dispatchEvent(new Event('input')); } });
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
  const button = $('process-button'); if (button) { button.disabled=true;button.textContent='Processing…'; }
});

// Keep country/printer choices when opening the next shop photo.
if (!window.stationPhotoId) {
  try {
    const lastPrinter = sessionStorage.getItem('photomatic-printer');
    if ([...printer.options].some(p => p.value === lastPrinter)) printer.value = lastPrinter;
    const lastCountry = sessionStorage.getItem('photomatic-country');
    if (countries.has(lastCountry)) selectCountry(lastCountry); else updatePrints();
  } catch (_) {}
}
