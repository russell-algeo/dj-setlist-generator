import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),req=createRequire(import.meta.url);
const {PGlite}=req(process.env.PGLITE_PACKAGE_ROOT||'@electric-sql/pglite');
function call(mode,input){const p=spawnSync(process.env.PYTHON||'python3',['scripts/test_yoon_enrichment_projection.py',mode],{cwd:root,input,encoding:'utf8',maxBuffer:32*1024*1024,env:{...process.env,PYTHONPATH:root}});if(p.status!==0)throw Error(p.stderr);return JSON.parse(p.stdout);}
const x=call('input'),db=new PGlite();
try{
 await db.exec('CREATE SCHEMA ops; CREATE TABLE ops.segment_hits(set_run_id uuid,segment_index int,raw_data jsonb)');
 for(const d of x.runs)await db.query('INSERT INTO ops.segment_hits SELECT $1::uuid,(h->>\'segment_index\')::int,h->\'raw_data\' FROM jsonb_array_elements($2::jsonb) h',[d.run,JSON.stringify(d.hits)]);
 const rows=async(sql,run,first=false)=>(await db.query(`SELECT segment_index,raw_data::text AS raw_text FROM (${sql}) q ${first?'WHERE segment_index=0':''} ORDER BY segment_index`,[run])).rows;
 const out={runs:[],variations:[]};
 for(const d of x.runs)out.runs.push({run:d.run,old:await rows(x.fullSql,d.run),new:await rows(x.projectionSql,d.run)});
 const run=x.runs[0].run;
 for(const v of x.variations){await db.query('UPDATE ops.segment_hits SET raw_data=$1::jsonb WHERE set_run_id=$2 AND segment_index=0',[v.raw_text,run]);out.variations.push({name:v.name,old:await rows(x.fullSql,run,true),new:await rows(x.projectionSql,run,true)});}
 await db.query('UPDATE ops.segment_hits SET raw_data=NULL WHERE set_run_id=$1 AND segment_index=0',[run]);out.null_preserved=(await rows(x.projectionSql,run,true))[0].raw_text===null;
 console.log(JSON.stringify(call('compare',JSON.stringify(out))));
}finally{await db.close();}
