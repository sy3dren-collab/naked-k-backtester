'use strict';
// A small, guided layer compiles into the same validated graph as the editor.
const learning={recipes:[],recipe:'opening',study:null,selected:null,checks:new Map(),preview:0,timer:null,working:false};
function setLearningMode(mode){
  const simple=mode==='simple';document.body.classList.toggle('learning-mode',simple);document.body.classList.toggle('advanced-mode',!simple);
  for(const name of ['simple','advanced']){$('mode-'+name).classList.toggle('selected',mode===name);$('mode-'+name).setAttribute('aria-pressed',String(mode===name));}
  $('mode-hint').textContent=simple?'系統自動連接條件與停損，你只需要描述想測試的交易方式。':'進階模式可自由組合積木；修改後請檢查引用與進出場配置。';
  $('cost-details').open=!simple;
  if(simple&&strategy&&['TX','MTX','TMF'].includes(strategy.instrument)){$('learn-instrument').value=strategy.instrument;scheduleLearningPreview();}
}
$('mode-simple').onclick=()=>setLearningMode('simple');$('mode-advanced').onclick=()=>setLearningMode('advanced');
function learningConfig(){
  const costs={};$('costs').querySelectorAll('[data-cost]').forEach(el=>costs[el.dataset.cost]=Number(el.value));costs.tax_mode=$('tax-mode').value;
  return {recipe:learning.recipe,instrument:$('learn-instrument').value,direction:$('learn-direction').value,timeframe:Number($('learn-timeframe').value),
    opening_minutes:Number($('learn-opening').value),stop_points:Number($('learn-stop').value),exit:$('learn-exit').value,reward_r:Number($('learn-reward').value),
    session:$('learn-session').value,max_trades:Number($('learn-max-trades').value),drawdown_budget:Number($('learn-budget').value),costs};
}
function syncLearningInstrument(){
  const instrument=$('learn-instrument').value,value={MTX:50,TMF:10,TX:200}[instrument],field=document.querySelector('[data-cost="point_value"]');
  if(field)field.value=value;if(strategy){strategy.instrument=instrument;strategy.costs.point_value=value;}if($('instrument'))$('instrument').value=instrument;
}
function renderRecipes(){
  $('recipe-cards').innerHTML=learning.recipes.map((r,i)=>`<button class="recipe-card ${r.id===learning.recipe?'selected':''}" data-recipe="${r.id}" aria-pressed="${r.id===learning.recipe}"><small>0${i+1} · ${esc(r.tag)}</small><strong>${esc(r.name)}</strong><span>${esc(r.description)}</span></button>`).join('');
  $('recipe-cards').querySelectorAll('button').forEach(el=>el.onclick=()=>{learning.recipe=el.dataset.recipe;renderRecipes();scheduleLearningPreview();});
  const recipe=learning.recipes.find(r=>r.id===learning.recipe);$('recipe-lesson').textContent=recipe?.lesson||'';
  $('recipe-detail-list').innerHTML=(recipe?.details||[]).map(d=>`<li>${esc(d)}</li>`).join('');
  $('learn-opening-label').hidden=learning.recipe==='pullback';
}
function scheduleLearningPreview(){clearTimeout(learning.timer);learning.preview++;learning.timer=setTimeout(previewLearning,180);}
async function previewLearning(){
  const token=++learning.preview;
  $('learn-reward-label').hidden=$('learn-exit').value!=='rr';
  const config=learningConfig();$('quick-run-summary').textContent=(learning.recipes.find(r=>r.id===learning.recipe)?.name||'策略')+' · 停損 '+config.stop_points+' 點';$('learn-risk-cash').textContent=`停損距離 × 點值＝${fmt(config.stop_points*config.costs.point_value)} 元／口（未含費稅與滑價；跳空可能超過此金額）。`;
  try{
    const data=await api('learning/preview',{config});if(token!==learning.preview)return;
    $('learn-rules').innerHTML=data.rules.map(r=>`<li>${esc(r)}</li>`).join('');$('learn-preview-error').textContent='';
  }catch(error){if(token===learning.preview){$('learn-preview-error').textContent=error.message;$('learn-rules').innerHTML='<li>請先修正上方設定，再整理這套交易規則。</li>';}}
}
$('learning-builder').addEventListener('change',event=>{if(event.target.id==='learn-instrument')syncLearningInstrument();scheduleLearningPreview();});
$('cost-card').addEventListener('change',scheduleLearningPreview);
async function learningDataset(){
  if(preparingCSV)await preparingCSV;if(importPromise)await importPromise;
  if(!$('dataset').value&&csvText){const imported=await importDataset();if(imported.report.errors.length)throw Error(imported.report.errors[0]);}
  if(!$('dataset').value)throw Error('先選擇左邊的 CSV，或按「載入人工示範行情」熟悉操作。');
  const selected=datasets.find(d=>d.id===$('dataset').value);if(selected?.report.errors.length)throw Error(selected.report.errors[0]);
  return $('dataset').value;
}
function learningBusy(value,text=''){
  learning.working=value;for(const id of ['simple-run','simple-compare','check-holdout','quick-run'])$(id).disabled=value;
  if(text)$('learning-status').textContent=text;
}
async function runLearning(compare){
  if(learning.working||busy)return;
  const fields=[...$('learning-builder').querySelectorAll('input')];if(fields.some(el=>!el.reportValidity()))return;
  learningBusy(true,compare?'正在回測 3 種停損距離，只計算學習期…':'正在建立基準，只計算學習期…');
  try{
    const dataset_id=await learningDataset(),study=await api('learning/run',{dataset_id,config:learningConfig(),settings:{start:$('start').value||null,end:$('end').value||null},compare});
    learning.study=study;learning.selected=study.candidates[0].id;renderStudy();await refreshStudies(study.id);tab('study');
    message(compare?'學習期比較完成。先選一組設定，再查看保留期。':'基準回測完成。先看交易樣本與回撤，再決定下一步。');
    $('learning-status').textContent='研究已保存，可從「學習與比較」重新開啟。';
  }catch(error){message(error.message,true);$('learning-status').textContent=error.message;}
  finally{learningBusy(false);if(learning.study)renderHoldoutButton();}
}
$('quick-run').onclick=()=>runLearning(false);$('simple-run').onclick=()=>runLearning(false);$('simple-compare').onclick=()=>runLearning(true);
$('simple-to-advanced').onclick=()=>guard(async()=>{const data=await api('learning/preview',{config:learningConfig()});strategy=data.strategy;renderStrategy();setLearningMode('advanced');message('已將目前規則帶入積木。所有進出場與停損引用已自動設定。');});
$('study-back').onclick=()=>guard(async()=>{
  const study=learning.study,c=selectedCandidate()?.config;
  if(c){
    learning.recipe=c.recipe;
    const fields={'learn-instrument':'instrument','learn-direction':'direction','learn-timeframe':'timeframe','learn-opening':'opening_minutes','learn-stop':'stop_points','learn-exit':'exit','learn-reward':'reward_r','learn-session':'session','learn-max-trades':'max_trades','learn-budget':'drawdown_budget'};
    for(const [id,key]of Object.entries(fields)){const el=$(id);if(el.tagName==='SELECT'&&![...el.options].some(o=>o.value===String(c[key])))el.add(new Option(String(c[key])+'（已保存）',String(c[key])));el.value=c[key];}
    $('costs').querySelectorAll('[data-cost]').forEach(el=>el.value=c.costs[el.dataset.cost]);$('tax-mode').value=c.costs.tax_mode;
    strategy.instrument=c.instrument;strategy.costs=clone(c.costs);if($('instrument'))$('instrument').value=c.instrument;
    await loadDatasets(study.dataset_id);$('start').value=study.split.training.start;$('end').value=(study.split.validation||study.split.training).end;
    renderRecipes();await previewLearning();
  }
  setLearningMode('simple');tab('workspace');message('已帶回選定設定與原本的資料日期；建議這次只調整一件事，再比較結果。');
});
async function refreshStudies(selected){
  const studies=await api('learning/studies');$('study-library').innerHTML=option('','選擇已保存的研究',selected||'')+studies.map(s=>option(s.id,`${s.recipe.name} · ${s.config.instrument} · 停損 ${s.config.stop_points} 點 · ${s.split.training.start}–${s.split.training.end}`,selected)).join('');
}
$('study-library').onchange=()=>guard(async()=>{if(!$('study-library').value)return;learning.study=await api('learning/studies/'+$('study-library').value);learning.selected=learning.study.candidates[0].id;renderStudy();});
function selectedCandidate(){return learning.study?.candidates.find(c=>c.id===learning.selected);}
function smallMetrics(m){return `<div class="mini-metrics"><div><small>扣成本淨損益</small><strong class="${m.net_pnl<0?'negative':'positive'}">${fmt(m.net_pnl)}</strong></div><div><small>最大回撤</small><strong>${fmt(m.max_drawdown)}</strong></div><div><small>交易筆數</small><strong>${m.trade_count}</strong></div><div><small>獲利因子</small><strong>${fmt(m.profit_factor,2)}</strong></div></div>`;}
function assessmentHTML(a){return `<strong>${esc(a.label)}</strong><ul>${a.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>${a.cancellations.length?'<details><summary>查看取消進場的原因</summary><ul>'+a.cancellations.map(w=>`<li>${esc(w)}</li>`).join('')+'</ul></details>':''}`;}
function renderStudy(){
  const s=learning.study;if(!s)return;$('study-empty').hidden=true;$('study-content').hidden=false;
  const name=datasets.find(d=>d.id===s.dataset_id)?.name||s.data_name||'已匯入資料';
  $('study-context').innerHTML=`<div class="study-title"><div><span class="eyebrow">${esc(s.config.instrument)} · 1 口 · ${s.config.timeframe} 分 K · ${{long:'僅做多',short:'僅做空',both:'多空雙向'}[s.config.direction]}</span><h2>${esc(s.recipe.name)}</h2><p>${esc(name)}</p></div><span class="pill">已保存研究</span></div>${name.includes('人工')?'<p class="demo-note">目前是人工示範／驗收資料，只用來熟悉操作，不代表市場獲利能力。</p>':''}<div class="period-cards"><div><small>學習期 · ${s.split.training_days} 個交易日</small><strong>${s.split.training.start} → ${s.split.training.end}</strong></div><div><small>保留期 · ${s.split.validation_days} 個交易日</small><strong>${s.split.validation?s.split.validation.start+' → '+s.split.validation.end:'只有一天資料，無法切出保留期'}</strong></div></div><details><summary>這次的規則與資料檢查</summary><ol>${s.rules.map(r=>`<li>${esc(r)}</li>`).join('')}</ol><ul>${s.data_warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details><p class="hint">${esc(s.selection_note)}</p>`;
  $('candidate-cards').innerHTML=s.candidates.map(c=>`<button class="candidate-card ${c.id===learning.selected?'selected':''}" data-candidate="${c.id}" aria-pressed="${c.id===learning.selected}"><span class="candidate-heading"><strong>${esc(c.name)}</strong><small>${esc(c.assessment.label)}${(s.checked_candidates||[]).includes(c.id)?' · 已查看保留期':''}</small></span>${smallMetrics(c.metrics)}<span class="candidate-select">${c.id===learning.selected?'✓ 目前選擇':'選擇這組設定'}</span></button>`).join('');
  $('candidate-cards').querySelectorAll('button').forEach(el=>el.onclick=()=>{learning.selected=el.dataset.candidate;renderStudy();});
  $('selected-assessment').innerHTML=assessmentHTML(selectedCandidate().assessment);renderHoldoutButton();renderValidation();
}
function renderHoldoutButton(){
  const s=learning.study,hasPeriod=!!s?.split.validation;const checked=learning.checks.has(s?.id+'/'+learning.selected);
  $('check-holdout').disabled=learning.working||!hasPeriod;$('check-holdout').textContent=checked?'重新顯示這組保留期結果':'選定這組，查看保留期 →';
  $('holdout-hint').textContent=hasPeriod?(s.holdout_views?'這個匯入資料的重疊保留期已有檢視紀錄。再次調參後，請找另一段未查看資料驗證。':'比較過程沒有使用保留期績效。選定設定後，才會計算並顯示。'):'只有一個交易日，這次僅供練習；請增加交易日才能檢查另一段資料。';
}
$('check-holdout').onclick=async()=>{
  if(learning.working||!learning.study)return;const study=learning.study.id,candidate=learning.selected;learningBusy(true);$('holdout-hint').textContent='正在計算選定設定的保留期與滑價壓力測試…';
  try{const data=await api('learning/check',{study_id:study,candidate_id:candidate});learning.checks.set(study+'/'+candidate,data);if(learning.study.id===study){learning.study.holdout_views=Math.max(1,learning.study.holdout_views||0);learning.study.checked_candidates=[...new Set([...(learning.study.checked_candidates||[]),candidate])];renderStudy();}message('保留期驗證完成。這段資料現在已被查看。');}
  catch(error){message(error.message,true);$('holdout-hint').textContent=error.message;}
  finally{learningBusy(false);renderHoldoutButton();}
};
function renderValidation(){
  const check=learning.checks.get(learning.study.id+'/'+learning.selected);$('validation-content').hidden=!check;if(!check)return;
  $('validation-content').innerHTML=`<div class="validation-heading"><span class="eyebrow">HOLDOUT / 已選定的設定</span><h2>換一段行情，結果如何？</h2></div><div class="validation-grid"><article><h3>保留期 · 原成本</h3>${smallMetrics(check.metrics)}<div class="learning-assessment">${assessmentHTML(check.assessment)}</div><button class="text-button" id="view-validation">看這段交易與 K 棒 →</button></article><article><h3>滑價壓力測試</h3><p class="hint">單邊滑價改為 ${fmt(check.stress.slippage,2)} 點，其餘規則不變；原本 0 點則改為 1 點。</p>${smallMetrics(check.stress.metrics)}<button class="text-button" id="view-stress">看壓力測試明細 →</button></article></div><p class="holdout-note">${esc(check.note)}</p><p class="hint">保留期仍可能是小樣本。請同時看月份、逐筆原因與回撤，不能只看勝率或總獲利。</p>`;
  $('view-validation').onclick=()=>openLearningRun(check.run_id);$('view-stress').onclick=()=>openLearningRun(check.stress.run_id);
}
async function openLearningRun(id){await guard(async()=>{result=await api('runs/'+id);tradePage=0;renderResult();tab('report');});}
$('view-training').onclick=()=>{const c=selectedCandidate();if(c)openLearningRun(c.run_id);};
const reportToggle=document.createElement('button');reportToggle.id='report-detail-toggle';reportToggle.className='text-button';reportToggle.textContent='展開完整績效統計';$('metrics').before(reportToggle);
reportToggle.onclick=()=>{const expanded=document.body.classList.toggle('report-expanded');reportToggle.textContent=expanded?'收起完整績效統計':'展開完整績效統計';};
async function bootLearning(){
  const data=await api('learning/recipes');learning.recipes=data.recipes;learning.recipe=data.defaults.recipe;syncLearningInstrument();renderRecipes();await previewLearning();await refreshStudies();
}
if(window.NAKED_READY)guard(bootLearning);else window.addEventListener('naked-ready',()=>guard(bootLearning),{once:true});
