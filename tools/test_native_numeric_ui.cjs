/* Use the installed Frappe controls, rather than approximate their parsers. */
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const frappeRoot=process.env.HOSPITALITY_FRAPPE_ROOT||(process.platform==='win32'?'\\\\wsl.localhost\\Ubuntu-24.04\\home\\frappe\\benches\\hospitality-bench\\apps\\frappe':'/home/frappe/benches/hospitality-bench/apps/frappe');
const read=name=>fs.readFileSync(path.join(frappeRoot,'frappe/public/js/frappe',name),'utf8');
const utils=read('utils/utils.js'),common=read('utils/common.js'),base=read('form/controls/base_control.js');
const evaluator=utils.slice(utils.indexOf('\teval_expression(value, number_format) {'),utils.indexOf('\n\tget_installed_apps()',utils.indexOf('\teval_expression(value, number_format) {')));
const lstrip=common.slice(common.indexOf('window.lstrip ='),common.indexOf('\n};',common.indexOf('window.lstrip ='))+3);
const parsed=base.slice(base.indexOf('\tget_parsed_value(value) {'),base.indexOf('\n\tset_value(',base.indexOf('\tget_parsed_value(value) {')));
assert(evaluator.startsWith('\teval_expression(')&&evaluator.endsWith('},'));
assert(lstrip.startsWith('window.lstrip =')&&parsed.includes('this.parse(value)'));
function fixture(numberFormat='#,###.##',precision){
  class Desk{}
  const context={console,window:null,__:(text,args)=>String(text).replace(/\{(\d+)\}/g,(_,n)=>args?.[n]??_),
    frappe:{utils:{},ui:{form:{}},boot:{sysdefaults:{number_format:numberFormat,float_precision:precision}},defaults:{is_enabled:()=>false},meta:{get_field_currency:()=>null}}};
  context.window=context;context.hospitality_suite={Desk};vm.createContext(context);
  vm.runInContext(lstrip,context);
  vm.runInContext(read('utils/datatype.js'),context);
  vm.runInContext(read('utils/number_format.js').replace(/^import .*;\s*$/m,''),context);
  vm.runInContext('Object.assign(frappe.utils,{'+evaluator+'});',context);
  vm.runInContext('frappe.ui.form.ControlData=class {get_doc(){return {}}'+parsed+'};',context);
  vm.runInContext(read('form/controls/int.js'),context);vm.runInContext(read('form/controls/float.js'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_forms.js'),'utf8'),context);
  const desk=new Desk();
  const control=type=>{const field=new context.frappe.ui.form[['Int','Long Int'].includes(type)?'ControlInt':'ControlFloat']();field.df={fieldtype:type};return field;};
  return{desk,control};
}

test('native integer controls cannot silently truncate scientific notation or a large expression after passing preflight',()=>{
  const {desk,control}=fixture();
  for(const type of ['Int','Long Int'])for(const raw of ['1e2','-2e3','10**21']){
    const field=control(type),evaluated=Number(field.eval_expression(raw)),parsed=field.get_parsed_value(raw);
    assert(Number.isInteger(evaluated));assert.notEqual(parsed,evaluated,raw+' reproduces the native conversion');
    assert.match(desk.form_numeric_error(field,raw),/entero/,type+': '+raw);
  }
});

test('native integer and decimal controls reject radix literals that Number interprets differently',()=>{
  const {desk,control}=fixture();
  for(const type of ['Int','Long Int','Float','Currency','Percent'])for(const raw of ['0x10','0b10','0o10']){
    const field=control(type);assert.notEqual(field.get_parsed_value(raw),Number(raw));
    assert(desk.form_numeric_error(field,raw),type+': '+raw);
  }
});

test('native formulas, locale grouping, signed values, zero and precise decimal rounding remain accepted',()=>{
  for(const format of ['#,###.##','#.###,##']){
    const {desk,control}=fixture(format,2);
    for(const type of ['Int','Long Int','Float','Currency','Percent'])for(const raw of ['0','-2','1+2','2*3',format==='#,###.##'?'2,000':'2.000']){
      const field=control(type);assert.equal(desk.form_numeric_error(field,raw),null,type+': '+raw+' '+format);
      assert.equal(field.get_parsed_value(raw),raw==='0'?0:raw==='-2'?-2:raw==='1+2'?3:raw==='2*3'?6:2000);
    }
    for(const type of ['Float','Currency','Percent']){
      const field=control(type),raw=format==='#,###.##'?'1.234':'1,234';
      assert.equal(desk.form_numeric_error(field,raw),null);assert.equal(field.get_parsed_value(raw),1.23);
    }
  }
});

test('scientific notation accepted by native decimal controls remains a decimal while fractional integers fail',()=>{
  const {desk,control}=fixture();
  for(const type of ['Float','Currency','Percent'])for(const raw of ['1e2','-2e3','1e-2']){
    const field=control(type);assert.equal(field.get_parsed_value(raw),Number(raw));assert.equal(desk.form_numeric_error(field,raw),null);
  }
  for(const type of ['Int','Long Int']){
    const field=control(type);assert(desk.form_numeric_error(field,'1.5'));assert.equal(desk.form_numeric_error(field,'1e0'),null);
  }
});

test('numeric drafts without a mounted native editor reject radix and integer exponents as well',()=>{
  const {desk}=fixture();
  for(const type of ['Int','Long Int','Float','Currency','Percent']){
    const field={df:{fieldtype:type}};assert(desk.form_numeric_error(field,'0x10'));
    assert.equal(Boolean(desk.form_numeric_error(field,'1e2')),['Int','Long Int'].includes(type));
    assert.equal(desk.form_numeric_error(field,'-2'),null);
  }
});
