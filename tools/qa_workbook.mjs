// Read-only inspection of the XLSX produced by Frappe's installed export API.
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
// The bundled Node runtime resolves its own QA libraries without adding a
// node_modules link inside the app's public assets (which slows native migrate).
const runtimeRequire=createRequire(process.execPath);
const { FileBlob,SpreadsheetFile }=await import(pathToFileURL(runtimeRequire.resolve("@oai/artifact-tool")).href);

const path=process.argv[2];
const workbook=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const sheet=workbook.worksheets.getItemAt(0);
console.log((await workbook.inspect({kind:"table",sheetId:sheet.name,range:"A1:I6",include:"values,formulas",tableMaxRows:6,tableMaxCols:9,maxChars:3500})).ndjson);
const values=sheet.getRange("A1:I6").values;
if(values[0][3]!=="Esperado" || typeof values[1][3]!=="number" || values[1][5]!==0)throw new Error("Numeric types or reconciliation values differ from the source");
const preview=await workbook.render({sheetName:sheet.name,range:"A1:I6",scale:1.5,format:"png"});
await fs.writeFile(process.argv[3],new Uint8Array(await preview.arrayBuffer()));
console.log("XLSX: read-only import, numeric amounts and zero differences verified; preview rendered");
