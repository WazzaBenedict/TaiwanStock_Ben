/* 每日報告（v15.1）：讀排程自動存檔的 data/reports.json。盤前與收盤各一段，另有當沖 5 檔候選的模擬追蹤。 */
var REPORTS=(function(){
  var data=null,loading=false;
  function $(id){return document.getElementById(id);}
  function e(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
  function pc(v,d){if(v==null||isNaN(v))return '<span class="rp-na">—</span>';return '<span class="'+(v>0?"up":v<0?"down":"")+'">'+(v>0?"+":"")+Number(v).toFixed(d==null?2:d)+'%</span>';}
  function nt(v){if(v==null||isNaN(v))return '<span class="rp-na">—</span>';return '<span class="'+(v>0?"up":v<0?"down":"")+'">'+(v>0?"+":v<0?"−":"")+Math.abs(Math.round(v)).toLocaleString("en-US")+'</span>';}
  function wk(d){try{return "週"+"日一二三四五六".charAt(new Date(d+"T00:00:00+08:00").getDay());}catch(x){return "";}}
  function hm(iso){return iso?String(iso).slice(11,16):"";}
  function picksTable(day){
    var p=day.picks,res={};(day.results||[]).forEach(function(r){res[r.code]=r;});
    if(!p||!p.items||!p.items.length)return "";
    var has=!!(day.results&&day.results.length);
    var h='<div class="rp-sub">當沖 5 檔候選<span class="rp-hint">規則 '+e(p.version)+'，母體 '+e(p.universe_n)+' 檔，模擬追蹤</span></div><div class="rp-scroll"><table class="rp-table"><thead><tr><th>股票</th><th>昨收</th><th>B 版買進上限</th>'+(has?'<th>開盤</th><th>收盤</th><th>A 版損益</th><th>B 版損益</th>':'<th>波動 ATR</th>')+'</tr></thead><tbody>';
    p.items.forEach(function(x){var r=res[x.code];
      h+='<tr><td><button class="td-link" data-rp-stock="'+e(x.code)+'">'+e(x.code)+'</button> '+e(x.name)+'</td><td>'+e(x.close)+'</td><td>'+e(x.buy_b_max)+'</td>'
        +(has?(r?'<td>'+e(r.open)+' '+pc(r.gap_pct)+'</td><td>'+e(r.close)+(r.stop_hit?' <span class="rp-warn">停損</span>':'')+'</td><td>'+nt(r.a_net)+'</td><td>'+(r.b_taken?nt(r.b_net):'<span class="rp-na">沒買</span>')+'</td>':'<td colspan="4" class="rp-na">沒有成交資料</td>'):'<td>'+e(x.atr_pct)+'%</td>')+'</tr>';
    });
    h+='</tbody></table></div><div class="rp-hint">A 版：開盤買、收盤賣。B 版：開盤價不高於「買進上限」才買。兩版都是每檔 1 張、跌破開盤價 3% 停損，損益已扣元大手續費與當沖稅。</div>';
    return h;
  }
  function dayHtml(d,open){
    var pre=d.pre,cl=d.close,h='<details class="rp-day"'+(open?" open":"")+'><summary><span class="rp-date">'+e(d.date.slice(5).replace("-","/"))+' '+wk(d.date)+'</span><span class="rp-tags">'+(pre?'<span class="rp-tag">盤前</span>':'')+(cl?'<span class="rp-tag done">收盤</span>':'')+(d.picks?'<span class="rp-tag pk">5 檔</span>':'')+'</span><span class="rp-one">'+e(pre&&pre.conclusion||(cl?"0050 收盤 "+(cl.close_chg_pct>0?"+":"")+cl.close_chg_pct+"%":""))+'</span></summary><div class="rp-body">';
    if(pre){
      h+='<div class="rp-sub">盤前報告<span class="rp-hint">'+e(hm(pre.at))+' 產生</span></div><div class="rp-concl">'+e(pre.conclusion||"")+'</div><div class="rp-kpis">'
        +'<div class="rp-kpi"><span>0050 開盤預估</span><b>'+(pre.gap&&pre.gap.ok?pc(pre.gap.pct):"—")+'</b></div>'
        +'<div class="rp-kpi"><span>大盤風險燈</span><b class="rp-light '+e(pre.risk&&pre.risk.color||"")+'">'+e(pre.risk&&pre.risk.label||"—")+'</b></div>'
        +'<div class="rp-kpi"><span>加權距 200 日線</span><b>'+pc(pre.risk&&pre.risk.dist_ma200_pct,1)+'</b></div></div>';
      if(pre.overnight&&pre.overnight.length)h+='<div class="td-chips">'+pre.overnight.map(function(x){return '<span class="td-chip">'+e(x.name)+' '+pc(x.chg_pct)+'</span>';}).join("")+'</div>';
    }
    h+=picksTable(d);
    if(cl){
      h+='<div class="rp-sub">收盤總結<span class="rp-hint">'+e(hm(cl.at))+' 產生</span></div><div class="rp-kpis"><div class="rp-kpi"><span>0050 實際開盤</span><b>'+pc(cl.gap_pct)+'</b></div><div class="rp-kpi"><span>0050 收盤</span><b>'+pc(cl.close_chg_pct)+'</b></div>'
        +(pre&&pre.gap&&pre.gap.ok&&cl.gap_pct!=null?'<div class="rp-kpi"><span>開盤方向</span><b>'+((pre.gap.pct>0)===(cl.gap_pct>0)?"猜對":"猜錯")+'</b></div>':'')+'</div>';
      if(cl.watchlist&&cl.watchlist.length)h+='<div class="td-chips">'+cl.watchlist.map(function(x){return '<span class="td-chip">'+e(x.code)+' '+pc(x.chg_pct)+'</span>';}).join("")+'</div>';
    }else if(pre){h+='<div class="rp-hint">收盤總結會在 13:45 後自動補上。</div>';}
    if(pre&&pre.news&&pre.news.length)h+='<details class="rp-news"><summary>盤前新聞標題（'+pre.news.length+'）</summary><ul>'+pre.news.map(function(t){return '<li>'+e(t)+'</li>';}).join("")+'</ul></details>';
    return h+'</div></details>';
  }
  function totalsHtml(){
    var t=data.picks_totals||{},a=t.a||{},b=t.b||{};
    if(!a.n)return '<div class="rp-hint">當沖 5 檔的模擬成績會從第一個交易日收盤後開始累積。</div>';
    function box(name,x){return '<div class="rp-kpi"><span>'+name+'（'+x.n+' 筆）</span><b>'+nt(x.net)+' 元</b><small>勝率 '+(x.win_rate_pct==null?"—":x.win_rate_pct+"%")+'，每邊多滑 1 檔是 '+nt(x.net_tick1)+'</small></div>';}
    return '<div class="rp-kpis">'+box("A 版累計",a)+box("B 版累計",b)+'</div>';
  }
  function render(){
    var box=$("rpBody");if(!box)return;
    if(!data){box.innerHTML='<div class="rp-na">報告還沒產生。</div>';return;}
    var days=data.days||[];
    var h='<div class="rp-sub">當沖 5 檔模擬成績<span class="rp-hint">已對答案 '+(data.picks_days||0)+' 天</span></div>'+totalsHtml()+'<div class="rp-caution">'+e((data.picks_rule||{}).note||"")+'</div>';
    h+='<div class="rp-sub">每日報告<span class="rp-hint">交易日 06:50 盤前、13:45 收盤自動存檔，保留最近 60 天</span></div>';
    h+=days.length?days.map(function(d,i){return dayHtml(d,i===0);}).join(""):'<div class="rp-empty">第一份報告會在下一個交易日 06:50 後自動出現，之後每天累積。</div>';
    box.innerHTML=h;bind(box);
  }
  function bind(root){root.querySelectorAll("[data-rp-stock]").forEach(function(b){b.addEventListener("click",function(){if(typeof showPage==="function"&&typeof loadStock==="function"){showPage("p-trade");loadStock(b.getAttribute("data-rp-stock"));}});});}
  function home(){
    var box=$("rpHome");if(!box)return;
    var d=data&&(data.days||[])[0];
    if(!d){box.innerHTML='<div class="rp-home-h"><b>每日報告</b><button class="ghost sm" data-hq-go="p-reports">全部報告</button></div><div class="rp-hint">第一份報告會在下一個交易日 06:50 後自動出現。</div>';box.style.display="block";return;}
    var h='<div class="rp-home-h"><b>每日報告</b><span class="rp-hint">'+e(d.date.slice(5).replace("-","/"))+' '+wk(d.date)+(d.close?"，已收盤":"，盤前")+'</span><button class="ghost sm" data-hq-go="p-reports">全部報告</button></div>';
    if(d.close)h+='<div class="rp-concl">0050 開盤 '+pc(d.close.gap_pct)+'，收盤 '+pc(d.close.close_chg_pct)+'</div>';
    h+=picksTable(d)||'<div class="rp-hint">今天沒有當沖候選。</div>';
    box.innerHTML=h;box.style.display="block";bind(box);
  }
  function load(){
    if(loading)return Promise.resolve();loading=true;
    return fetch("data/reports.json?t="+Math.floor(Date.now()/60000),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();})
      .then(function(d){data=d;}).catch(function(){data=data||{days:[]};}).then(function(){loading=false;home();render();});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",load);else load();
  setInterval(function(){if(!document.hidden)load();},10*60*1000);
  return {open:function(){render();load();}};
})();
