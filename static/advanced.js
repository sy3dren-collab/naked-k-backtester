'use strict';
// Python-backed catalog editor. The archived standalone v1.2 uses its own frozen UI.
let blockCatalog={},selectedBlock=null,draggedBlock=null;
const categoryNames={price:'價格參考',entry:'進場訊號',filter:'進場過濾',stop:'保護停損',target:'觸價停利',exit:'收盤出場',logic:'邏輯控制'};
const originalBlocks=renderBlocks,originalStrategy=renderStrategy,originalCollect=collect,originalBindings=renderBindings,originalResult=renderResult,originalApi=api;
function upgradeLegacy(s){
  if(s.schema_version===2)return s;
  const copy=clone(s);copy.schema_version=2;copy.version=String(copy.version)+'.v2';
  copy.direction='both';copy.quantity=1;
  copy.blocks.forEach(b=>{if(b.type==='retest')b.type='touch_reference';});
  copy.limits.force_close='13:45';copy.limits.daily_max_loss=0;
  for(const side of ['long','short'])copy.exits[side]=Array.isArray(copy.exits[side])?copy.exits[side]:copy.exits[side]?[copy.exits[side]]:[];
  return copy;
}
api=async function(path,body){
  if(path==='run'&&body?.strategy?.schema_version===2)body={...body,auto_version:true};
  const data=await originalApi(path,body);
  if(path==='run'&&data.strategy?.strategy_id===strategy?.strategy_id){strategy.version=data.strategy.version;$('strategy-version').value=strategy.version;}
  return data;
};
function definition(kind){return blockCatalog[kind];}
function refOptions(type,selected,exclude,accepted){
  const eligible=strategy.blocks.filter(b=>b.id!==exclude&&(!accepted||accepted.includes(b.type))&&(type==='price_ref'?definition(b.type)?.category==='price':['Condition','Event'].includes(b.output)));
  return option('','請選擇',selected)+eligible.map(b=>option(b.id,`${b.name} · ${b.id}`,selected)).join('');
}
function newBlock(kind){
  const d=definition(kind);if(!d)return;
  let i=1;while(strategy.blocks.some(b=>b.id===kind+'-'+i))i++;
  const params={};for(const [key,spec]of Object.entries(d.params)){params[key]=clone(spec.default);if(spec.type==='price_ref')params[key]=strategy.blocks.find(b=>definition(b.type)?.category==='price'&&(!spec.accepts||spec.accepts.includes(b.type)))?.id||'';if(spec.type==='condition_ref')params[key]=strategy.blocks.find(b=>['Condition','Event'].includes(b.output))?.id||'';}
  strategy.blocks.push({id:kind+'-'+i,type:kind,name:d.name,enabled:true,timeframe:d.category==='price'&&kind==='opening_range'?1:strategy.timeframe,params,output:d.output});
  selectedBlock=kind+'-'+i;renderBlocks();renderBindings();renderSummary();
}
function renderToolbox(){
  $('toolbox').innerHTML='<label>積木工具箱<input id="tool-search" placeholder="搜尋名稱或 P01、E01…"></label><div id="tool-list"></div>';
  const fill=()=>{const term=$('tool-search').value.toLowerCase();$('tool-list').innerHTML=Object.entries(categoryNames).map(([category,label])=>{
    const choices=Object.values(blockCatalog).filter(d=>d.category===category&&(d.name+d.code+d.type).toLowerCase().includes(term));
    return choices.length?`<details open><summary>${label}</summary>${choices.map(d=>`<button class="tool-item" draggable="true" data-kind="${d.type}"><small>${d.code}</small>${esc(d.name)}</button>`).join('')}</details>`:'';
  }).join('');$('tool-list').querySelectorAll('[data-kind]').forEach(el=>{el.onclick=()=>newBlock(el.dataset.kind);el.ondragstart=e=>{e.dataTransfer.setData('application/x-naked-kind',el.dataset.kind);e.dataTransfer.effectAllowed='copy';};});};
  $('tool-search').oninput=fill;fill();
}
renderBlocks=function(){
  if(!Object.keys(blockCatalog).length){originalBlocks();return;}
  if(!strategy.blocks.some(b=>b.id===selectedBlock))selectedBlock=strategy.blocks[0]?.id;
  $('blocks').innerHTML=strategy.blocks.map(b=>`<article class="graph-block ${b.id===selectedBlock?'selected':''}" draggable="true" data-id="${esc(b.id)}" data-category="${definition(b.type)?.category||'entry'}"><div class="graph-title"><span>⠿</span><input type="checkbox" data-enable ${b.enabled?'checked':''} aria-label="啟用 ${esc(b.name)}"><b>${esc(b.name)}</b><small>${esc(definition(b.type)?.code||b.type)}</small></div><div class="graph-meta">${esc(b.id)} · ${esc(b.output)} · ${b.timeframe} 分 K</div><div class="graph-actions"><button class="text-button" data-copy>複製</button><button class="text-button" data-up>↑</button><button class="text-button" data-down>↓</button><button class="text-button" data-remove>刪除</button></div></article>`).join('')||'<p class="hint">將左側積木拖曳至此，或點擊工具箱新增。</p>';
  $('blocks').querySelectorAll('[data-id]').forEach(el=>{
    const b=strategy.blocks.find(b=>b.id===el.dataset.id);
    el.onclick=e=>{if(e.target.closest('button,input'))return;selectedBlock=b.id;renderBlocks();};
    el.querySelector('[data-enable]').onchange=e=>{b.enabled=e.target.checked;renderSummary();};
    el.querySelector('[data-copy]').onclick=()=>{let i=1,id;do{id=b.id+'-copy'+i++;}while(strategy.blocks.some(x=>x.id===id));strategy.blocks.splice(strategy.blocks.indexOf(b)+1,0,{...clone(b),id,name:b.name+' 副本'});selectedBlock=id;renderBlocks();renderBindings();};
    el.querySelector('[data-remove]').onclick=()=>{strategy.blocks.splice(strategy.blocks.indexOf(b),1);renderBlocks();renderBindings();renderSummary();};
    const move=delta=>{const i=strategy.blocks.indexOf(b),j=i+delta;if(j>=0&&j<strategy.blocks.length){[strategy.blocks[i],strategy.blocks[j]]=[strategy.blocks[j],strategy.blocks[i]];renderBlocks();}};
    el.querySelector('[data-up]').onclick=()=>move(-1);el.querySelector('[data-down]').onclick=()=>move(1);
    el.ondragstart=e=>{draggedBlock=b.id;e.dataTransfer.setData('application/x-naked-block',b.id);e.dataTransfer.effectAllowed='move';};
    el.ondragover=e=>e.preventDefault();el.ondrop=e=>{e.preventDefault();e.stopPropagation();const kind=e.dataTransfer.getData('application/x-naked-kind');if(kind){newBlock(kind);return;}const id=e.dataTransfer.getData('application/x-naked-block');const from=strategy.blocks.findIndex(x=>x.id===id),to=strategy.blocks.indexOf(b);if(from>=0&&from!==to){const [item]=strategy.blocks.splice(from,1);strategy.blocks.splice(to,0,item);renderBlocks();}};
  });
  $('blocks').ondragover=e=>e.preventDefault();$('blocks').ondrop=e=>{e.preventDefault();const kind=e.dataTransfer.getData('application/x-naked-kind');if(kind)newBlock(kind);};
  renderInspector();renderSummary();
};
function renderInspector(){
  const block=strategy.blocks.find(b=>b.id===selectedBlock);if(!block){$('inspector').textContent='選擇積木以編輯參數。';return;}
  const d=definition(block.type);if(!d){$('inspector').textContent='此積木無法辨識，請檢查 JSON。';return;}
  let html=`<h3>${esc(d.code)} ${esc(d.name)}</h3><label>顯示名稱<input data-name value="${esc(block.name)}"></label><label>週期<select data-tf ${['stop','target'].includes(d.category)?'disabled':''}>${[1,5,15,30].map(tf=>option(tf,tf+' 分 K',block.timeframe)).join('')}</select></label>`;
  for(const [key,spec]of Object.entries(d.params)){
    const value=block.params[key]??spec.default;
    if(spec.type==='condition_refs'){
      html+=`<div class="sequence-inputs"><label>${esc(spec.label)}</label>${value.map((id,i)=>`<div><span>${i+1}</span><select data-list="${key}" data-index="${i}">${refOptions('condition_ref',id,block.id)}</select><button class="text-button" data-drop-input="${key}:${i}">×</button></div>`).join('')}<button class="text-button" data-add-input="${key}">＋ 加入下一個條件</button></div>`;
    }else if(spec.type==='boolean')html+=`<label><input type="checkbox" data-param="${key}" ${value?'checked':''}>${esc(spec.label)}</label>`;
    else if(spec.type==='price_ref'||spec.type==='condition_ref')html+=`<label>${esc(spec.label)}<select data-param="${key}">${refOptions(spec.type,value,block.id,spec.accepts)}</select></label>`;
    else if(spec.type==='select')html+=`<label>${esc(spec.label)}<select data-param="${key}">${spec.choices.map(v=>option(v,({up:'向上／多方',down:'向下／空方',both:'雙向',wick:'影線',body:'實體',close:'收盤',touch:'觸價',cross:'穿越',high:'最高',low:'最低',mid:'中線',strict:'不接受同價',latest:'同價取最後',earliest:'同價取最早',swing:'波段',box:'箱體',zone:'區域',line:'水平線',support:'支撐',resistance:'壓力',none:'無',color:'紅／黑 K',break_candle:'突破確認 K',hl_lh:'HL／LH'}[v]||v),value)).join('')}</select></label>`;
    else html+=`<label>${esc(spec.label)}<input data-param="${key}" type="${['number','integer'].includes(spec.type)?'number':spec.type==='time'?'time':'text'}" ${spec.type==='number'?'step="any"':''} ${spec.min!=null?'min="'+spec.min+'"':''} ${spec.max!=null?'max="'+spec.max+'"':''} value="${esc(Array.isArray(value)?value.join(','):value)}">${['date_list','integer_list'].includes(spec.type)?'<small>以逗號分隔</small>':''}</label>`;
  }
  if(!['price','stop','target'].includes(d.category))html+=`<label>確認訊號有效 K 棒數<input data-valid type="number" min="1" value="${block.params.valid_bars||1}"></label>`;
  $('inspector').innerHTML=html;
  $('inspector').querySelector('[data-name]').onchange=e=>{block.name=e.target.value;renderBlocks();renderBindings();};
  $('inspector').querySelector('[data-tf]').onchange=e=>{block.timeframe=Number(e.target.value);renderBlocks();};
  $('inspector').querySelectorAll('[data-param]').forEach(el=>el.onchange=()=>{const key=el.dataset.param,spec=d.params[key];let value=el.type==='checkbox'?el.checked:['number','integer'].includes(spec.type)?Number(el.value):['date_list','integer_list'].includes(spec.type)?el.value.split(',').map(x=>x.trim()).filter(Boolean).map(x=>spec.type==='integer_list'?Number(x):x):el.value;block.params[key]=value;renderSummary();});
  $('inspector').querySelectorAll('[data-list]').forEach(el=>el.onchange=()=>{block.params[el.dataset.list]??=clone(d.params[el.dataset.list].default);block.params[el.dataset.list][Number(el.dataset.index)]=el.value;renderSummary();});
  $('inspector').querySelectorAll('[data-add-input]').forEach(el=>el.onclick=()=>{block.params[el.dataset.addInput]??=[];block.params[el.dataset.addInput].push('');renderInspector();});
  $('inspector').querySelectorAll('[data-drop-input]').forEach(el=>el.onclick=()=>{const [key,index]=el.dataset.dropInput.split(':');block.params[key].splice(Number(index),1);renderInspector();renderSummary();});
  const valid=$('inspector').querySelector('[data-valid]');if(valid)valid.onchange=()=>{block.params.valid_bars=Number(valid.value);};
}
function multi(id,label,ids,category){return `<label>${label}<select id="${id}" multiple size="3">${strategy.blocks.filter(b=>definition(b.type)?.category===category).map(b=>`<option value="${esc(b.id)}"${ids.includes(b.id)?' selected':''}>${esc(b.name)} · ${esc(b.id)}</option>`).join('')}</select><small>可選多個；停損選最緊、停利選最近的有效價</small></label>`;}
renderBindings=function(){
  if(!Object.keys(blockCatalog).length){originalBindings();return;}
  $('bindings').innerHTML=['entries','exits'].flatMap(section=>['long','short'].map(side=>{
    const ids=Array.isArray(strategy[section][side])?strategy[section][side]:strategy[section][side]?[strategy[section][side]]:[];
    return `<label>${side==='long'?'多單':'空單'}${section==='entries'?'進場':'出場（任一成立）'}<select data-section="${section}" data-side="${side}" ${section==='exits'?'multiple size="3"':''}>${section==='entries'?option('','停用',ids[0]||''):''}${strategy.blocks.filter(b=>['Condition','Event'].includes(b.output)).map(b=>`<option value="${esc(b.id)}"${ids.includes(b.id)?' selected':''}>${esc(b.name)} · ${esc(b.id)}</option>`).join('')}</select></label>`;
  })).join('');
  $('bindings').querySelectorAll('select').forEach(el=>el.onchange=()=>{strategy[el.dataset.section][el.dataset.side]=el.multiple?[...el.selectedOptions].map(o=>o.value):el.value||null;renderSummary();});
  $('structure').innerHTML=option('','停用',strategy.risk.structure_source||'')+strategy.blocks.filter(b=>definition(b.type)?.category==='price').map(b=>option(b.id,b.name,strategy.risk.structure_source)).join('');
  $('risk-bindings').innerHTML='<h3>多空獨立的停損／停利積木</h3><div class="field-grid">'+['long','short'].flatMap(side=>['stop','target'].map(category=>multi(`risk-${side}-${category}`,`${side==='long'?'多單':'空單'}${category==='stop'?'停損':'停利'}`,(strategy.risk[side]||{})[category+'_blocks']||[],category))).join('')+'</div>';
}
function renderSettings(){
  $('execution-settings').innerHTML=`<div class="field-grid three"><label>商品<select id="instrument">${[['TX','大台 TX · 預設每點 200'],['MTX','小台 MTX · 預設每點 50'],['TMF','微台 TMF · 預設每點 10']].map(([v,l])=>option(v,l,strategy.instrument)).join('')}</select></label><label>交易方向<select id="trade-direction">${[['both','多空雙向（單一持倉）'],['long','僅做多'],['short','僅做空']].map(([v,l])=>option(v,l,strategy.direction||'both')).join('')}</select></label><label>單筆口數<input id="quantity" type="number" min="1" max="100" value="${strategy.quantity||1}"></label></div><div class="field-grid"><label>成交方式<select id="entry-mode">${option('next_open','收盤確認，下一根開盤',strategy.execution.entry)}${option('touch','確認後以 1 分 K 模擬觸價',strategy.execution.entry)}</select></label><label>觸價委託價格來源<select id="execution-source">${refOptions('price_ref',strategy.execution.source||'')}</select></label></div>`;
  $('execution-settings').insertAdjacentHTML('beforeend',`<div class="field-grid"><label>觸價委託價位<select id="execution-field">${[['auto','多單取高、空單取低'],['high','參考區間上緣'],['low','參考區間下緣'],['mid','參考區間中線'],['value','價格積木選定值']].map(([v,l])=>option(v,l,strategy.execution.field||'auto')).join('')}</select></label><label>觸價委託有效根數（主要週期）<input id="execution-valid" type="number" min="1" value="${strategy.execution.valid_bars||3}"></label></div>`);
  $('instrument').onchange=()=>{strategy.instrument=$('instrument').value;const value={TX:200,MTX:50,TMF:10}[strategy.instrument];strategy.costs.point_value=value;document.querySelector('[data-cost="point_value"]').value=value;renderSummary();};
  const limitSpecs={force_close:['指定強制平倉','time','13:45'],daily_max_loss:['每日已實現虧損上限（0=不限）','number',0],cooldown_bars:['停損後冷卻根數','number',0],max_stop_distance:['最大停損距離（0=不限）','number',0],min_space:['最小停利空間（0=不限）','number',0],excluded_weekdays:['排除星期（週一=0，逗號分隔）','text',[]],excluded_dates:['排除日期（逗號分隔）','text',[]]};
  $('advanced-limits').innerHTML=Object.entries(limitSpecs).map(([key,[label,type,defaultValue]])=>`<label>${label}<input data-limit="${key}" type="${type}" ${type==='number'?'min="0" step="any"':''} value="${esc(Array.isArray(strategy.limits[key])?strategy.limits[key].join(','):strategy.limits[key]??defaultValue)}"></label>`).join('');
}
renderStrategy=function(){strategy=upgradeLegacy(strategy);originalStrategy();if(Object.keys(blockCatalog).length){renderSettings();renderToolbox();renderBindings();renderSummary();}};
collect=function(){
  const previousRisk=clone(strategy.risk),previousLimits=clone(strategy.limits);const s=originalCollect();
  s.risk={...previousRisk,...s.risk};s.limits={...previousLimits,...s.limits};s.schema_version=2;
  if($('instrument')){s.instrument=$('instrument').value;s.direction=$('trade-direction').value;s.quantity=Number($('quantity').value);s.execution={...s.execution,entry:$('entry-mode').value,valid_bars:Number($('execution-valid').value),collision:'stop_first'};if(s.execution.entry==='touch'){s.execution.source=$('execution-source').value;const field=$('execution-field').value;if(field==='auto')delete s.execution.field;else s.execution.field=field;}else{delete s.execution.source;delete s.execution.field;}}
  for(const side of ['long','short'])for(const category of ['stop','target']){const el=$(`risk-${side}-${category}`);if(el){s.risk[side]??={};s.risk[side][category+'_blocks']=[...el.selectedOptions].map(o=>o.value);}}
  $('advanced-limits').querySelectorAll('[data-limit]').forEach(el=>{s.limits[el.dataset.limit]=el.dataset.limit==='excluded_dates'?el.value.split(',').map(x=>x.trim()).filter(Boolean):el.dataset.limit==='excluded_weekdays'?el.value.split(',').map(x=>x.trim()).filter(Boolean).map(Number):el.type==='number'?Number(el.value):el.value;});
  strategy=s;renderSummary();return clone(s);
};
function renderSummary(){
  if(!strategy)return;
  function expression(id,seen=new Set()){
    if(!id)return '停用';if(Array.isArray(id))return id.map(x=>expression(x,new Set(seen))).join(' OR ')||'無';
    if(seen.has(id))return '[循環]';seen.add(id);const b=strategy.blocks.find(b=>b.id===id);if(!b)return '[缺少 '+id+']';const p=b.params;
    if(['and','or','sequence'].includes(b.type))return '('+(p.inputs||[]).map(x=>expression(x,new Set(seen))).join(b.type==='sequence'?' → ':' '+b.type.toUpperCase()+' ')+')';
    if(b.type==='not')return 'NOT '+expression(p.source,seen);
    return b.name+(p.source?'〔'+p.source+'〕':'')+(b.enabled?'':'（停用）');
  }
  $('logic-summary').innerHTML='<strong>策略邏輯摘要</strong>'+['long','short'].map(side=>{const risk=strategy.risk[side]||{};return `<p>${side==='long'?'多單':'空單'}：進場 ${esc(expression(strategy.entries[side]))}<br>出場 ${esc(expression(strategy.exits[side]))}<br>停損 ${esc((risk.stop_blocks||[]).map(id=>strategy.blocks.find(b=>b.id===id)?.name||id).join('、')||'未選擇')}；停利 ${esc((risk.target_blocks||[]).map(id=>strategy.blocks.find(b=>b.id===id)?.name||id).join('、')||'未選擇')}</p>`;}).join('')+`<p>${esc(strategy.instrument)} · ${strategy.quantity||1} 口 · 進場 ${esc(strategy.limits.entry_start)}–${esc(strategy.limits.entry_end)} · 強平 ${esc(strategy.limits.force_close||'13:45')} · 每日最多 ${strategy.limits.max_trades_per_day} 筆</p><details><summary>全部啟用積木與參數</summary><ol>${strategy.blocks.filter(b=>b.enabled).map(b=>`<li>${esc(b.name)}（${b.timeframe} 分 K）：${Object.entries(b.params).map(([key,value])=>esc(definition(b.type)?.params[key]?.label||key)+'='+esc(Array.isArray(value)?value.join(' → '):value)).join('；')}</li>`).join('')}</ol></details><small>價格先經條件判斷；收盤訊號次棒成交，觸價保護停損優先。同時只保留單一持倉。</small>`;
}
document.addEventListener('change',event=>{if(strategy&&event.target.closest('#costs,#execution-settings,#advanced-limits,#risk-bindings'))collect();});
async function refreshLibrary(){const [t,s]=await Promise.all([api('templates'),api('strategies')]);presets=[...t,...s];$('template').innerHTML=presets.map((p,i)=>option(i,`${i<t.length?'驗收範例':'已儲存'} · ${p.name||p.strategy_id} v${p.version}`,0)).join('');}
$('refresh-library').onclick=()=>guard(async()=>{await refreshLibrary();message('策略庫已更新；目前編輯內容保留。');});
$('clone-strategy').onclick=()=>guard(async()=>{const current=collect(),id=current.strategy_id+'-copy-'+Date.now().toString(36);strategy=await api('strategies/clone',{strategy:current,strategy_id:id});renderStrategy();await refreshLibrary();message('已複製並儲存為獨立策略。');});
$('delete-strategy').onclick=()=>guard(async()=>{const current=collect(),response=await fetch('/api/strategies/'+encodeURIComponent(current.strategy_id)+'/'+encodeURIComponent(current.version),{method:'DELETE'}),data=await response.json();if(!response.ok)throw Error(data.error);await refreshLibrary();message('已從策略庫刪除；歷史回測與版本紀錄保留。');});
$('validate-strategy').onclick=()=>guard(async()=>{await api('validate',{strategy:collect()});message('積木參數、輸出型態、引用及循環檢查通過。');});
$('save-strategy').onclick=()=>guard(async()=>{strategy=await api('strategies/version',{strategy:collect()});renderStrategy();await refreshLibrary();message('已儲存策略 v'+strategy.version+'；變更內容會建立新版本。');});
$('add-block').onclick=()=>newBlock($('add-type').value);
renderResult=function(){originalResult();const labels={long_win_rate:'多單勝率',short_win_rate:'空單勝率',average_risk_reward:'平均實現 R',longest_win_streak:'最長連勝',max_consecutive_loss:'最大連續虧損金額'};for(const [key,label]of Object.entries(labels))if(key in result.metrics){const value=result.metrics[key];$('metrics').insertAdjacentHTML('beforeend',`<div class="metric"><div class="label">${label}</div><div class="value">${key.endsWith('win_rate')?fmt(value*100,1)+'%':fmt(value,key==='average_risk_reward'?2:0)}</div></div>`);}const daily=result.metrics.daily_pnl||{};$('monthly').innerHTML+='<details><summary>每日損益</summary>'+Object.entries(daily).map(([date,pnl])=>`<div class="month"><span>${date}</span><strong>${fmt(pnl,2)}</strong></div>`).join('')+'</details><details><summary>交易時段績效</summary>'+Object.entries(result.metrics.time_periods||{}).map(([time,m])=>`<div class="month"><span>${time} · ${m.trade_count} 筆</span><strong>${fmt(m.net_pnl,2)}</strong></div>`).join('')+'</details>';if(window.setupTradeReview)window.setupTradeReview();};
guard(async()=>{const list=await api('catalog');blockCatalog=Object.fromEntries(list.map(d=>[d.type,d]));$('add-type').innerHTML=list.map(d=>option(d.type,d.code+' '+d.name,'candle')).join('');if(strategy)renderStrategy();});
