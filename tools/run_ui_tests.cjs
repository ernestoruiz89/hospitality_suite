/* Run every serverless UI regression with the same Node executable on any OS. */
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const files=fs.readdirSync(__dirname).filter(name=>/^test_.+\.cjs$/.test(name)).sort().map(name=>path.join(__dirname,name));
if(!files.length)throw Error('No UI test files found');
const result=spawnSync(process.execPath,['--test',...files],{stdio:'inherit'});
if(result.error)throw result.error;
process.exit(result.status??1);
