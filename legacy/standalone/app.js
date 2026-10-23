'use strict';
const $ = id => document.getElementById(id);
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (x, digits=0) => x == null ? '—' : Number(x).toLocaleString('zh-TW', {maximumFractionDigits:digits});
const clone = x => JSON.parse(JSON.stringify(x));
let strategy, presets=[], datasets=[], result=null, tradePage=0, csvText='', busy=false;
const kinds = {opening_range:'開盤區間', rolling_range:'前 N 根區間', swing:'確認波段高低點', ma:'移動平均', snapshot:'鎖定突破價格', breakout:'收盤突破', retest:'支撐壓力回踩', candle:'K 棒方向', compare:'收盤與價格比較', and:'AND 全部成立', or:'OR 任一成立', sequence:'先 A 後 B', event:'成立邊緣事件'};
const priceKinds = ['opening_range','rolling_range','swing','ma','snapshot'];
const costNames = {point_value:'每點價值', commission:'單邊手續費', tax_rate:'單邊交易稅率', tax_fixed:'單邊固定交易稅', slippage:'單邊滑價點數', initial_capital:'初始模擬資金'};

function message(text, error=false) { $('message').hidden=false; $('message').className=error?'error':''; $('message').textContent=text; }
async function api(path, body) {
  if(window.NAKED_LOCAL_API)return window.NAKED_LOCAL_API(path,body);
  const response = await fetch('/api/'+path, body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '操作失敗');
  return data;
}
function tab(id) { document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.tab===id)); }
document.querySelectorAll('.nav').forEach(x=>x.onclick=()=>{tab(x.dataset.tab);if(x.dataset.tab==='history')guard(loadHistory);});
async function guard(fn) { try { await fn(); } catch(e) { message(e.message,true); } }
function download(name, text, type='application/json') { const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000); }
function option(value, label, selected) { return `<option value="${esc(value)}"${value===selected?' selected':''}>${esc(label)}</option>`; }
function references(output, selected, nullable=false) {
  return (nullable?option('','停用',selected):'') + strategy.blocks.filter(b=>b.output===output || (output==='signal' && b.output!=='PriceLevel')).map(b=>option(b.id,`${b.name} · ${b.id}`,selected)).join('');
}
function paramInput(key, value, label, numeric=false) { return `<label>${esc(label)}<input data-param="${key}" value="${esc(value)}"${numeric?' type="number" min="0" step="any"':''}></label>`; }
function paramSelect(key, value, label, options) { return `<label>${esc(label)}<select data-param="${key}">${options.map(([v,l])=>option(v,l,value)).join('')}</select></label>`; }
function renderBlocks() {
  $('blocks').innerHTML=strategy.blocks.map((b,i)=>{
    const p=b.params;let fields='';
    for(const key of ['minutes','period','left','right','within','tolerance']) if(key in p) fields+=paramInput(key,p[key],{minutes:'開盤區間分鐘',period:'回看 K 棒數',left:'左側確認根數',right:'右側確認根數',within:'等待上限（分鐘）',tolerance:'回踩容許點數'}[key],true);
    if('source' in p) fields+=`<label>來源積木<select data-param="source">${references(['breakout','retest','compare','snapshot'].includes(b.type)?'PriceLevel':'Condition',p.source)}</select></label>`;
    if('trigger' in p) fields+=`<label>鎖定觸發條件<select data-param="trigger">${references('Condition',p.trigger)}</select></label>`;
    if('direction' in p) fields+=paramSelect('direction',p.direction,'方向',[['up','向上 / 陽 K'],['down','向下 / 陰 K']]);
    if('field' in p) fields+=paramSelect('field',p.field,'價格欄位',[['high','區間上緣'],['low','區間下緣'],['value','均線數值']]);
    if('inputs' in p) fields+=p.inputs.map((dep,j)=>`<label>輸入 ${j+1}${b.type==='sequence'?(j===0?' · A 先成立':' · B 後成立'):''}<select data-input="${j}">${references('Condition',dep)}</select></label>`).join('');
    return `<details class="block" data-index="${i}" data-output="${b.output}"><summary><input type="checkbox" data-enabled ${b.enabled?'checked':''} aria-label="啟用 ${esc(b.name)}"><b>${esc(b.name)}</b><span class="type-tag">${esc(b.output)} · ${b.timeframe}m</span><button class="text-button remove" data-remove="${i}" aria-label="刪除 ${esc(b.name)}">×</button></summary><div class="block-body"><div class="field-grid">${paramInput('_name',b.name,'顯示名稱')}<label>週期<select data-tf>${[1,5,15].map(t=>option(t,`${t} 分 K`,b.timeframe)).join('')}</select></label>${fields}</div><small>ID: ${esc(b.id)} · ${esc(kinds[b.type])} · 引用依 ID 驗證，禁止循環依賴</small></div></details>`;
  }).join('');
  $('blocks').querySelectorAll('[data-index]').forEach(el=>{
    const b=strategy.blocks[Number(el.dataset.index)];
    el.querySelector('[data-enabled]').onchange=e=>{b.enabled=e.target.checked;};
    el.querySelector('[data-enabled]').onclick=e=>e.stopPropagation();
    el.querySelector('[data-tf]').onchange=e=>{b.timeframe=Number(e.target.value);};
    el.querySelectorAll('[data-param]').forEach(input=>input.onchange=()=>{const key=input.dataset.param;if(key==='_name')b.name=input.value;else b.params[key]=input.type==='number'?Number(input.value):input.value;});
    el.querySelectorAll('[data-input]').forEach(input=>input.onchange=()=>{b.params.inputs[Number(input.dataset.input)]=input.value;});
    el.querySelector('[data-remove]').onclick=e=>{e.preventDefault();strategy.blocks.splice(Number(el.dataset.index),1);renderBlocks();renderBindings();};
  });
}
function renderBindings() {
  $('bindings').innerHTML=['entries','exits'].flatMap(section=>['long','short'].map(side=>`<label>${side==='long'?'多單':'空單'}${section==='entries'?'進場':'出場'}條件<select data-section="${section}" data-side="${side}">${references('signal',strategy[section][side]||'',true)}</select></label>`)).join('');
  $('bindings').querySelectorAll('select').forEach(el=>el.onchange=()=>{strategy[el.dataset.section][el.dataset.side]=el.value||null;});
  $('structure').innerHTML=references('PriceLevel',strategy.risk.structure_source||'',true);
}
function renderStrategy() {
  $('strategy-id').value=strategy.strategy_id;$('strategy-version').value=strategy.version;$('timeframe').value=strategy.timeframe;
  $('stop').value=strategy.risk.stop_points??'';$('target').value=strategy.risk.target_points??'';
  $('entry-start').value=strategy.limits.entry_start;$('entry-end').value=strategy.limits.entry_end;$('max-trades').value=strategy.limits.max_trades_per_day;
  $('costs').innerHTML=Object.entries(costNames).map(([key,label])=>`<label>${label}<input type="number" min="0" step="any" data-cost="${key}" value="${strategy.costs[key]}"></label>`).join('');
  $('tax-mode').value=strategy.costs.tax_mode;renderBlocks();renderBindings();
}
function collect() {
  strategy.strategy_id=$('strategy-id').value.trim();strategy.version=$('strategy-version').value.trim();strategy.timeframe=Number($('timeframe').value);
  strategy.risk={stop_points:$('stop').value===''?null:Number($('stop').value),target_points:$('target').value===''?null:Number($('target').value),structure_source:$('structure').value||null};
  strategy.limits={entry_start:$('entry-start').value,entry_end:$('entry-end').value,max_trades_per_day:Number($('max-trades').value)};
  $('costs').querySelectorAll('[data-cost]').forEach(el=>{strategy.costs[el.dataset.cost]=Number(el.value);});strategy.costs.tax_mode=$('tax-mode').value;
  return clone(strategy);
}
$('template').onchange=()=>{strategy=clone(presets[Number($('template').value)]);renderStrategy();};
$('timeframe').onchange=()=>{strategy.timeframe=Number($('timeframe').value);strategy.blocks.forEach(b=>{b.timeframe=b.type==='opening_range'?1:strategy.timeframe;});renderBlocks();};
$('structure').onchange=()=>{strategy.risk.structure_source=$('structure').value||null;};
$('add-type').innerHTML=Object.entries(kinds).map(([v,l])=>option(v,l,'candle')).join('');
$('add-block').onclick=()=>{
  const type=$('add-type').value,price=strategy.blocks.find(b=>b.output==='PriceLevel')?.id||'',cond=strategy.blocks.find(b=>b.output==='Condition')?.id||'';
  const defaults={opening_range:{minutes:5},rolling_range:{period:20},swing:{left:2,right:2},ma:{period:20},snapshot:{source:price,trigger:cond},breakout:{source:price,field:'high',direction:'up'},retest:{source:price,field:'high',direction:'up',tolerance:2},compare:{source:price,field:'value',direction:'down'},candle:{direction:'up'},and:{inputs:[cond,cond]},or:{inputs:[cond,cond]},sequence:{inputs:[cond,cond],within:30},event:{source:cond}};
  let n=1;while(strategy.blocks.some(b=>b.id===`${type}-${n}`))n++;
  strategy.blocks.push({id:`${type}-${n}`,type,name:kinds[type],enabled:true,timeframe:strategy.timeframe,params:defaults[type],output:priceKinds.includes(type)?'PriceLevel':type==='event'?'Event':'Condition'});
  renderBlocks();renderBindings();$('blocks').lastElementChild.open=true;
};
$('save-strategy').onclick=()=>guard(async()=>{await api('strategies',{strategy:collect()});message('策略版本已儲存。修改內容後請增加版本號。');});
$('export-strategy').onclick=()=>guard(()=>download('strategy.json',JSON.stringify(collect(),null,2)));
$('strategy-file').onchange=()=>guard(async()=>{const candidate=JSON.parse(await $('strategy-file').files[0].text());await api('strategies',{strategy:candidate});strategy=candidate;renderStrategy();message('已匯入並儲存策略版本。');});
let detectedEncoding='utf-8',csvGeneration=0,preparingCSV=null,importPromise=null;
const rangeEdited={start:false,end:false};
for(const key of ['start','end'])$(key).addEventListener('input',()=>{rangeEdited[key]=true;});
async function prepareCSV(){
  const file=$('csv-file').files[0];if(!file)return;
  const generation=++csvGeneration;rangeEdited.start=false;rangeEdited.end=false;
  $('dataset').value='';$('import').disabled=true;csvText='';$('encoding-field').hidden=false;
  $('mapping').hidden=true;$('mapping').replaceChildren();$('csv-preview').replaceChildren();$('import').hidden=true;$('file-label').textContent=file.name;
  $('csv-status').textContent='正在解碼 CSV…';
  try{
  const buffer=await file.arrayBuffer();if(generation!==csvGeneration)return;
  const decoded=NakedCSV.decode(buffer,$('encoding').value);csvText=decoded.text;detectedEncoding=decoded.encoding;
  const headers=NakedCSV.headers(csvText),guessed=NakedCSV.guess(headers),labels={datetime:'日期／完整時間',time:'獨立時間（選填）',open:'開盤價',high:'最高價',low:'最低價',close:'收盤價',volume:'成交量（選填）'};
  $('file-label').textContent=file.name;$('mapping').hidden=false;$('import').hidden=false;
  $('mapping').innerHTML='<div class="field-grid">'+Object.entries(labels).map(([k,label])=>`<label>${label} · ${k}<select data-map="${k}">${option('',k==='time'?'已包含在日期欄':k==='volume'?'不使用成交量':'請選擇欄位',guessed[k])}${headers.map(h=>option(h,h,guessed[k])).join('')}</select></label>`).join('')+'</div>';
  $('mapping').querySelectorAll('select').forEach(el=>el.onchange=()=>{$('dataset').value='';});
  const examples=[];let count=0;for(const row of NakedCSV.rows(csvText)){if(count++===0)continue;examples.push(row);if(examples.length===3)break;}
  $('csv-preview').innerHTML='<table><caption>解碼後前 3 筆資料</caption><thead><tr>'+headers.map(h=>`<th>${esc(h)}</th>`).join('')+'</tr></thead><tbody>'+examples.map(row=>'<tr>'+row.map(v=>`<td>${esc(v)}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
  const complete=['datetime','open','high','low','close'].every(k=>guessed[k]);
  $('csv-status').textContent=`已使用 ${detectedEncoding.toUpperCase()} 解碼。${complete?'已自動對應中文／英文欄位；可直接執行回測。':'請完成必要欄位對應後再匯入。'}${guessed.time?'日期與時間將自動合併。':''}`;
  $('import').disabled=false;
  }catch(error){if(generation!==csvGeneration)return;csvText='';$('mapping').hidden=true;$('mapping').replaceChildren();$('csv-preview').replaceChildren();$('import').hidden=true;$('import').disabled=true;$('csv-status').textContent=error.message;throw error;}
}
function chooseCSV(){const pending=prepareCSV();preparingCSV=pending;guard(()=>pending);}
$('csv-file').onchange=chooseCSV;$('encoding').onchange=chooseCSV;
async function loadDatasets(selected) { datasets=await api('datasets');$('dataset').innerHTML=option('','選擇匯入資料','')+datasets.map(d=>option(d.id,`${d.name} · ${d.report.rows} 列`,selected||$('dataset').value)).join('');if(selected){$('dataset').value=selected;renderData();} }
function renderData() {const d=datasets.find(d=>d.id===$('dataset').value);if(!d)return;const r=d.report;$('data-report').className='data-report'+(r.errors.length?' error':'');$('data-report').innerHTML=`<strong>${r.errors.length?'資料有錯誤，無法回測':'✓ 必要資料驗證通過'}</strong><br>${fmt(r.rows)} 列 · 夜盤 ${fmt(r.night_rows)} 列 · 缺棒 ${fmt(r.missing_minutes.length)} 根${[...r.errors,...r.warnings].length?'<details><summary>查看檢查報告</summary><ul>'+[...r.errors,...r.warnings].slice(0,100).map(s=>`<li>${esc(s)}</li>`).join('')+'</ul></details>':''}${r.missing_minutes.length?'<details><summary>缺棒時間（前 100 筆）</summary>'+r.missing_minutes.slice(0,100).map(esc).join('<br>')+'</details>':''}`;}
$('dataset').onchange=renderData;
function importDataset(){
  if(importPromise)return importPromise;
  const pending=(async()=>{
  if(preparingCSV)await preparingCSV;
  if(!csvText)throw Error('請先選擇可正確解碼的 CSV。');
  const mapping={};$('mapping').querySelectorAll('select').forEach(el=>{mapping[el.dataset.map]=el.value;});
  for(const key of ['datetime','open','high','low','close'])if(!mapping[key])throw Error('請先對應必要欄位：'+key);
  mapping._source_encoding=detectedEncoding;$('import').disabled=true;
  try{const d=await api('import',{name:$('csv-file').files[0].name,csv:csvText,mapping});await loadDatasets(d.id);if(!rangeEdited.start)$('start').value=d.first?.slice(0,10)||'';if(!rangeEdited.end)$('end').value=d.last?.slice(0,10)||'';message(d.report.errors.length?'資料檢查未通過：'+d.report.errors[0]:'行情已匯入並自動選取，可執行回測。',!!d.report.errors.length);return d;}finally{$('import').disabled=false;}
  })();
  importPromise=pending;pending.finally(()=>{if(importPromise===pending)importPromise=null;}).catch(()=>{});return pending;
}
$('import').onclick=()=>guard(importDataset);
$('sample').onclick=()=>guard(async()=>{
  if(importPromise)await importPromise;csvGeneration++;preparingCSV=null;csvText='';$('csv-file').value='';$('file-label').textContent='人工示範行情（非實際市場）';$('mapping').hidden=true;$('mapping').replaceChildren();$('csv-preview').replaceChildren();$('encoding-field').hidden=true;$('import').hidden=true;$('csv-status').textContent='';rangeEdited.start=false;rangeEdited.end=false;
  let rows=['datetime,open,high,low,close,volume'];
  for(let day=19;day<=21;day++){let last=22000;for(let i=0;i<300;i++){const minute=525+i,h=Math.floor(minute/60),m=minute%60;const close=22000+Math.round(70*Math.sin(i/17)+i*.12+(day-19)*8);rows.push(`2026-10-${day} ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:00,${last},${Math.max(last,close)+5},${Math.min(last,close)-5},${close},${100+i%50}`);last=close;}}
  const d=await api('import',{name:'人工示範行情_非真實市場.csv',csv:rows.join('\n')});await loadDatasets(d.id);$('start').value='2026-10-19';$('end').value='2026-10-21';message('已載入 3 日日盤人工行情，僅供功能示範，並非實際績效。');
});
$('run').onclick=()=>guard(async()=>{if(busy)return;busy=true;$('run').disabled=true;$('run').textContent='回測計算中…';try{if(preparingCSV)await preparingCSV;if(importPromise)await importPromise;if(!$('dataset').value&&csvText){const d=await importDataset();if(d.report.errors.length)throw Error('資料檢查未通過：'+d.report.errors[0]);}if(!$('dataset').value)throw Error('請先選擇 CSV，或載入人工示範行情。');result=await api('run',{dataset_id:$('dataset').value,strategy:collect(),settings:{start:$('start').value||null,end:$('end').value||null}});tradePage=0;renderResult();tab('report');message(window.NAKED_LOCAL_API?(result.storage_mode==='persistent'?'回測完成，結果已儲存於此瀏覽器；可匯出 JSON／CSV。':'回測完成；瀏覽器限制持久儲存，請匯出結果，關閉頁面後本次資料不保留。'):'回測完成，策略版本、設定、訊號與逐筆交易均已存入 SQLite。');}finally{busy=false;$('run').disabled=false;$('run').textContent='執行回測 ↗';}});
function renderResult() {
  $('empty-report').hidden=true;$('result-content').hidden=false;const m=result.metrics;
  $('result-label').textContent=`${result.strategy.name||result.strategy.strategy_id} · v${result.strategy.version} · ${result.strategy.instrument} · ${result.strategy.timeframe} 分 K`;
  const labels={net_pnl:'淨損益',win_rate:'勝率',trade_count:'交易總數',max_drawdown:'最大資金回撤',gross_profit:'總獲利（淨獲利交易）',gross_loss:'總虧損（淨虧損絕對值）',profit_factor:'獲利因子',average_pnl:'平均每筆淨損益',average_win:'平均獲利',average_loss:'平均虧損',long_count:'多單交易次數',short_count:'空單交易次數',longest_loss_streak:'最長連續虧損',total_cost:'手續費＋交易稅',total_slippage_cost:'滑價成本（已反映成交價）',final_equity:'期末模擬資金'};
  $('metrics').innerHTML=Object.entries(labels).map(([key,label])=>`<div class="metric"><div class="label">${label}</div><div class="value ${['net_pnl','average_pnl','average_win','average_loss'].includes(key)?(m[key]<0?'negative':'positive'):''}">${key==='win_rate'?fmt(m[key]*100,1)+'%':fmt(m[key],key==='profit_factor'?2:0)}</div></div>`).join('');
  drawCurve();$('monthly').innerHTML=Object.entries(m.monthly_pnl).map(([month,v])=>`<div class="month"><span>${month}</span><strong class="${v<0?'negative':'positive'}">${fmt(v,2)}</strong></div>`).join('')||'<p class="muted">無交易</p>';
  $('assumptions').innerHTML=[...result.assumptions,...result.warnings,...(result.data_report?.warnings||[])].map(s=>`<li>${esc(s)}</li>`).join('');
  $('signals').textContent=JSON.stringify(result.signals.slice(0,100),null,2);renderTrades();
}
function drawCurve() {
  const original=[{equity:result.strategy.costs.initial_capital,time:result.equity[0].time},...result.equity];
  const stride=Math.max(1,Math.floor(original.length/1500)),points=original.filter((_,i)=>i%stride===0||i===original.length-1);
  let min=Infinity,max=-Infinity;for(const p of original){min=Math.min(min,p.equity);max=Math.max(max,p.equity);}const pad=Math.max((max-min)*.15,1);min-=pad;max+=pad;
  const y=v=>225-(v-min)/(max-min)*205;
  const path=points.map((p,i)=>`${i?'L':'M'}${(80+i/(points.length-1)*900).toFixed(2)},${y(p.equity).toFixed(2)}`).join(' ');
  $('chart').innerHTML=[0,1,2,3].map(i=>{const v=min+(max-min)*i/3;return `<line x1="80" x2="980" y1="${y(v)}" y2="${y(v)}" stroke="#e8ede3"/><text x="0" y="${y(v)+4}">${fmt(v)}</text>`;}).join('')+`<path d="${path} L980,225 L80,225Z" fill="#e9f2e5"/><path d="${path}" fill="none" stroke="#337855" stroke-width="2"/><text x="80" y="252">${esc(original[0].time.slice(0,16))}</text><text x="980" y="252" text-anchor="end">${esc(original.at(-1).time.slice(0,16))}</text>`;
  $('curve-range').textContent=`${fmt(result.strategy.costs.initial_capital)} → ${fmt(result.metrics.final_equity)}`;
}
function renderTrades(){const rows=result.trades.slice(tradePage*100,(tradePage+1)*100);$('trades').innerHTML=rows.map((t,i)=>`<tr><td>${tradePage*100+i+1} / ${t.side==='long'?'多':'空'}<small>1 口</small></td><td>${esc(t.entry_time.slice(0,19).replace('T',' '))}<small>${fmt(t.entry_price,2)}</small></td><td>${esc(t.exit_time.slice(0,19).replace('T',' '))}<small>${fmt(t.exit_price,2)}${t.exit_time_precision==='within_1m_bar'?' · 該分鐘內觸價':''}</small></td><td>${fmt(t.cost,2)}<small>滑價 ${fmt(t.slippage_cost)}</small></td><td class="${t.net_pnl<0?'negative':'positive'}">${fmt(t.net_pnl,2)}</td><td class="reason">${esc(t.entry_reason)}<small>${esc(t.exit_reason)}${t.ambiguous_order?' · ⚑ 同棒順序不確定，停損優先':''}</small></td></tr>`).join('')||'<tr><td colspan="6">此設定未產生交易，請檢查資料、暖機根數與進場條件。</td></tr>';$('trade-page').textContent=`${tradePage+1} / ${Math.max(1,Math.ceil(result.trades.length/100))} 頁 · ${result.trades.length} 筆`;$('prev-trades').disabled=tradePage===0;$('next-trades').disabled=(tradePage+1)*100>=result.trades.length;}
$('prev-trades').onclick=()=>{if(tradePage>0){tradePage--;renderTrades();}};$('next-trades').onclick=()=>{if((tradePage+1)*100<result.trades.length){tradePage++;renderTrades();}};
$('export-result').onclick=()=>{if(result)download('backtest-result.json',JSON.stringify(result,null,2));else message('請先執行回測。',true);};
$('export-trades').onclick=()=>{if(!result)return;const keys=['side','quantity','entry_time','entry_price','exit_time','exit_price','cost','slippage_cost','gross_pnl','net_pnl','entry_reason','exit_reason','ambiguous_order','exit_time_precision','strategy_version','signal_id'];const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';download('trades.csv','\uFEFF'+[keys.join(','),...result.trades.map(t=>keys.map(k=>quote(t[k])).join(','))].join('\r\n'),'text/csv;charset=utf-8');};
async function loadHistory(){const runs=await api('runs');$('history-rows').innerHTML=runs.map(r=>`<tr><td>${esc(r.strategy_id)}<small>v${esc(r.strategy_version)}</small></td><td>${esc(datasets.find(d=>d.id===r.dataset_id)?.name||r.dataset_id.slice(0,10))}<small>${esc(r.settings.start||'全部')} — ${esc(r.settings.end||'全部')}</small></td><td>${r.metrics.trade_count}</td><td>${fmt(r.metrics.win_rate*100,1)}%</td><td class="${r.metrics.net_pnl<0?'negative':'positive'}">${fmt(r.metrics.net_pnl,2)}</td><td>${fmt(r.metrics.profit_factor,2)}</td><td>${fmt(r.metrics.max_drawdown,2)}</td><td><button class="text-button" data-run-id="${esc(r.id)}">檢視 ↗</button></td></tr>`).join('')||'<tr><td colspan="8">尚無回測紀錄。</td></tr>';$('history-rows').querySelectorAll('[data-run-id]').forEach(el=>el.onclick=()=>guard(async()=>{result=await api('runs/'+el.dataset.runId);tradePage=0;renderResult();tab('report');}));}
$('refresh-history').onclick=()=>guard(loadHistory);
guard(async()=>{const [t,s]=await Promise.all([api('templates'),api('strategies')]);presets=[...t,...s];$('template').innerHTML=presets.map((p,i)=>option(i,`${i<t.length?'範例':'已儲存'} · ${p.name||p.strategy_id} v${p.version}`,0)).join('');strategy=clone(presets[0]);renderStrategy();await loadDatasets();});
