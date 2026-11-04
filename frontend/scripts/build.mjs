import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const pages=path.join(root,'pages');
const names=fs.readdirSync(pages).filter(name=>name.endsWith('.html')).sort();
const screens=Object.fromEntries(names.map(name=>[path.basename(name,'.html'),fs.readFileSync(path.join(pages,name),'utf8')]));
for(const key of ['home','event','items-print','items-drink','items-food','items-goods','analysis','recommend','recommend-more','report','custom-dialog','sources-dialog']){
  if(!screens[key]?.trim())throw new Error('필수 화면이 비어 있거나 없습니다: '+key);
}
fs.writeFileSync(path.join(root,'screens.json'),JSON.stringify(screens));
console.log(names.length+'개 화면을 screens.json에 반영했습니다.');
