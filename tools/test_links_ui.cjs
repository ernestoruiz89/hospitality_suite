const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  class Desk{amount(amount,currency){return `${currency} ${amount}`;}}
  const context={window:{hospitality_suite:{Desk}},frappe:{utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}},__:(text,args)=>args?text.replace(/\{(\d+)\}/g,(_,i)=>args[i]):text};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hospitality_suite/public/js/hospitality_links.js'),'utf8'),context);
  const desk=new Desk();desk.prop={brand_name:'Jardín'};desk.data={categories:[{name:'cat-hash',category_name:'Estándar',capacity:2}],rooms:[{name:'room-hash',room_number:'H101',category:'cat-hash',active:1}],rates:[{name:'rate-hash',title:'Noche estándar',mode:'Hotel',amount:1500,currency:'NIO'}]};
  const control=()=>({merge_duplicates(rows){return rows;}});
  const link=(fieldname,options,extra={})=>({fieldname,fieldtype:'Link',options,...extra});
  return{desk,control,link};
}
const plain=value=>JSON.parse(JSON.stringify(value));

test('recursive operational Link preparation retains native types, requirements, defaults and scoped query functions',()=>{
  const {desk,link}=fixture(),query=()=>({filters:{property:'original-property',active:1}});
  const category=link('category','HS Category',{reqd:1,get_query:query,default:'cat-hash'}),room=link('room','HS Room',{get_query:query}),rate=link('rate','HS Rate'),currency=link('currency','Currency'),item=link('item','Item');
  const fields=[currency,{fieldtype:'Table',fields:[category,room,{fieldtype:'Table',fields:[rate,item]}]}];
  desk.prepare_operational_links(fields);desk.prop={brand_name:'Other property'};
  for(const field of [category,room,rate]){assert.equal(field.fieldtype,'Link');assert.equal(field.only_select,1);assert.match(field.filter_description,/Jardín/);}
  assert.equal(category.reqd,1);assert.equal(category.default,'cat-hash');assert.equal(category.get_query,query);assert.equal(room.get_query().filters.property,'original-property');
  assert.equal(currency.on_make,undefined);assert.equal(item.only_select,undefined,'inventory query and choices stay native; nested controls receive labels only');
});

test('native search results keep their keys and current labels but show useful descriptions instead of internal names',()=>{
  const {desk,control,link}=fixture();
  for(const [type,value,expected] of [['HS Category','cat-hash','Capacidad: 2 personas'],['HS Room','room-hash','Categoría: Estándar'],['HS Rate','rate-hash','Hotel · Precio base: NIO 1500']]){
    const field=link('selected',type);desk.prepare_operational_links([field]);const input=control();field.on_make(input);
    const original={value,label:'Nombre actual del servidor',description:'raw/internal-code',html:'<b>unsafe pre-rendered HTML</b>'};
    const result=plain(input.merge_duplicates([original]))[0];assert.equal(result.value,value);assert.equal(result.label,'Nombre actual del servidor');assert.equal(result.description,expected);assert.equal(result.html,undefined);
    assert.equal(original.description,'raw/internal-code');assert.match(original.html,/unsafe/);
  }
});

test('a newly created authorized record absent from bootstrap remains searchable and the final record of a large snapshot is not truncated',()=>{
  const {desk,control,link}=fixture();desk.data.categories=Array.from({length:1201},(_,i)=>({name:`cat-${i}`,category_name:`Categoría ${i}`,capacity:2}));
  const field=link('category','HS Category');desk.prepare_operational_links([field]);const input=control();field.on_make(input);
  const rows=plain(input.merge_duplicates([{value:'new-key',label:'Nueva categoría',description:'new-key'},{value:'cat-1200',label:'cat-1200',description:'cat-1200'}]));
  assert.equal(rows[0].value,'new-key');assert.equal(rows[0].label,'Nueva categoría');assert.equal(rows[0].description,'');
  assert.equal(rows[1].label,'Categoría 1200');assert.equal(rows[1].value,'cat-1200');assert.equal(rows[1].description,'Capacidad: 2 personas');
  const unknown=plain(input.merge_duplicates([{value:'unknown-id',label:'unknown-id'}]))[0];assert.equal(unknown.label,'Categoría del establecimiento');assert.equal(unknown.value,'unknown-id');
});

test('native on_make hooks keep their context and each row control is wrapped once without replacing native prototypes',()=>{
  const {desk,control,link}=fixture();let calls=0,hookContext;
  const field=link('room','HS Room',{on_make(input){calls++;hookContext=this;input.createdByHook=true;}}),native=control().merge_duplicates;
  desk.prepare_operational_links([field]);const hook=field.on_make;desk.prepare_operational_links([field]);assert.equal(field.on_make,hook);
  const a=control(),b=control();field.on_make(a);const first=a.merge_duplicates;field.on_make(a);field.on_make(b);
  assert.equal(hookContext,field);assert.equal(calls,3);assert.equal(a.merge_duplicates,first);assert.notEqual(a.merge_duplicates,b.merge_duplicates);assert.equal(a.createdByHook,true);
  assert.equal(control().merge_duplicates.toString(),native.toString());field.on_make({});
});

test('plain master labels stay as data for native escaping, arbitrary result HTML is dropped and filter hints escape the property name',()=>{
  const {desk,control,link}=fixture();desk.prop.brand_name='<Jardín "Norte">';desk.data.rooms[0].active=0;
  const field=link('room','HS Room');desk.prepare_operational_links([field]);assert.equal(field.filter_description,'Opciones de &lt;Jardín &quot;Norte&quot;&gt;');
  const input=control();field.on_make(input);const row=plain(input.merge_duplicates([{value:'room-hash',label:'<H101>',description:'room-hash',html:'<img src=x onerror=bad>'}]))[0];
  assert.equal(row.label,'<H101>','native Link escapes plain label data when rendering, so pre-escaping would corrupt the displayed name');assert.equal(row.html,undefined);
  assert.equal(row.description,'Categoría: Estándar · Habitación no habilitada');
  desk.data.categories[0].category_name='<img src=x onerror=bad>';
  const escaped=plain(input.merge_duplicates([{value:'room-hash',label:'H101'}]))[0].description;
  assert.match(escaped,/&lt;img src=x onerror=bad&gt;/);
  const nativeEscaped=escaped.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const nativeDescriptionHtml=nativeEscaped.replace(/&(amp|lt|gt|quot);/g,(_,entity)=>({amp:'&',lt:'<',gt:'>',quot:'"'}[entity]));
  assert.doesNotMatch(nativeDescriptionHtml,/<img/,'native escape + one HTML text decode must still leave markup encoded');assert.match(nativeDescriptionHtml,/&lt;img/);
});

test('row form controls receive their visible field label while existing native labels and non-Link behavior stay intact',()=>{
  const {desk,link}=fixture(),fields=[link('category','HS Category',{label:'Categoría'}),{fieldname:'people',fieldtype:'Int',label:'Personas'},link('item','Item',{label:'Artículo'})];
  desk.prepare_operational_links([{fieldtype:'Table',fields}]);
  for(const df of fields){
    const attrs={},input={getAttribute:key=>attrs[key],setAttribute:(key,value)=>attrs[key]=value,labels:[]};
    df.on_make({$input:[input]});assert.equal(attrs['aria-label'],df.label);
    attrs['aria-label']='Etiqueta nativa';df.on_make({$input:[input]});assert.equal(attrs['aria-label'],'Etiqueta nativa');
    delete attrs['aria-label'];input.labels=[{}];df.on_make({$input:[input]});assert.equal(attrs['aria-label'],undefined);
  }
  assert.equal(fields[1].fieldtype,'Int');assert.equal(fields[2].only_select,undefined);
});
