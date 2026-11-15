  (function(){
    var rows=[];
    function fmtR(x){if(x==null)return"—";var c=x>0?"up":x<0?"down":"flat";return'<span class="'+c+'">'+(x>0?"+":"")+x.toFixed(2)+'R</span>';}
    function draw(levels){
      var tb=document.querySelector("#dtTable tbody"); if(!tb) return;
      tb.innerHTML=rows.map(function(r){
        var L=(levels||{})[r.stock_id]||r._lv||{}; r._lv=L;
        var f=function(v){return v==null?"—":v;};
        return '<tr><td>'+esc(r.stock_id)+' '+esc(r.name)+(r.attention?' <span class="dt-neg">注意股</span>':'')+'</td>'+
          '<td>'+r.close+'</td><td>'+r.avg_range_pct.toFixed(1)+'%</td><td>'+r.round_trip_cost_pct.toFixed(2)+'%</td>'+
          '<td>'+r.orb.n+'</td><td>'+fmtR(r.orb.avg_net_r)+'</td><td>'+fmtR(r.random.avg_net_r)+'</td>'+
          '<td class="'+(r.passed?"dt-pass":"dt-fail")+'">'+(r.passed?"通過（只做模擬）":"不建議")+'</td>'+
          '<td>'+f(L.entry)+(L.entry_is_estimate?"*":"")+'</td><td>'+f(L.stop)+'</td><td>'+f(L.target)+'</td>'+
          '<td class="dt-st">'+esc(L.message||"按「更新今日價位」")+'</td>'+
          '<td><button class="ghost sm" data-tm="'+esc(r.stock_id)+'" data-date="'+esc(r.to)+'">時光機</button></td></tr>';
      }).join("");
      tb.querySelectorAll("button[data-tm]").forEach(function(b){b.addEventListener("click",function(){
        var i=document.getElementById("tmId"),d=document.getElementById("tmDate");
        if(i)i.value=b.dataset.tm; if(d)d.value=b.dataset.date; var go=document.getElementById("btnTm"); if(go)go.click();
        var t=document.getElementById("tmOut"); if(t)t.scrollIntoView({behavior:"smooth"});});});
    }
    async function scan(refresh){
      var msg=document.getElementById("dtMsg"); msg.textContent="掃描中…第一次每天約需 1 分鐘";
      try{
        var r=await apiFetch(API+"/api/daytrade/screen?fee_discount="+(window.feeDisc?feeDisc():0.6)+(refresh?"&refresh=true":""),{},180000); var d=await r.json();
        if(!r.ok){msg.textContent="⚠ "+(d.detail||r.status);return;}
        rows=d.candidates||[]; msg.textContent="分 K 資料到 "+(d.last_session||d.as_of)+"：成交值前 "+d.universe+" 名中，"+rows.length+" 檔波動夠大，"+d.passed+" 檔扣成本後通過。"+(d.notes||[]).join(" ");
        document.getElementById("dtRule").textContent=d.how_to_trade;
        document.getElementById("dtFoot").textContent="* 預估進場價（突破後下一根開盤才確定）。"+d.disclaimer+" 略過 "+(d.skipped||[]).length+" 檔。";
        document.getElementById("dtTable").style.display=rows.length?"table":"none"; draw();
        if(rows.length) levels();
      }catch(e){msg.textContent=(e&&e.name==="TypeError")||/fetch/i.test(e&&e.message||"")?"⚠ 伺服器還在計算或剛喚醒，約 1 分鐘後再按一次":"⚠ "+e.message;}
    }
    async function levels(){
      if(!rows.length) return scan(false);
      var ids=rows.slice(0,10).map(function(r){return r.stock_id;}).join(",");
      try{var r=await apiFetch(API+"/api/daytrade/levels?ids="+ids+"&fee_discount="+(window.feeDisc?feeDisc():0.6),{},60000); var d=await r.json(); if(r.ok){draw(d.levels);
        document.getElementById("dtFoot").textContent=document.getElementById("dtFoot").textContent.split(" | ")[0]+" | "+d.data_note;}}catch(e){}
    }
    function init(){var a=document.getElementById("btnDtScan"),b=document.getElementById("btnDtLevels");
      if(a)a.addEventListener("click",function(){scan(false);}); if(b)b.addEventListener("click",levels);}
    if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
  })();
