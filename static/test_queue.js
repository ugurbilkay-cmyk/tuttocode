'use strict';
const queuePhotos=[...document.querySelectorAll('input[name=photo_ids]')];
function queueCount(){const value=queuePhotos.filter(input=>input.checked).length;const label=document.getElementById('queue-selection-count');if(label)label.textContent=`${value} selected`;}
document.querySelectorAll('[data-select-count]').forEach(button=>button.addEventListener('click',()=>{const count=Number(button.dataset.selectCount);queuePhotos.forEach((input,index)=>input.checked=index<count);queueCount();}));
queuePhotos.forEach(input=>input.addEventListener('change',queueCount));queueCount();
document.getElementById('test-queue-form')?.addEventListener('submit',event=>{if(!queuePhotos.some(input=>input.checked)){event.preventDefault();document.getElementById('queue-selection-count').textContent='Select at least one prepared photo.';return;}document.getElementById('queue-building').hidden=false;event.currentTarget.querySelector('button[type=submit]').disabled=true;});
const govSession=document.getElementById('open-gov-session');
function sessionNote(){try{if(sessionStorage.getItem('manual-gov-photo-session'))document.getElementById('gov-session-note').textContent='GOV.UK was opened for this workflow. Switch to that tab and use change photo; opening this link again starts navigation again.';}catch(_){}}
if(govSession){sessionNote();govSession.addEventListener('click',()=>{try{sessionStorage.setItem('manual-gov-photo-session','1');}catch(_){}sessionNote();});}
document.getElementById('test-observation-form')?.addEventListener('submit',event=>{if(event.submitter?.name){const field=document.createElement('input');field.type='hidden';field.name=event.submitter.name;field.value=event.submitter.value;event.currentTarget.append(field);}document.querySelectorAll('#test-observation-form button[type=submit]').forEach(button=>{button.disabled=true;});});
