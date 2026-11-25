'use strict';
const assert=require('node:assert/strict'),{analyze,blobHash,readPinned}=require('./real_diagnostic.js');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
assert.equal(blobHash(Buffer.from('hello\n')),'ce013625030ba8dba906f756967f9e9ca394464a');
assert.throws(()=>analyze(['','','{}']));
const rows=[],refs=[],assign=[];for(let i=0;i<478;i++){let f=i%287,fold=f%5;rows.push({molecule_id:`m${i}`,family_id:`f${f}`,candidates:[{candidate_id:'a',cheap_kcal:0},{candidate_id:'b',cheap_kcal:i%3===0?.3:.03}]});refs.push({molecule_id:`m${i}`,references:{a:i%3===0?2:0,b:0}});assign.push({molecule_id:`m${i}`,family_id:`f${f}`,fold_id:fold,n_candidates:2});}
const raw=()=>[rows.map(JSON.stringify).join('\n'),refs.map(JSON.stringify).join('\n'),JSON.stringify({assignments:assign})];
const result=analyze(raw());assert.equal(result.rows,478);assert.equal(result.families,287);assert.equal(result.results[0].success,318);assert.equal(result.results[1].success,478);assert.equal(result.results[1].calls,956);assert.equal(result.bins.reduce((n,x)=>n+x.n,0),478);assert.ok(result.brier.gap<result.brier.constant);assert.deepEqual(result,analyze(raw()));
assign[287].fold_id=3;assert.throws(()=>analyze(raw()),/family split/);assign[287].fold_id=0;
refs[0].references={a:0,c:0};assert.throws(()=>analyze(raw()),/candidate data/);refs[0].references={a:0,b:0};
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'erkidu-'));try{fs.mkdirSync(path.join(tmp,'results/real/prepared'),{recursive:true});fs.writeFileSync(path.join(tmp,'results/real/prepared/development_features.jsonl'),'bad');assert.throws(()=>readPinned(tmp),/Source pin mismatch/);}finally{fs.rmSync(tmp,{recursive:true,force:true});}
console.log('Real diagnostic: Git blob pin, cohort/accounting, family leakage, candidate matching, determinism, and corruption rejection checks passed (synthetic fixture).');
