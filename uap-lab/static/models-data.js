'use strict';
((root)=>{
 const number=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
 function accuracy(m){if(!m)return null;if(number(m.accuracy)!==null)return m.accuracy;if(m.total>0){const correct=number(m.correct)??Object.values(m.per_class||{}).reduce((n,c)=>n+(c.tp||0),0);return correct/m.total;}return null;}
 const version=r=>r.candidate_version||r.evaluation?.candidate_version||r.version;
 function merge(metrics={},history={},catalog={}){
  const records=Array.isArray(history)?history:history.hours||history.runs||[];const used=new Set(),rows=[];
  for(const [i,p] of (metrics.points||[]).entries()){
   const record=records.find((r,j)=>!used.has(j)&&((p.run_id&&r.run_id===p.run_id)||(version(r)===p.version&&(!r.started_epoch||p.epoch>=r.started_epoch-120&&p.epoch<=(r.finished_epoch||r.started_epoch+86400)+120))));
   if(record)used.add(records.indexOf(record));rows.push({key:'run:'+(p.run_id||p.epoch+':'+i),epoch:record?.started_epoch||p.epoch,version:p.version,point:p,record,kind:'Training run'});
  }
  records.forEach((record,i)=>{if(!used.has(i))rows.push({key:'history:'+(record.run_id||record.slot||record.started_epoch||i),epoch:record.started_epoch||record.finished_epoch||0,version:version(record),record,kind:'Training run'});});
  for(const model of catalog.models||[]){const match=rows.filter(r=>r.version===model.version&&!r.model).sort((a,b)=>b.epoch-a.epoch)[0];if(match){match.model=model;match.kind='Training run · Saved model';}else rows.push({key:'model:'+model.id,epoch:model.created_epoch||0,version:model.version,model,kind:'Saved model'});}
  return rows.map(row=>{
   const p=row.point,r=row.record,m=row.model,phase=r?.phase||p?.phase,job=m?.test;
   const test=job?.state==='complete'&&job.benchmark_id===catalog.benchmark?.id?job.result:null;
   const candidate=p?.candidate||r?.evaluation?.candidate,baseline=p?.baseline||r?.evaluation?.baseline;
   const released=!!metrics.releases?.[row.version]||phase==='deployed';
   const statuses={error:'Training failed',rejected:'Not released',not_promoted:'Earlier model kept',validated_no_improvement:'Earlier model kept',validated_unchanged:'Unchanged',rolled_back:'Rolled back',waiting_for_data:'Waiting for data',superseded:'Labels changed',training:'Training',building:'Preparing data',evaluating:'Evaluating',activation_pending:'Activation pending',activating:'Deploying'};
   let status=m?.active?'Current model':phase==='rolled_back'?'Rolled back':released?'Previous model':statuses[phase]||(phase?phase.replaceAll('_',' '):m?'Saved model':'Training run');
   const reason=r?.reason||r?.error||p?.release_reason||(p?.reasons||r?.evaluation?.reasons||[]).join('; ');
   const count=p?.reviewed_examples??m?.reviewed_frames??(r?.labels?Object.values(r.labels).reduce((a,b)=>a+b,0):null);
   const duration=r?.finished_epoch&&r?.started_epoch?Math.max(0,r.finished_epoch-r.started_epoch):null;
   return {...row,candidate,baseline,test,job,status,reason,count,duration,released,runAccuracy:accuracy(candidate),baselineAccuracy:accuracy(baseline),testAccuracy:accuracy(test),cohort:p?.cohort||null};
  }).sort((a,b)=>b.epoch-a.epoch||a.key.localeCompare(b.key));
 }
 function score(row,series,measure){const data=row[series];if(measure==='accuracy')return accuracy(data);return number(data?.per_class?.anomalous?.[measure]);}
 const api={merge,score,accuracy};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.ModelDashboardData=api;
})(typeof window==='undefined'?globalThis:window);
