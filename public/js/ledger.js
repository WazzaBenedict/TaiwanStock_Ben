/* 帳本（v14.2）：真實成交 → 扣元大成本的淨損益、對照同期 0050、紀律檢查、每週結算。
   成交紀錄存在 Firestore users/{uid}/trade_journal/ledger_tw，計算在後端 /api/ledger/compute。 */
var LEDGER=(function(){
  var fills=[],result=null,loadedUid=null,busy=false,chart=null,pending=null,again=false;
  function $(id){return document.getElementById(id);}
  function e(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
  function money(v,sign){if(v==null||isNaN(v))return '<span class="lg-na">—</span>';var n=Math.round(v),cls=n>0?"up":(n<0?"down":"");return '<span class="'+cls+'">'+(sign!==false&&n>0?"+":"")+n.toLocaleString("en-US")+'</span>';}
  function uid(){return (typeof currentUser!=="undefined"&&currentUser)?currentUser.uid:null;}
  function ref(){var u=uid();return (typeof db!=="undefined"&&db&&u)?db.collection("users").doc(u).collection("trade_journal").doc("ledger_tw"):null;}
  function lsKey(){return "tw_ledger_fills_"+(uid()||"guest");}
  function status(t,cls){var el=$("lgStatus");if(el){el.textContent=t||"";el.className="lg-status "+(cls||"");}}
  function today(){return new Date(Date.now()+8*36e5).toISOString().slice(0,10);}

  async function load(){
    var r=ref(),local=[];
    try{local=JSON.parse(localStorage.getItem(lsKey())||"[]");}catch(x){}
    if(r){
      try{var s=await r.get();fills=(s.exists&&Array.isArray(s.data().fills))?s.data().fills:[];
        if(!s.exists&&local.length){fills=local;}
      }catch(x){fills=local;status("雲端讀取失敗，先顯示這台裝置上的紀錄。","warn");}
    }else fills=local;
    loadedUid=uid();
  }
  async function save(){
    try{localStorage.setItem(lsKey(),JSON.stringify(fills));}catch(x){}
    var r=ref();if(!r){status("尚未登入，紀錄只存在這台裝置。","warn");return false;}
    try{await r.set({fills:fills,updated_at:new Date().toISOString()});return true;}
    catch(x){status("雲端儲存失敗（"+(x.code||x.message)+"），紀錄暫存在這台裝置。","warn");return false;}
  }
  // 用使用者在「當沖風控」存的上限檢查紀律（沒存過就用預設 50,000／1,000／10,000）
  function userRules(){try{var c=JSON.parse(localStorage.getItem("tw_dt_risk_cfg")||"{}")||{},r={};
    if(Number(c.maxN)>0)r.max_notional=Number(c.maxN);if(Number(c.day)>0)r.daily_stop=Number(c.day);
    if(Number(c.total)>0)r.total_stop=Number(c.total)===2500?10000:Number(c.total);return r;}catch(e){return {};}}
  async function compute(){
    if(busy){again=true;return;}busy=true;again=false;
    renderFills();
    if(!fills.length){result=null;render();status("還沒有成交紀錄。先在下面新增一筆，或匯入對帳單。");busy=false;return;}
    status("計算中。主機若在休眠，喚醒大約需要一分鐘。");
    try{
      var res=await apiFetch(API+"/api/ledger/compute",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({fills:fills,fee_discount:(typeof feeDisc==="function"?feeDisc():null),rules:userRules()})},100000);
      if(!res.ok)throw new Error("HTTP "+res.status);
      result=await res.json();render();
      var d=result.data||{};
      status("已計算 "+result.fees.fills+" 筆成交。0050 資料到 "+(d.last_0050_date||"（抓不到）")+"。");
    }catch(x){status("計算失敗："+x.message,"bad");}
    busy=false;if(again){again=false;compute();}
  }

  function box(label,big,sub){return '<div class="lg-box"><div class="lg-label">'+label+'</div><div class="lg-big">'+big+'</div><div class="lg-sub">'+(sub||"")+'</div></div>';}
  function aggSub(a){return a.n?(a.n+" 筆，勝率 "+a.win_rate_pct+"%，成本 "+Math.round(a.cost).toLocaleString("en-US")+" 元"):"尚無交易";}
  function render(){
    var S=$("lgSummary"),W=$("lgWeekly"),V=$("lgViol"),P=$("lgPos"),T=$("lgTrades"),N=$("lgNotes"),V2=$("lgVerdict");
    if(!S)return;
    if(!result){S.innerHTML="";W.innerHTML=P.innerHTML=T.innerHTML=V.innerHTML='<div class="lg-empty">尚無資料</div>';N.innerHTML="";V2.innerHTML="";drawChart([]);return;}
    var s=result.summary,a=s.all;
    var verdict="";
    if(a.n&&a.vs_0050!=null){
      verdict=a.vs_0050>=0?"到目前為止，你的實際交易比同期放在 0050 多賺 "+Math.round(a.vs_0050).toLocaleString("en-US")+" 元。"
        :"到目前為止，你的實際交易比同期放在 0050 少 "+Math.round(-a.vs_0050).toLocaleString("en-US")+" 元。";
      if(a.shadow_coverage<a.n)verdict+="有 "+(a.n-a.shadow_coverage)+" 筆缺 0050 資料，沒有列入這個比較。";
      if(a.n<30)verdict+="樣本只有 "+a.n+" 筆，還不足以下結論。";
    }
    V2.innerHTML=e(verdict);
    S.innerHTML=box("已實現淨損益",money(a.net),"毛利 "+Math.round(a.gross).toLocaleString("en-US")+"，成本 "+Math.round(a.cost).toLocaleString("en-US"))
      +box("同期放 0050",money(a.shadow_0050),a.shadow_coverage<a.n?("有 "+(a.n-a.shadow_coverage)+" 筆缺 0050 資料未計入"):"影子帳，未扣 0050 買賣成本")
      +box("和 0050 的差距",money(a.vs_0050),a.vs_0050==null?"":(a.vs_0050>=0?"贏過 0050":"輸給 0050"))
      +box("當沖",money(s.daytrade.net),aggSub(s.daytrade))
      +box("隔日以上",money(s.swing.net),aggSub(s.swing))
      +box("未平倉",money(s.unrealized_net),s.open_positions+" 筆，已扣預估出場成本")
      +box("違反紀律",'<span'+(s.violations?' style="color:var(--yellow)"':'')+'>'+s.violations+' 次</span>',s.violating_trades.n?("這些交易合計 "+Math.round(s.violating_trades.net).toLocaleString("en-US")+" 元"):"")
      +(s.plan_slip?box("偏離計畫價",money(-s.plan_slip),"買得比計畫價貴的金額（負數代表多付）"):"");
    drawChart(result.equity||[]);

    var wk=result.weekly||[],R=result.rules;
    W.innerHTML=wk.length?'<div class="lg-scroll"><table class="lg-table"><tr><th>週</th><th>當沖淨損益</th><th>應轉入 0050</th><th>緩衝金</th></tr>'
      +wk.slice().reverse().map(function(w){return '<tr><td>'+e(w.week)+'</td><td>'+money(w.daytrade_net)+'</td><td>'+(w.to_0050?Math.round(w.to_0050).toLocaleString("en-US"):"0")+'</td><td>'+Math.round(w.cushion_after).toLocaleString("en-US")+'</td></tr>';}).join("")
      +'</table></div><div class="lg-sub">規則：每週當沖淨利的 '+R.profit_to_0050_pct+'% 轉入 0050，其餘留作緩衝金；緩衝金超過 '+R.cushion_cap.toLocaleString("en-US")+' 元的部分也轉入 0050；虧損週由緩衝金吸收。</div>'
      :'<div class="lg-empty">還沒有當沖交易</div>';

    var vs=result.violations||[];
    V.innerHTML=(vs.length?'<ul class="lg-list">'+vs.slice().reverse().map(function(v){return '<li><span class="lg-tag bad">'+e(v.date.slice(5))+' '+e(v.code)+'</span>'+e(v.text)+'</li>';}).join("")+'</ul>'
      :'<div class="lg-ok">沒有違反紀律的紀錄。</div>')
      +'<div class="lg-sub">檢查項目：每筆買進上限 '+R.max_notional.toLocaleString("en-US")+' 元、當日當沖虧損達 '+R.daily_stop.toLocaleString("en-US")+' 元後不再進場、當沖累計虧損達 '+R.total_stop.toLocaleString("en-US")+' 元後不再進場、'+e(R.no_entry_after)+' 後不進場（有填時間才檢查）、不先賣後買。</div>';

    var ps=result.positions||[];
    P.innerHTML=ps.length?'<div class="lg-scroll"><table class="lg-table"><tr><th>代號</th><th>買進日</th><th>股數</th><th>買價</th><th>現價</th><th>未實現淨損益</th><th>同期 0050</th></tr>'
      +ps.map(function(p){return '<tr><td>'+e(p.code)+'</td><td>'+e(p.open_date.slice(5))+'</td><td>'+p.shares.toLocaleString("en-US")+'</td><td>'+p.buy_price+'</td><td>'+(p.last_price==null?"—":p.last_price)+'</td><td>'+money(p.unrealized_net)+'</td><td>'+money(p.shadow_0050)+'</td></tr>';}).join("")+'</table></div>'
      :'<div class="lg-empty">目前沒有未平倉部位</div>';

    var ts=(result.trades||[]).slice().reverse();
    T.innerHTML=ts.length?'<div class="lg-scroll"><table class="lg-table"><tr><th>代號</th><th>出場日</th><th>類型</th><th>股數</th><th>買</th><th>賣</th><th>成本</th><th>淨損益</th><th>同期 0050</th><th>差距</th></tr>'
      +ts.slice(0,200).map(function(t){return '<tr><td>'+e(t.code)+'</td><td>'+e(t.close_date.slice(5))+'</td><td>'+(t.daytrade?"當沖":"持有 "+t.hold_days+" 天")+'</td><td>'+t.shares.toLocaleString("en-US")+'</td><td>'+t.buy_price+'</td><td>'+t.sell_price+'</td><td>'+Math.round(t.cost)+'</td><td>'+money(t.net)+'</td><td>'+money(t.shadow_0050)+'</td><td>'+money(t.vs_0050)+'</td></tr>';}).join("")
      +'</table></div>'+(ts.length>200?'<div class="lg-sub">只顯示最近 200 筆，統計包含全部 '+ts.length+' 筆。</div>':"")
      :'<div class="lg-empty">還沒有已出場的交易</div>';

    var f=result.fees,sk=result.skipped||[];
    N.innerHTML='<div class="lg-sub">成本模型：'+e(f.name)+'，折數 '+f.fee_discount+'。'+f.fills+' 筆成交中有 '+f.fills_with_actual_costs+' 筆使用對帳單上的實際手續費。</div>'
      +(result.notes||[]).map(function(n){return '<div class="lg-sub">'+e(n)+'</div>';}).join("")
      +(sk.length?'<div class="lg-sub warn">有 '+sk.length+' 筆紀錄格式有問題，未計入。</div>':"");
  }
  function drawChart(eq){
    var c=$("lgChart");if(!c||typeof Chart==="undefined")return;
    c.parentNode.style.display=eq.length>1?"block":"none";
    if(chart){chart.destroy();chart=null;}
    if(eq.length<2)return;
    chart=new Chart(c,{type:"line",data:{labels:eq.map(function(x){return x.date.slice(5);}),datasets:[
      {label:"你的淨損益",data:eq.map(function(x){return x.net;}),borderColor:"#ffd23f",backgroundColor:"#ffd23f",borderWidth:2,pointRadius:eq.length>40?0:2,tension:0},
      {label:"同期放 0050",data:eq.map(function(x){return x.shadow_0050;}),borderColor:"#8ea0b8",backgroundColor:"#8ea0b8",borderWidth:2,borderDash:[5,4],pointRadius:0,tension:0}]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
        plugins:{legend:{labels:{color:"#dfe7f3",boxWidth:14,font:{size:11}}}},
        scales:{x:{ticks:{color:"#8ea0b8",maxTicksLimit:6,font:{size:10}},grid:{display:false}},y:{ticks:{color:"#8ea0b8",font:{size:10}},grid:{color:"rgba(255,255,255,.07)"}}}}});
  }
  function renderFills(){
    var F=$("lgFills"),B=$("lgFillCount");if(!F)return;
    if(B)B.textContent=fills.length+" 筆";
    var rows=fills.map(function(f,i){return {f:f,i:i};}).sort(function(a,b){return (b.f.date+(b.f.time||"")).localeCompare(a.f.date+(a.f.time||""))||b.i-a.i;});
    F.innerHTML=rows.length?'<div class="lg-scroll"><table class="lg-table"><tr><th>日期</th><th>時間</th><th>代號</th><th>買賣</th><th>價格</th><th>股數</th><th>手續費</th><th>交易稅</th><th></th></tr>'
      +rows.slice(0,300).map(function(r){var f=r.f;return '<tr><td>'+e(String(f.date).slice(5))+'</td><td>'+e(f.time||"")+'</td><td>'+e(f.code)+'</td><td class="'+(f.side==="buy"?"up":"down")+'">'+(f.side==="buy"?"買":"賣")+'</td><td>'+e(f.price)+'</td><td>'+Number(f.shares).toLocaleString("en-US")+'</td><td>'+(f.fee==null?'<span class="lg-na">估</span>':e(f.fee))+'</td><td>'+(f.tax==null?'<span class="lg-na">估</span>':e(f.tax))+'</td><td><button class="lg-del" data-lg-del="'+e(f.id)+'" aria-label="刪除這筆">刪除</button></td></tr>';}).join("")
      +'</table></div>'+(rows.length>300?'<div class="lg-sub">只顯示最近 300 筆。</div>':"")
      :'<div class="lg-empty">尚無成交紀錄</div>';
  }

  function val(id){var el=$(id);return el?String(el.value).trim():"";}
  async function addManual(){
    var f={id:"m_"+Date.now().toString(36)+Math.random().toString(36).slice(2,6),date:val("lgDate"),time:val("lgTime"),code:val("lgCode").toUpperCase(),
      side:val("lgSide"),price:Number(val("lgPrice")),shares:Number(val("lgShares")),source:"manual"};
    if(val("lgUnit")==="lot")f.shares=f.shares*1000;
    ["fee","tax","plan_price"].forEach(function(k){var v=val({fee:"lgFee",tax:"lgTax",plan_price:"lgPlan"}[k]);if(v!==""&&!isNaN(Number(v)))f[k]=Number(v);});
    var note=val("lgNote");if(note)f.note=note.slice(0,200);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(f.date))return toast("請選日期","err");
    if(!/^\d{4,6}[A-Z]?$/.test(f.code))return toast("股票代號格式不對","err");
    if(!(f.price>0)||!(f.shares>0)||f.shares!==Math.floor(f.shares))return toast("價格與股數要是正數","err");
    fills.push(f);await save();
    ["lgPrice","lgShares","lgFee","lgTax","lgPlan","lgNote"].forEach(function(id){if($(id))$(id).value="";});
    toast("已新增 "+f.code+(f.side==="buy"?" 買進":" 賣出"),"ok");compute();
  }
  async function del(id){
    var i=fills.findIndex(function(f){return String(f.id)===String(id);});if(i<0)return;
    var f=fills[i];
    if(!window.confirm("刪除 "+f.date+" "+f.code+(f.side==="buy"?" 買 ":" 賣 ")+f.shares+" 股 @"+f.price+"？"))return;
    fills.splice(i,1);await save();compute();
  }
  function readFile(file){
    return new Promise(function(ok,no){var r=new FileReader();r.onerror=function(){no(new Error("讀檔失敗"));};
      r.onload=function(){var buf=r.result,t;
        try{t=new TextDecoder("utf-8",{fatal:true}).decode(buf);}catch(x){try{t=new TextDecoder("big5").decode(buf);}catch(y){t=new TextDecoder().decode(buf);}}
        ok(t);};
      r.readAsArrayBuffer(file);});
  }
  async function preview(){
    var P=$("lgImportPreview"),file=$("lgFile")&&$("lgFile").files[0],text=val("lgPaste");
    pending=null;
    try{
      if(file){
        if(/\.(xlsx?|pdf)$/i.test(file.name)){P.innerHTML='<div class="lg-sub warn">目前只讀得懂 CSV 或文字檔。請在元大匯出時選 CSV，或把表格內容複製後貼到下面的框。</div>';return;}
        text=await readFile(file);
      }
      if(!text){P.innerHTML='<div class="lg-sub warn">請選一個檔案，或把對帳單表格貼到框裡。</div>';return;}
      P.innerHTML='<div class="lg-sub">解析中。主機若在休眠，喚醒大約需要一分鐘。</div>';
      var res=await apiFetch(API+"/api/ledger/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:text})},100000);
      if(!res.ok)throw new Error("HTTP "+res.status);
      var r=await res.json();
      if(r.error){P.innerHTML='<div class="lg-sub warn">'+e(r.error)+'</div>';return;}
      var have={};fills.forEach(function(f){have[f.id]=1;});
      var fresh=r.fills.filter(function(f){return !have[f.id];});
      pending=fresh;
      var h='<div class="lg-sub">讀到 '+r.fills.length+' 筆成交，其中 '+fresh.length+' 筆是新的'+(r.fills.length-fresh.length?"，"+(r.fills.length-fresh.length)+" 筆之前匯入過會略過":"")+'。</div>';
      h+='<div class="lg-sub">欄位對應：'+Object.keys(r.columns).map(function(k){return e(r.columns[k]);}).join("、")+'</div>';
      if(r.implied_fee_discount)h+='<div class="lg-sub">從實際手續費反推，你的折數大約是 '+r.implied_fee_discount.discount+'（'+r.implied_fee_discount.samples+' 筆樣本）。</div>';
      if(r.skipped.length)h+='<div class="lg-sub warn">有 '+r.skipped.length+' 列看不懂：'+r.skipped.slice(0,5).map(function(s){return "第 "+s.line+" 列（"+e(s.reason)+"）";}).join("、")+(r.skipped.length>5?"…":"")+'</div>';
      if(fresh.length){
        h+='<div class="lg-scroll"><table class="lg-table"><tr><th>日期</th><th>代號</th><th>買賣</th><th>價格</th><th>股數</th><th>手續費</th><th>交易稅</th></tr>'
          +fresh.slice(0,8).map(function(f){return '<tr><td>'+e(f.date)+'</td><td>'+e(f.code)+'</td><td>'+(f.side==="buy"?"買":"賣")+'</td><td>'+f.price+'</td><td>'+f.shares.toLocaleString("en-US")+'</td><td>'+(f.fee==null?"—":f.fee)+'</td><td>'+(f.tax==null?"—":f.tax)+'</td></tr>';}).join("")+'</table></div>'
          +'<button id="lgImportConfirm" class="lg-primary">確認匯入這 '+fresh.length+' 筆</button>';
      }
      P.innerHTML=h;
    }catch(x){P.innerHTML='<div class="lg-sub warn">匯入失敗：'+e(x.message)+'</div>';}
  }
  async function confirmImport(){
    if(!pending||!pending.length)return;
    fills=fills.concat(pending);var n=pending.length;pending=null;
    await save();$("lgImportPreview").innerHTML='<div class="lg-ok">已匯入 '+n+' 筆。</div>';
    if($("lgFile"))$("lgFile").value="";if($("lgPaste"))$("lgPaste").value="";
    compute();
  }
  async function open(){
    if($("lgDate")&&!$("lgDate").value)$("lgDate").value=today();
    if(loadedUid!==uid()||!result){status("讀取中。");await load();await compute();}
  }
  document.addEventListener("click",function(ev){
    var t=ev.target;if(!t||!t.closest)return;
    if(t.closest("#lgAdd")){ev.preventDefault();addManual();}
    else if(t.closest("#lgRefresh")){result=null;open();}
    else if(t.closest("#lgImportBtn")){preview();}
    else if(t.closest("#lgImportConfirm")){confirmImport();}
    else if(t.closest("[data-lg-del]")){del(t.closest("[data-lg-del]").getAttribute("data-lg-del"));}
  });
  return {open:open,_state:function(){return {fills:fills,result:result};},_set:function(f){fills=f;loadedUid=uid();return compute();}};
})();
