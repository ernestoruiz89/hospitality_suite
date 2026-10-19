// Read-only inspection of native Frappe exports from the synthetic finance run.
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const runtimeRequire=createRequire(process.execPath);
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')).href);
const path=process.argv[2];
const book=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const sheet=book.worksheets.getItemAt(0);
const values=sheet.getRange('A1:N2').values;
for(const [label,expected] of [['Importe',30],['Comisión',2.9],['Retención',.3],['Neto bancario',26.8]]){
  const index=values[0].indexOf(label);
  if(index<0||typeof values[1][index]!=='number'||values[1][index]!==expected)throw Error('Incorrect numeric export: '+label);
}
console.log((await book.inspect({kind:'table',sheetId:sheet.name,range:'A1:N2',include:'values',tableMaxRows:2,tableMaxCols:14,maxChars:3500})).ndjson);
const preview=await book.render({sheetName:sheet.name,range:'E1:J2',scale:1.5,format:'png'});
await fs.writeFile(process.argv[3],new Uint8Array(await preview.arrayBuffer()));
console.log('XLSX: gross/fee/withholding/net preserved as numbers; source export unchanged');
