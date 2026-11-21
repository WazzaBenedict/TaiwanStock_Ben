/* 研究室（v14.3）：讀每日自動重算的評分表 data/research.json。標籤由程式依固定門檻判定。 */
var LAB=(function(){
  var data=null,loading=false;
  function $(id){return document.getElementById(id);}
  function e(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
  function pc(v){if(v==null||isNaN(v))return '<span class="lb-na">—</span>';return '<span class="'+(v>0?"up":v<0?"down":"")+'">'+(v>0?"+":"")+Number(v).toFixed(2)+'%</span>';}
  function seg(title,s,hint,vs){vs=vs||"0050";
    if(!s||!s.n)return '<div class="lb-seg"><div class="lb-seg-t">'+title+'</div><div class="lb-na">還沒有資料</div><div class="lb-hint">'+hint+'</div></div>';
    return '<div class="lb-seg"><div class="lb-seg-t">'+title+'（'+s.n+(vs==="0050"?' 筆':' 期')+'）</div><div>'+(vs==="0050"?'每筆':'每期')+'平均 '+pc(s.avg_net_pct)+'</div><div>比 '+e(vs)+' '+pc(s.avg_excess_pct)+'</div><div class="lb-hint">勝率 '+s.win_rate_pct+'%　'+hint+'</div></div>';
  }
  function render(){
    var box=$("labBody");if(!box)return;
    if(!data){box.innerHTML='<div class="lb-na">評分表還沒產生，下一次排程（交易日 06:50、13:45、19:00）後會出現。</div>';return;}
    var c=data.counts||{},cls={"可用":"ok","研究中":"mid","未通過":"bad"};
    var h='<div class="lb-verdict">'+(c["可用"]?'目前有 '+c["可用"]+' 條規則通過檢驗。':'目前沒有任何一條規則通過檢驗。能做的最好選擇仍是持有 0050。')+'</div>';
    h+='<div class="lb-counts"><span class="lb-tag ok">可用 '+(c["可用"]||0)+'</span><span class="lb-tag mid">研究中 '+(c["研究中"]||0)+'</span><span class="lb-tag bad">未通過 '+(c["未通過"]||0)+'</span><span class="lb-age">'+e(data.today)+' 更新，已自動重算 '+(data.runs||1)+' 次</span></div>';
    var order={"可用":0,"研究中":1,"未通過":2};
    (data.cards||[]).slice().sort(function(a,b){return order[a.label]-order[b.label];}).forEach(function(k){
      // 未通過的規則預設收合，手機上不用滑過一大段
      var fold=k.label==="未通過";
      h+=(fold?'<details class="lb-card lb-fold"><summary>':'<div class="lb-card">')+'<div class="lb-head"><span class="lb-tag '+cls[k.label]+'">'+e(k.label)+'</span><span class="lb-name">'+e(k.name)+'</span><span class="lb-kind">'+e(k.kind)+'</span></div>'+(fold?'</summary>':'')
        +'<div class="lb-desc">'+e(k.desc)+'。'+e(k.why)+'。</div>'
        +(k.caution?'<div class="lb-caution">注意：'+e(k.caution)+'。</div>':'')
        +'<div class="lb-segs">'+seg("上線後",k.live,"規則定稿後才發生，最可信",k.vs)+seg("樣本外",k.oos,"最近兩年",k.vs)+seg("樣本內",k.is,"較早歷史，僅供參考",k.vs)+'</div>'+(fold?'</details>':'</div>');
    });
    var ch=data.changes||[];
    h+='<div class="lb-sub-t">標籤變動紀錄</div>'+(ch.length?'<ul class="lb-list">'+ch.slice().reverse().map(function(x){return '<li>'+e(x.date)+'　'+e(x.name)+'：'+e(x.from)+' 變成 '+e(x.to)+'</li>';}).join("")+'</ul>':'<div class="lb-na">還沒有變動。規則被升級或淘汰時會記在這裡。</div>');
    var ev=data.evidence||[],rw=data.rule_watch||[],gname={A:"學術或官方",B:"媒體轉述或工作論文",C:"業者回測"};
    if(ev.length){
      h+='<div class="lb-sub-t">外部研究怎麼說（'+e(data.evidence_date||"")+' 整理）</div>';
      ev.forEach(function(x){h+='<details class="lb-ev"><summary><span class="lb-grade g'+e(x.grade)+'">'+e(gname[x.grade]||x.grade)+'</span>'+e(x.topic)+'</summary><div class="lb-ev-t">'+e(x.text)+'<span class="lb-hint">　資料期間：'+e(x.year)+'</span></div></details>';});
    }
    if(rw.length){
      h+='<div class="lb-sub-t">規則變動與複查日期</div><ul class="lb-list">'+rw.map(function(x){return '<li><span class="lb-date'+(x.date<=data.today?" past":"")+'">'+e(x.date)+'</span>'+e(x.text)+'</li>';}).join("")+'</ul>';
    }
    h+='<div class="lb-note">怎麼判定：每筆約 '+(data.trade_size||50000).toLocaleString("en-US")+' 元，扣元大手續費（'+data.fee_discount+' 折）與交易稅，再和同一筆錢同期放 0050 比。樣本外至少 '+data.min_n+' 筆才下結論；扣成本後虧損或輸給 0050 就是「未通過」；樣本內、樣本外都贏 0050 且差距穩定才是「可用」。「上線後」從 '+e(data.live_start)+' 起每個交易日自動累積。價格含股利（還原價）。這是歷史統計，不是獲利保證。</div>';
    box.innerHTML=h;
  }
  async function open(){
    if(data||loading){render();return;}
    loading=true;
    try{var r=await fetch("data/research.json?t="+Math.floor(Date.now()/6e5));if(r.ok)data=await r.json();}catch(x){}
    loading=false;render();
  }
  return {open:open,_data:function(){return data;}};
})();
