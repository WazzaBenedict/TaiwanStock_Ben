/* 今日頁：讀每日快照 data/today.json（由 GitHub Actions 定時產生），不經過後端，所以不必等主機喚醒。 */
var TODAY=null;
(function(){
  function $(id){return document.getElementById(id);}
  function e(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
  function pc(v,d){if(v==null||isNaN(v))return '<span class="td-na">—</span>';var cls=v>0?"up":(v<0?"down":"");return '<span class="'+cls+'">'+(v>0?"+":"")+Number(v).toFixed(d==null?2:d)+'%</span>';}
  function ageText(iso){
    var t=new Date(iso),h=(Date.now()-t.getTime())/36e5;
    var hh=("0"+((t.getUTCHours()+8)%24)).slice(-2)+":"+("0"+t.getUTCMinutes()).slice(-2);
    var day=new Date(t.getTime()+8*36e5).toISOString().slice(5,10).replace("-","/");
    return {text:day+" "+hh+" 更新",stale:h>30,hours:h};
  }
  function heroLines(d){
    var L={},g=d.gap_estimate||{},r=d.risk||{},hl=d.hit_log||{},w=d.watchlist||[];
    var night=(d.overnight||{}).night,sox=((d.overnight||{}).us||[]).filter(function(x){return x.symbol==="^SOX";})[0];
    if(g.ok)L.vanguard=(night&&night.fresh?"夜盤 "+(night.pct>0?"+":"")+night.pct+"%":(sox?"費半 "+(sox.chg_pct>0?"+":"")+sox.chg_pct+"%":"隔夜資料"))+"，0050 預估"+(g.pct>0.15?"開高":g.pct<-0.15?"開低":"平盤")+"。";
    if(r.ok)L.bastion="大盤"+r.label+"：距 200 日線 "+(r.dist_ma200_pct>0?"+":"")+r.dist_ma200_pct+"%，波動 "+r.vol20_pct+"%。";
    L.volt="今天的預設是不做當沖，有證據才改。";
    if(hl.n)L.nexus="開盤預估命中 "+hl.hits+"/"+hl.n+"，基準 "+hl.baseline_hits+"/"+hl.n+"。";
    else L.nexus="開盤預估的命中率從今天開始累積。";
    var hot=w.filter(function(x){return x.disposition;});
    if(hot.length)L.swift="注意："+hot.map(function(x){return x.code;}).join("、")+" 是處置股。";
    L.haven="資料"+ageText(d.generated_at).text+"。";
    return L;
  }
  function render(d){
    var box=$("todayCard");if(!box)return;
    var g=d.gap_estimate||{},r=d.risk||{},ov=d.overnight||{},age=ageText(d.generated_at),hl=d.hit_log||{};
    var h='<div class="td-head"><span class="td-kicker">今日</span><span class="td-age'+(age.stale?" stale":"")+'">'+e(age.text)+(age.stale?"（資料較舊）":"")+'</span></div>';
    h+='<div class="td-grid">';
    h+='<div class="td-box"><div class="td-label">0050 開盤預估</div><div class="td-big">'+(g.ok?pc(g.pct):"—")+'</div><div class="td-sub">'+e(g.note||"")+'</div><div class="td-sub">只預估開盤，不預測收盤</div></div>';
    h+='<div class="td-box td-risk td-'+e(r.color||"unknown")+'"><div class="td-label">大盤風險燈</div><div class="td-big"><span class="td-dot"></span>'+e(r.label||"—")+'</div><div class="td-sub">'+e(r.text||"")+'</div>'+(r.ok?'<div class="td-sub">距 200 日線 '+pc(r.dist_ma200_pct,1)+' · 20 日波動 '+e(r.vol20_pct)+'% · '+e(r.note)+'</div>':"")+'</div>';
    h+='</div>';
    var us=(ov.us||[]);
    if(us.length||ov.night){
      h+='<div class="td-label td-sec">隔夜</div><div class="td-chips">';
      if(ov.night)h+='<span class="td-chip'+(ov.night.fresh?"":" td-old")+'">台指期夜盤 '+pc(ov.night.pct)+(ov.night.fresh?"":"（"+e(ov.night.date.slice(5))+"，已開過盤）")+'</span>';
      us.forEach(function(x){h+='<span class="td-chip">'+e(x.name)+' '+pc(x.chg_pct)+'</span>';});
      h+='</div>';
    }
    var w=d.watchlist||[];
    if(w.length){
      h+='<div class="td-label td-sec">觀察名單</div><div class="td-scroll"><table class="td-table"><thead><tr><th>代號</th><th>收盤</th><th>漲跌</th><th>距 200 日線</th><th>20 日波動</th><th>月營收年增</th></tr></thead><tbody>';
      w.forEach(function(x){
        h+='<tr><td><button class="td-link" data-td-stock="'+e(x.code)+'">'+e(x.code)+'</button>'+(x.disposition?' <span class="td-warn">處置</span>':"")+'</td><td>'+e(x.close)+'</td><td>'+pc(x.chg_pct)+'</td><td>'+pc(x.dist_ma200_pct,1)+'</td><td>'+(x.vol20_pct==null?"—":e(x.vol20_pct)+"%")+'</td><td>'+(x.rev_yoy_pct==null?'<span class="td-na">—</span>':pc(x.rev_yoy_pct,1))+'</td></tr>';
      });
      h+='</tbody></table></div><div class="td-sub">收盤日 '+e(w[0].date)+' · 要買的在尾盤 13:25–13:30 買，要賣的在開盤賣（個股報酬集中在隔夜）</div>';
    }
    if(d.actual){h+='<div class="td-label td-sec">今日結果</div><div class="td-sub td-result">0050 實際開盤 '+pc(d.actual.gap_pct)+'，收盤 '+pc(d.actual.close_chg_pct)+'</div>';}
    h+='<div class="td-label td-sec">開盤預估命中率</div><div class="td-sub">'+(hl.n?('預估 '+hl.hits+'/'+hl.n+'（'+hl.hit_rate_pct+'%），基準「跟費半同向」'+hl.baseline_hits+'/'+hl.n+'（'+hl.baseline_rate_pct+'%），平均誤差 '+e(hl.mean_abs_error_pct)+' 個百分點。'+(hl.n<30?"樣本不到 30 天，先不要下結論。":"")):"從今天開始累積，還沒有樣本。")+'</div>';
    var nw=d.news||[];
    if(nw.length){
      h+='<details class="td-news"><summary>盤前新聞標題（'+nw.length+'）</summary><ul>';
      nw.forEach(function(n){h+='<li><span class="td-time">'+e(n.time)+'</span> <a href="'+e(n.link)+'" target="_blank" rel="noopener noreferrer">'+e(n.title)+'</a></li>';});
      h+='</ul></details>';
    }
    box.innerHTML=h;box.style.display="block";
    box.querySelectorAll("[data-td-stock]").forEach(function(b){b.addEventListener("click",function(){
      var id=b.getAttribute("data-td-stock");
      if(typeof loadStock==="function"&&typeof showPage==="function"){showPage("p-trade");loadStock(id);}
    });});
    var be=$("hqBrief");if(be&&d.conclusion)be.textContent="今日結論｜"+d.conclusion;
  }
  function fail(msg){var box=$("todayCard");if(box){box.innerHTML='<div class="td-head"><span class="td-kicker">今日</span></div><div class="td-sub">'+e(msg)+'</div>';box.style.display="block";}}
  window.loadToday=function(){
    return fetch("data/today.json?t="+Math.floor(Date.now()/60000),{cache:"no-store"}).then(function(r){
      if(!r.ok)throw new Error("HTTP "+r.status);return r.json();
    }).then(function(d){
      if(!d||!d.generated_at)throw new Error("格式錯誤");
      TODAY=d;window.TODAY_HERO_LINES=heroLines(d);render(d);
    }).catch(function(err){fail("今日快照還沒準備好（"+(err.message||err)+"）。排程會在交易日 06:50、13:45、19:00 更新。");});
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",window.loadToday);else window.loadToday();
  setInterval(function(){if(!document.hidden)window.loadToday();},10*60*1000);
})();
