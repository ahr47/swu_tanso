// The catalog mirrors the existing item screens. Coefficients are not inferred
// from totals: only the A4 reference value supplied by the design is available.
const groups = [
  {name:'인쇄물·홍보물',items:['A4 용지','리플릿','포스터','현수막','종이 명찰·프로그램북'],note:'종이·원단의 재질, 크기와 총 무게를 기준으로 자료의 단위를 확인해주세요.'},
  {name:'음료·일회용품',items:['생수','캔 음료','페트 음료','종이컵(뚜껑 포함)','PET컵(뚜껑 포함)','일회용 수저 세트','위생장갑','포장랩'],note:'용량, 포장재의 재질과 뚜껑 포함 여부가 같은 자료인지 확인해주세요.'},
  {name:'음식·간식',items:['샌드위치','피자','봉지과자','초콜릿바','젤리','컵라면'],note:'제품의 중량과 제공 단위, 원재료 및 포장 포함 범위를 확인해주세요.'},
  {name:'굿즈',items:['에코백','티셔츠','텀블러','볼펜','아크릴 키링'],note:'재질, 무게 및 제조 범위가 같은 자료인지 확인해주세요.'},
  {name:'배송',items:['품목 배송'],note:'배송 거리와 운송수단, 적재량 및 왕복 포함 여부를 확인해주세요.'},
  {name:'이동',items:['승용차','버스','지하철','기차','도보·자전거'],note:'이동 거리와 인원, 교통수단별 산정 단위 및 왕복 포함 여부를 확인해주세요.'}
];
const normalize=value=>value.normalize('NFKC').toLocaleLowerCase('ko').replace(/[\s·・()↗]/g,'');

export function enhanceSourcesDialog(panel){
  panel.classList.add('sources-panel');
  const find=name=>panel.querySelector(`[data-name="${name}"]`);
  const tabs=find('Source categories');
  const list=find('Item list');
  const detail=find('Source details scroll');
  const detailTemplate=find('Detail content').cloneNode(true);
  const itemTemplate=list.firstElementChild.cloneNode(true);
  const listLabel=find('List label');
  const searchShell=find('Search items');
  const status=document.createElement('p');status.className='source-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  listLabel.after(status);
  list.setAttribute('aria-label','출처 품목 목록');
  detail.id='source-detail';detail.setAttribute('role','region');detail.setAttribute('aria-label','선택한 품목의 배출계수 출처');
  let category=0,selected='A4 용지',query='';const remembered=new Map();
  tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','배출계수 출처 카테고리');
  const tabButtons=[...tabs.children].map((old,index)=>{
    const b=document.createElement('button');b.type='button';b.className=old.className+' source-tab';b.innerHTML=old.innerHTML;b.dataset.name=old.dataset.name;
    b.setAttribute('role','tab');b.id=`source-category-${index}`;b.setAttribute('aria-controls','source-detail');b.setAttribute('aria-label',`${groups[index].name} ${groups[index].items.length}개`);
    b.addEventListener('click',()=>selectCategory(index));
    b.addEventListener('keydown',e=>{let next;if(e.key==='ArrowRight')next=(index+1)%groups.length;else if(e.key==='ArrowLeft')next=(index+groups.length-1)%groups.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=groups.length-1;else return;e.preventDefault();selectCategory(next);tabButtons[next].focus();});
    old.replaceWith(b);return b;
  });
  searchShell.querySelector('p').hidden=true;
  const search=document.createElement('input');search.type='search';search.className='source-search';search.placeholder='품목명 또는 출처 검색';search.setAttribute('aria-label','품목명 또는 출처 검색');searchShell.append(search);
  const clear=document.createElement('button');clear.type='button';clear.className='source-search-clear';clear.textContent='×';clear.setAttribute('aria-label','검색어 지우기');searchShell.append(clear);
  clear.addEventListener('click',()=>{search.value='';query='';renderList();search.focus();});
  search.addEventListener('input',()=>{query=search.value;renderList();});
  function selectCategory(index){category=index;query='';search.value='';selected=remembered.get(index)||groups[index].items[0];renderList();}
  function entries(){const term=normalize(query);return groups.flatMap((g,index)=>g.items.map(name=>({name,category:index}))).filter(item=>term?normalize(`${item.name} ${groups[item.category].name} ${item.name==='A4 용지'?'ECOSQUARE 에코스퀘어 국내 통합 DB':''}`).includes(term):item.category===category);}
  function renderList(){
    const results=entries();
    tabButtons.forEach((b,i)=>{b.setAttribute('aria-selected',String(i===category));b.tabIndex=i===category?0:-1;});
    const label=listLabel.querySelectorAll('p');label[0].textContent=query.trim()?'전체 검색 결과':groups[category].name;label[1].textContent=results.length+'개';
    clear.hidden=!query;
    if(!results.some(r=>r.name===selected))selected=results[0]?.name||null;
    list.replaceChildren();
    for(const item of results){const b=document.createElement('button');b.type='button';b.className=itemTemplate.className+' source-item';b.dataset.name='Item / '+item.name;b.setAttribute('aria-label',item.name);b.setAttribute('aria-pressed',String(item.name===selected));b.setAttribute('aria-controls','source-detail');
      const title=document.createElement('span');title.textContent=item.name;const arrow=document.createElement('span');arrow.textContent='›';arrow.setAttribute('aria-hidden','true');b.append(title,arrow);
      b.addEventListener('click',()=>{selected=item.name;remembered.set(item.category,item.name);for(const other of list.children)other.setAttribute('aria-pressed',String(other===b));renderDetail(item);status.textContent=item.name+' 선택됨';});
      list.append(b);
    }
    if(!results.length){const empty=document.createElement('p');empty.className='source-empty';empty.textContent='검색 결과가 없어요. 다른 품목명으로 검색해보세요.';list.append(empty);detail.replaceChildren();status.textContent='검색 결과 0개';return;}
    renderDetail(results.find(r=>r.name===selected));status.textContent=query.trim()?`검색 결과 ${results.length}개`:`${groups[category].name} ${results.length}개 품목`;
  }
  function renderDetail(item){
    const content=detailTemplate.cloneNode(true);detail.replaceChildren(content);detail.scrollTop=0;
    const set=(id,value)=>{content.querySelector(`[data-node-id="${id}"]`).textContent=value;};
    const a4=item.name==='A4 용지';
    set('118:458',item.name);
    set('118:461',a4?'디자인 참고값':'자료 미등록');
    set('118:462',a4?'복사지·백상지 / 무게 기준':groups[item.category].name+' · '+item.name);
    set('118:466',a4?'1.12':'미확보');set('118:467',a4?'kgCO₂e/kg':'단위 확인 필요');
    set('118:471',a4?'ECOSQUARE · 국내 통합 DB':'원문 자료 미등록');
    set('118:472',a4?'디자인에 기재된 자료명 · 개별 원문 파일 미등록':'해당 품목의 배출계수와 원문이 아직 등록되지 않았어요.');
    set('118:478',a4?'미기재':'미등록');set('118:481',a4?'미기재':'미등록');set('118:484',a4?'원문 확인 필요':'원문 등록 후 확인');
    set('118:487',a4?'종이의 총 무게(kg)에 계수를 곱해요. 디자인의 예시 값이며 자료 연도와 산정 범위는 원문 확인이 필요해요.':groups[item.category].note);
    if(!a4){set('118:491','미등록');set('118:494','미확보');set('118:495','품목에 맞는 가격 자료가 등록되면 표시됩니다.');set('118:496','자료 등록 전 · 임의의 값은 표시하지 않아요.');}
    const old=content.querySelector('[data-name="Button / 원문 보기 ↗"]');
    const control=document.createElement(a4?'a':'button');control.className=old.className+' source-original';control.textContent=a4?'자료 사이트 ↗':'출처 안내';
    if(a4){control.href='https://ecosq.or.kr/';control.target='_blank';control.rel='noopener noreferrer';control.setAttribute('aria-label','ECOSQUARE 자료 사이트 열기 (새 탭)');}
    else{control.type='button';control.setAttribute('aria-expanded','false');control.setAttribute('aria-controls','source-availability');}
    old.replaceWith(control);
    const notice=document.createElement('p');notice.className='source-availability';notice.id='source-availability';notice.textContent=a4?'에코스퀘어의 자료 사이트를 엽니다. 이 예시 값에 해당하는 개별 원문 링크는 아직 제공되지 않았어요.':`${item.name}의 원문 링크가 아직 등록되지 않았어요. 출처·단위·계수가 확보되면 이 위치에서 확인할 수 있습니다.`;notice.hidden=!a4;
    content.querySelector('[data-name="Source reference"]').append(notice);
    if(!a4)control.addEventListener('click',()=>{notice.hidden=!notice.hidden;control.setAttribute('aria-expanded',String(!notice.hidden));});
  }
  renderList();
}
