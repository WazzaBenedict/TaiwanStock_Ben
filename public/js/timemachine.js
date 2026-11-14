  (function(){
    function v(id){var e=document.getElementById(id);return e?e.value.trim():"";}
    function lastWeekday(){var d=new Date();d.setDate(d.getDate()-1);while(d.getDay()===0||d.getDay()===6)d.setDate(d.getDate()-1);return d.toISOString().slice(0,10);}
    function init(){
      var dt=document.getElementById("tmDate"); if(dt&&!dt.value) dt.value=lastWeekday();
      var dc=document.getElementById("tmDisc"); if(dc&&window.feeDisc) dc.value=feeDisc();
      var b=document.getElementById("btnTm"); if(b) b.addEventListener("click",runTm);
    }
    async function runTm(){
      var msg=document.getElementById("tmMsg"),out=document.getElementById("tmOut");
      var q={stock_id:v("tmId"),date:v("tmDate"),orb_minutes:v("tmOrb"),target_r:v("tmR"),shares:v("tmShares"),fee_discount:v("tmDisc"),slip_ticks:v("tmSlip")};
      if(!/^\d{4,6}[A-Z]?$/.test(q.stock_id)||!q.date){msg.textContent="請輸入股票代號與日期";return;}
      if(v("tmEntry")){q.entry=v("tmEntry");q.stop=v("tmStop");q.target=v("tmTarget");q.entry_time=v("tmTime");
        if(!q.stop||!q.target||!q.entry_time){msg.textContent="手動計畫需要進場價、進場時間、停損與停利";return;}}
      msg.textContent="抓取分 K 並重播中…第一次抓 60 天資料可能要 1 分鐘";out.style.display="none";
      try{
        var r=await apiFetch(API+"/api/daytrade/timemachine?"+new URLSearchParams(q).toString(),{},120000);
        var d=await r.json(); if(!r.ok){msg.textContent="⚠ "+(d.detail||("錯誤 "+r.status));return;}
        msg.textContent=""; render(d);
      }catch(e){msg.textContent="⚠ "+e.message;}
    }
    function render(d){
      var p=d.plan,m=d.mc,h=d.history,a=d.actual_day,out=document.getElementById("tmOut");
      var pct=function(x){return x.toFixed(1)+"%";};
      var html='<div style="font-family:var(--mono);font-size:12px;margin:6px 0">'+esc(p.stock_id)+" "+esc(p.date)+"　"+(p.source==="orb"?"開盤區間突破 自動計畫":"手動計畫")+
        "　進場 "+p.entry+" @"+esc(p.entry_time)+"　停損 "+p.stop+"　停利 "+p.target+"（"+p.target_r+"R）　"+p.shares+" 股　來回成本約 "+p.round_trip_cost_pct+"%</div>";
      html+='<div class="tm-bar"><div style="width:'+m.target_first+'%;background:#3ddc97">停利 '+pct(m.target_first)+'</div><div style="width:'+m.neither+'%;background:#8aa0bf">收盤 '+pct(m.neither)+'</div><div style="width:'+m.stop_first+'%;background:#ff6b6b">停損 '+pct(m.stop_first)+'</div></div>';
      html+='<div class="tm-kv">'+
        '<div><b>'+pct(m.profitable_after_costs)+'</b><span>扣成本後賺錢的比例</span></div>'+
        '<div><b>'+m.avg_net_r.toFixed(3)+'R</b><span>扣成本後平均每筆</span></div>'+
        '<div><b>'+m.exit_median+'</b><span>出場價中位數（90%: '+m.exit_p5+'–'+m.exit_p95+'）</span></div>'+
        '<div><b>'+(h.trades?h.avg_net_r.toFixed(3)+"R":"—")+'</b><span>歷史實際 '+(h.trades||0)+' 筆 / '+h.sessions+' 天</span></div>'+
        '<div><b>'+(a.net_pnl>=0?"+":"")+a.net_pnl+'</b><span>當天實際（'+esc(a.outcome)+'，'+a.net_r+'R）</span></div></div>';
      html+=d.verdict.map(function(s){return '<div class="tm-verdict">'+esc(s)+'</div>';}).join("");
      html+='<div style="font-family:var(--mono);font-size:11px;color:var(--muted)">'+m.replays+' 次重播，seed '+m.seed+'，樣本 '+esc(d.pool.from)+' ~ '+esc(d.pool.to)+'。'+esc(d.disclaimer)+'</div>';
      out.innerHTML=html; out.style.display="block";
    }
    if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
  })();
